"""Unit tests for M4 AI Agent orchestration, LLM providers, and legal source adapters."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import mido
import pytest

from lyraforge.agent import (
    ALLOWED_TOOLS,
    FORBIDDEN_TOOLS,
    AgentOrchestrator,
    OpenAICompatibleLLMProvider,
    RuleBasedLLMProvider,
    resolve_llm_provider,
)
from lyraforge.cli import EXIT_OK, main
from lyraforge.errors import ErrorCode, LyraError
from lyraforge.instruments import load_builtin_profile
from lyraforge.library import LibraryStore
from lyraforge.music_core import arrange, build_performance, load_midi_file
from lyraforge.music_core.arranger import Style
from lyraforge.preview import synthesize_performance_to_wav
from lyraforge.sources import DirectUrlSourceAdapter, LocalLibrarySourceAdapter

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "midi"


class _FakeHttpResponse:
    def __init__(self, body: bytes) -> None:
        self._buf = io.BytesIO(body)

    def __enter__(self) -> _FakeHttpResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)


class _FakeOpener:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls = 0

    def open(self, _req: Any, timeout: float = 15.0) -> _FakeHttpResponse:
        _ = timeout
        self.calls += 1
        return _FakeHttpResponse(self.payload)


def _make_chromatic_dense_midi(tmp_path: Path) -> Path:
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    tr.append(mido.MetaMessage("set_tempo", tempo=500_000, time=0))
    # Dense chromatic chords so initial balanced/default triggers quality warning / drop
    pitches = [61, 63, 66, 68, 70]  # all sharp keys on C diatonic lyre
    t = 0
    for rep in range(6):
        st = rep * 120
        for idx, p in enumerate(pitches):
            delta = (st - t) if idx == 0 else 0
            tr.append(mido.Message("note_on", note=p, velocity=90, time=delta))
            t = st
        for idx, p in enumerate(pitches):
            delta = 80 if idx == 0 else 0
            tr.append(mido.Message("note_off", note=p, velocity=0, time=delta))
            t += delta
    tr.append(mido.MetaMessage("end_of_track", time=0))
    mid.tracks.append(tr)
    p_file = tmp_path / "dense_sharp.mid"
    mid.save(p_file)
    return p_file


def test_rule_based_llm_provider_parses_intents() -> None:
    llm = RuleBasedLLMProvider()

    i1 = llm.parse_intent("搜索《千本樱》，转换成原神风物之诗琴的主旋律曲谱，优化并保存")
    assert i1.action == "arrange"
    assert i1.query == "千本樱"
    assert i1.instrument_profile_id == "genshin.windsong_lyre.v1"
    assert i1.style == Style.MELODY

    i2 = llm.parse_intent("帮我找 C Major 转成镜花之琴 1.2x 丰满琶音版本并对比")
    assert i2.action == "compare"
    assert i2.instrument_profile_id == "genshin.floral_zither.v1"
    assert i2.style == Style.RICH
    assert i2.arpeggiate_ms == 20
    assert i2.speed == pytest.approx(1.2)

    i3 = llm.parse_intent("只搜索 星空")
    assert i3.action == "search"
    assert i3.query == "星空"

    i4 = llm.parse_intent(
        "再升2个半音调整一下",
        context={"arrangement_id": "arr-1", "current_transpose": 1},
    )
    assert i4.action == "adjust"
    assert i4.transpose_delta == 2

    with pytest.raises(LyraError) as empty_exc:
        llm.parse_intent("   ")
    assert empty_exc.value.code == ErrorCode.INVALID_ARGUMENT


def test_openai_compatible_provider_and_offline_default() -> None:
    offline = resolve_llm_provider({})
    assert offline.provider_id == "rule-based-offline"

    resp_json = json.dumps({
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "action": "arrange",
                        "query": "Senbonzakura",
                        "instrument_profile_id": "genshin.floral_zither.v1",
                        "style": "melody",
                        "transpose": 2,
                        "transpose_delta": 0,
                        "speed": 0.9,
                        "arpeggiate_ms": 15,
                        "explanation": "mocked",
                    })
                }
            }
        ]
    }).encode("utf-8")
    opener = _FakeOpener(resp_json)
    remote = OpenAICompatibleLLMProvider(
        base_url="http://127.0.0.1:11434/v1",
        api_key="test-key",
        model="qwen2.5",
        opener=opener,
    )
    intent = remote.parse_intent("arrange Senbonzakura")
    assert opener.calls == 1
    assert intent.query == "Senbonzakura"
    assert intent.instrument_profile_id == "genshin.floral_zither.v1"
    assert intent.transpose == 2
    assert intent.arpeggiate_ms == 15

    bad_remote = OpenAICompatibleLLMProvider(
        base_url="http://127.0.0.1:11434/v1",
        api_key="",
        model="qwen2.5",
        opener=_FakeOpener(b"not-json"),
    )
    with pytest.raises(LyraError) as bad_exc:
        bad_remote.parse_intent("hello")
    assert bad_exc.value.code == ErrorCode.SOURCE_UNAVAILABLE


def test_source_adapters_ssrf_auth_and_size_guards(tmp_path: Path) -> None:
    midi_bytes = (FIXTURE_DIR / "c_major_scale.mid").read_bytes()
    url_adapter = DirectUrlSourceAdapter(max_bytes=512, opener=_FakeOpener(midi_bytes))

    for bad_url in (
        "file:///etc/passwd",
        "ftp://93.184.216.34/song.mid",
        "http://127.0.0.1/secret.mid",
        "http://localhost:8000/secret.mid",
        "http://169.254.169.254/latest/meta-data/a.mid",
        "http://[::1]/a.mid",
    ):
        with pytest.raises(LyraError) as ssrf_exc:
            url_adapter.fetch(bad_url, tmp_path, user_authorized=True)
        assert ssrf_exc.value.code == ErrorCode.INVALID_ARGUMENT

    with pytest.raises(LyraError) as auth_exc:
        url_adapter.fetch("https://93.184.216.34/demo.mid", tmp_path, user_authorized=False)
    assert auth_exc.value.code == ErrorCode.PERMISSION_REQUIRED

    big_adapter = DirectUrlSourceAdapter(max_bytes=16, opener=_FakeOpener(midi_bytes))
    with pytest.raises(LyraError) as limit_exc:
        big_adapter.fetch("https://93.184.216.34/demo.mid", tmp_path, user_authorized=True)
    assert limit_exc.value.code == ErrorCode.LIMIT_EXCEEDED

    big_ok = DirectUrlSourceAdapter(max_bytes=100_000, opener=_FakeOpener(midi_bytes))
    saved = big_ok.fetch("https://93.184.216.34/demo.mid", tmp_path, user_authorized=True)
    assert saved.read_bytes() == midi_bytes

    scan_dir = tmp_path / "scan"
    scan_dir.mkdir()
    (scan_dir / "sakura_theme.mid").write_bytes(midi_bytes)
    (scan_dir / "ignore.txt").write_text("x", encoding="utf-8")
    local_adapter = LocalLibrarySourceAdapter(search_dirs=[scan_dir])
    found = local_adapter.search("sakura")
    assert len(found) == 1
    assert found[0].source_type == "local_dir"


def test_agent_orchestrator_end_to_end_and_optimization(tmp_path: Path, capsys: Any) -> None:
    assert "playback.start" in FORBIDDEN_TOOLS
    assert all(t["name"] not in FORBIDDEN_TOOLS for t in ALLOWED_TOOLS)

    midi_bytes = (FIXTURE_DIR / "c_major_scale.mid").read_bytes()
    data_dir = tmp_path / "agent_data"
    scan_dir = tmp_path / "local_music"
    scan_dir.mkdir()
    (scan_dir / "senbonzakura_demo.mid").write_bytes(midi_bytes)

    with LibraryStore(data_dir) as store:
        opener = _FakeOpener(midi_bytes)
        orch = AgentOrchestrator(
            store,
            search_dirs=[scan_dir],
            url_adapter=DirectUrlSourceAdapter(opener=opener),
        )

        # 1. Finds MIDI in local folder, imports, arranges for windsong lyre, renders WAV preview
        res = orch.run("搜索《senbonzakura_demo》，转换成原神风物之诗琴的主旋律曲谱并优化")
        assert res.status == "completed"
        assert res.selected_song is not None
        assert res.selected_arrangement is not None
        assert res.preview_url is not None
        assert any(s.tool == "preview.render" for s in res.steps)

        # 2. Natural language relative adjustment on current arrangement (+2 semitones)
        adj = orch.run(
            "升2个半音重新调整一下",
            arrangement_id=res.selected_arrangement["id"],
        )
        assert adj.status == "completed"
        assert adj.selected_arrangement is not None
        assert adj.selected_arrangement["transpose"] == res.selected_arrangement["transpose"] + 2

        # 3. External URL without allow_network returns confirmation prompt without fetching
        blocked = orch.run("转换 https://93.184.216.34/senbonzakura.mid 成风物之诗琴曲谱")
        assert blocked.status == "needs_confirmation"
        assert blocked.requires_confirmation is True
        assert opener.calls == 0

        # 4. External URL WITH allow_network=True fetches, imports, arranges cleanly
        allowed = orch.run(
            "转换 https://93.184.216.34/senbonzakura.mid 成镜花之琴主旋律",
            allow_network=True,
        )
        assert allowed.status == "completed"
        assert opener.calls == 1

        # 5. Audio-only song triggers auto-transcribe + arrange
        prof = load_builtin_profile()
        score = load_midi_file(FIXTURE_DIR / "c_major_scale.mid")
        perf = build_performance(score, prof, arrange(score, prof))
        wav_path = tmp_path / "solo_agent.wav"
        synthesize_performance_to_wav(perf, wav_path)
        aud_imp = store.import_audio(wav_path, title="Solo Vocal")
        aud_res = orch.run("转成风物之诗琴均衡版并对比", song_id=aud_imp.song.id)
        assert aud_res.status == "completed"
        assert any(s.tool == "transcribe.run" for s in aud_res.steps)
        assert any(s.tool == "arrange.compare" for s in aud_res.steps)

        # 6. Challenging chromatic dense score triggers programmatic re-arrangement
        dense_mid = _make_chromatic_dense_midi(tmp_path)
        dense_res = orch.run("请优化这首密集曲目", local_path=dense_mid)
        assert dense_res.status == "completed"
        assert any(s.tool == "arrange.compare" for s in dense_res.steps)

        # 7. Not found case is honest
        nf = orch.run("查找 nonexistent_missing_track")
        assert nf.status == "not_found"

    # 8. CLI command round-trip
    rc = main([
        "agent",
        "搜索 senbonzakura_demo 转成风物之诗琴曲谱",
        "--data-dir",
        str(data_dir),
    ])
    assert rc == EXIT_OK
    cli_out = json.loads(capsys.readouterr().out)
    assert cli_out["status"] == "completed"
