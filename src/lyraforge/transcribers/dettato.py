"""Isolated subprocess adapter for kobimusic/dettato (Apache-2.0, ADR-0001)."""

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

DETTATO_PYTHON_ENV = "LYRAFORGE_DETTATO_PYTHON"
DETTATO_CLI_ENV = "LYRAFORGE_DETTATO_BIN"


def _resolve_runner() -> list[str] | None:
    return resolve_runner(
        python_env=DETTATO_PYTHON_ENV,
        python_module_args=["-m", "dettato"],
        cli_env=DETTATO_CLI_ENV,
        binary_name="dettato",
    )


class DettatoSubprocessTranscriber:
    """Runs dettato inside an isolated subprocess without polluting main deps."""

    id = "dettato"

    def probe(self) -> ModelInfo:
        runner = _resolve_runner()
        return ModelInfo(
            id=self.id,
            display_name="dettato 多乐器转录 (隔离进程)",
            available=runner is not None,
            license="Apache-2.0 (代码与权重；部分辅助训练数据含非商用条款)",
            scope_note=(
                "高质量多声部/多乐器分轨模型；按 ADR-0001 通过独立环境隔离调用。"
            ),
            details={
                "runner": runner,
                "python_env": DETTATO_PYTHON_ENV,
                "cli_env": DETTATO_CLI_ENV,
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
            display_name="dettato",
            runner=_resolve_runner(),
            missing_hint=(
                f"dettato is not installed; configure {DETTATO_PYTHON_ENV} "
                "or install 'dettato' in an isolated environment"
            ),
            audio_path=audio_path,
            build_cmd=lambda base, wav_in, out_dir: [
                *base,
                str(wav_in),
                "-o",
                str(out_dir / "dettato.mid"),
            ],
            options=options,
            on_progress=on_progress,
            stop_token=stop_token,
        )
