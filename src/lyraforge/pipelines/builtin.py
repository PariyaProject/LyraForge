"""Built-in transcription pipelines: direct baseline and vocal-separated stems."""

from __future__ import annotations

import math
import struct
import tempfile
import wave
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.music_core.cleanup import (
    CleanupOptions,
    clean_score,
    merge_stem_scores,
    vocal_cleanup_options,
)
from lyraforge.music_core.midi_export import score_to_midi_bytes
from lyraforge.music_core.midi_import import parse_midi_bytes
from lyraforge.music_core.models import NormalizedScore
from lyraforge.pipelines.base import (
    PipelineInfo,
    PipelineRequest,
    PipelineResult,
)
from lyraforge.playback.guards import StopToken
from lyraforge.separators import get_separator
from lyraforge.transcribers import (
    DEFAULT_TRANSCRIBER_ID,
    ProgressCallback,
    TranscribeOptions,
    Transcriber,
    get_transcriber,
    list_transcribers,
)

VOCAL_RANGE_PRESETS: dict[str, tuple[int, int, float, float]] = {
    "auto": (38, 93, 73.0, 1760.0),    # D2..A6 wide vocal range (baritone G2..anime soprano)
    "male": (36, 77, 65.0, 700.0),     # C2..F5
    "female": (51, 93, 155.0, 1760.0), # Eb3..A6
}
_MONOPHONIC_ENGINE_IDS = frozenset({"builtin-mono", "swift-f0"})


def _extract_wav_db_envelope(wav_path: Path | None, hop_ms: int = 500) -> list[float]:
    """Compute per-frame dBFS envelope (clamped to [-60.0, 0.0]) from a local PCM WAV."""
    if wav_path is None or not wav_path.is_file():
        return []
    try:
        with wave.open(str(wav_path), "rb") as wf:
            channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            sr = wf.getframerate()
            nframes = wf.getnframes()
            if channels <= 0 or sr <= 0 or nframes <= 0 or sampwidth not in {1, 2, 3, 4}:
                return []
            hop_frames = max(1, int(round(sr * hop_ms / 1000.0)))
            out_db: list[float] = []
            while True:
                raw = wf.readframes(hop_frames)
                if not raw:
                    break
                if sampwidth == 1:
                    vals = [(b - 128) / 128.0 for b in raw]
                elif sampwidth == 2:
                    cnt = len(raw) // 2
                    vals = [v / 32768.0 for v in struct.unpack(f"<{cnt}h", raw)]
                elif sampwidth == 3:
                    vals = []
                    for idx in range(0, len(raw) - 2, 3):
                        v = raw[idx] | (raw[idx + 1] << 8) | (raw[idx + 2] << 16)
                        if v & 0x800000:
                            v -= 0x1000000
                        vals.append(v / 8388608.0)
                else:
                    cnt = len(raw) // 4
                    vals = [v / 2147483648.0 for v in struct.unpack(f"<{cnt}i", raw)]
                if not vals:
                    continue
                mean_sq = sum(x * x for x in vals) / len(vals)
                rms = math.sqrt(mean_sq)
                db = -60.0 if rms <= 1e-3 else max(-60.0, min(0.0, 20.0 * math.log10(rms)))
                out_db.append(round(db, 1))
            return out_db
    except Exception:
        return []


def _check_stop(stop_token: StopToken | None) -> None:
    if stop_token is not None and stop_token.stopped:
        raise LyraError(ErrorCode.PLAYBACK_ABORTED, stop_token.reason or "transcription cancelled")


def _sub_progress(
    on_progress: ProgressCallback | None,
    lo: float,
    hi: float,
    stage: str | None = None,
) -> ProgressCallback | None:
    if on_progress is None:
        return None
    span = max(0.0, hi - lo)

    def _emit(frac: float, sub_stage: str) -> None:
        clamped = max(0.0, min(1.0, frac))
        on_progress(lo + clamped * span, stage or sub_stage)

    return _emit


def _available_engine_ids() -> set[str]:
    return {m.id for m in list_transcribers() if m.available}


def _pick_vocal_engine(requested: str | None) -> str:
    if requested and requested != "auto":
        return requested
    avail = _available_engine_ids()
    if "swift-f0" in avail:
        return "swift-f0"
    if "basic-pitch" in avail:
        return "basic-pitch"
    return DEFAULT_TRANSCRIBER_ID


