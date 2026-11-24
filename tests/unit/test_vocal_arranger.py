"""Unit tests for music-theory vocal_lead arranger, vibrato cleanup, and stem merging."""

from __future__ import annotations

from pathlib import Path

from lyraforge.instruments import load_builtin_profile
from lyraforge.music_core import (
    ArrangeOptions,
    CleanupOptions,
    NormalizedScore,
    Note,
    TempoChange,
    TempoMap,
    TrackInfo,
    arrange,
    build_performance,
    clean_score,
    detect_melody_track,
    get_arranger_strategy,
    list_arranger_strategies,
    load_midi_file,
    merge_stem_scores,
)
from lyraforge.music_core.arranger import DropReason, Style

ROOT = Path(__file__).resolve().parents[2]
MIDI_DIR = ROOT / "tests" / "fixtures" / "midi"


def _score_from_notes(
    notes: list[Note],
    tracks: tuple[TrackInfo, ...],
) -> NormalizedScore:
    ordered = sorted(notes, key=lambda n: (n.start_us, n.pitch, n.track, n.channel, n.end_us))
    return NormalizedScore(
        source_sha256="a" * 64,
        midi_type=1 if len(tracks) > 1 else 0,
        ticks_per_beat=500,
        tempo_map=TempoMap(500, [TempoChange(0, 500_000)]),
        time_signatures=(),
        tracks=tracks,
        notes=tuple(ordered),
        duration_us=max((n.end_us for n in ordered), default=0),
        warnings=(),
    )


def _note(
    ms: int,
    dur_ms: int,
    pitch: int,
    *,
    track: int = 0,
    channel: int = 0,
    vel: int = 96,
) -> Note:
    return Note(
        pitch=pitch,
        velocity=vel,
        start_tick=ms,
        end_tick=ms + dur_ms,
        start_us=ms * 1000,
        end_us=(ms + dur_ms) * 1000,
        track=track,
        channel=channel,
    )


def test_arranger_strategy_registry_and_classic_parity() -> None:
    strategies = {s.id: s for s in list_arranger_strategies()}
    assert {"classic", "vocal_lead"}.issubset(strategies)
    assert get_arranger_strategy("vocal_lead").id == "vocal_lead"

    score = load_midi_file(MIDI_DIR / "chords_type1.mid")
    profile = load_builtin_profile("genshin.windsong_lyre.v1")
    legacy = arrange(score, profile, ArrangeOptions(style=Style.BALANCED))
    explicit_classic = arrange(
        score, profile, ArrangeOptions(style=Style.BALANCED, arranger_strategy="classic")
    )
    assert legacy.events == explicit_classic.events
    assert legacy.transpose == explicit_classic.transpose
    assert build_performance(score, profile, legacy)["arrangement_id"] == build_performance(
        score, profile, explicit_classic
    )["arrangement_id"]


def test_vocal_lead_weighted_transpose_prioritizes_vocal_over_dense_accomp() -> None:
    # Vocal track (Track 0) is cleanly in D major (D4, E4, F#4, G4, A4 -> needs -2 to C major)
    # Dense accomp track (Track 1) has many notes biased toward Eb/Ab where classic flips away.
    notes: list[Note] = [
        _note(0, 400, 62, track=0),   # D4
        _note(400, 400, 64, track=0), # E4
        _note(800, 400, 66, track=0), # F#4
        _note(1200, 400, 67, track=0), # G4
        _note(1600, 400, 69, track=0), # A4
    ]
    # 20 accompaniment notes centered in Eb major (+9 / -3) so classic bends away from D major
    for i in range(10):
        ms = i * 200
        notes.append(_note(ms, 180, 51, track=1, channel=1))  # Eb3
        notes.append(_note(ms, 180, 58, track=1, channel=1))  # Bb3

    score = _score_from_notes(
        notes,
        (
            TrackInfo(index=0, name="Vocal Lead", note_count=5, channels=(0,)),
            TrackInfo(index=1, name="Accompaniment", note_count=20, channels=(1,)),
        ),
    )
    profile = load_builtin_profile("genshin.windsong_lyre.v1")
    assert detect_melody_track(score) == 0

    vocal_arr = arrange(
        score,
        profile,
        ArrangeOptions(style=Style.BALANCED, arranger_strategy="vocal_lead"),
    )
    mel_events = [e for e in vocal_arr.events if e.source_track == 0]
    assert len(mel_events) == 5
    # With -2 transpose, all 5 vocal notes map directly without semitone substitution
    assert sum(1 for e in mel_events if e.adjustments) == 0


