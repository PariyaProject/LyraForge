"""Safe AI Agent orchestrator with explicit tool allowlist and self-optimization."""

from __future__ import annotations

import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from lyraforge.agent.llm import AgentIntent, LLMProvider, resolve_llm_provider
from lyraforge.errors import ErrorCode, LyraError
from lyraforge.library.store import ArrangementRecord, LibraryStore
from lyraforge.music_core.arranger import ArrangeOptions, Style
from lyraforge.sources.local import MIDI_EXTENSIONS, LocalLibrarySourceAdapter, classify_extension
from lyraforge.sources.url import DirectUrlSourceAdapter, validate_public_http_url

ALLOWED_TOOLS: tuple[dict[str, str], ...] = (
    {"name": "library.search", "description": "检索本地 SQLite 曲库"},
    {"name": "source.search", "description": "搜索本地目录与用户显式传入来源"},
    {"name": "source.import_local", "description": "导入本地 MIDI 或音视频文件"},
    {"name": "source.import_url", "description": "经明确授权后从公网直链下载并校验来源"},
    {"name": "transcribe.run", "description": "将无 MIDI 的音频曲目转谱为 MIDI"},
    {"name": "arrange.run", "description": "按目标乐器生成可执行改编"},
    {"name": "arrange.compare", "description": "按质量评分模型对比候选版本并择优"},
    {"name": "preview.render", "description": "离线合成 WAV 试听音频"},
    {"name": "arrangement.favorite", "description": "收藏保留选定编曲版本"},
)

FORBIDDEN_TOOLS: tuple[str, ...] = ("playback.start", "playback.windows")

QUALITY_REARRANGE_THRESHOLD = 78.0
_REARRANGE_WARNING_TRIGGERS = frozenset({
    "dense_key_conflicts",
    "high_note_drop_rate",
    "many_semitone_substitutions",
})


@dataclass(frozen=True, slots=True)
class AgentStep:
    tool: str
    status: str
    detail: str
    output: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentRunResult:
    status: str  # "completed" | "needs_confirmation" | "not_found"
    provider: str
    intent: dict[str, Any]
    steps: tuple[AgentStep, ...]
    candidates: tuple[dict[str, Any], ...]
    selected_song: dict[str, Any] | None
    selected_arrangement: dict[str, Any] | None
    comparison: dict[str, Any] | None
    preview_url: str | None
    requires_confirmation: bool
    confirmation_prompt: str | None
    message: str

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "provider": self.provider,
            "intent": self.intent,
            "steps": [s.to_json() for s in self.steps],
            "candidates": list(self.candidates),
            "selected_song": self.selected_song,
            "selected_arrangement": self.selected_arrangement,
            "comparison": self.comparison,
            "preview_url": self.preview_url,
            "requires_confirmation": self.requires_confirmation,
            "confirmation_prompt": self.confirmation_prompt,
            "message": self.message,
        }


