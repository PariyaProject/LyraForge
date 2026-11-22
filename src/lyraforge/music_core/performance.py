"""performance.json v1: build, validate, and the companion report.

The document contains no wall-clock timestamps or absolute paths so that the
same input + profile + options always produce byte-identical output.
IDs are UUIDv5 derived from content hashes (deterministic; M1 library may
assign its own song IDs and keep these as content IDs).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from functools import cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator

from lyraforge import __version__
from lyraforge.errors import ErrorCode, LyraError
from lyraforge.music_core.arranger import ARRANGER_VERSION, Arrangement
from lyraforge.music_core.canonical import canonical_json_bytes
from lyraforge.music_core.models import NormalizedScore
from lyraforge.music_core.profile import InstrumentProfile
from lyraforge.music_core.scoring import score_arrangement

SCHEMA_VERSION = 1
LYRAFORGE_NS = uuid.UUID("6f1c7d1e-6a43-5b8e-9a51-1f0c5a0b7e21")


@cache
def _validator() -> Draft202012Validator:
    text = resources.files("lyraforge.music_core.schemas").joinpath(
        "performance.v1.schema.json").read_text(encoding="utf-8")
    return Draft202012Validator(json.loads(text))


def transform_json(arr: Arrangement) -> dict[str, Any]:
    o = arr.options
    return {
        "strategy": str(o.style),
        "transpose_semitones": arr.transpose,
        "transpose_mode": "auto" if o.transpose is None else "fixed",
        "speed": float(o.speed),
        "semitone_policy": str(o.semitone_policy),
        "max_chord_keys": arr.max_chord_keys,
        "chord_window_ms": o.chord_window_ms,
        "include_tracks": list(o.include_tracks) if o.include_tracks is not None else None,
        "exclude_percussion": o.exclude_percussion,
        "arpeggiate_ms": o.arpeggiate_ms,
        "prefer_melody_track": o.prefer_melody_track,
    }


def build_performance(score: NormalizedScore, profile: InstrumentProfile,
                      arr: Arrangement) -> dict[str, Any]:
    transform = transform_json(arr)
    song_id = uuid.uuid5(LYRAFORGE_NS, f"song:{score.source_sha256}")
    arr_key = hashlib.sha256(canonical_json_bytes({
        "input": score.source_sha256, "profile": profile.hash, "transform": transform,
        "arranger": ARRANGER_VERSION,
    })).hexdigest()
    arrangement_id = uuid.uuid5(LYRAFORGE_NS, f"arrangement:{arr_key}")
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "lyraforge.performance",
        "song_id": str(song_id),
        "arrangement_id": str(arrangement_id),
        "instrument_profile_id": profile.id,
        "instrument_profile_hash": profile.hash,
        "tempo_map": score.tempo_map.to_json(),
        "duration_ms": arr.stats["duration_ms"],
        "events": [e.to_json() for e in arr.events],
        "transform": transform,
        "provenance": {
            "input_sha256": score.source_sha256,
            "transcriber": "none",
            "arranger_version": ARRANGER_VERSION,
            "lyraforge_version": __version__,
        },
    }


def build_report(score: NormalizedScore, profile: InstrumentProfile,
                 arr: Arrangement) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "lyraforge.arrangement_report",
        "source": score.summary(),
        "instrument_profile_id": profile.id,
        "instrument_profile_hash": profile.hash,
        "calibration_status": profile.calibration_status,
        "transform": transform_json(arr),
        "transpose_candidates": [{"semitones": k, "cost": c} for k, c in arr.transpose_candidates],
        "stats": arr.stats,
        "quality": score_arrangement(score, arr).to_json(),
        "dropped_notes": [d.to_json() for d in arr.dropped],
        "disclaimer": (
            "playable_ratio measures how many source notes were mapped to keys; "
            "it is not a measure of musical fidelity. Listen before playing."
        ),
    }


def validate_performance(doc: Any, profile: InstrumentProfile | None = None) -> None:
    """Raise LyraError(PERFORMANCE_INVALID) listing every problem found."""
    if not isinstance(doc, dict):
        raise LyraError(ErrorCode.PERFORMANCE_INVALID, "performance must be a JSON object")
    problems = [
        f"{'/'.join(str(x) for x in e.absolute_path) or '<root>'}: {e.message}"
        for e in sorted(_validator().iter_errors(doc), key=lambda e: list(e.absolute_path))
    ]
    if problems:
        raise LyraError(ErrorCode.PERFORMANCE_INVALID, "performance failed schema validation",
                        {"problems": problems[:50], "total": len(problems)})

    sem: list[str] = []
    events = doc["events"]
    prev_at = -1
    key_free_at: dict[str, int] = {}
    max_end = 0
    for i, e in enumerate(events):
        at, key, hold = e["at_ms"], e["key_id"], e["hold_ms"]
        if at < prev_at:
            sem.append(f"events/{i}: at_ms {at} is before previous event ({prev_at})")
        prev_at = at
        free = key_free_at.get(key)
        if free is not None and at < free:
            sem.append(f"events/{i}: key {key} pressed at {at} while still held until {free}")
        key_free_at[key] = at + hold
        max_end = max(max_end, at + hold)
        if profile is not None:
            k = profile.key_by_id(key)
            if k is None:
                sem.append(f"events/{i}: key_id {key!r} not in profile {profile.id}")
            elif k.pitch != e["mapped_pitch"]:
                sem.append(f"events/{i}: mapped_pitch {e['mapped_pitch']} != key pitch {k.pitch}")
        if len(sem) >= 50:
            break
    if doc["duration_ms"] < max_end:
        sem.append(f"duration_ms {doc['duration_ms']} < last key release {max_end}")
    if profile is not None:
        if doc["instrument_profile_id"] != profile.id:
            sem.append(f"instrument_profile_id {doc['instrument_profile_id']} != {profile.id}")
        elif doc["instrument_profile_hash"] != profile.hash:
            sem.append("instrument_profile_hash does not match the loaded profile "
                       "(profile changed since arrangement; re-arrange)")
    if sem:
        raise LyraError(ErrorCode.PERFORMANCE_INVALID, "performance failed semantic validation",
                        {"problems": sem})
