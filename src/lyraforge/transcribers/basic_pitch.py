"""Isolated subprocess adapter for Spotify Basic Pitch (Apache-2.0, ADR-0001)."""

from __future__ import annotations

import sys
from pathlib import Path

from lyraforge.playback.guards import StopToken
from lyraforge.transcribers._subprocess import resolve_runner, run_isolated_transcriber
from lyraforge.transcribers.base import (
    ModelInfo,
    ProgressCallback,
    TranscribeOptions,
    TranscriptionResult,
)

BASIC_PITCH_PYTHON_ENV = "LYRAFORGE_BASIC_PITCH_PYTHON"
BASIC_PITCH_CLI_ENV = "LYRAFORGE_BASIC_PITCH_BIN"


def _resolve_runner() -> list[str] | None:
    return resolve_runner(
        python_env=BASIC_PITCH_PYTHON_ENV,
        # basic-pitch 0.4.x moved the CLI entry point from ``basic_pitch.inference`` to
        # ``basic_pitch.predict``; ``predict`` keeps the same ``OUTPUT_DIR AUDIO`` contract.
        python_module_args=["-m", "basic_pitch.predict"],
        cli_env=BASIC_PITCH_CLI_ENV,
        binary_name="basic-pitch",
    )


class BasicPitchSubprocessTranscriber:
    """Runs Basic Pitch inside an isolated subprocess without polluting main deps."""

    id = "basic-pitch"

    def probe(self) -> ModelInfo:
        runner = _resolve_runner()
        return ModelInfo(
            id=self.id,
            display_name="Spotify Basic Pitch (隔离进程)",
            available=runner is not None,
            license="Apache-2.0",
            scope_note=(
                "支持多音识别；按 ADR-0001 通过独立 Python 环境或 basic-pitch CLI 隔离调用。"
            ),
            details={
                "runner": runner,
                "python_env": BASIC_PITCH_PYTHON_ENV,
                "cli_env": BASIC_PITCH_CLI_ENV,
                "platform": sys.platform,
            },
        )

    def transcribe(
        self,
        audio_path: Path,
        options: TranscribeOptions | None = None,
        on_progress: ProgressCallback | None = None,
        stop_token: StopToken | None = None,
    ) -> TranscriptionResult:
        return run_isolated_transcriber(
            engine_id=self.id,
            display_name="Basic Pitch",
            runner=_resolve_runner(),
            missing_hint=(
                f"Basic Pitch is not installed; configure {BASIC_PITCH_PYTHON_ENV} "
                "or install 'basic-pitch' in an isolated environment"
            ),
            audio_path=audio_path,
            build_cmd=lambda base, wav_in, out_dir: [*base, str(out_dir), str(wav_in)],
            options=options,
            on_progress=on_progress,
            stop_token=stop_token,
        )
