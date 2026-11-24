"""Isolated subprocess adapter for Demucs 4-stem source separation (MIT)."""

from __future__ import annotations

import array
import json
import os
import subprocess
import sys
import wave
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.media.subprocess_utils import (
    format_log_tail,
    hidden_subprocess_kwargs,
    run_bounded_subprocess,
)
from lyraforge.playback.guards import StopToken
from lyraforge.separators.base import (
    SeparatedStems,
    SeparatorInfo,
    SeparatorProgressCallback,
)
from lyraforge.transcribers._subprocess import (
    _effective_timeout_s,
    _utf8_child_env,
    _wav_duration_s,
    probe_installed_version,
    resolve_runner,
)

DEMUCS_PYTHON_ENV = "LYRAFORGE_DEMUCS_PYTHON"
DEMUCS_CLI_ENV = "LYRAFORGE_DEMUCS_BIN"
DEMUCS_DEVICE_ENV = "LYRAFORGE_DEMUCS_DEVICE"
DEMUCS_MODEL_ENV = "LYRAFORGE_DEMUCS_MODEL"
DEFAULT_DEMUCS_MODEL = "htdemucs"

_DEVICE_PROBE = (
    "import torch;"
    "print('cuda' if torch.cuda.is_available() else "
    "('mps' if getattr(torch.backends, 'mps', None) is not None "
    "and torch.backends.mps.is_available() else 'cpu'))"
)
_DEVICE_CACHE: dict[str, str] = {}


def clear_device_cache() -> None:
    """Invalidate cached torch device probe results (e.g. after installing CUDA wheels)."""
    _DEVICE_CACHE.clear()

_DEMUCS_RUN_SCRIPT = r"""
import json, pathlib, sys
import numpy as np
import soundfile as sf
import torch
from demucs.apply import apply_model
from demucs.pretrained import get_model

wav_path, out_dir, model_name, device = sys.argv[1:5]
out_root = pathlib.Path(out_dir)
out_root.mkdir(parents=True, exist_ok=True)

audio_np, sr = sf.read(wav_path, dtype="float32", always_2d=True)
wav = torch.from_numpy(audio_np.T)  # (C, T)
if wav.shape[0] == 1:
    wav = wav.repeat(2, 1)
elif wav.shape[0] > 2:
    wav = wav[:2]

model = get_model(model_name)
model.to(device)
model.eval()

target_sr = int(getattr(model, "samplerate", sr))
if sr != target_sr:
    import torchaudio.functional as AF
    wav = AF.resample(wav, sr, target_sr)

ref = wav.mean(0)
ref_std = float(ref.std())
if ref_std > 1e-8:
    wav_norm = (wav - ref.mean()) / ref_std
else:
    wav_norm = wav

with torch.no_grad():
    sources = apply_model(
        model, wav_norm.unsqueeze(0), device=device, split=True, progress=False
    )[0]
if ref_std > 1e-8:
    sources = sources * ref_std + ref.mean()

sources_cpu = sources.detach().cpu().numpy()
raw_by_name = {}
stem_peaks = {}


def _peak_limit(arr: np.ndarray, limit: float = 0.98) -> tuple[np.ndarray, float]:
    peak = float(np.max(np.abs(arr))) if arr.size else 0.0
    if peak > limit:
        return (arr * (limit / peak)).astype(np.float32), peak
    return arr.astype(np.float32), peak


for idx, name in enumerate(model.sources):
    raw_stem = sources_cpu[idx].T.astype(np.float32)
    raw_by_name[name] = raw_stem
    safe_stem, raw_peak = _peak_limit(raw_stem)
    stem_peaks[name] = round(raw_peak, 4)
    sf.write(str(out_root / f"{name}.wav"), safe_stem, target_sr, subtype="PCM_16")

present_acc = [k for k in ("bass", "other") if k in raw_by_name]
no_drums = None
acc_source = None
if present_acc:
    for key in present_acc:
        no_drums = raw_by_name[key].copy() if no_drums is None else (no_drums + raw_by_name[key])
    acc_source = "+".join(present_acc)
    no_drums_safe, mix_peak = _peak_limit(no_drums)
    stem_peaks["no_drums"] = round(mix_peak, 4)
    sf.write(str(out_root / "no_drums.wav"), no_drums_safe, target_sr, subtype="PCM_16")

meta = {
    "actual_device": device,
    "model": model_name,
    "sample_rate": target_sr,
    "sources": list(model.sources),
    "accompaniment_source": acc_source,
    "drums_removed": bool(present_acc),
    "stem_peaks": stem_peaks,
}
(out_root / "demucs_meta.json").write_text(json.dumps(meta), encoding="utf-8")
"""


