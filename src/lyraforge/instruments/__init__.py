"""Built-in instrument profile registry (data only; validation lives in music_core)."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.music_core.profile import InstrumentProfile, profile_from_dict

DEFAULT_PROFILE_ID = "genshin.windsong_lyre.v1"
_DATA_PACKAGE = "lyraforge.instruments.data"


def list_profile_ids() -> list[str]:
    root = resources.files(_DATA_PACKAGE)
    ids = sorted(p.name[: -len(".json")] for p in root.iterdir() if p.name.endswith(".json"))
    if DEFAULT_PROFILE_ID in ids:
        ids.remove(DEFAULT_PROFILE_ID)
        ids.insert(0, DEFAULT_PROFILE_ID)
    return ids


def load_builtin_profile(profile_id: str = DEFAULT_PROFILE_ID) -> InstrumentProfile:
    if profile_id not in list_profile_ids():
        raise LyraError(ErrorCode.PROFILE_INVALID, f"unknown instrument profile: {profile_id}",
                        {"available": list_profile_ids()})
    text = resources.files(_DATA_PACKAGE).joinpath(f"{profile_id}.json").read_text(encoding="utf-8")
    profile = profile_from_dict(json.loads(text))
    if profile.id != profile_id:
        raise LyraError(ErrorCode.PROFILE_INVALID,
                        f"profile file {profile_id}.json declares id {profile.id}")
    return profile


def load_profile_file(path: str | Path) -> InstrumentProfile:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LyraError(ErrorCode.SOURCE_UNAVAILABLE, f"profile not found: {p.name}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LyraError(ErrorCode.PROFILE_INVALID, f"profile is not valid JSON: {exc}") from exc
    return profile_from_dict(data)