def _pick_accomp_engine(requested: str | None) -> str | None:
    if requested and requested != "auto":
        return requested
    avail = _available_engine_ids()
    if "dettato" in avail:
        return "dettato"
    if "basic-pitch" in avail:
        return "basic-pitch"
    return None


def _vocal_options(
    base: TranscribeOptions,
    *,
    range_preset: str = "auto",
    engine_id: str = "basic-pitch",
) -> TranscribeOptions:
    key = (range_preset or "auto").strip().lower()
    if key not in VOCAL_RANGE_PRESETS:
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            f"unknown vocal range preset: {range_preset!r}",
            {"available": list(VOCAL_RANGE_PRESETS)},
        )
    p_lo, p_hi, hz_lo, hz_hi = VOCAL_RANGE_PRESETS[key]
    if key == "auto":
        min_pitch = min(base.min_pitch, p_lo) if base.min_pitch != 36 else p_lo
        max_pitch = max(base.max_pitch, p_hi) if base.max_pitch != 96 else p_hi
    else:
        min_pitch = p_lo
        max_pitch = p_hi

    if base.min_note_ms != 60:
        min_note_ms = base.min_note_ms
    elif engine_id == "swift-f0":
        min_note_ms = 55
    else:
        min_note_ms = 45

    opts = TranscribeOptions(
        min_pitch=min_pitch,
        max_pitch=max_pitch,
        min_note_ms=min_note_ms,
        onset_rms_threshold=base.onset_rms_threshold,
        timeout_s=base.timeout_s,
        onset_threshold=base.onset_threshold if base.onset_threshold is not None else 0.58,
        frame_threshold=base.frame_threshold if base.frame_threshold is not None else 0.35,
        min_frequency_hz=(
            base.min_frequency_hz if base.min_frequency_hz is not None else hz_lo
        ),
        max_frequency_hz=(
            base.max_frequency_hz if base.max_frequency_hz is not None else hz_hi
        ),
    )
    opts.validate()
    return opts


def _run_engine(
    engine_id: str,
    wav_path: Path,
    options: TranscribeOptions,
    cleanup_opts: CleanupOptions | None,
    *,
    on_progress: ProgressCallback | None,
    stop_token: StopToken | None,
    transcriber_resolver: Callable[[str], Transcriber] | None = None,
) -> tuple[bytes, NormalizedScore, NormalizedScore, str, dict[str, int], tuple[str, ...]]:
    resolver = transcriber_resolver or get_transcriber
    transcriber = resolver(engine_id)
    res = transcriber.transcribe(
        wav_path,
        options=options,
        on_progress=on_progress,
        stop_token=stop_token,
    )
    raw_score = parse_midi_bytes(res.midi_bytes)
    cleaned_score, clean_stats = clean_score(raw_score, cleanup_opts)
    return (
        res.midi_bytes,
        raw_score,
        cleaned_score,
        res.engine_version,
        clean_stats,
        res.warnings,
    )


class DirectPipeline:
    """Original full-mix audio transcription flow (preserved verbatim as default)."""

    id = "direct"

    def probe(self) -> PipelineInfo:
        return PipelineInfo(
            id=self.id,
            display_name="经典直转（原流程）",
            description="直接把音频送入所选转谱引擎识别，速度快，与原有行为完全一致。",
            recommended_for="纯钢琴 / 独奏 / BGM / 现成简单混音",
            stages=("音频提取", "单引擎转谱", "常规清理入库"),
            required_tools=(),
            available=True,
            missing_tools=(),
            default_engine_id=DEFAULT_TRANSCRIBER_ID,
            default_arranger_strategy="classic",
            supports_engine_override=True,
            low_resource_available=True,
        )

    def run(
        self,
        wav_path: Path,
        request: PipelineRequest,
        *,
        on_progress: ProgressCallback | None = None,
        stop_token: StopToken | None = None,
    ) -> PipelineResult:
        _check_stop(stop_token)
        opts = request.options
        opts.validate()
        engine_id = request.engine_id or DEFAULT_TRANSCRIBER_ID
        raw_bytes, _raw_score, cleaned_score, engine_ver, clean_stats, eng_warnings = _run_engine(
            engine_id,
            wav_path,
            opts,
            None,
            on_progress=on_progress,
            stop_token=stop_token,
            transcriber_resolver=request.transcriber_resolver,
        )
        cleaned_bytes = score_to_midi_bytes(cleaned_score)
        _check_stop(stop_token)
        return PipelineResult(
            pipeline_id=self.id,
            engine_id=engine_id,
            engine_version=engine_ver,
            raw_midi_bytes=raw_bytes,
            cleaned_score=cleaned_score,
            cleaned_midi_bytes=cleaned_bytes,
            metadata={
                "mode": "direct",
                "engines": {"primary": {"id": engine_id, "version": engine_ver}},
                "cleanup_stats": clean_stats,
                "degraded_mode": False,
                "warnings": list(eng_warnings),
            },
        )


