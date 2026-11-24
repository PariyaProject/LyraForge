"""Unit tests for lyraforge.media.extract."""

from __future__ import annotations

import array
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

import pytest

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.media import (
    FFMPEG_BIN_ENV,
    MediaLimits,
    extract_audio_to_wav,
    probe_wav,
)
from lyraforge.media.extract import SUPPORTED_MEDIA_EXTENSIONS
from lyraforge.playback import StopToken


def _write_pcm16_wav(
    path: Path, *, channels: int = 2, rate: int = 44_100, frames: int = 4410
) -> None:
    samples = array.array("h", [1000] * (frames * channels))
    if sys.byteorder != "little":
        samples.byteswap()
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())


def test_native_wav_probe_and_mono_resampling(tmp_path: Path) -> None:
    src = tmp_path / "stereo_44k.wav"
    dest = tmp_path / "mono_22k.wav"
    _write_pcm16_wav(src, channels=2, rate=44_100, frames=4410)

    info = extract_audio_to_wav(src, dest, sample_rate=22_050)
    assert info.channels == 1
    assert info.sample_rate == 22_050
    assert info.sample_width == 2
    assert abs(info.duration_s - 0.1) < 0.02

    # Same format copies cleanly too
    dest2 = tmp_path / "copy.wav"
    info2 = extract_audio_to_wav(dest, dest2, sample_rate=22_050)
    assert info2.sample_rate == 22_050

    with pytest.raises(LyraError) as exc:
        probe_wav(tmp_path / "missing.wav")
    assert exc.value.code == ErrorCode.SOURCE_UNAVAILABLE


def test_media_validation_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad_ext = tmp_path / "song.txt"
    bad_ext.write_text("hello", encoding="utf-8")
    with pytest.raises(LyraError) as exc1:
        extract_audio_to_wav(bad_ext, tmp_path / "out.wav")
    assert exc1.value.code == ErrorCode.MEDIA_UNSUPPORTED

    fake_mp3 = tmp_path / "song.mp3"
    fake_mp3.write_bytes(b"ID3...")
    with pytest.raises(LyraError) as exc2:
        extract_audio_to_wav(fake_mp3, tmp_path / "out.wav", limits=MediaLimits(max_file_bytes=2))
    assert exc2.value.code == ErrorCode.LIMIT_EXCEEDED

    monkeypatch.setenv(FFMPEG_BIN_ENV, str(tmp_path / "nonexistent_ffmpeg"))
    with pytest.raises(LyraError) as exc3:
        extract_audio_to_wav(fake_mp3, tmp_path / "out.wav")
    assert exc3.value.code == ErrorCode.MODEL_MISSING


@pytest.mark.parametrize("ext", sorted(SUPPORTED_MEDIA_EXTENSIONS - {".wav"}))
def test_media_extensions_are_routed_to_ffmpeg(
    ext: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / f"input{ext}"
    src.write_bytes(b"fake-media-segment")
    dest = tmp_path / "out.wav"
    calls: list[str] = []

    def fake_extract(
        _ffmpeg: str, src_path: Path, dest_path: Path, **_kwargs: Any
    ) -> None:
        calls.append(src_path.name)
        _write_pcm16_wav(dest_path, channels=1, rate=22_050, frames=2205)

    monkeypatch.setattr("lyraforge.media.extract._run_ffmpeg_extract", fake_extract)
    monkeypatch.setattr("lyraforge.media.extract.find_ffmpeg", lambda: "ffmpeg")

    info = extract_audio_to_wav(src, dest)
    assert calls == [src.name]
    assert info.sample_rate == 22_050
    assert info.duration_s > 0


def test_ffmpeg_subprocess_mocked_success_failure_and_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mp3 = tmp_path / "demo.mp3"
    mp3.write_bytes(b"fake-mp3")
    dest = tmp_path / "out.wav"
    seen_cmd: list[str] = []

    class FakeProc:
        def __init__(self, cmd: list[str], rc: int = 0, stderr_data: bytes = b"") -> None:
            nonlocal seen_cmd
            seen_cmd = cmd
            self.returncode = rc
            self._polls = 0
            self.stderr = type("R", (), {"read": lambda _s: stderr_data})()
            if rc == 0:
                _write_pcm16_wav(Path(cmd[-1]), channels=1, rate=22_050, frames=2205)

        def poll(self) -> int | None:
            self._polls += 1
            return self.returncode if self._polls >= 2 else None

        def terminate(self) -> None:
            self.returncode = -15

        def wait(self, timeout: float | None = None) -> int:  # noqa: ARG002
            return self.returncode

        def kill(self) -> None:
            self.returncode = -9

    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **_kw: FakeProc(cmd, rc=0))
    info = extract_audio_to_wav(mp3, dest, ffmpeg_bin="/usr/bin/ffmpeg")
    assert info.sample_rate == 22_050
    assert seen_cmd[0] == "/usr/bin/ffmpeg"
    assert "-vn" in seen_cmd

    # Non-zero exit -> MEDIA_DECODE_FAILED
    monkeypatch.setattr(
        subprocess, "Popen", lambda cmd, **_kw: FakeProc(cmd, rc=1, stderr_data=b"bad stream")
    )
    with pytest.raises(LyraError) as exc_fail:
        extract_audio_to_wav(mp3, dest, ffmpeg_bin="/usr/bin/ffmpeg")
    assert exc_fail.value.code == ErrorCode.MEDIA_DECODE_FAILED

    # Cancellation during polling -> PLAYBACK_ABORTED
    stop = StopToken()

    class HangingProc(FakeProc):
        def poll(self) -> Any:
            stop.request_stop("cancel")
            return None

    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **_kw: HangingProc(cmd, rc=1))
    with pytest.raises(LyraError) as exc_cancel:
        extract_audio_to_wav(mp3, dest, ffmpeg_bin="/usr/bin/ffmpeg", stop_token=stop)
    assert exc_cancel.value.code == ErrorCode.PLAYBACK_ABORTED


def test_format_log_tail_preserves_stdout_errors_alongside_stderr_warnings() -> None:
    from lyraforge.media.subprocess_utils import format_log_tail

    out = format_log_tail(
        b"UserWarning: HF Hub token missing",
        b"TypeError: Cannot convert a MPS Tensor to float64 dtype",
    )
    assert "HF Hub token missing" in out
    assert "[stdout]" in out
    assert "MPS Tensor to float64" in out
    assert format_log_tail(b"", b"fatal stdout only") == "fatal stdout only"
    assert format_log_tail(b"", b"") == "non-zero exit"