def test_vocal_lead_asymmetric_vintage_lyre_transpose() -> None:
    # Vintage Lyre supports Ab5 (80) but not G5 (79), while Bb3 (58) exists in low octave
    score = _score_from_notes(
        [
            _note(0, 300, 60, track=0),   # C4
            _note(300, 300, 62, track=0), # D4
            _note(600, 300, 63, track=0), # Eb4
            _note(900, 300, 75, track=0), # Eb5
            _note(1200, 300, 80, track=0), # Ab5 (native on Vintage Lyre, not G5!)
        ],
        (TrackInfo(index=0, name="Vocal Lead", note_count=5, channels=(0,)),),
    )
    vintage = load_builtin_profile("genshin.vintage_lyre.v1")
    arr = arrange(
        score,
        vintage,
        ArrangeOptions(style=Style.MELODY, arranger_strategy="vocal_lead"),
    )
    assert arr.transpose == 0
    assert arr.stats["semitone_substituted"] == 0


def test_vocal_lead_ceiling_anti_clash_and_ducking_with_interlude_handoff() -> None:
    # Vocal sings 0..900ms (C4=60, E4=64), rests 900..2200ms (interlude), sings again at 2200ms.
    # High accomp at t=0ms (G5=79) should fold below vocal pitch;
    # Chromatic F4=65 / C#4=61 clashing within 1-2 semitones of active vocal should be suppressed;
    # Accomp notes inside 900..2200ms interlude (e.g. t=1600ms) remain playable even in MELODY!
    notes = [
        _note(0, 400, 60, track=0),     # Vocal C4 at t=0
        _note(400, 400, 64, track=0),   # Vocal E4 at t=400
        _note(2400, 400, 67, track=0),  # Vocal G4 at t=2400
        # Accomp during vocal t=0: G5 (79), clash B3 (59, 1 semitone from C4), clean C3 (48)
        _note(0, 350, 79, track=1, channel=1),
        _note(0, 350, 59, track=1, channel=1),
        _note(0, 350, 48, track=1, channel=1),
        # Chromatic F#4 (66) during Vocal E4 (64) at t=400 -> adjacent 2-semitone neighbors dropped
        _note(400, 350, 66, track=1, channel=1),
        # Interlude at t=1600ms (>600ms after t=400 and >=300ms before t=2400): synth riff
        _note(1600, 350, 72, track=1, channel=1),
        _note(1600, 350, 55, track=1, channel=1),
    ]
    score = _score_from_notes(
        notes,
        (
            TrackInfo(index=0, name="Vocal Lead", note_count=3, channels=(0,)),
            TrackInfo(index=1, name="Accompaniment", note_count=6, channels=(1,)),
        ),
    )
    lyre = load_builtin_profile("genshin.windsong_lyre.v1")

    mel_only = arrange(
        score,
        lyre,
        ArrangeOptions(style=Style.MELODY, transpose=0, arranger_strategy="vocal_lead"),
    )
    at_zero = [e for e in mel_only.events if e.at_ms == 0]
    assert [e.mapped_pitch for e in at_zero] == [60]  # Ducking suppressed accomp during vocal!
    interlude = [e for e in mel_only.events if e.at_ms == 1600]
    assert {e.mapped_pitch for e in interlude} == {55, 72}  # Interlude opened accompaniment!

    balanced = arrange(
        score,
        lyre,
        ArrangeOptions(style=Style.BALANCED, transpose=0, arranger_strategy="vocal_lead"),
    )
    bal_zero = [e for e in balanced.events if e.at_ms == 0]
    # All kept accomp notes at t=0 stay strictly below Vocal C4 (60) and avoid 59 clash
    for ev in bal_zero:
        if ev.source_track == 1:
            assert ev.mapped_pitch < 60
            assert abs(ev.mapped_pitch - 60) not in (1, 2)
    assert any(d.reason == DropReason.SEMITONE_DROPPED for d in balanced.dropped)