_SPLIT_SPECS: dict[Literal["full", "lead", "accomp"], dict[str, object]] = {
    "full": {
        "id": "vocal_split_full",
        "display_name": "人声分离 · 主旋律 + 无鼓伴奏双轨",
        "description": (
            "先用 Demucs 拆分 4 轨并自动丢弃鼓组；干人声走人声参数识别与颤音清洗，"
            "去鼓伴奏独立转谱后合并成双角色多轨 MIDI。"
        ),
        "recommended_for": "华语/日语人声流行歌、二次元主题曲（推荐对比）",
        "stages": (
            "Demucs 4 轨分离与去鼓",
            "人声主旋律识别与颤音清洗",
            "无鼓伴奏识别",
            "双角色多轨 MIDI 融合",
        ),
        "default_arranger_strategy": "vocal_lead",
    },
    "lead": {
        "id": "vocal_split_lead",
        "display_name": "人声分离 · 纯人声主旋律",
        "description": "分离后仅转录干人声并消除颤音碎击，输出干净的单轨人声主旋律 MIDI。",
        "recommended_for": "复杂编曲流行歌、只想弹出最清晰原唱旋律",
        "stages": ("Demucs 人声提取", "人声主旋律识别", "颤音碎片合并"),
        "default_arranger_strategy": "vocal_lead",
    },
    "accomp": {
        "id": "vocal_split_accomp",
        "display_name": "人声分离 · 纯无鼓伴奏",
        "description": "分离后去掉人声与鼓组，仅把 bass + other 伴奏合流转为纯伴奏 MIDI。",
        "recommended_for": "纯伴奏弹唱打底、双人合奏（伴奏轨）",
        "stages": ("Demucs 伴奏提取与去鼓", "伴奏多音转谱", "常规清理入库"),
        "default_arranger_strategy": "classic",
    },
}