class AgentOrchestrator:
    """Executes user-authorized natural-language arrangement workflows end-to-end."""

    def __init__(
        self,
        store: LibraryStore,
        *,
        provider: LLMProvider | None = None,
        search_dirs: Sequence[str | Path] = (),
        url_adapter: DirectUrlSourceAdapter | None = None,
    ) -> None:
        self.store = store
        self.provider = provider or resolve_llm_provider(store.get_settings())
        self.local_adapter = LocalLibrarySourceAdapter(store=store, search_dirs=search_dirs)
        self.url_adapter = url_adapter or DirectUrlSourceAdapter()

    def _build_context(self, arrangement_id: str | None) -> dict[str, Any]:
        if not arrangement_id:
            return {}
        rec = self.store.get_arrangement(arrangement_id)
        return {
            "arrangement_id": rec.id,
            "song_id": rec.song_id,
            "instrument_profile_id": rec.profile_id,
            "style": rec.style,
            "current_transpose": rec.transpose,
            "speed": rec.speed,
        }

    def _import_path(self, path: Path, steps: list[AgentStep]) -> str:
        kind = classify_extension(path.suffix)
        res = (
            self.store.import_midi(path)
            if kind == "midi"
            else self.store.import_audio(path)
        )
        steps.append(
            AgentStep(
                tool="source.import_local",
                status="ok",
                detail=f"导入{kind.upper()}来源：{res.song.title}",
                output={"song_id": res.song.id, "deduplicated": res.deduplicated},
            )
        )
        return res.song.id

    def _maybe_optimize_arrangement(
        self,
        song_id: str,
        intent: AgentIntent,
        primary: ArrangementRecord,
        base_opts: ArrangeOptions,
        steps: list[AgentStep],
    ) -> tuple[ArrangementRecord, dict[str, Any] | None]:
        report = self.store.load_arrangement_report(primary.id)
        quality = report.get("quality") or {}
        score_val = float(quality.get("overall_score", 0.0))
        warnings = set(quality.get("warnings") or [])
        needs_retry = (
            intent.action == "compare"
            or score_val < QUALITY_REARRANGE_THRESHOLD
            or bool(warnings & _REARRANGE_WARNING_TRIGGERS)
        )
        if not needs_retry:
            return primary, None

        candidates_opts: list[tuple[str, ArrangeOptions]] = []
        if base_opts.style != Style.MELODY:
            candidates_opts.append(
                (
                    "Agent 优化 · 主旋律简化",
                    ArrangeOptions(
                        style=Style.MELODY,
                        transpose=base_opts.transpose,
                        semitone_policy=base_opts.semitone_policy,
                        speed=base_opts.speed,
                        arpeggiate_ms=0,
                        prefer_melody_track=True,
                    ),
                )
            )
        if base_opts.arpeggiate_ms == 0 and base_opts.style != Style.MELODY:
            candidates_opts.append(
                (
                    "Agent 优化 · 轻微琶音分时",
                    ArrangeOptions(
                        style=base_opts.style,
                        transpose=base_opts.transpose,
                        semitone_policy=base_opts.semitone_policy,
                        speed=base_opts.speed,
                        arpeggiate_ms=20,
                        prefer_melody_track=True,
                    ),
                )
            )
        best = primary
        last_cmp: dict[str, Any] | None = None
        for label, cand_opts in candidates_opts[:2]:
            cand_rec = self.store.arrange_song(
                song_id,
                profile_id=intent.instrument_profile_id,
                options=cand_opts,
                parent_id=primary.id,
                label=label,
            )
            cmp = self.store.compare_arrangements(best.id, cand_rec.id)
            last_cmp = cmp
            winner_id = cmp["winner"]
            if winner_id == cand_rec.id:
                best = cand_rec
            steps.append(
                AgentStep(
                    tool="arrange.compare",
                    status="ok",
                    detail=cmp["summary"],
                    output={
                        "winner": winner_id,
                        "score_a": cmp["score_a"],
                        "score_b": cmp["score_b"],
                    },
                )
            )
        return best, last_cmp

    def run(
        self,
        prompt: str,
        *,
        song_id: str | None = None,
        arrangement_id: str | None = None,
        allow_network: bool = False,
        local_path: str | Path | None = None,
        source_url: str | None = None,
    ) -> AgentRunResult:
        ctx = self._build_context(arrangement_id)
        intent = self.provider.parse_intent(prompt, ctx)
        steps: list[AgentStep] = []

        target_url = source_url or intent.source_url
        target_local = str(local_path) if local_path is not None else intent.local_path
        resolved_song_id = song_id or ctx.get("song_id")
        found_candidates: list[dict[str, Any]] = []

        if resolved_song_id is not None:
            self.store.get_song(resolved_song_id)
        elif target_local:
            p = Path(target_local).expanduser()
            if not p.is_file():
                raise LyraError(ErrorCode.SOURCE_UNAVAILABLE, f"local file not found: {p.name}")
            resolved_song_id = self._import_path(p, steps)
        elif target_url:
            validate_public_http_url(target_url)
            url_cands = [c.to_json() for c in self.url_adapter.search(target_url)]
            found_candidates.extend(url_cands)
            if not allow_network:
                msg = (
                    f"外部直链需要明确用户授权后才允许下载：{target_url}。"
                    "请确认您拥有访问与改编权限并勾选允许访问。"
                )
                steps.append(
                    AgentStep(
                        tool="source.import_url",
                        status="blocked",
                        detail="等待用户授权外网下载",
                        output={"url": target_url},
                    )
                )
                return AgentRunResult(
                    status="needs_confirmation",
                    provider=self.provider.provider_id,
                    intent=intent.to_json(),
                    steps=tuple(steps),
                    candidates=tuple(found_candidates),
                    selected_song=None,
                    selected_arrangement=None,
                    comparison=None,
                    preview_url=None,
                    requires_confirmation=True,
                    confirmation_prompt=msg,
                    message=msg,
                )
            with tempfile.TemporaryDirectory(prefix="lyraforge-agent-url-") as tmpdir:
                downloaded = self.url_adapter.fetch(
                    target_url, Path(tmpdir), user_authorized=True
                )
                kind = "midi" if downloaded.suffix.lower() in MIDI_EXTENSIONS else "audio"
                res = (
                    self.store.import_midi(downloaded)
                    if kind == "midi"
                    else self.store.import_audio(downloaded)
                )
                resolved_song_id = res.song.id
                steps.append(
                    AgentStep(
                        tool="source.import_url",
                        status="ok",
                        detail=f"已按用户授权下载并导入：{res.song.title}",
                        output={"song_id": resolved_song_id, "url": target_url},
                    )
                )
        else:
            cands = self.local_adapter.search(intent.query)
            found_candidates = [c.to_json() for c in cands]
            steps.append(
                AgentStep(
                    tool="library.search",
                    status="ok",
                    detail=f"检索关键词“{intent.query or '(全部)'}”，命中 {len(cands)} 项",
                    output={"count": len(cands)},
                )
            )
            if not cands:
                return AgentRunResult(
                    status="not_found",
                    provider=self.provider.provider_id,
                    intent=intent.to_json(),
                    steps=tuple(steps),
                    candidates=(),
                    selected_song=None,
                    selected_arrangement=None,
                    comparison=None,
                    preview_url=None,
                    requires_confirmation=False,
                    confirmation_prompt=None,
                    message=(
                        f"未在本地曲库中找到“{intent.query or prompt}”。"
                        "请先导入本地 MIDI/音视频，或在指令中附带经授权的公开音源直链 URL。"
                    ),
                )
            top = cands[0]
            if top.source_type == "library":
                resolved_song_id = top.id
            else:
                resolved_song_id = self._import_path(Path(top.location), steps)

        assert resolved_song_id is not None
        detail = self.store.get_song(resolved_song_id)

        if intent.action == "search":
            return AgentRunResult(
                status="completed",
                provider=self.provider.provider_id,
                intent=intent.to_json(),
                steps=tuple(steps),
                candidates=tuple(found_candidates),
                selected_song=detail.song.to_json(),
                selected_arrangement=None,
                comparison=None,
                preview_url=None,
                requires_confirmation=False,
                confirmation_prompt=None,
                message=(
                    f"已找到曲目《{detail.song.title}》，"
                    f"共 {len(found_candidates)} 个候选来源。"
                ),
            )

        has_midi = any(s.kind == "midi" for s in detail.sources)
        if not has_midi and not detail.transcriptions:
            tr = self.store.transcribe_song(resolved_song_id, engine_id="builtin-mono")
            steps.append(
                AgentStep(
                    tool="transcribe.run",
                    status="ok",
                    detail=f"完成音频转谱 ({tr.engine})：{tr.note_count} 音符",
                    output={"transcription_id": tr.id, "note_count": tr.note_count},
                )
            )

        transpose = intent.transpose
        if transpose is None and intent.transpose_delta != 0 and "current_transpose" in ctx:
            transpose = max(-48, min(48, int(ctx["current_transpose"]) + intent.transpose_delta))
        elif transpose is None and intent.transpose_delta != 0:
            transpose = max(-48, min(48, intent.transpose_delta))

        opts = ArrangeOptions(
            style=intent.style,
            transpose=transpose,
            semitone_policy=intent.semitone_policy,
            speed=intent.speed,
            arpeggiate_ms=intent.arpeggiate_ms,
            prefer_melody_track=True,
        )
        primary = self.store.arrange_song(
            resolved_song_id,
            profile_id=intent.instrument_profile_id,
            options=opts,
            parent_id=arrangement_id,
            label=f"Agent · {intent.style}",
        )
        steps.append(
            AgentStep(
                tool="arrange.run",
                status="ok",
                detail=(
                    f"生成初版编曲 ({primary.style}, 移调 {primary.transpose:+d})，"
                    f"评分 {primary.score if primary.score is not None else '-'}"
                ),
                output={"arrangement_id": primary.id, "score": primary.score},
            )
        )

        best, cmp = self._maybe_optimize_arrangement(
            resolved_song_id, intent, primary, opts, steps
        )
        self.store.render_preview(best.id)
        preview_url = f"/v1/arrangements/{best.id}/preview.wav"
        steps.append(
            AgentStep(
                tool="preview.render",
                status="ok",
                detail=f"已生成离线试听 WAV ({best.event_count} 音符)",
                output={"arrangement_id": best.id, "preview_url": preview_url},
            )
        )
        best_fresh = self.store.get_arrangement(best.id)
        song_fresh = self.store.get_song(resolved_song_id).song
        return AgentRunResult(
            status="completed",
            provider=self.provider.provider_id,
            intent=intent.to_json(),
            steps=tuple(steps),
            candidates=tuple(found_candidates),
            selected_song=song_fresh.to_json(),
            selected_arrangement=best_fresh.to_json(),
            comparison=cmp,
            preview_url=preview_url,
            requires_confirmation=False,
            confirmation_prompt=None,
            message=(
                f"已为《{song_fresh.title}》完成 {best_fresh.profile_id} 编曲与试听准备"
                f"（综合评分 {best_fresh.score or 0:.1f}，共 {best_fresh.event_count} 音；"
                "如需游戏内演奏，请在工作台手动完成两步安全确认）。"
            ),
        )
