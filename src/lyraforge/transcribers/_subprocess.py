"""Shared helper for isolated subprocess-based AMT transcribers (ADR-0001)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import wave
from collections.abc import Callable
from pathlib import Path

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.media.extract import DEFAULT_AUDIO_SAMPLE_RATE, extract_audio_to_wav
from lyraforge.media.subprocess_utils import (
    format_log_tail,
    hidden_subprocess_kwargs,
    run_bounded_subprocess,
)
from lyraforge.music_core.midi_import import parse_midi_bytes
from lyraforge.playback.guards import StopToken
from lyraforge.transcribers.base import (
    ProgressCallback,
    TranscribeOptions,
    TranscriptionResult,
)

_VERSION_CACHE: dict[tuple[str, str], str] = {}


def resolve_runner(
    *,
    python_env: str,
    python_module_args: list[str],
    cli_env: str,
    binary_name: str,
) -> list[str] | None:
    py = os.environ.get(python_env, "").strip()
    if py and Path(py).is_file():
        return [py, *python_module_args]
    cli_override = os.environ.get(cli_env, "").strip()
    if cli_override and Path(cli_override).is_file():
        return [cli_override]
    found = shutil.which(binary_name)
    if found:
        return [found]
    return None


def probe_installed_version(runner: list[str] | None, dist_name: str) -> str:
    """Return installed Python distribution version for ``runner``, or ``'subprocess'``."""
    if not runner or not dist_name or len(runner) < 3 or runner[1] != "-m":
        return "subprocess"
    python = runner[0]
    cache_key = (python, dist_name)
    cached = _VERSION_CACHE.get(cache_key)
    if cached is not None:
        return cached
    version = "subprocess"
    try:
        res = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [
                python,
                "-c",
                f"import importlib.metadata as m;print(m.version({dist_name!r}))",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=15,
            **hidden_subprocess_kwargs(),
        )
        candidate = (res.stdout or "").strip()
        if res.returncode == 0 and candidate:
            version = candidate
            _VERSION_CACHE[cache_key] = version
    except (OSError, subprocess.TimeoutExpired):
        version = "subprocess"
    return version


def _utf8_child_env() -> dict[str, str]:
    """Force UTF-8 stdio in child Python tools.

    Basic Pitch prints emoji progress lines; on a Chinese Windows console the inherited
    ``cp936`` codec raises ``UnicodeEncodeError`` and aborts the whole transcription.
    """
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _wav_duration_s(path: Path) -> float:
    """Read a WAV's duration for timeout scaling; 0 when it cannot be read."""
    try:
        with wave.open(str(path), "rb") as wf:
            rate = wf.getframerate()
            return wf.getnframes() / rate if rate > 0 else 0.0
    except (wave.Error, EOFError, OSError):
        return 0.0


def _effective_timeout_s(
    base_timeout_s: float,
    duration_s: float,
    *,
    per_audio_second: float,
    slack_s: float,
) -> float:
    """Grow the subprocess budget with audio length so CPU inference cannot time out."""
    if per_audio_second <= 0:
        return base_timeout_s
    scaled = slack_s + duration_s * per_audio_second
    return max(base_timeout_s, scaled)


def run_isolated_transcriber(
    *,
    engine_id: str,
    display_name: str,
    runner: list[str] | None,
    missing_hint: str,
    audio_path: Path,
    build_cmd: Callable[[list[str], Path, Path], list[str]],
    options: TranscribeOptions | None = None,
    on_progress: ProgressCallback | None = None,
    stop_token: StopToken | None = None,
    timeout_per_audio_second: float = 0.0,
    timeout_slack_s: float = 120.0,
    sample_rate: int = DEFAULT_AUDIO_SAMPLE_RATE,
    engine_version: str | None = None,
) -> TranscriptionResult:
    opts = options or TranscribeOptions()
    opts.validate()
    if runner is None:
        raise LyraError(ErrorCode.MODEL_MISSING, missing_hint)
    if stop_token is not None and stop_token.stopped:
        raise LyraError(ErrorCode.PLAYBACK_ABORTED, "transcription cancelled")

    with tempfile.TemporaryDirectory(prefix=f"lyraforge-{engine_id}-") as tmpdir:
        work = Path(tmpdir)
        wav_in = work / "input.wav"
        out_dir = work / "out"
        out_dir.mkdir()
        if on_progress is not None:
            on_progress(0.1, "extracting wav")
        extract_audio_to_wav(
            audio_path, wav_in, sample_rate=sample_rate, stop_token=stop_token
        )
        if stop_token is not None and stop_token.stopped:
            raise LyraError(ErrorCode.PLAYBACK_ABORTED, "transcription cancelled")

        cmd = build_cmd(runner, wav_in, out_dir)
        if on_progress is not None:
            on_progress(0.3, f"running {engine_id} subprocess")

        timeout_s = _effective_timeout_s(
            opts.timeout_s,
            _wav_duration_s(wav_in),
            per_audio_second=timeout_per_audio_second,
            slack_s=timeout_slack_s,
        )
        res = run_bounded_subprocess(
            cmd,
            work_dir=work,
            prefix=engine_id,
            timeout_s=timeout_s,
            stop_token=stop_token,
            cancel_message="transcription cancelled",
            timeout_code=ErrorCode.TRANSCRIPTION_FAILED,
            timeout_message=f"{display_name} timed out after {timeout_s:.1f}s",
            env=_utf8_child_env(),
        )
        if stop_token is not None and stop_token.stopped:
            raise LyraError(ErrorCode.PLAYBACK_ABORTED, "transcription cancelled")
        if res.returncode != 0:
            stderr_text = format_log_tail(
                res.stderr_tail,
                res.stdout_tail,
                stderr_truncated=res.stderr_truncated,
                stderr_bytes=res.stderr_bytes,
            )
            raise LyraError(
                ErrorCode.TRANSCRIPTION_FAILED,
                f"{display_name} exited with code {res.returncode}: {stderr_text}",
            )

        mids = sorted(out_dir.glob("*.mid")) + sorted(out_dir.glob("*.midi"))
        if not mids:
            raise LyraError(
                ErrorCode.TRANSCRIPTION_FAILED,
                f"{display_name} completed but produced no MIDI output",
            )
        midi_bytes = mids[0].read_bytes()
        score = parse_midi_bytes(midi_bytes)
        if on_progress is not None:
            on_progress(1.0, "completed")
        return TranscriptionResult(
            engine_id=engine_id,
            engine_version=engine_version or "subprocess",
            midi_bytes=midi_bytes,
            note_count=len(score.notes),
            duration_ms=round(score.duration_us / 1000),
        )
