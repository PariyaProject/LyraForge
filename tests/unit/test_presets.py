"""Tests for built-in arrangement presets and the Vintage Lyre profile."""

from __future__ import annotations

from pathlib import Path

import pytest

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.instruments import list_profile_ids, load_builtin_profile
from lyraforge.music_core.arranger import arrange
from lyraforge.music_core.midi_import import load_midi_file
from lyraforge.music_core.performance import build_performance, validate_performance
from lyraforge.presets import PRESETS, get_preset, list_presets, preset_options

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "midi"


def test_presets_cover_every_supported_profile_with_unique_ids() -> None:
    presets = list_presets()
    assert len(presets) == len(PRESETS)
    ids = [str(item["id"]) for item in presets]
    assert len(ids) == len(set(ids))
    for profile_id in (
        "genshin.windsong_lyre.v1",
        "genshin.floral_zither.v1",
        "genshin.vintage_lyre.v1",
    ):
        assert profile_id in list_profile_ids()
        filtered = list_presets(profile_id)
        assert len(filtered) == 5
        assert {item["profile_id"] for item in filtered} == {profile_id}


def test_every_preset_yields_valid_arrange_options() -> None:
    for preset in PRESETS:
        options = preset_options(preset.id)
        assert options.style == preset.style
        assert options.speed == preset.speed
        assert preset.profile_id in list_profile_ids()


def test_unknown_preset_and_profile_are_rejected() -> None:
    with pytest.raises(LyraError) as exc:
        get_preset("no.such.preset")
    assert exc.value.code == ErrorCode.INVALID_ARGUMENT

    with pytest.raises(LyraError) as exc2:
        list_presets("genshin.unknown.v1")
    assert exc2.value.code == ErrorCode.PROFILE_INVALID


def test_vintage_lyre_uses_dorian_and_phrygian_pitch_mapping() -> None:
    profile = load_builtin_profile("genshin.vintage_lyre.v1")
    # C Dorian (lower two rows) and C Phrygian (top row), C3-B5.
    assert profile.pitches == (
        48, 50, 51, 53, 55, 57, 58,
        60, 62, 63, 65, 67, 69, 70,
        72, 73, 75, 77, 79, 80, 82,
    )
    assert profile.min_pitch == 48
    assert profile.max_pitch == 82
    assert profile.calibration_status == "unverified"
    assert [key.binding for key in profile.keys] == [
        "Z", "X", "C", "V", "B", "N", "M",
        "A", "S", "D", "F", "G", "H", "J",
        "Q", "W", "E", "R", "T", "Y", "U",
    ]


def test_vintage_lyre_arranges_a_c_major_fixture() -> None:
    score = load_midi_file(FIXTURE_DIR / "c_major_scale.mid")
    profile = load_builtin_profile("genshin.vintage_lyre.v1")
    arrangement = arrange(score, profile)
    assert len(arrangement.events) > 0
    performance = build_performance(score, profile, arrangement)
    validate_performance(performance, profile)
    assert all(
        event["key_id"] in profile.by_id for event in performance["events"]
    )


def test_presets_api_endpoint(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from lyraforge.api import SESSION_TOKEN_HEADER, create_app

    token = "preset-token"
    client = TestClient(create_app(data_dir=tmp_path / "preset_data", session_token=token))
    headers = {SESSION_TOKEN_HEADER: token}

    res = client.get("/v1/presets", headers=headers)
    assert res.status_code == 200
    assert len(res.json()["presets"]) == 15

    filtered = client.get(
        "/v1/presets", params={"profile_id": "genshin.vintage_lyre.v1"}, headers=headers
    )
    assert filtered.status_code == 200
    assert len(filtered.json()["presets"]) == 5

    bad = client.get(
        "/v1/presets", params={"profile_id": "genshin.unknown.v1"}, headers=headers
    )
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "PROFILE_INVALID"
