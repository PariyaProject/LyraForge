"""Unit tests for lyraforge.music_core.profile and lyraforge.instruments."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.instruments import (
    DEFAULT_PROFILE_ID,
    list_profile_ids,
    load_builtin_profile,
    load_profile_file,
)
from lyraforge.music_core.profile import profile_from_dict


def test_builtin_windsong_lyre_profile() -> None:
    assert DEFAULT_PROFILE_ID == "genshin.harmonic_keys.v1"
    ids = list_profile_ids()
    assert DEFAULT_PROFILE_ID in ids
    assert "genshin.windsong_lyre.v1" in ids
    p = load_builtin_profile("genshin.windsong_lyre.v1")
    assert p.id == "genshin.windsong_lyre.v1"
    hk = load_builtin_profile(DEFAULT_PROFILE_ID)
    assert hk.id == "genshin.harmonic_keys.v1"
    assert hk.display_name == "谐律键琴"
    assert len(hk.keys) == 21
    assert p.game_id == "genshin"
    assert p.kind == "pitched_diatonic"
    assert len(p.keys) == 21
    assert p.min_pitch == 48
    assert p.max_pitch == 83
    assert p.calibration_status == "unverified"
    assert p.hash.startswith("sha256:")
    # Verify unique bindings and pitches across 3 diatonic octaves (C3..B5)
    assert len({k.key_id for k in p.keys}) == 21
    assert len({k.pitch for k in p.keys}) == 21
    assert len({k.binding for k in p.keys}) == 21
    assert p.key_for_pitch(60) is not None
    assert p.key_for_pitch(61) is None
    assert p.key_by_id("mid_1") is not None
    # Deterministic hash
    assert load_builtin_profile("genshin.windsong_lyre.v1").hash == p.hash


def test_load_profile_file_and_errors(tmp_path: Path) -> None:
    p = load_builtin_profile(DEFAULT_PROFILE_ID)
    fp = tmp_path / "lyre.json"
    fp.write_text(json.dumps(p.raw), encoding="utf-8")
    loaded = load_profile_file(fp)
    assert loaded.hash == p.hash

    with pytest.raises(LyraError) as exc_info:
        load_builtin_profile("genshin.unknown.v1")
    assert exc_info.value.code == ErrorCode.PROFILE_INVALID

    with pytest.raises(LyraError) as exc_info:
        load_profile_file(tmp_path / "missing.json")
    assert exc_info.value.code == ErrorCode.SOURCE_UNAVAILABLE

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not json", encoding="utf-8")
    with pytest.raises(LyraError) as exc_info:
        load_profile_file(bad_json)
    assert exc_info.value.code == ErrorCode.PROFILE_INVALID


def test_profile_semantic_and_schema_rejections() -> None:
    base = copy.deepcopy(load_builtin_profile(DEFAULT_PROFILE_ID).raw)

    with pytest.raises(LyraError) as exc_info:
        profile_from_dict([])  # type: ignore[arg-type]
    assert exc_info.value.code == ErrorCode.PROFILE_INVALID

    wrong_count = copy.deepcopy(base)
    wrong_count["key_count"] = 20
    with pytest.raises(LyraError) as exc_info:
        profile_from_dict(wrong_count)
    assert exc_info.value.code == ErrorCode.PROFILE_INVALID

    dup_pitch = copy.deepcopy(base)
    dup_pitch["keys"][1]["pitch"] = dup_pitch["keys"][0]["pitch"]
    with pytest.raises(LyraError) as exc_info:
        profile_from_dict(dup_pitch)
    assert exc_info.value.code == ErrorCode.PROFILE_INVALID

    bad_timing = copy.deepcopy(base)
    bad_timing["timing"]["min_same_key_interval_ms"] = 5
    with pytest.raises(LyraError) as exc_info:
        profile_from_dict(bad_timing)
    assert exc_info.value.code == ErrorCode.PROFILE_INVALID

    sustain = copy.deepcopy(base)
    sustain["supports_sustain"] = True
    with pytest.raises(LyraError) as exc_info:
        profile_from_dict(sustain)
    assert exc_info.value.code == ErrorCode.PROFILE_INVALID