def test_explicit_melody_track_and_single_track_contour() -> None:
    score = _score_from_notes(
        [
            _note(0, 300, 72, track=0, channel=0),
            _note(0, 300, 60, track=1, channel=1),
            _note(300, 300, 79, track=0, channel=0),
            _note(300, 300, 62, track=1, channel=1),
        ],
        (
            TrackInfo(index=0, name="High Arpeggio", note_count=2, channels=(0,)),
            TrackInfo(index=1, name="Low Melody", note_count=2, channels=(1,)),
        ),
    )
    lyre = load_builtin_profile("genshin.windsong_lyre.v1")
    arr = arrange(
        score,
        lyre,
        ArrangeOptions(
            style=Style.MELODY,
            transpose=0,
            arranger_strategy="vocal_lead",
            melody_track=1,
        ),
    )
    assert arr.stats["melody_track"] == 1
    assert [e.mapped_pitch for e in arr.events] == [60, 62]

    # Single-track vocal_lead drops clash and stays playable
    single = _score_from_notes(
        [
            _note(0, 300, 72, track=0, vel=110),
            _note(0, 300, 71, track=0, vel=70),  # 1-semitone clash against lead 72
            _note(0, 300, 48, track=0, vel=85),
        ],
        (TrackInfo(index=0, name="Mix", note_count=3, channels=(0,)),),
    )
    arr_s = arrange(
        single,
        lyre,
        ArrangeOptions(style=Style.BALANCED, transpose=0, arranger_strategy="vocal_lead"),
    )
    pitches_s = {e.mapped_pitch for e in arr_s.events}
    assert 72 in pitches_s
    assert 48 in pitches_s
    assert 71 not in pitches_s


def test_clean_score_vibrato_merge_velocity_and_merge_stem_scores() -> None:
    raw = _score_from_notes(
        [
            _note(0, 200, 60, track=0, vel=95),
            _note(210, 40, 61, track=0, vel=88),   # ±1 semitone short vibrato dip
            _note(260, 220, 60, track=0, vel=100), # returns to 60 within gap
            _note(490, 120, 60, track=0, vel=90),  # short same-pitch continuation gap
            _note(700, 150, 64, track=0, vel=8),   # low velocity ghost note
        ],
        (TrackInfo(index=0, name="Raw Vocal", note_count=5, channels=(0,)),),
    )
    cleaned, stats = clean_score(
        raw, CleanupOptions(min_note_ms=35, merge_vibrato_gap_ms=60, min_velocity=15)
    )
    assert stats["removed_low_velocity"] == 1
    assert stats["merged_vibrato"] >= 2
    assert len(cleaned.notes) == 1
    assert cleaned.notes[0].pitch == 60
    assert cleaned.notes[0].start_us == 0
    assert cleaned.notes[0].end_us == 610_000

    accomp = _score_from_notes(
        [
            _note(0, 300, 48, track=0, channel=0),
            _note(0, 50, 36, track=1, channel=9),  # GM percussion drum note
        ],
        (
            TrackInfo(index=0, name="Piano", note_count=1, channels=(0,)),
            TrackInfo(index=1, name="Drums", note_count=1, channels=(9,)),
        ),
    )
    merged = merge_stem_scores([("Vocal Lead", cleaned, 0), ("Accompaniment", accomp, 1)])
    assert len(merged.tracks) == 3
    assert merged.tracks[0].name == "Vocal Lead"
    assert merged.tracks[1].name == "Accompaniment: Piano"
    assert merged.tracks[2].channels == (9,)
    assert len(merged.notes) == 3
