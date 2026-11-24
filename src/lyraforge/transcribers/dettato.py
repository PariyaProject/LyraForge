"""Isolated subprocess adapter for kobimusic/dettato (Apache-2.0)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from lyraforge.media.subprocess_utils import hidden_subprocess_kwargs
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

DETTATO_PYTHON_ENV = "LYRAFORGE_DETTATO_PYTHON"
DETTATO_CLI_ENV = "LYRAFORGE_DETTATO_BIN"
DETTATO_DEVICE_ENV = "LYRAFORGE_DETTATO_DEVICE"

# dettato 2.0.0 uses float64 tensors internally which crash on Apple Silicon MPS
# ("Cannot convert a MPS Tensor to float64 dtype"). Auto-selection probes CUDA -> CPU only.
_DEVICE_PROBE = "import torch;print('cuda' if torch.cuda.is_available() else 'cpu')"
_DEVICE_CACHE: dict[str, str] = {}


def clear_device_cache() -> None:
    """Invalidate cached torch device probe results (e.g. after installing CUDA wheels)."""
    _DEVICE_CACHE.clear()


def _resolve_runner() -> list[str] | None:
    return resolve_runner(
        python_env=DETTATO_PYTHON_ENV,
        python_module_args=["-m", "dettato"],
        cli_env=DETTATO_CLI_ENV,
        binary_name="dettato",
    )


def resolve_device(runner: list[str]) -> str:
    """Pick inference device: explicit env override, else CUDA or CPU (never auto-MPS)."""
    forced = os.environ.get(DETTATO_DEVICE_ENV, "").strip().lower()
    if forced in {"cpu", "cuda", "mps"}:
        return forced
    if len(runner) < 3 or runner[1] != "-m":
        return "cpu"  # CLI wrapper: cannot probe torch, keep the safe default
    python = runner[0]
    cached = _DEVICE_CACHE.get(python)
    if cached is not None:
        return cached
    device = "cpu"
    try:
        res = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [python, "-c", _DEVICE_PROBE],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
            **hidden_subprocess_kwargs(),
        )
        candidate = (res.stdout or "").strip()
        if res.returncode == 0 and candidate in {"cpu", "cuda"}:
            device = candidate
    except (OSError, subprocess.TimeoutExpired):
        device = "cpu"
    _DEVICE_CACHE[python] = device
    return device


def _build_cmd(base: list[str], wav_in: Path, out_dir: Path) -> list[str]:
    return [
        *base,
        str(wav_in),
        "--device",
        resolve_device(base),
        "-o",
        # dettato's -o is an output *directory*; it writes <stem>.mid there.
        str(out_dir),
    ]


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
                "高质量多声部/多乐器分轨模型；自动优先使用 CUDA，macOS 上自动使用 CPU 推理"
                "（CLI 仅支持 --device，不支持频段/门限参数）。"
            ),
            details={
                "runner": runner,
                "python_env": DETTATO_PYTHON_ENV,
                "cli_env": DETTATO_CLI_ENV,
                "device_env": DETTATO_DEVICE_ENV,
                "polyphonic": True,
                "supported_options": ["device"],
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
        runner = _resolve_runner()
        return run_isolated_transcriber(
            engine_id=self.id,
            display_name="dettato",
            runner=runner,
            missing_hint=(
                f"dettato is not installed; configure {DETTATO_PYTHON_ENV} "
                "or install 'dettato' in an isolated environment"
            ),
            audio_path=audio_path,
            build_cmd=_build_cmd,
            options=options,
            on_progress=on_progress,
            stop_token=stop_token,
            timeout_per_audio_second=10.0,
            timeout_slack_s=180.0,
            engine_version=probe_installed_version(runner, "dettato"),
        )
