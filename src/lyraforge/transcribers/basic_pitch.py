"""Isolated subprocess adapter for Spotify Basic Pitch (Apache-2.0, ADR-0001)."""

from __future__ import annotations

import sys
from pathlib import Path

from lyraforge.playback.guards import StopToken
from lyraforge.transcribers._subprocess import (
    probe_installed_version,
    resolve_runner,
    run_isolated_transcriber,
)
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
                "支持多音/和弦识别；在独立 Python 环境中运行，不需要装进主程序。"
            ),
            details={
                "runner": runner,
                "python_env": BASIC_PITCH_PYTHON_ENV,
                "cli_env": BASIC_PITCH_CLI_ENV,
                "polyphonic": True,
                "supported_options": [
                    "onset_threshold",
                    "frame_threshold",
                    "min_frequency_hz",
                    "max_frequency_hz",
                    "min_note_ms",
                ],
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
        opts = options or TranscribeOptions()
        opts.validate()
        runner = _resolve_runner()
        flags: list[str] = []
        if opts.onset_threshold is not None:
            flags.extend(("--onset-threshold", f"{opts.onset_threshold:.3f}"))
        if opts.frame_threshold is not None:
            flags.extend(("--frame-threshold", f"{opts.frame_threshold:.3f}"))
        if (
            opts.min_note_ms != 60
            or opts.onset_threshold is not None
            or opts.frame_threshold is not None
        ):
            flags.extend(("--minimum-note-length", f"{float(opts.min_note_ms):.1f}"))
        if opts.min_frequency_hz is not None:
            flags.extend(("--minimum-frequency", f"{opts.min_frequency_hz:.2f}"))
        if opts.max_frequency_hz is not None:
            flags.extend(("--maximum-frequency", f"{opts.max_frequency_hz:.2f}"))

        return run_isolated_transcriber(
            engine_id=self.id,
            display_name="Basic Pitch",
            runner=runner,
            missing_hint=(
                f"Basic Pitch is not installed; configure {BASIC_PITCH_PYTHON_ENV} "
                "or install 'basic-pitch' in an isolated environment"
            ),
            audio_path=audio_path,
            build_cmd=lambda base, wav_in, out_dir: [*base, *flags, str(out_dir), str(wav_in)],
            options=opts,
            on_progress=on_progress,
            stop_token=stop_token,
            timeout_per_audio_second=3.0,
            timeout_slack_s=60.0,
            engine_version=probe_installed_version(runner, "basic-pitch"),
        )
