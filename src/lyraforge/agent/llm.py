"""Configurable LLM intent providers (offline rule-based default; optional HTTP API)."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.instruments import DEFAULT_PROFILE_ID, list_profile_ids
from lyraforge.music_core.arranger import SemitonePolicy, Style
from lyraforge.secrets import redact_secret

_URL_RE = re.compile(r"(https?://[^\s<>\"']+)", re.IGNORECASE)
_PATH_RE = re.compile(
    r"([A-Za-z0-9_./\\~-]+\.(?:mid|midi|wav|mp3|flac|ogg|m4a|mp4|mkv))",
    re.IGNORECASE,
)
_QUOTED_TITLE_RE = re.compile(r"[《\"「『']([^》\"」』']{1,80})[》\"」』']")
_SPEED_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:x|倍速)", re.IGNORECASE)
_ABS_TRANSPOSE_RE = re.compile(r"(?:移调|transpose)\s*([+-]?\d+)", re.IGNORECASE)
_UP_TRANSPOSE_RE = re.compile(r"(?:升|升高|上移)\s*(\d+)\s*(?:个)?半音")
_DOWN_TRANSPOSE_RE = re.compile(r"(?:降|降低|下移)\s*(\d+)\s*(?:个)?半音")
_ARP_MS_RE = re.compile(r"(?:琶音|arpegg\w*)\s*(\d+)\s*ms", re.IGNORECASE)

_STRIP_PHRASES = (
    "只搜索",
    "仅搜索",
    "搜一下",
    "搜索",
    "查找",
    "帮我把",
    "帮我",
    "请你",
    "请",
    "找到合适的音源",
    "找到",
    "合适的音源",
    "音源",
    "转换成",
    "转成",
    "转为",
    "转化为",
    "适配成",
    "适配为",
    "适配",
    "编曲",
    "重新编曲",
    "重编",
    "优化并保存",
    "优化",
    "并保存",
    "保存",
    "并对比",
    "对比",
    "原神",
    "风物之诗琴",
    "镜花之琴",
    "诗琴",
    "主旋律优先",
    "主旋律",
    "均衡",
    "平衡",
    "丰满",
    "丰富",
    "琶音",
    "的曲谱",
    "曲谱",
    "版本",
)


@dataclass(frozen=True, slots=True)
class AgentIntent:
    action: str = "arrange"  # "search" | "arrange" | "adjust" | "compare"
    query: str = ""
    instrument_profile_id: str = DEFAULT_PROFILE_ID
    style: Style = Style.BALANCED
    transpose: int | None = None
    transpose_delta: int = 0
    speed: float = 1.0
    arpeggiate_ms: int = 0
    semitone_policy: SemitonePolicy = SemitonePolicy.NEAREST
    local_path: str | None = None
    source_url: str | None = None
    explanation: str = ""

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["style"] = str(self.style)
        data["semitone_policy"] = str(self.semitone_policy)
        return data


class LLMProvider(Protocol):
    provider_id: str

    def parse_intent(
        self,
        prompt: str,
        context: dict[str, Any] | None = None,
    ) -> AgentIntent:
        ...


class RuleBasedLLMProvider:
    """Zero-dependency deterministic Chinese/English natural-language parser."""

    provider_id = "rule-based-offline"

    def parse_intent(
        self,
        prompt: str,
        context: dict[str, Any] | None = None,
    ) -> AgentIntent:
        ctx = context or {}
        text = prompt.strip()
        if not text:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "agent prompt must not be empty")
        low = text.lower()

        source_url: str | None = None
        url_match = _URL_RE.search(text)
        if url_match:
            source_url = url_match.group(1)

        local_path: str | None = None
        if source_url is None:
            path_match = _PATH_RE.search(text)
            if path_match:
                local_path = path_match.group(1)

        profile_id = str(ctx.get("instrument_profile_id") or DEFAULT_PROFILE_ID)
        if any(tok in low for tok in ("镜花", "floral", "zither")):
            profile_id = "genshin.floral_zither.v1"
        elif any(tok in low for tok in ("风物", "诗琴", "windsong", "lyre")):
            profile_id = "genshin.windsong_lyre.v1"
        if profile_id not in list_profile_ids():
            profile_id = DEFAULT_PROFILE_ID

        style = Style.BALANCED
        if any(tok in low for tok in ("主旋律", "单音", "melody")):
            style = Style.MELODY
        elif any(tok in low for tok in ("丰满", "丰富", "和弦", "rich")):
            style = Style.RICH

        arpeggiate_ms = 0
        arp_match = _ARP_MS_RE.search(text)
        if arp_match:
            arpeggiate_ms = max(0, min(60, int(arp_match.group(1))))
        elif "琶音" in text or "arpegg" in low:
            arpeggiate_ms = 20

        transpose: int | None = None
        transpose_delta = 0
        abs_t = _ABS_TRANSPOSE_RE.search(text)
        if abs_t:
            transpose = max(-48, min(48, int(abs_t.group(1))))
        else:
            up_m = _UP_TRANSPOSE_RE.search(text)
            down_m = _DOWN_TRANSPOSE_RE.search(text)
            if up_m:
                transpose_delta = int(up_m.group(1))
            elif down_m:
                transpose_delta = -int(down_m.group(1))
            elif "高八度" in text:
                transpose_delta = 12
            elif "低八度" in text:
                transpose_delta = -12

        speed = float(ctx.get("speed") or 1.0)
        sp_m = _SPEED_RE.search(text)
        if sp_m:
            speed = max(0.25, min(4.0, float(sp_m.group(1))))
        elif any(tok in low for tok in ("慢一点", "放慢", "稍慢", "slower")):
            speed = max(0.25, round(speed * 0.85, 2))
        elif any(tok in low for tok in ("快一点", "加快", "稍快", "faster")):
            speed = min(4.0, round(speed * 1.15, 2))

        semitone_policy = SemitonePolicy.NEAREST
        if any(tok in low for tok in ("舍弃半音", "丢弃半音", "drop semitone")):
            semitone_policy = SemitonePolicy.DROP

        is_compare = any(tok in low for tok in ("对比", "比较", "a/b", "compare"))
        has_arrange_verb = any(
            tok in low
            for tok in ("编", "转", "配", "优化", "调整", "修改", "移调", "arrange", "琶音")
        )
        is_search_only = (
            any(tok in low for tok in ("搜索", "查找", "搜一下", "search"))
            and not has_arrange_verb
            and not source_url
            and not local_path
        )
        if is_compare:
            action = "compare"
        elif is_search_only:
            action = "search"
        elif ctx.get("arrangement_id") and (
            transpose_delta != 0
            or any(tok in low for tok in ("重编", "调整", "修改", "换成", "改成", "再"))
        ):
            action = "adjust"
        else:
            action = "arrange"

        query = self._extract_query(text, source_url=source_url, local_path=local_path)
        return AgentIntent(
            action=action,
            query=query,
            instrument_profile_id=profile_id,
            style=style,
            transpose=transpose,
            transpose_delta=transpose_delta,
            speed=speed,
            arpeggiate_ms=arpeggiate_ms,
            semitone_policy=semitone_policy,
            local_path=local_path,
            source_url=source_url,
            explanation=f"离线规则解析：action={action}, style={style}, profile={profile_id}",
        )

    def _extract_query(
        self,
        text: str,
        *,
        source_url: str | None,
        local_path: str | None,
    ) -> str:
        quoted = _QUOTED_TITLE_RE.search(text)
        if quoted:
            return quoted.group(1).strip()
        cleaned = text
        if source_url:
            cleaned = cleaned.replace(source_url, " ")
        if local_path:
            cleaned = cleaned.replace(local_path, " ")
        for pattern in (
            _SPEED_RE,
            _ABS_TRANSPOSE_RE,
            _UP_TRANSPOSE_RE,
            _DOWN_TRANSPOSE_RE,
            _ARP_MS_RE,
        ):
            cleaned = pattern.sub(" ", cleaned)
        for phrase in _STRIP_PHRASES:
            cleaned = cleaned.replace(phrase, " ")
        cleaned = re.sub(r"[，。、；：！？,!?;:()\[\]（）]+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned


class OpenAICompatibleLLMProvider:
    """Optional external LLM endpoint via standard HTTP JSON (no Antigravity CLI runtime)."""

    provider_id = "openai-compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: float = 15.0,
        opener: Any | None = None,
    ) -> None:
        parsed = urllib.parse.urlparse(base_url.strip())
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "llm_base_url must be a valid http(s) URL")
        if not model.strip():
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "llm_model must not be empty")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s
        self._opener = opener or urllib.request.build_opener()
        self._fallback = RuleBasedLLMProvider()

    def parse_intent(
        self,
        prompt: str,
        context: dict[str, Any] | None = None,
    ) -> AgentIntent:
        baseline = self._fallback.parse_intent(prompt, context)
        system_msg = (
            "Extract JSON intent for LyraForge music arranger with keys: "
            "action (search|arrange|adjust|compare), query, instrument_profile_id, "
            "style (melody|balanced|rich), transpose (int or null), transpose_delta (int), "
            "speed (0.25..4.0), arpeggiate_ms (0..60), explanation. Output JSON only."
        )
        payload = json.dumps({
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_msg},
                {
                    "role": "user",
                    "content": json.dumps({"prompt": prompt, "context": context or {}}),
                },
            ],
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            with self._opener.open(req, timeout=self.timeout_s) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            safe_err = redact_secret(str(exc), (self.api_key,))
            raise LyraError(
                ErrorCode.SOURCE_UNAVAILABLE, f"LLM provider request failed: {safe_err}"
            ) from exc

        try:
            content = raw["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            safe_err = redact_secret(str(exc), (self.api_key,))
            raise LyraError(
                ErrorCode.INVALID_ARGUMENT, f"LLM returned malformed JSON intent: {safe_err}"
            ) from exc

        action = parsed.get("action", baseline.action)
        if action not in {"search", "arrange", "adjust", "compare"}:
            action = baseline.action
        prof = parsed.get("instrument_profile_id", baseline.instrument_profile_id)
        if prof not in list_profile_ids():
            prof = baseline.instrument_profile_id
        try:
            style = Style(str(parsed.get("style", baseline.style)))
        except ValueError:
            style = baseline.style
        tr = parsed.get("transpose", baseline.transpose)
        if tr is not None:
            tr = max(-48, min(48, int(tr)))
        delta = max(-48, min(48, int(parsed.get("transpose_delta", baseline.transpose_delta))))
        sp = max(0.25, min(4.0, float(parsed.get("speed", baseline.speed))))
        arp = max(0, min(60, int(parsed.get("arpeggiate_ms", baseline.arpeggiate_ms))))
        return AgentIntent(
            action=action,
            query=str(parsed.get("query", baseline.query)),
            instrument_profile_id=prof,
            style=style,
            transpose=tr,
            transpose_delta=delta,
            speed=sp,
            arpeggiate_ms=arp,
            semitone_policy=baseline.semitone_policy,
            local_path=baseline.local_path,
            source_url=baseline.source_url,
            explanation=str(parsed.get("explanation", baseline.explanation)),
        )


def resolve_llm_provider(
    settings: dict[str, Any] | None = None,
    *,
    api_key: str | None = None,
) -> LLMProvider:
    """Resolve configured LLM provider; defaults safely to offline rule-based parser."""
    cfg = settings or {}
    enabled = bool(cfg.get("llm_enabled", False))
    base_url = str(cfg.get("llm_base_url") or os.environ.get("LYRAFORGE_LLM_BASE_URL", "")).strip()
    resolved_key = str(
        api_key or os.environ.get("LYRAFORGE_LLM_API_KEY", "") or cfg.get("llm_api_key", "")
    ).strip()
    model = str(cfg.get("llm_model") or os.environ.get("LYRAFORGE_LLM_MODEL", "")).strip()
    if enabled and base_url and model:
        return OpenAICompatibleLLMProvider(
            base_url=base_url, api_key=resolved_key, model=model
        )
    return RuleBasedLLMProvider()
