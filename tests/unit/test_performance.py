"""Unit tests for lyraforge.music_core.performance."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.instruments import load_builtin_profile
from lyraforge.music_core.arranger import arrange
from lyraforge.music_core.midi_import import load_midi_file
from lyraforge.music_core.performance import (
    build_performance,
    build_report,
    validate_performance,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
from midi_builders import VALID_FIXTURES  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "midi"


@pytest.mark.parametrize("fixture_name", VALID_FIXTURES)
def test_all_valid_fixtures_produce_valid_performance_and_report(fixture_name: str) -> None:
    prof = load_builtin_profile()
    score = load_midi_file(FIXTURE_DIR / fixture_name)
    arr = arrange(score, prof)
    perf = build_performance(score, prof, arr)
    validate_performance(perf, prof)

    report = build_report(score, prof, arr)
    assert report["kind"] == "lyraforge.arrangement_report"
    assert report["calibration_status"] == "unverified"
    assert report["stats"]["emitted_events"] == len(perf["events"])


def test_validate_performance_rejections() -> None:
    prof = load_builtin_profile()
    score = load_midi_file(FIXTURE_DIR / "c_major_scale.mid")
    perf = build_performance(score, prof, arrange(score, prof))

    with pytest.raises(LyraError) as exc:
        validate_performance(["not", "an", "object"])
    assert exc.value.code == ErrorCode.PERFORMANCE_INVALID

    bad_schema = copy.deepcopy(perf)
    del bad_schema["events"]
    with pytest.raises(LyraError) as exc:
        validate_performance(bad_schema, prof)
    assert exc.value.code == ErrorCode.PERFORMANCE_INVALID

    unsorted = copy.deepcopy(perf)
    unsorted["events"][0], unsorted["events"][1] = unsorted["events"][1], unsorted["events"][0]
    with pytest.raises(LyraError) as exc:
        validate_performance(unsorted, prof)
    assert exc.value.code == ErrorCode.PERFORMANCE_INVALID
    assert any("before previous event" in p for p in exc.value.details["problems"])

    overlap = copy.deepcopy(perf)
    overlap["events"][1]["key_id"] = overlap["events"][0]["key_id"]
    overlap["events"][1]["mapped_pitch"] = overlap["events"][0]["mapped_pitch"]
    overlap["events"][0]["hold_ms"] = 1000
    with pytest.raises(LyraError) as exc:
        validate_performance(overlap, prof)
    assert exc.value.code == ErrorCode.PERFORMANCE_INVALID
    assert any("while still held" in p for p in exc.value.details["problems"])

    bad_key = copy.deepcopy(perf)
    bad_key["events"][0]["key_id"] = "does_not_exist"
    with pytest.raises(LyraError) as exc:
        validate_performance(bad_key, prof)
    assert exc.value.code == ErrorCode.PERFORMANCE_INVALID

    bad_pitch = copy.deepcopy(perf)
    bad_pitch["events"][0]["mapped_pitch"] = 127
    with pytest.raises(LyraError) as exc:
        validate_performance(bad_pitch, prof)
    assert exc.value.code == ErrorCode.PERFORMANCE_INVALID

    short_dur = copy.deepcopy(perf)
    short_dur["duration_ms"] = 1
    with pytest.raises(LyraError) as exc:
        validate_performance(short_dur, prof)
    assert exc.value.code == ErrorCode.PERFORMANCE_INVALID

    wrong_hash = copy.deepcopy(perf)
    wrong_hash["instrument_profile_hash"] = "sha256:" + "0" * 64
    with pytest.raises(LyraError) as exc:
        validate_performance(wrong_hash, prof)
    assert exc.value.code == ErrorCode.PERFORMANCE_INVALID
