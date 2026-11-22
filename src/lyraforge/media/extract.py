"""Cross-platform audio/video probing and WAV extraction.

Supports native pure-Python WAV inspection & normalization (works offline with
zero external tools) and controlled FFmpeg subprocess extraction for compressed
audio/video formats (``shell=False``, fixed argv, timeout, cooperative cancel).
"""

from __future__ import annotations

import array
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.fs import atomic_write_bytes
from lyraforge.playback.guards import StopToken

FFMPEG_BIN_ENV = "LYRAFORGE_FFMPEG_BIN"
DEFAULT_AUDIO_SAMPLE_RATE = 22_050

SUPPORTED_MEDIA_EXTENSIONS: frozenset[str] = frozenset(
    {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".mp4", ".mkv", ".webm"}
)


@dataclass(frozen=True, slots=True)
class MediaLimits:
    max_file_bytes: int = 200 * 1024 * 1024
    max_duration_s: float = 1800.0
    timeout_s: float = 300.0


@dataclass(frozen=True, slots=True)
class AudioInfo:
    path: Path
    sample_rate: int
    channels: int
    sample_width: int
    duration_s: float
    size_bytes: int


def find_ffmpeg() -> str | None:
    """Locate FFmpeg binary via ``LYRAFORGE_FFMPEG_BIN`` or system ``PATH``."""
    override = os.environ.get(FFMPEG_BIN_ENV, "").strip()
    if override:
        p = Path(override)
        return str(p) if p.is_file() else None
    return shutil.which("ffmpeg")


def probe_wav(path: str | Path) -> AudioInfo:
    """Inspect a PCM WAV file using stdlib ``wave``."""
    p = Path(path)
    if not p.is_file():
        raise LyraError(ErrorCode.SOURCE_UNAVAILABLE, f"WAV file not found: {p.name}")
    try:
        with wave.open(str(p), "rb") as wf:
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            sample_rate = wf.getframerate()
            nframes = wf.getnframes()
    except (wave.Error, EOFError, OSError) as exc:
        raise LyraError(
            ErrorCode.MEDIA_DECODE_FAILED,
            f"cannot probe WAV {p.name}: {exc}",
        ) from exc

    if channels <= 0 or sample_rate <= 0:
        raise LyraError(ErrorCode.MEDIA_DECODE_FAILED, f"invalid WAV header in {p.name}")
    return AudioInfo(
        path=p,
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
        duration_s=nframes / sample_rate,
        size_bytes=p.stat().st_size,
    )


def _normalize_pcm16_wav(src: Path, dest: Path, target_rate: int) -> AudioInfo:
    """Convert an uncompressed PCM WAV (8/16-bit, mono/multi) to mono 16-bit WAV."""
    try:
        with wave.open(str(src), "rb") as wf:
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            rate = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
    except (wave.Error, EOFError, OSError) as exc:
        raise LyraError(
            ErrorCode.MEDIA_DECODE_FAILED,
            f"cannot decode WAV {src.name}: {exc}",
        ) from exc

    if width not in (1, 2) or channels <= 0 or rate <= 0:
        raise LyraError(
            ErrorCode.MEDIA_UNSUPPORTED,
            f"WAV {src.name} requires FFmpeg (channels={channels}, sample_width={width})",
        )

    if channels == 1 and width == 2 and rate == target_rate:
        atomic_write_bytes(dest, src.read_bytes())
        return probe_wav(dest)

    if width == 1:
        samples = [((b - 128) / 128.0) for b in raw]
    else:
        pcm = array.array("h")
        pcm.frombytes(raw)
        if sys.byteorder != "little":
            pcm.byteswap()
        samples = [s / 32768.0 for s in pcm]

    nframes = len(samples) // channels
    mono = [
        sum(samples[i * channels + c] for c in range(channels)) / channels
        for i in range(nframes)
    ]

    if rate != target_rate and mono:
        out_len = max(1, round(len(mono) * target_rate / rate))
        resampled: list[float] = []
        ratio = rate / target_rate
        last = len(mono) - 1
        for i in range(out_len):
            pos = i * ratio
            idx = min(int(pos), last)
            frac = pos - idx
            nxt = min(idx + 1, last)
            resampled.append(mono[idx] * (1.0 - frac) + mono[nxt] * frac)
        mono = resampled

    out_pcm = array.array("h", (max(-32767, min(32767, round(x * 32767.0))) for x in mono))
    if sys.byteorder != "little":
        out_pcm.byteswap()

    buf = io.BytesIO()
    with wave.open(buf, "wb") as out_wf:
        out_wf.setnchannels(1)
        out_wf.setsampwidth(2)
        out_wf.setframerate(target_rate)
        out_wf.writeframes(out_pcm.tobytes())
    atomic_write_bytes(dest, buf.getvalue())
    return probe_wav(dest)


