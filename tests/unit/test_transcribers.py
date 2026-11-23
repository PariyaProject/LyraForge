"""Unit tests for lyraforge.transcribers (BuiltinMono + BasicPitch subprocess)."""

from __future__ import annotations

import array
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

import pytest

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.instruments import load_builtin_profile
from lyraforge.music_core import (
    arrange,
    build_performance,
    load_midi_file,
    parse_midi_bytes,
    validate_performance,
)
from lyraforge.playback import DryRunDriver, Player, VirtualClock
from lyraforge.preview import synthesize_performance_to_wav
from lyraforge.transcribers import (
    BASIC_PITCH_CLI_ENV,
    BASIC_PITCH_PYTHON_ENV,
    DETTATO_CLI_ENV,
    DETTATO_PYTHON_ENV,
    BasicPitchSubprocessTranscriber,
    BuiltinMonoTranscriber,
    DettatoSubprocessTranscriber,
    TranscribeOptions,
    get_transcriber,
    list_transcribers,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "midi"


def _note_f1(
    truth_notes: tuple[tuple[int, int], ...],
    pred_notes: tuple[tuple[int, int], ...],
    onset_tol_ms: int = 80,
) -> float:
    matched_pred: set[int] = set()
    tp = 0
    for t_ms, t_pitch in truth_notes:
        for j, (p_ms, p_pitch) in enumerate(pred_notes):
            if j not in matched_pred and p_pitch == t_pitch and abs(p_ms - t_ms) <= onset_tol_ms:
                matched_pred.add(j)
                tp += 1
                break
    if not truth_notes or not pred_notes or tp == 0:
        return 0.0
    prec = tp / len(pred_notes)
    rec = tp / len(truth_notes)
    return 2 * prec * rec / (prec + rec)


def test_builtin_mono_wav_to_midi_f1_and_end_to_end_lyre_dryrun(tmp_path: Path) -> None:
    prof = load_builtin_profile()
    truth_score = load_midi_file(FIXTURE_DIR / "c_major_scale.mid")
    truth_perf = build_performance(truth_score, prof, arrange(truth_score, prof))
    wav_path = tmp_path / "c_major.wav"
    synthesize_performance_to_wav(truth_perf, wav_path)

    progress_seen: list[float] = []
    engine = get_transcriber("builtin-mono")
    result = engine.transcribe(
        wav_path,
        on_progress=lambda p, _msg: progress_seen.append(p),
    )
    assert progress_seen and progress_seen[-1] == 1.0

    rec_score = parse_midi_bytes(result.midi_bytes)
    truth_pairs = tuple((round(n.start_us / 1000), n.pitch) for n in truth_score.notes)
    pred_pairs = tuple((round(n.start_us / 1000), n.pitch) for n in rec_score.notes)
    assert _note_f1(truth_pairs, pred_pairs) >= 0.75

    arr = arrange(rec_score, prof)
    perf = build_performance(rec_score, prof, arr)
    validate_performance(perf, prof)
    clock = VirtualClock()
    driver = DryRunDriver(clock)
    pb_res = Player(driver, clock).play(perf["events"])
    assert pb_res.state == "completed"
    assert driver.pressed == set()


def test_builtin_mono_silence_raises_no_playable_notes(tmp_path: Path) -> None:
    silent_wav = tmp_path / "silence.wav"
    pcm = array.array("h", [0] * 22_050)
    with wave.open(str(silent_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22_050)
        wf.writeframes(pcm.tobytes())

    with pytest.raises(LyraError) as exc:
        BuiltinMonoTranscriber().transcribe(silent_wav)
    assert exc.value.code == ErrorCode.NO_PLAYABLE_NOTES

    with pytest.raises(LyraError) as exc2:
        TranscribeOptions(min_pitch=80, max_pitch=60).validate()
    assert exc2.value.code == ErrorCode.INVALID_ARGUMENT


def test_basic_pitch_probe_missing_and_mocked_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(BASIC_PITCH_PYTHON_ENV, raising=False)
    monkeypatch.delenv(BASIC_PITCH_CLI_ENV, raising=False)
    monkeypatch.setattr("shutil.which", lambda _name: None)

    models = {m.id: m for m in list_transcribers()}
    assert models["builtin-mono"].available is True
    assert models["basic-pitch"].available is False

    wav = tmp_path / "tone.wav"
    pcm = array.array("h", [1000] * 11_025)
    if sys.byteorder != "little":
        pcm.byteswap()
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22_050)
        wf.writeframes(pcm.tobytes())

    bp = BasicPitchSubprocessTranscriber()
    with pytest.raises(LyraError) as exc:
        bp.transcribe(wav)
    assert exc.value.code == ErrorCode.MODEL_MISSING

    fake_cli = tmp_path / "basic-pitch"
    fake_cli.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv(BASIC_PITCH_CLI_ENV, str(fake_cli))
    assert bp.probe().available is True

    midi_sample = (FIXTURE_DIR / "c_major_scale.mid").read_bytes()

    class FakeBPProc:
        def __init__(self, cmd: list[str], rc: int = 0) -> None:
            self.returncode = rc
            self.stderr = type("R", (), {"read": lambda _s: b"err"})()
            if rc == 0:
                out_dir = Path(cmd[-2])
                (out_dir / "input_basic_pitch.mid").write_bytes(midi_sample)

        def poll(self) -> int:
            return self.returncode

    captured: dict[str, Any] = {}

    def fake_popen(cmd: list[str], **kwargs: Any) -> FakeBPProc:
        captured.update(kwargs)
        return FakeBPProc(cmd, rc=0)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    res = bp.transcribe(wav)
    assert res.engine_id == "basic-pitch"
    assert res.note_count == 8
    # Child Python tools must receive UTF-8 stdio (Chinese Windows defaults to cp936).
    assert captured["env"]["PYTHONUTF8"] == "1"
    assert captured["env"]["PYTHONIOENCODING"] == "utf-8"

    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **_kw: FakeBPProc(cmd, rc=2))
    with pytest.raises(LyraError) as exc_fail:
        bp.transcribe(wav)
    assert exc_fail.value.code == ErrorCode.TRANSCRIPTION_FAILED

    with pytest.raises(LyraError) as exc_unknown:
        get_transcriber("does-not-exist")
    assert exc_unknown.value.code == ErrorCode.INVALID_ARGUMENT


