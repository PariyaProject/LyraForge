"""Built-in one-click arrangement presets.

These are the default way to get a good arrangement without an agent, an LLM or any
network call: each preset is a validated :class:`ArrangeOptions` bundle for one built-in
instrument profile (style, transposition policy, arpeggiation and speed).
"""

from __future__ import annotations

from dataclasses import dataclass

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.instruments import list_profile_ids, load_builtin_profile
from lyraforge.music_core.arranger import (
    ArrangeOptions,
    SemitonePolicy,
    Style,
)


@dataclass(frozen=True, slots=True)
class ArrangePreset:
    id: str
    profile_id: str
    name: str
    name_en: str
    description: str
    style: Style
    transpose: int | None = None
    arpeggiate_ms: int = 0
    speed: float = 1.0
    semitone_policy: SemitonePolicy = SemitonePolicy.NEAREST
    max_chord_keys: int | None = None

    def options(self) -> ArrangeOptions:
        return ArrangeOptions(
            style=self.style,
            transpose=self.transpose,
            semitone_policy=self.semitone_policy,
            max_chord_keys=self.max_chord_keys,
            arpeggiate_ms=self.arpeggiate_ms,
            speed=self.speed,
        )

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.id,
            "profile_id": self.profile_id,
            "name": self.name,
            "name_en": self.name_en,
            "description": self.description,
            "style": str(self.style),
            "transpose": self.transpose,
            "arpeggiate_ms": self.arpeggiate_ms,
            "speed": self.speed,
            "semitone_policy": str(self.semitone_policy),
            "max_chord_keys": self.max_chord_keys,
        }


_PROFILE_IDS: tuple[str, ...] = (
    "genshin.harmonic_keys.v1",
    "genshin.windsong_lyre.v1",
    "genshin.floral_zither.v1",
    "genshin.vintage_lyre.v1",
)

_VARIANTS: tuple[dict[str, object], ...] = (
    {
        "suffix": "melody",
        "name": "主旋律优先",
        "name_en": "Melody first",
        "description": "只保留主旋律与必要低音，最容易在游戏里弹准。",
        "style": Style.MELODY,
        "arpeggiate_ms": 0,
        "speed": 1.0,
    },
    {
        "suffix": "balanced",
        "name": "均衡",
        "name_en": "Balanced",
        "description": "主旋律 + 三音和弦，默认推荐。",
        "style": Style.BALANCED,
        "arpeggiate_ms": 12,
        "speed": 1.0,
    },
    {
        "suffix": "rich",
        "name": "丰满",
        "name_en": "Rich",
        "description": "最多六音和弦并琶音展开，适合慢曲与副歌。",
        "style": Style.RICH,
        "arpeggiate_ms": 24,
        "speed": 1.0,
    },
    {
        "suffix": "slow",
        "name": "慢速练习",
        "name_en": "Slow practice",
        "description": "主旋律优先并放慢到 0.85 倍，便于跟弹练习。",
        "style": Style.MELODY,
        "arpeggiate_ms": 0,
        "speed": 0.85,
    },
    {
        "suffix": "lively",
        "name": "轻快",
        "name_en": "Lively",
        "description": "均衡编曲并提速到 1.15 倍，适合节奏明快的曲子。",
        "style": Style.BALANCED,
        "arpeggiate_ms": 8,
        "speed": 1.15,
    },
)


def _build_presets() -> tuple[ArrangePreset, ...]:
    items: list[ArrangePreset] = []
    for profile_id in _PROFILE_IDS:
        profile = load_builtin_profile(profile_id)
        name = profile.display_name
        name_en = str(profile.raw.get("display_name_en") or profile_id)
        for variant in _VARIANTS:
            suffix = str(variant["suffix"])
            items.append(
                ArrangePreset(
                    id=f"{profile_id}.{suffix}",
                    profile_id=profile_id,
                    name=f"{name} · {variant['name']}",
                    name_en=f"{name_en} · {variant['name_en']}",
                    description=str(variant["description"]),
                    style=Style(str(variant["style"])),
                    arpeggiate_ms=int(variant["arpeggiate_ms"]),  # type: ignore[arg-type]
                    speed=float(variant["speed"]),  # type: ignore[arg-type]
                )
            )
    return tuple(items)


PRESETS: tuple[ArrangePreset, ...] = _build_presets()
_BY_ID: dict[str, ArrangePreset] = {preset.id: preset for preset in PRESETS}


def list_presets(profile_id: str | None = None) -> list[dict[str, object]]:
    """Return presets (optionally for one instrument profile) as JSON-ready dicts."""
    if profile_id is not None and profile_id not in list_profile_ids():
        raise LyraError(
            ErrorCode.PROFILE_INVALID,
            f"unknown instrument profile: {profile_id}",
            {"available": list_profile_ids()},
        )
    return [
        preset.to_json()
        for preset in PRESETS
        if profile_id is None or preset.profile_id == profile_id
    ]


def get_preset(preset_id: str) -> ArrangePreset:
    preset = _BY_ID.get(preset_id)
    if preset is None:
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            f"unknown arrangement preset: {preset_id}",
            {"available": sorted(_BY_ID)},
        )
    return preset


def preset_options(preset_id: str) -> ArrangeOptions:
    """Return validated :class:`ArrangeOptions` for a preset id."""
    options = get_preset(preset_id).options()
    options.validate()
    return options


__all__ = [
    "PRESETS",
    "ArrangePreset",
    "get_preset",
    "list_presets",
    "preset_options",
]
