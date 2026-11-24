"""Built-in transcription pipelines: direct baseline and vocal-separated stems."""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.music_core.cleanup import CleanupOptions, clean_score, merge_stem_scores
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
    return "basic-pitch" if "basic-pitch" in avail else DEFAULT_TRANSCRIBER_ID


def _pick_accomp_engine(requested: str | None) -> str:
    if requested and requested != "auto":
        return requested
    avail = _available_engine_ids()
    if "dettato" in avail:
        return "dettato"
    if "basic-pitch" in avail:
        return "basic-pitch"
    return DEFAULT_TRANSCRIBER_ID


def _vocal_options(base: TranscribeOptions) -> TranscribeOptions:
    opts = TranscribeOptions(
        min_pitch=max(base.min_pitch, 45),
        max_pitch=min(base.max_pitch, 88) if base.max_pitch > 45 else base.max_pitch,
        min_note_ms=max(base.min_note_ms, 55),
        onset_rms_threshold=base.onset_rms_threshold,
        timeout_s=base.timeout_s,
        onset_threshold=base.onset_threshold if base.onset_threshold is not None else 0.58,
        frame_threshold=base.frame_threshold if base.frame_threshold is not None else 0.35,
        min_frequency_hz=base.min_frequency_hz if base.min_frequency_hz is not None else 110.0,
        max_frequency_hz=base.max_frequency_hz if base.max_frequency_hz is not None else 1400.0,
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
) -> tuple[bytes, NormalizedScore, NormalizedScore, str]:
    resolver = transcriber_resolver or get_transcriber
    transcriber = resolver(engine_id)
    res = transcriber.transcribe(
        wav_path,
        options=options,
        on_progress=on_progress,
        stop_token=stop_token,
    )
    raw_score = parse_midi_bytes(res.midi_bytes)
    cleaned_score, _ = clean_score(raw_score, cleanup_opts)
    return res.midi_bytes, raw_score, cleaned_score, res.engine_version


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
        raw_bytes, _raw_score, cleaned_score, engine_ver = _run_engine(
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
            metadata={"mode": "direct"},
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
        missing = () if sep_info.available else ("demucs",)
        vocal_default = _pick_vocal_engine(None)
        accomp_default = _pick_accomp_engine(None)
        primary_default = accomp_default if self.mode == "accomp" else vocal_default
        return PipelineInfo(
            id=self.id,
            display_name=str(self._meta["display_name"]),
            description=str(self._meta["description"]),
            recommended_for=str(self._meta["recommended_for"]),
            stages=tuple(self._meta["stages"]),  # type: ignore[arg-type]
            required_tools=("demucs",),
            available=sep_info.available,
            missing_tools=missing,
            default_engine_id=primary_default,
            default_vocal_engine_id=vocal_default if self.mode != "accomp" else None,
            default_accomp_engine_id=accomp_default if self.mode != "lead" else None,
            default_arranger_strategy=str(self._meta["default_arranger_strategy"]),
            supports_engine_override=False,
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
            direct_raw_bytes: bytes | None = None

            if self.mode in {"full", "lead"}:
                if stems.vocals is None or not stems.vocals.is_file():
                    raise LyraError(
                        ErrorCode.TRANSCRIPTION_FAILED,
                        "Demucs did not produce vocals.wav stem",
                    )
                vocal_engine = _pick_vocal_engine(request.vocal_engine_id or request.engine_id)
                vocal_clean_opts = CleanupOptions(
                    min_note_ms=max(opts.min_note_ms, 55),
                    merge_vibrato_gap_ms=70,
                )
                hi_vocal = 0.72 if self.mode == "full" else 0.92
                if on_progress is not None:
                    on_progress(0.46, "transcribing_vocal")
                v_raw_bytes, v_raw, v_clean, _ = _run_engine(
                    vocal_engine,
                    stems.vocals,
                    _vocal_options(opts),
                    vocal_clean_opts,
                    on_progress=_sub_progress(
                        on_progress, 0.46, hi_vocal, "transcribing_vocal"
                    ),
                    stop_token=stop_token,
                    transcriber_resolver=request.transcriber_resolver,
                )
                used_engines.append(vocal_engine)
                raw_parts.append(("Vocal Lead", v_raw, 0))
                clean_parts.append(("Vocal Lead", v_clean, 0))
                if self.mode == "lead":
                    direct_raw_bytes = v_raw_bytes
                _check_stop(stop_token)

            if self.mode in {"full", "accomp"}:
                accomp_wav = stems.accompaniment or stems.other
                if accomp_wav is None or not accomp_wav.is_file():
                    raise LyraError(
                        ErrorCode.TRANSCRIPTION_FAILED,
                        "Demucs did not produce accompaniment/no_drums stem",
                    )
                accomp_engine = _pick_accomp_engine(
                    request.accomp_engine_id
                    or (request.engine_id if self.mode == "accomp" else None)
                )
                lo_acc = 0.73 if self.mode == "full" else 0.46
                if on_progress is not None:
                    on_progress(lo_acc, "transcribing_accomp")
                a_raw_bytes, a_raw, a_clean, _ = _run_engine(
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

            engine_label = "+".join(dict.fromkeys(used_engines))
            if on_progress is not None:
                on_progress(1.0, "completed")
            return PipelineResult(
                pipeline_id=self.id,
                engine_id=engine_label,
                engine_version="demucs+sub",
                raw_midi_bytes=raw_midi_bytes,
                cleaned_score=cleaned_score,
                cleaned_midi_bytes=cleaned_midi_bytes,
                metadata={
                    "mode": self.mode,
                    "separator": stems.metadata,
                    "engines": list(used_engines),
                },
            )
