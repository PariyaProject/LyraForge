"""Unit tests for lyraforge.music_core.tempo."""

from __future__ import annotations

from fractions import Fraction

import pytest

from lyraforge.music_core.tempo import DEFAULT_US_PER_BEAT, TempoChange, TempoMap


def test_default_tempo_when_empty() -> None:
    tm = TempoMap(480, [])
    assert len(tm.changes) == 1
    assert tm.changes[0] == TempoChange(0, DEFAULT_US_PER_BEAT)
    assert tm.changes[0].bpm == pytest.approx(120.0)
    assert tm.tick_to_us(0) == 0
    assert tm.tick_to_us(480) == 500_000
    assert tm.tick_to_us(960) == 1_000_000


def test_multi_tempo_fraction_precision() -> None:
    # 0..1920 @ 120 BPM (500_000 us/beat) => 4 beats = 2_000_000 us
    # 1920..3840 @ 60 BPM (1_000_000 us/beat) => 4 beats = 4_000_000 us (total 6_000_000 us)
    # 3840..4320 @ 180 BPM (333_333 us/beat) => 1 beat = 333_333 us
    tm = TempoMap(
        480,
        [
            TempoChange(0, 500_000),
            TempoChange(1920, 1_000_000),
            TempoChange(3840, 333_333),
        ],
    )
    assert tm.tick_to_us(0) == 0
    assert tm.tick_to_us(1920) == 2_000_000
    assert tm.tick_to_us(2400) == 3_000_000
    assert tm.tick_to_us(3840) == 6_000_000
    assert tm.tick_to_us(4320) == 6_333_333
    assert tm.tick_to_us_exact(160) == Fraction(500_000, 3)


def test_duplicate_tick_last_wins_and_missing_tick_zero_uses_default() -> None:
    tm = TempoMap(
        480,
        [
            TempoChange(480, 1_000_000),
            TempoChange(480, 250_000),
        ],
    )
    assert tm.changes[0] == TempoChange(0, DEFAULT_US_PER_BEAT)
    assert tm.changes[1] == TempoChange(480, 250_000)
    assert tm.tick_to_us(480) == 500_000
    assert tm.tick_to_us(960) == 750_000


def test_tempo_map_invalid_arguments_and_to_json() -> None:
    with pytest.raises(ValueError, match="ticks_per_beat"):
        TempoMap(0, [])
    with pytest.raises(ValueError, match="invalid tempo change"):
        TempoMap(480, [TempoChange(-1, 500_000)])
    with pytest.raises(ValueError, match="invalid tempo change"):
        TempoMap(480, [TempoChange(0, 0)])

    tm = TempoMap(480, [TempoChange(0, 500_000)])
    with pytest.raises(ValueError, match="tick must be >= 0"):
        tm.tick_to_us(-1)

    j = tm.to_json()
    assert j == [{"tick": 0, "at_ms": 0, "us_per_beat": 500_000, "bpm": 120.0}]
