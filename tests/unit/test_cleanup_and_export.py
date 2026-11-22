"""Unit tests for music_core.cleanup and music_core.midi_export."""

from __future__ import annotations

import io
from pathlib import Path

import mido
import pytest

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.instruments import load_builtin_profile
from lyraforge.music_core import (
    CleanupOptions,
    arrange,
    arrangement_to_midi_bytes,
    clean_score,
    load_midi_file,
    parse_midi_bytes,
    score_to_midi_bytes,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "midi"


def test_clean_score_removes_short_glitches_deduplicates_and_quantizes() -> None:
    mid = mido.MidiFile(type=0, ticks_per_beat=500)  # 1 tick == 1 ms @ 120 BPM
    trk = mido.MidiTrack([
        mido.MetaMessage("set_tempo", tempo=500_000, time=0),
        mido.Message("note_on", note=60, velocity=80, time=0),
        mido.Message("note_off", note=60, velocity=0, time=15),   # 15 ms glitch -> removed
        mido.Message("note_on", note=62, velocity=90, time=90),   # @105 ms -> quantizes to 100 ms
        mido.Message("note_on", note=62, velocity=60, time=5),    # @110 ms -> quantizes to 100 ms
        mido.Message("note_off", note=62, velocity=0, time=200),
        mido.Message("note_off", note=62, velocity=0, time=50),
        mido.MetaMessage("end_of_track", time=0),
    ])
    mid.tracks.append(trk)
    buf = io.BytesIO()
    mid.save(file=buf)
    score = parse_midi_bytes(buf.getvalue())

    cleaned, stats = clean_score(score, CleanupOptions(min_note_ms=35, quantize_ms=50))
    assert stats == {
        "input_notes": 3,
        "kept_notes": 1,
        "removed_short_notes": 1,
        "removed_duplicates": 1,
    }
    assert len(cleaned.notes) == 1
    assert cleaned.notes[0].pitch == 62
    assert cleaned.notes[0].start_us == 100_000
    assert cleaned.notes[0].velocity == 90

    with pytest.raises(LyraError) as exc:
        CleanupOptions(min_note_ms=-1).validate()
    assert exc.value.code == ErrorCode.INVALID_ARGUMENT


def test_score_and_arrangement_midi_export_round_trip() -> None:
    score = load_midi_file(FIXTURE_DIR / "chords_type1.mid")
    cleaned, _ = clean_score(score)
    midi_bytes = score_to_midi_bytes(cleaned)
    reloaded = parse_midi_bytes(midi_bytes)
    assert len(reloaded.notes) == len(cleaned.notes)
    assert [n.pitch for n in reloaded.notes] == [n.pitch for n in cleaned.notes]

    prof = load_builtin_profile()
    arr = arrange(score, prof)
    arr_midi = arrangement_to_midi_bytes(arr)
    arr_score = parse_midi_bytes(arr_midi)
    assert len(arr_score.notes) == len(arr.events)
    assert [n.pitch for n in arr_score.notes] == [e.mapped_pitch for e in arr.events]