def _run_ffmpeg_extract(
    ffmpeg: str,
    src: Path,
    dest: Path,
    *,
    sample_rate: int,
    timeout_s: float,
    stop_token: StopToken | None,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".wav", dir=dest.parent)
    os.close(fd)
    tmp_path = Path(tmp_name)
    err_fd, err_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".log", dir=dest.parent)
    os.close(err_fd)
    stderr_log = Path(err_name)

    cmd = [
        ffmpeg,
        "-y",
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(src),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_s16le",
        str(tmp_path),
    ]
    try:
        with stderr_log.open("wb") as err_fh:
            proc = subprocess.Popen(  # noqa: S603
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=err_fh,
                shell=False,
            )
            deadline = time.monotonic() + timeout_s
            while proc.poll() is None:
                if stop_token is not None and stop_token.stopped:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    raise LyraError(ErrorCode.PLAYBACK_ABORTED, "media extraction cancelled")
                if time.monotonic() > deadline:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    raise LyraError(
                        ErrorCode.MEDIA_DECODE_FAILED,
                        f"FFmpeg timed out after {timeout_s:.1f}s",
                    )
                time.sleep(0.05)

        stderr_bytes = stderr_log.read_bytes()[-8192:] if stderr_log.is_file() else b""
        if proc.returncode != 0:
            msg = stderr_bytes.decode("utf-8", errors="replace").strip() or "non-zero exit"
            raise LyraError(
                ErrorCode.MEDIA_DECODE_FAILED,
                f"FFmpeg failed extracting {src.name}: {msg}",
            )
        os.replace(tmp_path, dest)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    finally:
        stderr_log.unlink(missing_ok=True)


def extract_audio_to_wav(
    src_path: str | Path,
    out_wav_path: str | Path,
    *,
    sample_rate: int = DEFAULT_AUDIO_SAMPLE_RATE,
    limits: MediaLimits | None = None,
    stop_token: StopToken | None = None,
    ffmpeg_bin: str | None = None,
) -> AudioInfo:
    """Validate and convert an audio/video file to mono 16-bit PCM WAV."""
    limits = limits or MediaLimits()
    src = Path(src_path)
    dest = Path(out_wav_path)
    if not src.is_file():
        raise LyraError(ErrorCode.SOURCE_UNAVAILABLE, f"media file not found: {src.name}")

    ext = src.suffix.lower()
    if ext not in SUPPORTED_MEDIA_EXTENSIONS:
        raise LyraError(
            ErrorCode.MEDIA_UNSUPPORTED,
            f"unsupported media extension {ext!r}",
            {"supported": sorted(SUPPORTED_MEDIA_EXTENSIONS)},
        )

    size = src.stat().st_size
    if size > limits.max_file_bytes:
        raise LyraError(
            ErrorCode.LIMIT_EXCEEDED,
            f"media file exceeds size limit ({size} bytes > {limits.max_file_bytes})",
            {"size": size, "limit": limits.max_file_bytes},
        )

    if stop_token is not None and stop_token.stopped:
        raise LyraError(ErrorCode.PLAYBACK_ABORTED, "media extraction cancelled")

    ffmpeg = ffmpeg_bin or find_ffmpeg()
    if ext == ".wav":
        try:
            info = _normalize_pcm16_wav(src, dest, sample_rate)
        except LyraError as exc:
            if exc.code == ErrorCode.MEDIA_UNSUPPORTED and ffmpeg:
                _run_ffmpeg_extract(
                    ffmpeg,
                    src,
                    dest,
                    sample_rate=sample_rate,
                    timeout_s=limits.timeout_s,
                    stop_token=stop_token,
                )
                info = probe_wav(dest)
            else:
                raise
    else:
        if not ffmpeg:
            raise LyraError(
                ErrorCode.MODEL_MISSING,
                f"FFmpeg is required to extract {ext} files; "
                f"install FFmpeg or set {FFMPEG_BIN_ENV}",
            )
        _run_ffmpeg_extract(
            ffmpeg,
            src,
            dest,
            sample_rate=sample_rate,
            timeout_s=limits.timeout_s,
            stop_token=stop_token,
        )
        info = probe_wav(dest)

    if info.duration_s > limits.max_duration_s:
        dest.unlink(missing_ok=True)
        raise LyraError(
            ErrorCode.LIMIT_EXCEEDED,
            f"audio duration {info.duration_s:.1f}s exceeds limit {limits.max_duration_s:.1f}s",
        )
    return info