def test_basic_pitch_python_env_uses_predict_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_python = tmp_path / "python.exe"
    fake_python.write_text("", encoding="utf-8")
    monkeypatch.setenv(BASIC_PITCH_PYTHON_ENV, str(fake_python))
    monkeypatch.delenv(BASIC_PITCH_CLI_ENV, raising=False)

    assert BasicPitchSubprocessTranscriber().probe().details["runner"] == [
        str(fake_python),
        "-m",
        "basic_pitch.predict",
    ]


@pytest.mark.parametrize(
    ("fixture_name", "min_notes"),
    [
        ("c_major_scale.mid", 7),   # Solo monophonic
        ("chords_type1.mid", 6),    # Melody + triads accompaniment
        ("dense_chords.mid", 2),    # Dense polyphonic chords
    ],
)
def test_three_audio_categories_pipeline_stability(
    tmp_path: Path, fixture_name: str, min_notes: int
) -> None:
    from lyraforge.music_core import arrangement_to_midi_bytes, clean_score, score_to_midi_bytes

    prof = load_builtin_profile()
    src_score = load_midi_file(FIXTURE_DIR / fixture_name)
    src_perf = build_performance(src_score, prof, arrange(src_score, prof))
    wav_path = tmp_path / f"{fixture_name}.wav"
    synthesize_performance_to_wav(src_perf, wav_path)

    res = BuiltinMonoTranscriber().transcribe(wav_path)
    assert res.note_count >= min_notes
    raw_score = parse_midi_bytes(res.midi_bytes)
    cleaned_score, _ = clean_score(raw_score)
    assert len(parse_midi_bytes(score_to_midi_bytes(cleaned_score)).notes) == len(
        cleaned_score.notes
    )
    arr = arrange(cleaned_score, prof)
    assert len(parse_midi_bytes(arrangement_to_midi_bytes(arr)).notes) == len(arr.events)
    perf = build_performance(cleaned_score, prof, arr)
    validate_performance(perf, prof)


def test_dettato_subprocess_probe_and_mocked_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(DETTATO_PYTHON_ENV, raising=False)
    monkeypatch.delenv(DETTATO_CLI_ENV, raising=False)
    monkeypatch.setattr("shutil.which", lambda _name: None)

    dt = DettatoSubprocessTranscriber()
    assert dt.probe().available is False

    wav = tmp_path / "tone.wav"
    pcm = array.array("h", [1000] * 11_025)
    if sys.byteorder != "little":
        pcm.byteswap()
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22_050)
        wf.writeframes(pcm.tobytes())

    with pytest.raises(LyraError) as exc:
        dt.transcribe(wav)
    assert exc.value.code == ErrorCode.MODEL_MISSING

    fake_cli = tmp_path / "dettato"
    fake_cli.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv(DETTATO_CLI_ENV, str(fake_cli))
    assert dt.probe().available is True

    midi_sample = (FIXTURE_DIR / "c_major_scale.mid").read_bytes()

    class FakeDettatoProc:
        def __init__(self, cmd: list[str], rc: int = 0) -> None:
            self.returncode = rc
            self.cmd = cmd
            self.stderr = type("R", (), {"read": lambda _s: b"err"})()
            if rc == 0:
                # dettato's -o is an output directory and it writes <stem>.mid inside it.
                out_dir = Path(cmd[-1])
                assert out_dir.is_dir()
                (out_dir / "dettato.mid").write_bytes(midi_sample)

        def poll(self) -> int:
            return self.returncode

    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **_kw: FakeDettatoProc(cmd, rc=0))
    res = dt.transcribe(wav)
    assert res.engine_id == "dettato"
    assert res.note_count == 8


def test_dettato_python_env_uses_module_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_python = tmp_path / "python.exe"
    fake_python.write_text("", encoding="utf-8")
    monkeypatch.setenv(DETTATO_PYTHON_ENV, str(fake_python))
    monkeypatch.delenv(DETTATO_CLI_ENV, raising=False)

    assert DettatoSubprocessTranscriber().probe().details["runner"] == [
        str(fake_python),
        "-m",
        "dettato",
    ]