class VocalSplitPipeline:
    """Demucs source-separation + role-specific multi-stem transcription pipeline."""

    def __init__(self, mode: Literal["full", "lead", "accomp"]) -> None:
        self.mode: Literal["full", "lead", "accomp"] = mode
        meta = _SPLIT_SPECS[mode]
        self.id = str(meta["id"])
        self._meta = meta

    def probe(self) -> PipelineInfo:
        sep_info = get_separator("demucs").probe()
        sep_ok = sep_info.available
        missing: list[str] = [] if sep_ok else ["demucs"]
        warnings: list[str] = []

        vocal_default = _pick_vocal_engine(None) if self.mode != "accomp" else None
        accomp_default = _pick_accomp_engine(None) if self.mode != "lead" else None

        available = sep_ok
        low_resource_available = sep_ok
        if self.mode in {"full", "accomp"} and accomp_default is None:
            available = False
            missing.append("dettato/basic-pitch")
            warnings.append(
                "未安装多音伴奏引擎（dettato 或 Basic Pitch）；自动多音伴奏不可用。"
                "请先安装其一，或手动选择内置单音低资源模式（仅单音，不支持和弦）。"
            )
        if self.mode in {"full", "lead"} and vocal_default == "builtin-mono":
            warnings.append(
                "当前人声主旋律将使用内置单音 YIN 基线；建议在设置中安装轻量 SwiftF0（35 MB）"
                "或 Basic Pitch 以显著提升旋律准确率。"
            )

        primary_default = (
            "+".join(e for e in (vocal_default, accomp_default) if e)
            or vocal_default
            or accomp_default
            or DEFAULT_TRANSCRIBER_ID
        )
        return PipelineInfo(
            id=self.id,
            display_name=str(self._meta["display_name"]),
            description=str(self._meta["description"]),
            recommended_for=str(self._meta["recommended_for"]),
            stages=tuple(self._meta["stages"]),  # type: ignore[arg-type]
            required_tools=tuple(missing) if missing else ("demucs",),
            available=available,
            missing_tools=tuple(missing),
            default_engine_id=primary_default,
            default_vocal_engine_id=vocal_default,
            default_accomp_engine_id=accomp_default,
            default_arranger_strategy=str(self._meta["default_arranger_strategy"]),
            supports_engine_override=False,
            resolved_vocal_engine_id=vocal_default,
            resolved_accomp_engine_id=accomp_default,
            low_resource_available=low_resource_available,
            warnings=tuple(warnings),
        )

    def run(
        self,
        wav_path: Path,
        request: PipelineRequest,
        *,
        on_progress: ProgressCallback | None = None,
        stop_token: StopToken | None = None,
    ) -> PipelineResult:
        _check_stop(stop_token)
        opts = request.options
        opts.validate()

        # Pre-validate engines and presets before spending time in Demucs separation.
        vocal_engine: str | None = None
        vocal_opts: TranscribeOptions | None = None
        vocal_clean_opts: CleanupOptions | None = None
        if self.mode in {"full", "lead"}:
            vocal_engine = _pick_vocal_engine(request.vocal_engine_id)
            vocal_opts = _vocal_options(
                opts, range_preset=request.vocal_range, engine_id=vocal_engine
            )
            vocal_clean_opts = vocal_cleanup_options(
                request.vocal_cleanup, min_note_ms=vocal_opts.min_note_ms
            )

        accomp_engine: str | None = None
        if self.mode in {"full", "accomp"}:
            accomp_engine = _pick_accomp_engine(request.accomp_engine_id)
            if accomp_engine is None:
                raise LyraError(
                    ErrorCode.MODEL_MISSING,
                    "vocal_split accompaniment requires a polyphonic engine "
                    "(dettato or basic-pitch); install one in Settings -> Toolchain or explicitly "
                    "choose accomp_engine_id='builtin-mono' for low-resource monophonic mode",
                )

        separator = get_separator("demucs")

        with tempfile.TemporaryDirectory(prefix=f"lyraforge-{self.id}-") as tmpdir:
            sep_dir = Path(tmpdir) / "stems"
            stems = separator.separate(
                wav_path,
                sep_dir,
                on_progress=_sub_progress(on_progress, 0.05, 0.45, "separating"),
                stop_token=stop_token,
            )
            _check_stop(stop_token)

            raw_parts: list[tuple[str, NormalizedScore, int]] = []
            clean_parts: list[tuple[str, NormalizedScore, int]] = []
            used_engines: list[str] = []
            engine_meta: dict[str, dict[str, Any]] = {}
            cleanup_stats: dict[str, dict[str, int]] = {}
            warnings: list[str] = [str(w) for w in (stems.metadata.get("warnings") or ())]
            degraded_mode = False
            degraded_reasons: list[str] = []
            direct_raw_bytes: bytes | None = None

            if self.mode in {"full", "lead"}:
                assert vocal_engine is not None and vocal_opts is not None
                if stems.vocals is None or not stems.vocals.is_file():
                    raise LyraError(
                        ErrorCode.TRANSCRIPTION_FAILED,
                        "Demucs did not produce vocals.wav stem",
                    )
                hi_vocal = 0.72 if self.mode == "full" else 0.92
                if on_progress is not None:
                    on_progress(0.46, "transcribing_vocal")
                try:
                    v_raw_bytes, v_raw, v_clean, v_ver, v_stats, v_warn = _run_engine(
                        vocal_engine,
                        stems.vocals,
                        vocal_opts,
                        vocal_clean_opts,
                        on_progress=_sub_progress(
                            on_progress, 0.46, hi_vocal, "transcribing_vocal"
                        ),
                        stop_token=stop_token,
                        transcriber_resolver=request.transcriber_resolver,
                    )
                    used_engines.append(vocal_engine)
                    engine_meta["vocal"] = {
                        "id": vocal_engine,
                        "version": v_ver,
                        "options": asdict(vocal_opts),
                        "range_preset": request.vocal_range,
                        "cleanup_preset": request.vocal_cleanup,
                    }
                    cleanup_stats["vocal"] = v_stats
                    warnings.extend(v_warn)
                    raw_parts.append(("Vocal Lead", v_raw, 0))
                    clean_parts.append(("Vocal Lead", v_clean, 0))
                    if self.mode == "lead":
                        direct_raw_bytes = v_raw_bytes
                except LyraError as exc:
                    if exc.code == ErrorCode.NO_PLAYABLE_NOTES and self.mode == "full":
                        warnings.append(
                            "人声分离轨未检测到有效旋律音符，已自动跳过人声轨并保留伴奏轨。"
                        )
                    else:
                        raise
                _check_stop(stop_token)

            if self.mode in {"full", "accomp"}:
                assert accomp_engine is not None
                accomp_wav = stems.accompaniment or stems.other
                if accomp_wav is None or not accomp_wav.is_file():
                    raise LyraError(
                        ErrorCode.TRANSCRIPTION_FAILED,
                        "Demucs did not produce accompaniment/no_drums stem",
                    )
                if accomp_engine in _MONOPHONIC_ENGINE_IDS:
                    degraded_mode = True
                    degraded_reasons.append(f"monophonic_accompaniment:{accomp_engine}")
                    warnings.append(
                        f"伴奏轨当前使用单音引擎 {accomp_engine}（低资源/显式降级模式），"
                        "不包含多声部和弦信息，不可视作高精度多音编曲伴奏。"
                    )
                lo_acc = 0.73 if self.mode == "full" else 0.46
                if on_progress is not None:
                    on_progress(lo_acc, "transcribing_accomp")
                a_raw_bytes, a_raw, a_clean, a_ver, a_stats, a_warn = _run_engine(
                    accomp_engine,
                    accomp_wav,
                    opts,
                    None,
                    on_progress=_sub_progress(
                        on_progress, lo_acc, 0.92, "transcribing_accomp"
                    ),
                    stop_token=stop_token,
                    transcriber_resolver=request.transcriber_resolver,
                )
                used_engines.append(accomp_engine)
                engine_meta["accomp"] = {
                    "id": accomp_engine,
                    "version": a_ver,
                    "options": asdict(opts),
                    "monophonic_override": accomp_engine in _MONOPHONIC_ENGINE_IDS,
                }
                cleanup_stats["accomp"] = a_stats
                for w in a_warn:
                    if w not in warnings:
                        warnings.append(w)
                raw_parts.append(("Accompaniment", a_raw, 1))
                clean_parts.append(("Accompaniment", a_clean, 1))
                if self.mode == "accomp":
                    direct_raw_bytes = a_raw_bytes
                _check_stop(stop_token)

            if on_progress is not None:
                on_progress(0.95, "merging")
            cleaned_score = merge_stem_scores(clean_parts)
            cleaned_midi_bytes = score_to_midi_bytes(cleaned_score)
            if self.mode == "full" or direct_raw_bytes is None:
                raw_score = merge_stem_scores(raw_parts)
                raw_midi_bytes = score_to_midi_bytes(raw_score)
            else:
                raw_midi_bytes = direct_raw_bytes

            stem_dynamics: dict[str, Any] | None = None
            vocal_db = _extract_wav_db_envelope(stems.vocals, hop_ms=500)
            accomp_wav_ref = stems.accompaniment or stems.other
            accomp_db = _extract_wav_db_envelope(accomp_wav_ref, hop_ms=500)
            if vocal_db or accomp_db:
                stem_dynamics = {
                    "hop_ms": 500,
                    "vocal_db": vocal_db,
                    "accomp_db": accomp_db,
                }

            engine_label = "+".join(dict.fromkeys(used_engines))
            sep_ver = str(stems.metadata.get("version") or "unknown")
            ver_parts = [f"demucs {sep_ver}"]
            for role, meta in engine_meta.items():
                ver_parts.append(f"{role}:{meta['id']} {meta['version']}")
            version_label = " | ".join(ver_parts)
            drums_removed = bool(stems.metadata.get("drums_removed", True))

            if on_progress is not None:
                on_progress(1.0, "completed")
            meta_out: dict[str, Any] = {
                "mode": self.mode,
                "separator": stems.metadata,
                "drums_removed": drums_removed,
                "accompaniment_source": stems.metadata.get("accompaniment_source"),
                "engines": engine_meta,
                "vocal_cleanup": request.vocal_cleanup if self.mode != "accomp" else None,
                "vocal_range": request.vocal_range if self.mode != "accomp" else None,
                "cleanup_stats": cleanup_stats,
                "degraded_mode": degraded_mode,
                "degraded_reasons": degraded_reasons,
                "warnings": list(dict.fromkeys(warnings)),
            }
            if stem_dynamics is not None:
                meta_out["stem_dynamics"] = stem_dynamics
            return PipelineResult(
                pipeline_id=self.id,
                engine_id=engine_label,
                engine_version=version_label,
                raw_midi_bytes=raw_midi_bytes,
                cleaned_score=cleaned_score,
                cleaned_midi_bytes=cleaned_midi_bytes,
                metadata=meta_out,
            )