def _resolve_runner() -> list[str] | None:
    return resolve_runner(
        python_env=DEMUCS_PYTHON_ENV,
        python_module_args=["-m", "demucs"],
        cli_env=DEMUCS_CLI_ENV,
        binary_name="demucs",
    )


def resolve_device(runner: list[str]) -> str:
    """Resolve Demucs inference device: env override -> cuda/mps probe -> cpu."""
    for env_key in (DEMUCS_DEVICE_ENV, "LYRAFORGE_DETTATO_DEVICE"):
        forced = os.environ.get(env_key, "").strip().lower()
        if forced in {"cpu", "cuda", "mps"}:
            return forced
    if len(runner) < 3 or runner[1] != "-m":
        return "cpu"
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
        if res.returncode == 0 and candidate in {"cpu", "cuda", "mps"}:
            device = candidate
    except (OSError, subprocess.TimeoutExpired):
        device = "cpu"
    _DEVICE_CACHE[python] = device
    return device


def _mix_pcm16_wavs(sources: Sequence[Path], dest: Path) -> Path | None:
    """Mix existing 16-bit PCM WAV stems cleanly into one WAV using Python stdlib."""
    existing = [p for p in sources if p.is_file()]
    if not existing:
        return None
    if len(existing) == 1:
        dest.write_bytes(existing[0].read_bytes())
        return dest

    tracks: list[list[int]] = []
    params: tuple[int, int, int] | None = None
    for path in existing:
        with wave.open(str(path), "rb") as wf:
            ch, sw, sr = wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
            if sw != 2:
                return None
            if params is None:
                params = (ch, sw, sr)
            elif (ch, sw, sr) != params:
                return None
            pcm = array.array("h")
            pcm.frombytes(wf.readframes(wf.getnframes()))
            if sys.byteorder != "little":
                pcm.byteswap()
            tracks.append(list(pcm))

    assert params is not None
    length = min(len(t) for t in tracks)
    if length <= 0:
        return None
    summed = [sum(t[i] for t in tracks) for i in range(length)]
    peak = max((abs(v) for v in summed), default=0)
    scale = 32000.0 / peak if peak > 32000 else 1.0
    mixed = array.array(
        "h",
        (max(-32767, min(32767, round(v * scale))) for v in summed),
    )
    if sys.byteorder != "little":
        mixed.byteswap()
    with wave.open(str(dest), "wb") as out_wf:
        out_wf.setnchannels(params[0])
        out_wf.setsampwidth(2)
        out_wf.setframerate(params[2])
        out_wf.writeframes(mixed.tobytes())
    return dest


def _find_cli_stem(root: Path, filename: str) -> Path | None:
    direct = root / filename
    if direct.is_file():
        return direct
    for match in sorted(root.rglob(filename)):
        if match.is_file():
            return match
    return None


