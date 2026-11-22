"""Shared helper for isolated subprocess-based AMT transcribers (ADR-0001)."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.media.extract import extract_audio_to_wav
from lyraforge.media.subprocess_utils import format_log_tail, run_bounded_subprocess
from lyraforge.music_core.midi_import import parse_midi_bytes
from lyraforge.playback.guards import StopToken
from lyraforge.transcribers.base import (
    ProgressCallback,
    TranscribeOptions,
    TranscriptionResult,
)


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
        extract_audio_to_wav(audio_path, wav_in, stop_token=stop_token)

        cmd = build_cmd(runner, wav_in, out_dir)
        if on_progress is not None:
            on_progress(0.3, f"running {engine_id} subprocess")

        res = run_bounded_subprocess(
            cmd,
            work_dir=work,
            prefix=engine_id,
            timeout_s=opts.timeout_s,
            stop_token=stop_token,
            cancel_message="transcription cancelled",
            timeout_code=ErrorCode.TRANSCRIPTION_FAILED,
            timeout_message=f"{display_name} timed out after {opts.timeout_s:.1f}s",
        )
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
            engine_version="subprocess",
            midi_bytes=midi_bytes,
            note_count=len(score.notes),
            duration_ms=round(score.duration_us / 1000),
        )
