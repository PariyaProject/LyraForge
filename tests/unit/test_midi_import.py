"""Unit tests for lyraforge.music_core.midi_import."""

from __future__ import annotations

import struct
from pathlib import Path

import mido
import pytest

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.music_core.midi_import import ImportLimits, load_midi_file, parse_midi_bytes

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "midi"


def test_load_smf_type0_and_type1() -> None:
    s0 = load_midi_file(FIXTURE_DIR / "c_major_scale.mid")
    assert s0.midi_type == 0
    assert s0.ticks_per_beat == 480
    assert len(s0.notes) == 8
    assert s0.notes[0].pitch == 60
    assert s0.notes[-1].pitch == 72

    s1 = load_midi_file(FIXTURE_DIR / "chords_type1.mid")
    assert s1.midi_type == 1
    assert len(s1.tracks) == 3
    assert len(s1.time_signatures) == 1
    assert s1.time_signatures[0].numerator == 4
    assert s1.time_signatures[0].denominator == 4
    assert len(s1.notes) == 28


def test_overlap_vel0_stray_off_and_unterminated() -> None:
    score = load_midi_file(FIXTURE_DIR / "overlap_edge.mid")
    assert len(score.notes) == 4
    assert any("without matching note-on" in w for w in score.warnings)
    assert any("unterminated note" in w for w in score.warnings)
    # FIFO pairing for overlapping C4 (0..480 and 240..720)
    c4_notes = [n for n in score.notes if n.pitch == 60]
    assert [(n.start_tick, n.end_tick) for n in c4_notes] == [(0, 480), (240, 720)]
    # note_on vel=0 closes D4 at tick 1200
    d4 = next(n for n in score.notes if n.pitch == 62)
    assert (d4.start_tick, d4.end_tick) == (960, 1200)
    # unterminated G4 closed at end of track (tick 1920)
    g4 = next(n for n in score.notes if n.pitch == 67)
    assert (g4.start_tick, g4.end_tick) == (1440, 1920)


def test_non_track_zero_tempo_warning() -> None:
    mid = mido.MidiFile(type=1, ticks_per_beat=480)
    t0 = mido.MidiTrack([mido.MetaMessage("end_of_track", time=0)])
    t1 = mido.MidiTrack([
        mido.MetaMessage("set_tempo", tempo=400_000, time=0),
        mido.Message("note_on", note=60, velocity=80, time=0),
        mido.Message("note_off", note=60, velocity=0, time=480),
        mido.MetaMessage("end_of_track", time=0),
    ])
    mid.tracks.extend([t0, t1])
    import io

    buf = io.BytesIO()
    mid.save(file=buf)
    score = parse_midi_bytes(buf.getvalue())
    assert any("track 1" in w for w in score.warnings)
    assert score.notes[0].end_us == 400_000


@pytest.mark.parametrize(
    ("filename", "expected_code"),
    [
        ("broken/not_midi.mid", ErrorCode.MEDIA_DECODE_FAILED),
        ("broken/truncated.mid", ErrorCode.MEDIA_DECODE_FAILED),
        ("broken/corrupt_track_length.mid", ErrorCode.MEDIA_DECODE_FAILED),
        ("broken/type2.mid", ErrorCode.MEDIA_UNSUPPORTED),
        ("broken/smpte_division.mid", ErrorCode.MEDIA_UNSUPPORTED),
    ],
)
def test_broken_and_unsupported_fixtures(filename: str, expected_code: ErrorCode) -> None:
    with pytest.raises(LyraError) as exc_info:
        load_midi_file(FIXTURE_DIR / filename)
    assert exc_info.value.code == expected_code


def test_missing_file_and_corrupt_headers() -> None:
    with pytest.raises(LyraError) as exc_info:
        load_midi_file(FIXTURE_DIR / "does_not_exist.mid")
    assert exc_info.value.code == ErrorCode.SOURCE_UNAVAILABLE

    bad_hlen = b"MThd" + struct.pack(">IHHH", 4, 0, 1, 480)
    with pytest.raises(LyraError) as exc_info:
        parse_midi_bytes(bad_hlen)
    assert exc_info.value.code == ErrorCode.MEDIA_DECODE_FAILED

    zero_tpb = b"MThd" + struct.pack(">IHHH", 6, 0, 1, 0)
    with pytest.raises(LyraError) as exc_info:
        parse_midi_bytes(zero_tpb)
    assert exc_info.value.code == ErrorCode.MEDIA_DECODE_FAILED


def test_import_limits_enforced() -> None:
    data = (FIXTURE_DIR / "c_major_scale.mid").read_bytes()
    with pytest.raises(LyraError) as exc_info:
        parse_midi_bytes(data, ImportLimits(max_file_bytes=16))
    assert exc_info.value.code == ErrorCode.LIMIT_EXCEEDED

    with pytest.raises(LyraError) as exc_info:
        load_midi_file(FIXTURE_DIR / "c_major_scale.mid", ImportLimits(max_file_bytes=16))
    assert exc_info.value.code == ErrorCode.LIMIT_EXCEEDED

    with pytest.raises(LyraError) as exc_info:
        parse_midi_bytes(data, ImportLimits(max_notes=3))
    assert exc_info.value.code == ErrorCode.LIMIT_EXCEEDED

    with pytest.raises(LyraError) as exc_info:
        parse_midi_bytes(data, ImportLimits(max_duration_us=1000))
    assert exc_info.value.code == ErrorCode.LIMIT_EXCEEDED


def test_empty_midi_summary() -> None:
    score = load_midi_file(FIXTURE_DIR / "empty.mid")
    assert score.notes == ()
    summary = score.summary()
    assert summary["note_count"] == 0
    assert summary["pitch_range"] is None