class DemucsSeparator:
    """Separates audio into vocals + bass + other (no_drums) + drums via Demucs."""

    id = "demucs"

    def probe(self) -> SeparatorInfo:
        runner = _resolve_runner()
        model_name = os.environ.get(DEMUCS_MODEL_ENV, "").strip() or DEFAULT_DEMUCS_MODEL
        return SeparatorInfo(
            id=self.id,
            display_name="Demucs 音源分离 (htdemucs)",
            available=runner is not None,
            license="MIT（代码；预训练权重含研究数据来源）",
            scope_note=(
                "将音频拆分为人声、低音、其他乐器与鼓组 4 轨，并混缩去鼓伴奏。"
            ),
            stems=("vocals", "no_drums", "bass", "other", "drums"),
            details={
                "runner": runner,
                "model": model_name,
                "python_env": DEMUCS_PYTHON_ENV,
                "cli_env": DEMUCS_CLI_ENV,
                "device_env": DEMUCS_DEVICE_ENV,
                "platform": sys.platform,
            },
        )

    def _build_cmd(
        self,
        runner: list[str],
        wav_path: Path,
        out_dir: Path,
        model_name: str,
        device: str,
    ) -> list[str]:
        if len(runner) >= 3 and runner[1] == "-m":
            return [
                runner[0],
                "-c",
                _DEMUCS_RUN_SCRIPT,
                str(wav_path),
                str(out_dir),
                model_name,
                device,
            ]
        return [
            *runner,
            "-n",
            model_name,
            "-d",
            device,
            "-o",
            str(out_dir),
            str(wav_path),
        ]

    def separate(
        self,
        wav_path: Path,
        out_dir: Path,
        *,
        on_progress: SeparatorProgressCallback | None = None,
        stop_token: StopToken | None = None,
        timeout_s: float = 300.0,
    ) -> SeparatedStems:
        runner = _resolve_runner()
        if runner is None:
            raise LyraError(
                ErrorCode.MODEL_MISSING,
                f"Demucs is not installed; configure {DEMUCS_PYTHON_ENV} "
                "or install 'demucs' in Settings -> Toolchain",
            )
        if stop_token is not None and stop_token.stopped:
            raise LyraError(ErrorCode.PLAYBACK_ABORTED, "source separation cancelled")

        out_dir.mkdir(parents=True, exist_ok=True)
        model_name = os.environ.get(DEMUCS_MODEL_ENV, "").strip() or DEFAULT_DEMUCS_MODEL
        device = resolve_device(runner)
        explicit_device = os.environ.get(DEMUCS_DEVICE_ENV, "").strip().lower()

        if on_progress is not None:
            on_progress(0.15, "separating")

        eff_timeout = _effective_timeout_s(
            timeout_s,
            _wav_duration_s(wav_path),
            per_audio_second=12.0,
            slack_s=300.0,
        )
        child_env = _utf8_child_env()
        child_env.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")
        child_env.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

        warnings: list[str] = []
        fallback_from_device: str | None = None
        cmd = self._build_cmd(runner, wav_path, out_dir, model_name, device)
        res = run_bounded_subprocess(
            cmd,
            work_dir=out_dir,
            prefix="demucs",
            timeout_s=eff_timeout,
            stop_token=stop_token,
            cancel_message="source separation cancelled",
            timeout_code=ErrorCode.TRANSCRIPTION_FAILED,
            timeout_message=f"Demucs timed out after {eff_timeout:.1f}s",
            env=child_env,
        )
        if stop_token is not None and stop_token.stopped:
            raise LyraError(ErrorCode.PLAYBACK_ABORTED, "source separation cancelled")
        if res.returncode != 0 and device == "mps" and not explicit_device:
            fallback_from_device = "mps"
            device = "cpu"
            warnings.append("Demucs MPS 加速运行失败，已自动回退至 CPU 分离。")
            cmd = self._build_cmd(runner, wav_path, out_dir, model_name, device)
            res = run_bounded_subprocess(
                cmd,
                work_dir=out_dir,
                prefix="demucs-cpu",
                timeout_s=eff_timeout,
                stop_token=stop_token,
                cancel_message="source separation cancelled",
                timeout_code=ErrorCode.TRANSCRIPTION_FAILED,
                timeout_message=f"Demucs timed out after {eff_timeout:.1f}s",
                env=child_env,
            )
            if stop_token is not None and stop_token.stopped:
                raise LyraError(ErrorCode.PLAYBACK_ABORTED, "source separation cancelled")

        if res.returncode != 0:
            stderr_text = format_log_tail(
                res.stderr_tail,
                res.stdout_tail,
                stderr_truncated=res.stderr_truncated,
                stderr_bytes=res.stderr_bytes,
            )
            if "torchcodec" in stderr_text.lower():
                raise LyraError(
                    ErrorCode.TRANSCRIPTION_FAILED,
                    "Demucs CLI failed because torchaudio requires TorchCodec; "
                    f"configure {DEMUCS_PYTHON_ENV} (managed Demucs venv with soundfile) instead: "
                    f"{stderr_text}",
                )
            raise LyraError(
                ErrorCode.TRANSCRIPTION_FAILED,
                f"Demucs exited with code {res.returncode}: {stderr_text}",
            )

        vocals = _find_cli_stem(out_dir, "vocals.wav")
        bass = _find_cli_stem(out_dir, "bass.wav")
        other = _find_cli_stem(out_dir, "other.wav")
        drums = _find_cli_stem(out_dir, "drums.wav")
        no_drums = _find_cli_stem(out_dir, "no_drums.wav")

        script_meta: dict[str, Any] = {}
        meta_file = out_dir / "demucs_meta.json"
        if meta_file.is_file():
            try:
                loaded = json.loads(meta_file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    script_meta = loaded
            except (OSError, ValueError):
                script_meta = {}

        accompaniment_source: str | None = (
            str(script_meta["accompaniment_source"])
            if isinstance(script_meta.get("accompaniment_source"), str)
            else None
        )
        drums_removed = bool(script_meta.get("drums_removed", False))

        if no_drums is not None and accompaniment_source is None:
            present = [n for n, p in (("bass", bass), ("other", other)) if p is not None]
            accompaniment_source = "+".join(present) if present else "no_drums"
            drums_removed = True
        elif no_drums is None:
            present_paths = [(n, p) for n, p in (("bass", bass), ("other", other)) if p is not None]
            if present_paths:
                no_drums_target = out_dir / "no_drums.wav"
                no_drums = _mix_pcm16_wavs([p for _, p in present_paths], no_drums_target)
                if no_drums is not None:
                    accompaniment_source = "+".join(n for n, _ in present_paths)
                    drums_removed = True

        if no_drums is None:
            no_vocals = _find_cli_stem(out_dir, "no_vocals.wav")
            if no_vocals is not None:
                no_drums = no_vocals
                accompaniment_source = "no_vocals_with_drums"
                drums_removed = False
                warnings.append(
                    "Demucs 回退至 no_vocals.wav，当前伴奏轨仍包含鼓声（未能移除鼓组）。"
                )

        if vocals is None and no_drums is None:
            raise LyraError(
                ErrorCode.TRANSCRIPTION_FAILED,
                "Demucs completed but produced no vocal or accompaniment stems",
            )
        if on_progress is not None:
            on_progress(0.45, "separated")

        metadata: dict[str, Any] = {
            "separator": self.id,
            "version": probe_installed_version(runner, "demucs"),
            "model": model_name,
            "device": device,
            "drums_removed": drums_removed,
            "accompaniment_source": accompaniment_source,
            "warnings": warnings,
        }
        if fallback_from_device is not None:
            metadata["fallback_from_device"] = fallback_from_device
        if script_meta.get("stem_peaks"):
            metadata["stem_peaks"] = script_meta["stem_peaks"]

        return SeparatedStems(
            vocals=vocals,
            accompaniment=no_drums,
            bass=bass,
            other=other,
            drums=drums,
            metadata=metadata,
        )
