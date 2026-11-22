"""Unit tests for lyraforge.music_core.arranger."""

from __future__ import annotations

from pathlib import Path

import pytest

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.instruments import load_builtin_profile
from lyraforge.music_core.arranger import (
    ArrangeOptions,
    DropReason,
    SemitonePolicy,
    Style,
    arrange,
)
from lyraforge.music_core.canonical import canonical_json_bytes
from lyraforge.music_core.midi_import import load_midi_file
from lyraforge.music_core.performance import build_performance

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "midi"


def test_c_major_and_d_major_auto_transpose_and_determinism() -> None:
    prof = load_builtin_profile()
    c_score = load_midi_file(FIXTURE_DIR / "c_major_scale.mid")
    arr1 = arrange(c_score, prof)
    arr2 = arrange(c_score, prof)
    assert arr1.transpose == 0
    assert arr1.stats["direct"] == 8
    assert arr1.stats["playable_ratio"] == 1.0
    assert canonical_json_bytes(build_performance(c_score, prof, arr1)) == canonical_json_bytes(
        build_performance(c_score, prof, arr2)
    )

    d_score = load_midi_file(FIXTURE_DIR / "d_major_scale.mid")
    d_arr = arrange(d_score, prof)
    assert d_arr.transpose == -2
    assert d_arr.stats["direct"] == 8
    assert d_arr.stats["semitone_substituted"] == 0


def test_chromatic_nearest_vs_drop() -> None:
    prof = load_builtin_profile()
    score = load_midi_file(FIXTURE_DIR / "chromatic.mid")

    nearest_arr = arrange(
        score, prof, ArrangeOptions(transpose=0, semitone_policy=SemitonePolicy.NEAREST)
    )
    assert nearest_arr.stats["emitted_events"] == 13
    assert nearest_arr.stats["semitone_substituted"] == 5

    drop_arr = arrange(
        score, prof, ArrangeOptions(transpose=0, semitone_policy=SemitonePolicy.DROP)
    )
    assert drop_arr.stats["emitted_events"] == 8
    assert drop_arr.stats["dropped"][DropReason.SEMITONE_DROPPED] == 5


def test_wide_range_octave_folding_and_repeated_notes() -> None:
    prof = load_builtin_profile()
    wide = load_midi_file(FIXTURE_DIR / "wide_range.mid")
    wide_arr = arrange(wide, prof)
    assert wide_arr.stats["emitted_events"] == 7
    assert wide_arr.stats["octave_folded"] >= 4
    for ev in wide_arr.events:
        assert prof.min_pitch <= ev.mapped_pitch <= prof.max_pitch

    rep = load_midi_file(FIXTURE_DIR / "repeated_notes.mid")
    rep_arr = arrange(rep, prof)
    assert rep_arr.stats["dropped"][DropReason.REPEAT_TOO_FAST] > 0
    times = [ev.at_ms for ev in rep_arr.events]
    for a, b in zip(times, times[1:], strict=False):
        assert b - a >= prof.timing.min_same_key_interval_ms


def test_dense_chords_styles_and_dedup() -> None:
    prof = load_builtin_profile()
    score = load_midi_file(FIXTURE_DIR / "dense_chords.mid")

    mel = arrange(score, prof, ArrangeOptions(style=Style.MELODY))
    bal = arrange(score, prof, ArrangeOptions(style=Style.BALANCED))
    rich = arrange(score, prof, ArrangeOptions(style=Style.RICH))

    assert mel.stats["max_chord_size"] == 1
    assert bal.stats["max_chord_size"] == 3
    assert rich.stats["max_chord_size"] == 6
    assert bal.stats["dropped"][DropReason.DUPLICATE_KEY] >= 2
    assert bal.stats["dropped"][DropReason.POLYPHONY_LIMIT] >= 6


def test_percussion_track_filter_tempo_triplets_and_speed() -> None:
    prof = load_builtin_profile()
    perc = load_midi_file(FIXTURE_DIR / "percussion.mid")
    arr_excl = arrange(perc, prof)
    assert arr_excl.stats["excluded_percussion"] == 4
    assert arr_excl.stats["emitted_events"] == 4

    arr_track = arrange(perc, prof, ArrangeOptions(include_tracks=(2,), exclude_percussion=False))
    assert arr_track.stats["excluded_percussion"] == 0
    assert arr_track.stats["excluded_tracks"] == 4

    tempo_score = load_midi_file(FIXTURE_DIR / "tempo_changes.mid")
    arr_1x = arrange(tempo_score, prof)
    assert [e.at_ms for e in arr_1x.events] == [
        0, 500, 1000, 1500, 2000, 3000, 4000, 5000, 6000, 6333, 6667, 7000
    ]
    arr_2x = arrange(tempo_score, prof, ArrangeOptions(speed=2.0))
    assert [e.at_ms for e in arr_2x.events] == [0, 250, 500, 750, 1000, 1500, 2000, 2500, 3000,
                                                3167, 3333, 3500]

    trip = load_midi_file(FIXTURE_DIR / "triplets.mid")
    trip_arr = arrange(trip, prof)
    assert [e.at_ms for e in trip_arr.events] == [0, 167, 333, 500, 667, 833]


def test_empty_midi_and_invalid_options() -> None:
    prof = load_builtin_profile()
    empty = load_midi_file(FIXTURE_DIR / "empty.mid")
    with pytest.raises(LyraError) as exc_info:
        arrange(empty, prof)
    assert exc_info.value.code == ErrorCode.NO_PLAYABLE_NOTES

    c_score = load_midi_file(FIXTURE_DIR / "c_major_scale.mid")
    with pytest.raises(LyraError) as exc_info:
        arrange(c_score, prof, ArrangeOptions(speed=10.0))
    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT
    with pytest.raises(LyraError) as exc_info:
        arrange(c_score, prof, ArrangeOptions(transpose=99))
    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT
