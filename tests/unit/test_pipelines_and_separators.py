"""Unit & integration tests for separators, extensible pipelines, Schema v4 & API."""

from __future__ import annotations

import io
import sqlite3
import sys
import wave
from pathlib import Path
from typing import Any

import mido
import pytest
from fastapi.testclient import TestClient

from lyraforge.api import SESSION_TOKEN_HEADER, create_app
from lyraforge.errors import ErrorCode, LyraError
from lyraforge.library import SCHEMA_VERSION, LibraryStore
from lyraforge.music_core import ArrangeOptions
from lyraforge.pipelines import (
    PipelineInfo,
    PipelineRequest,
    PipelineResult,
    get_pipeline,
    list_pipelines,
    register_pipeline,
)
from lyraforge.playback.guards import StopToken
from lyraforge.separators import (
    DemucsSeparator,
    SeparatedStems,
    SeparatorInfo,
    get_separator,
    list_separators,
    register_separator,
)
from lyraforge.separators.demucs import _mix_pcm16_wavs
from lyraforge.transcribers import TranscribeOptions, TranscriptionResult
from lyraforge.transcribers.basic_pitch import BasicPitchSubprocessTranscriber


def _write_pcm_wav(path: Path, *, sample_rate: int = 22050, duration_s: float = 0.2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    n_samples = max(1, int(sample_rate * duration_s))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x10\x02" * n_samples)
    path.write_bytes(buf.getvalue())


def _midi_bytes(notes: list[tuple[int, int, int]], *, name: str = "") -> bytes:
    mid = mido.MidiFile(type=0, ticks_per_beat=500)
    trk = mido.MidiTrack([mido.MetaMessage("set_tempo", tempo=500_000, time=0)])
    if name:
        trk.append(mido.MetaMessage("track_name", name=name, time=0))
    events: list[tuple[int, int, int, int]] = []
    for start_ms, dur_ms, pitch in notes:
        events.append((start_ms, 1, pitch, 96))
        events.append((start_ms + dur_ms, 0, pitch, 0))
    now = 0
    for tick, is_on, pitch, vel in sorted(events):
        delta = max(0, tick - now)
        trk.append(
            mido.Message("note_on" if is_on else "note_off", note=pitch, velocity=vel, time=delta)
        )
        now = tick
    trk.append(mido.MetaMessage("end_of_track", time=0))
    mid.tracks.append(trk)
    out = io.BytesIO()
    mid.save(file=out)
    return out.getvalue()


def test_separator_and_pipeline_registries_are_extensible() -> None:
    seps = {s.id for s in list_separators()}
    assert "demucs" in seps

    pipes = {p.id: p for p in list_pipelines()}
    assert {"direct", "vocal_split_full", "vocal_split_lead", "vocal_split_accomp"}.issubset(pipes)

    class _DummySep:
        id = "test-sep"

        def probe(self) -> SeparatorInfo:
            return SeparatorInfo(
                id=self.id, display_name="Test Sep", available=True, license="MIT", scope_note="x"
            )

        def separate(self, wav_path: Path, out_dir: Path, **_kw: Any) -> SeparatedStems:
            _ = out_dir
            return SeparatedStems(vocals=wav_path)

    class _DummyPipe:
        id = "test-pipe"

        def probe(self) -> PipelineInfo:
            return PipelineInfo(
                id=self.id,
                display_name="Test Pipe",
                description="custom",
                recommended_for="tests",
                stages=("step",),
                required_tools=(),
                available=True,
            )

        def run(self, wav_path: Path, request: PipelineRequest, **_kw: Any) -> PipelineResult:
            raise NotImplementedError

    from lyraforge.pipelines import registry as p_reg
    from lyraforge.separators import registry as s_reg

    register_separator(_DummySep())
    register_pipeline(_DummyPipe())
    try:
        assert get_separator("test-sep").id == "test-sep"
        assert get_pipeline("test-pipe").id == "test-pipe"
    finally:
        s_reg._SEPARATORS.pop("test-sep", None)
        p_reg._PIPELINES.pop("test-pipe", None)


def test_demucs_separator_windows_hidden_kwargs_no_drums_mix_and_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wav_in = tmp_path / "song.wav"
    _write_pcm_wav(wav_in)
    fake_py = tmp_path / "demucs_py.exe"
    fake_py.write_text("", encoding="utf-8")
    monkeypatch.setenv("LYRAFORGE_DEMUCS_PYTHON", str(fake_py))
    monkeypatch.setenv("LYRAFORGE_DEMUCS_DEVICE", "cpu")

    sep = DemucsSeparator()
    info = sep.probe()
    assert info.available is True

    # Cancel before start
    tok = StopToken()
    tok.request_stop("abort")
    with pytest.raises(LyraError) as exc:
        sep.separate(wav_in, tmp_path / "cancel_out", stop_token=tok)
    assert exc.value.code == ErrorCode.PLAYBACK_ABORTED

    # Mock run_bounded_subprocess simulating CLI layout (bass.wav + other.wav -> no_drums.wav mix)
    captured_cmds: list[list[str]] = []

    def fake_bounded(cmd: list[str], *, work_dir: Path, **_kw: Any) -> Any:
        captured_cmds.append(cmd)
        sub = work_dir / "htdemucs" / "song"
        _write_pcm_wav(sub / "vocals.wav")
        _write_pcm_wav(sub / "bass.wav")
        _write_pcm_wav(sub / "other.wav")
        _write_pcm_wav(sub / "drums.wav")
        from types import SimpleNamespace

        return SimpleNamespace(
            returncode=0,
            stdout_tail=b"",
            stderr_tail=b"",
            stdout_truncated=False,
            stderr_truncated=False,
            stdout_bytes=0,
            stderr_bytes=0,
            peak_disk_bytes=0,
        )

    monkeypatch.setattr("lyraforge.separators.demucs.run_bounded_subprocess", fake_bounded)
    out_dir = tmp_path / "sep_out"
    stems = sep.separate(wav_in, out_dir)
    assert stems.vocals is not None and stems.vocals.is_file()
    assert stems.accompaniment is not None and stems.accompaniment.name == "no_drums.wav"
    assert stems.accompaniment.is_file()
    assert captured_cmds[0][0] == str(fake_py)

    # Verify _mix_pcm16_wavs rejects empty cleanly
    assert _mix_pcm16_wavs([], tmp_path / "empty.wav") is None


def test_basic_pitch_passes_vocal_thresholds_when_specified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[list[str]] = []

    def fake_run(**kw: Any) -> TranscriptionResult:
        cmd = kw["build_cmd"](
            ["python", "-m", "basic_pitch.predict"], tmp_path / "in.wav", tmp_path
        )
        captured.append(cmd)
        return TranscriptionResult(
            engine_id="basic-pitch",
            engine_version="subprocess",
            midi_bytes=_midi_bytes([(0, 200, 60)]),
            note_count=1,
            duration_ms=200,
        )

    monkeypatch.setattr("lyraforge.transcribers.basic_pitch.run_isolated_transcriber", fake_run)
    bp = BasicPitchSubprocessTranscriber()
    bp.transcribe(tmp_path / "a.wav", TranscribeOptions())
    assert "--onset-threshold" not in captured[-1]

    bp.transcribe(
        tmp_path / "a.wav",
        TranscribeOptions(
            min_note_ms=45,
            onset_threshold=0.58,
            frame_threshold=0.35,
            min_frequency_hz=110.0,
            max_frequency_hz=1400.0,
        ),
    )
    flags_cmd = captured[-1]
    assert "--onset-threshold" in flags_cmd and "0.580" in flags_cmd
    assert "--frame-threshold" in flags_cmd and "0.350" in flags_cmd
    assert "--minimum-note-length" in flags_cmd and "45.0" in flags_cmd
    assert "--minimum-frequency" in flags_cmd and "110.00" in flags_cmd
    assert "--maximum-frequency" in flags_cmd and "1400.00" in flags_cmd


def test_all_four_pipelines_schema_v4_migration_and_api_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 1. Verify Schema v3 -> v4 upgrade keeps legacy rows intact
    legacy_dir = tmp_path / "legacy_v3"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    db_file = legacy_dir / "library.db"
    with sqlite3.connect(db_file) as conn:
        from lyraforge.library.schema import _MIGRATION_V1, _MIGRATION_V2

        conn.executescript(_MIGRATION_V1)
        conn.executescript(_MIGRATION_V2)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO schema_migrations VALUES (1, '2026-01-01T00:00:00Z')")
        conn.execute("INSERT INTO schema_migrations VALUES (2, '2026-01-01T00:00:00Z')")
        conn.execute(
            "ALTER TABLE arrangements ADD COLUMN parent_id TEXT"
        )
        conn.execute("ALTER TABLE arrangements ADD COLUMN score REAL")
        conn.execute("ALTER TABLE arrangements ADD COLUMN user_vote INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE arrangements ADD COLUMN label TEXT")
        conn.execute("INSERT INTO schema_migrations VALUES (3, '2026-01-01T00:00:00Z')")
        conn.execute(
            "INSERT INTO songs VALUES ('s1', 'Legacy', '', '[]', '2026-01-01', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO sources VALUES ('src1', 's1', 'audio', 'a.wav', 'h', 'a.wav', 10, 't')"
        )
        conn.execute(
            "INSERT INTO transcriptions VALUES "
            "('t1', 's1', 'src1', 'builtin-mono', '0.1', '{}', "
            "'r.mid', 'c.mid', 'completed', 5, 't')"
        )

    with LibraryStore(legacy_dir) as migrated:
        assert migrated.schema_version == SCHEMA_VERSION == 4
        detail = migrated.get_song("s1")
        assert detail.transcriptions[0].pipeline_id == "direct"
        assert detail.transcriptions[0].tracks == ()

    # 2. Full store + FastAPI multi-pipeline comparison test with mocked separator & transcribers
    data_dir = tmp_path / "multi_pipe_data"
    wav_src = tmp_path / "pop.wav"
    _write_pcm_wav(wav_src)

    class _FakeSep:
        id = "demucs"

        def probe(self) -> SeparatorInfo:
            return SeparatorInfo(
                id="demucs",
                display_name="Fake Demucs",
                available=True,
                license="MIT",
                scope_note="t",
            )

        def separate(self, wav_path: Path, out_dir: Path, **_kw: Any) -> SeparatedStems:
            out_dir.mkdir(parents=True, exist_ok=True)
            v = out_dir / "vocals.wav"
            a = out_dir / "no_drums.wav"
            v.write_bytes(wav_path.read_bytes())
            a.write_bytes(wav_path.read_bytes())
            return SeparatedStems(vocals=v, accompaniment=a, metadata={"separator": "demucs"})

    class _FakeTrans:
        def __init__(self, eid: str, mid: bytes) -> None:
            self.id = eid
            self._mid = mid

        def probe(self) -> Any:
            from lyraforge.transcribers.base import ModelInfo

            return ModelInfo(
                id=self.id, display_name=self.id, available=True, license="MIT", scope_note="ok"
            )

        def transcribe(self, _wav: Path, **_kw: Any) -> TranscriptionResult:
            return TranscriptionResult(
                engine_id=self.id,
                engine_version="1.0",
                midi_bytes=self._mid,
                note_count=3,
                duration_ms=800,
            )

    vocal_mid = _midi_bytes([(0, 300, 62), (300, 300, 64), (600, 300, 67)])
    accomp_mid = _midi_bytes([(0, 300, 48), (300, 300, 50), (600, 300, 79)])

    def fake_get_transcriber(eid: str = "builtin-mono") -> Any:
        if "basic" in eid or eid == "builtin-mono":
            return _FakeTrans(eid, vocal_mid)
        return _FakeTrans(eid, accomp_mid)

    from lyraforge.separators import registry as sep_reg

    orig_demucs = sep_reg._SEPARATORS["demucs"]
    register_separator(_FakeSep())
    monkeypatch.setattr("lyraforge.pipelines.builtin.get_transcriber", fake_get_transcriber)
    monkeypatch.setattr(
        "lyraforge.pipelines.builtin._available_engine_ids",
        lambda: {"basic-pitch", "dettato"},
    )
    monkeypatch.setattr("lyraforge.library.store.get_transcriber", fake_get_transcriber)
    monkeypatch.setattr("lyraforge.api.job_service.get_transcriber", fake_get_transcriber)

    try:
        token = "pipe-tok"
        app = create_app(data_dir=data_dir, session_token=token)
        headers = {SESSION_TOKEN_HEADER: token}
        client = TestClient(app)

        pipe_ids = {
            p["id"] for p in client.get("/v1/pipelines", headers=headers).json()["pipelines"]
        }
        assert pipe_ids >= {
            "direct",
            "vocal_split_full",
            "vocal_split_lead",
            "vocal_split_accomp",
        }
        strat_ids = {
            s["id"] for s in client.get("/v1/arrangers", headers=headers).json()["strategies"]
        }
        assert strat_ids == {
            "classic",
            "vocal_lead",
            "vocal_dynamic",
        }

        with wav_src.open("rb") as fh:
            imp = client.post(
                "/v1/imports",
                headers=headers,
                files={"file": ("pop.wav", fh, "audio/wav")},
                data={"title": "Pop Test"},
            )
        song_id = imp.json()["song"]["id"]

        # Run direct pipeline and vocal_split_full pipeline on the same song
        tr_direct = client.post(
            "/v1/jobs/transcribe",
            headers=headers,
            json={"song_id": song_id, "engine_id": "builtin-mono", "pipeline_id": "direct"},
        ).json()["transcription"]
        tr_full = client.post(
            "/v1/jobs/transcribe",
            headers=headers,
            json={"song_id": song_id, "pipeline_id": "vocal_split_full"},
        ).json()["transcription"]
        tr_lead = client.post(
            "/v1/jobs/transcribe",
            headers=headers,
            json={"song_id": song_id, "pipeline_id": "vocal_split_lead"},
        ).json()["transcription"]
        tr_acc = client.post(
            "/v1/jobs/transcribe",
            headers=headers,
            json={"song_id": song_id, "pipeline_id": "vocal_split_accomp"},
        ).json()["transcription"]

        assert tr_direct["pipeline_id"] == "direct"
        assert tr_full["pipeline_id"] == "vocal_split_full"
        assert [t["name"] for t in tr_full["tracks"]] == ["Vocal Lead", "Accompaniment"]
        assert tr_lead["tracks"][0]["name"] == "Vocal Lead"
        assert tr_acc["tracks"][0]["name"] == "Accompaniment"

        tracks_resp = client.get(
            f"/v1/library/songs/{song_id}/tracks",
            headers=headers,
            params={"transcription_id": tr_full["id"]},
        ).json()
        assert tracks_resp["tracks"] == tr_full["tracks"]
        vocal_idx = tracks_resp["tracks"][0]["index"]
        assert vocal_idx == 1  # SMF Type 1 track 0 is conductor
        assert tracks_resp["detected_melody_track"] == vocal_idx
        assert len(tracks_resp["tracks"]) == 2

        ab_resp = client.post(
            "/v1/jobs/arrange-ab",
            headers=headers,
            json={"song_id": song_id, "transcription_id": tr_full["id"]},
        )
        assert ab_resp.status_code == 200
        ab_json = ab_resp.json()
        assert ab_json["arrangement_a"]["arranger_strategy"] == "classic"
        assert ab_json["arrangement_b"]["arranger_strategy"] == "vocal_lead"
        assert ab_json["arrangement_b"]["transcription_id"] == tr_full["id"]

        # Editing arrangement preserves transcription_id and arranger_strategy
        detail_b = client.get(
            f"/v1/arrangements/{ab_json['arrangement_b']['id']}", headers=headers
        ).json()
        edited = client.post(
            f"/v1/arrangements/{ab_json['arrangement_b']['id']}/edit",
            headers=headers,
            json={"events": detail_b["performance"]["events"], "label": "Tweaked Vocal"},
        ).json()["arrangement"]
        assert edited["arranger_strategy"] == "vocal_lead"
        assert edited["transcription_id"] == tr_full["id"]
    finally:
        register_separator(orig_demucs)
        _ = sys.platform
        _ = ArrangeOptions()


def test_no_silent_accomp_degradation_range_presets_and_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lyraforge.pipelines.builtin import _pick_vocal_engine, _vocal_options

    wav = tmp_path / "song.wav"
    _write_pcm_wav(wav)

    class _FakeSep:
        id = "demucs"

        def probe(self) -> SeparatorInfo:
            return SeparatorInfo(
                id="demucs", display_name="Fake", available=True, license="MIT", scope_note="ok"
            )

        def separate(self, wav_path: Path, out_dir: Path, **_kw: Any) -> SeparatedStems:
            out_dir.mkdir(parents=True, exist_ok=True)
            v = out_dir / "vocals.wav"
            a = out_dir / "no_vocals.wav"
            v.write_bytes(wav_path.read_bytes())
            a.write_bytes(wav_path.read_bytes())
            return SeparatedStems(
                vocals=v,
                accompaniment=a,
                metadata={
                    "separator": "demucs",
                    "version": "4.0.1",
                    "drums_removed": False,
                    "accompaniment_source": "no_vocals_with_drums",
                    "warnings": ["Demucs 回退至 no_vocals.wav，当前伴奏轨仍包含鼓声"],
                },
            )

    class _FakeTrans:
        def __init__(self, eid: str) -> None:
            self.id = eid

        def probe(self) -> Any:
            from lyraforge.transcribers.base import ModelInfo

            return ModelInfo(
                id=self.id, display_name=self.id, available=True, license="MIT", scope_note="ok"
            )

        def transcribe(self, _wav: Path, **_kw: Any) -> TranscriptionResult:
            return TranscriptionResult(
                engine_id=self.id,
                engine_version="0.3.0" if self.id == "swift-f0" else "0.1.0",
                midi_bytes=_midi_bytes([(0, 250, 62), (250, 250, 64)]),
                note_count=2,
                duration_ms=500,
            )

    from lyraforge.separators import registry as sep_reg

    orig_demucs = sep_reg._SEPARATORS["demucs"]
    register_separator(_FakeSep())
    monkeypatch.setattr(
        "lyraforge.pipelines.builtin._available_engine_ids",
        lambda: {"builtin-mono", "swift-f0"},
    )
    try:
        assert _pick_vocal_engine(None) == "swift-f0"
        info_full = get_pipeline("vocal_split_full").probe()
        assert info_full.available is False
        assert info_full.low_resource_available is True
        assert "dettato/basic-pitch" in info_full.missing_tools
        assert info_full.resolved_vocal_engine_id == "swift-f0"
        assert info_full.resolved_accomp_engine_id is None

        # Auto accompaniment MUST NOT silently degrade to monophonic builtin-mono
        with pytest.raises(LyraError) as exc:
            get_pipeline("vocal_split_full").run(
                wav,
                PipelineRequest(transcriber_resolver=lambda eid: _FakeTrans(eid)),
            )
        assert exc.value.code == ErrorCode.MODEL_MISSING

        # Explicit user opt-in to builtin-mono accompaniment is allowed & labeled degraded
        res = get_pipeline("vocal_split_full").run(
            wav,
            PipelineRequest(
                accomp_engine_id="builtin-mono",
                vocal_cleanup="light",
                vocal_range="male",
                transcriber_resolver=lambda eid: _FakeTrans(eid),
            ),
        )
        assert res.engine_id == "swift-f0+builtin-mono"
        assert res.metadata["degraded_mode"] is True
        assert res.metadata["drums_removed"] is False
        assert res.metadata["vocal_cleanup"] == "light"
        assert res.metadata["vocal_range"] == "male"
        assert any("单音引擎" in w for w in res.metadata["warnings"])

        # Vocal range presets preserve male bass/baritone < 110Hz and female soprano > 1400Hz
        male_opts = _vocal_options(
            TranscribeOptions(), range_preset="male", engine_id="basic-pitch"
        )
        female_opts = _vocal_options(
            TranscribeOptions(), range_preset="female", engine_id="basic-pitch"
        )
        auto_opts = _vocal_options(TranscribeOptions(), range_preset="auto", engine_id="swift-f0")
        assert male_opts.min_frequency_hz == 65.0
        assert female_opts.max_frequency_hz == 1760.0
        assert auto_opts.min_pitch <= 38 and auto_opts.max_pitch >= 93

        # Store persists provenance & exposes it on get_song()
        store_dir = tmp_path / "prov_store"
        with LibraryStore(store_dir) as store:
            imp = store.import_audio(wav, title="Provenance Song")
            monkeypatch.setattr(
                "lyraforge.library.store.get_transcriber",
                lambda eid: _FakeTrans(eid),
            )
            tr = store.transcribe_song(
                imp.song.id,
                pipeline_id="vocal_split_full",
                accomp_engine_id="builtin-mono",
                vocal_cleanup="strong",
                vocal_range="female",
            )
            assert tr.metadata["degraded_mode"] is True
            assert tr.metadata["vocal_cleanup"] == "strong"
            assert tr.metadata["vocal_range"] == "female"
            assert "swift-f0 0.3.0" in tr.engine_version
    finally:
        register_separator(orig_demucs)


def test_demucs_mps_fallback_and_no_vocals_honesty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wav_in = tmp_path / "song.wav"
    _write_pcm_wav(wav_in)
    fake_py = tmp_path / "demucs_py"
    fake_py.write_text("", encoding="utf-8")
    monkeypatch.setenv("LYRAFORGE_DEMUCS_PYTHON", str(fake_py))
    monkeypatch.delenv("LYRAFORGE_DEMUCS_DEVICE", raising=False)
    monkeypatch.delenv("LYRAFORGE_DETTATO_DEVICE", raising=False)
    monkeypatch.setattr("lyraforge.separators.demucs.resolve_device", lambda _r: "mps")

    calls: list[str] = []

    def fake_bounded(cmd: list[str], *, work_dir: Path, **_kw: Any) -> Any:
        from types import SimpleNamespace

        dev = cmd[-1]
        calls.append(dev)
        if dev == "mps":
            return SimpleNamespace(
                returncode=1,
                stdout_tail=b"MPS op unsupported",
                stderr_tail=b"RuntimeError",
                stdout_truncated=False,
                stderr_truncated=False,
                stdout_bytes=0,
                stderr_bytes=0,
            )
        _write_pcm_wav(work_dir / "vocals.wav")
        _write_pcm_wav(work_dir / "no_vocals.wav")
        return SimpleNamespace(
            returncode=0,
            stdout_tail=b"",
            stderr_tail=b"",
            stdout_truncated=False,
            stderr_truncated=False,
            stdout_bytes=0,
            stderr_bytes=0,
        )

    monkeypatch.setattr("lyraforge.separators.demucs.run_bounded_subprocess", fake_bounded)
    stems = DemucsSeparator().separate(wav_in, tmp_path / "out_fb")
    assert calls == ["mps", "cpu"]
    assert stems.metadata["device"] == "cpu"
    assert stems.metadata["fallback_from_device"] == "mps"
    assert stems.metadata["drums_removed"] is False
    assert stems.metadata["accompaniment_source"] == "no_vocals_with_drums"
    assert len(stems.metadata["warnings"]) >= 2
