"""InstrumentProfile: configurable game-instrument model (PROJECT_SPEC §4.1).

The profile is data; this module only validates and indexes it. Concrete
profiles live in ``lyraforge.instruments`` as JSON files.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.music_core.canonical import sha256_prefixed


@dataclass(frozen=True, slots=True)
class KeyDef:
    key_id: str
    pitch: int
    binding: str
    row: str = ""
    degree: int | None = None


@dataclass(frozen=True)
class Timing:
    min_same_key_interval_ms: int
    min_key_hold_ms: int
    default_key_hold_ms: int
    max_key_hold_ms: int
    provisional: bool = True
    min_key_release_gap_ms: int = 20
    min_inter_key_interval_ms: int = 0
    trigger_mode: str = "one_shot"
    sustain_decay_ms: int | None = None


@dataclass(frozen=True)
class InstrumentProfile:
    id: str
    version: int
    display_name: str
    game_id: str
    kind: str
    keys: tuple[KeyDef, ...]
    polyphony_limit: int | None
    timing: Timing
    supports_sustain: bool
    calibration_status: str
    raw: dict[str, Any] = field(repr=False, compare=False)
    hash: str = ""
    by_pitch: dict[int, KeyDef] = field(default_factory=dict, repr=False, compare=False)
    by_id: dict[str, KeyDef] = field(default_factory=dict, repr=False, compare=False)

    @property
    def pitches(self) -> tuple[int, ...]:
        return tuple(sorted(k.pitch for k in self.keys))

    @property
    def min_pitch(self) -> int:
        return min(k.pitch for k in self.keys)

    @property
    def max_pitch(self) -> int:
        return max(k.pitch for k in self.keys)

    def key_for_pitch(self, pitch: int) -> KeyDef | None:
        return self.by_pitch.get(pitch)

    def key_by_id(self, key_id: str) -> KeyDef | None:
        return self.by_id.get(key_id)


@cache
def _schema_validator() -> Draft202012Validator:
    text = resources.files("lyraforge.music_core.schemas").joinpath(
        "instrument_profile.v1.schema.json").read_text(encoding="utf-8")
    return Draft202012Validator(json.loads(text))


def profile_from_dict(data: dict[str, Any]) -> InstrumentProfile:
    if not isinstance(data, dict):
        raise LyraError(ErrorCode.PROFILE_INVALID, "profile must be a JSON object")
    problems = [
        f"{'/'.join(str(x) for x in e.absolute_path) or '<root>'}: {e.message}"
        for e in sorted(_schema_validator().iter_errors(data), key=lambda e: list(e.absolute_path))
    ]
    if problems:
        raise LyraError(ErrorCode.PROFILE_INVALID, "profile failed schema validation",
                        {"problems": problems})

    keys = tuple(
        KeyDef(key_id=k["key_id"], pitch=k["pitch"], binding=k["binding"],
               row=k.get("row", ""), degree=k.get("degree"))
        for k in data["keys"]
    )
    sem: list[str] = []
    if data["key_count"] != len(keys):
        sem.append(f"key_count={data['key_count']} but {len(keys)} keys defined")
    for attr in ("key_id", "pitch", "binding"):
        values = [getattr(k, attr) for k in keys]
        dups = sorted({v for v in values if values.count(v) > 1}, key=str)
        if dups:
            sem.append(f"duplicate {attr}: {dups}")
    t = data["timing"]
    interval_room = max(0, int(t["min_same_key_interval_ms"]) - int(t["min_key_hold_ms"]))
    default_release_gap = min(20, interval_room)
    release_gap = int(t.get("min_key_release_gap_ms", default_release_gap))
    inter_key = int(t.get("min_inter_key_interval_ms", 0))
    trigger_mode = str(t.get("trigger_mode", "one_shot"))
    sustain_decay = t.get("sustain_decay_ms")
    if not (t["min_key_hold_ms"] <= t["default_key_hold_ms"] <= t["max_key_hold_ms"]):
        sem.append("timing requires min_key_hold_ms <= default_key_hold_ms <= max_key_hold_ms")
    if t["min_same_key_interval_ms"] < t["min_key_hold_ms"]:
        sem.append("timing requires min_same_key_interval_ms >= min_key_hold_ms")
    if release_gap < 0 or t["min_key_hold_ms"] + release_gap > t["min_same_key_interval_ms"]:
        sem.append(
            "timing requires 0 <= min_key_release_gap_ms and "
            "min_key_hold_ms + min_key_release_gap_ms <= min_same_key_interval_ms"
        )
    if inter_key < 0:
        sem.append("timing requires min_inter_key_interval_ms >= 0")
    if trigger_mode not in {"one_shot", "sustained"}:
        sem.append(f"invalid trigger_mode {trigger_mode!r}")
    if data["supports_sustain"]:
        sem.append("supports_sustain=true is not implemented in arranger v0")
    if sem:
        raise LyraError(ErrorCode.PROFILE_INVALID, "profile failed semantic validation",
                        {"problems": sem})

    return InstrumentProfile(
        id=data["id"],
        version=data["version"],
        display_name=data["display_name"],
        game_id=data["game_id"],
        kind=data["kind"],
        keys=keys,
        polyphony_limit=data["polyphony_limit"],
        timing=Timing(
            min_same_key_interval_ms=t["min_same_key_interval_ms"],
            min_key_hold_ms=t["min_key_hold_ms"],
            default_key_hold_ms=t["default_key_hold_ms"],
            max_key_hold_ms=t["max_key_hold_ms"],
            provisional=t.get("provisional", True),
            min_key_release_gap_ms=release_gap,
            min_inter_key_interval_ms=inter_key,
            trigger_mode=trigger_mode,
            sustain_decay_ms=int(sustain_decay) if sustain_decay is not None else None,
        ),
        supports_sustain=data["supports_sustain"],
        calibration_status=data["calibration"]["status"],
        raw=data,
        hash=sha256_prefixed(data),
        by_pitch={k.pitch: k for k in keys},
        by_id={k.key_id: k for k in keys},
    )


def with_timing_override(profile: InstrumentProfile, **timing_updates: Any) -> InstrumentProfile:
    """Return a derived InstrumentProfile with updated timing constraints."""
    raw = json.loads(json.dumps(profile.raw))
    timing_obj = dict(raw.get("timing") or {})
    for key, value in timing_updates.items():
        if value is not None or key == "sustain_decay_ms":
            timing_obj[key] = value
    raw["timing"] = timing_obj
    return profile_from_dict(raw)
