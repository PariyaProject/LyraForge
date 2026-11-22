"""Unit and store tests for M3 instrument profiles, melody extraction, scoring, and editing."""

from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import mido
import pytest

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.instruments import DEFAULT_PROFILE_ID, list_profile_ids, load_builtin_profile
from lyraforge.library import SCHEMA_VERSION, LibraryStore
from lyraforge.music_core import (
    ArrangeOptions,
    NormalizedScore,
    Note,
    TempoChange,
    TempoMap,
    TimeSignature,
    TrackInfo,
    arrange,
    compare_arrangements,
    detect_melody_track,
    parse_midi_bytes,
    score_arrangement,
)
from lyraforge.music_core.arranger import SemitonePolicy, Style
from lyraforge.music_core.performance import build_report


def _note(
    start_us: int,
    dur_us: int,
    pitch: int,
    velocity: int = 85,
    track: int = 0,
    channel: int = 0,
) -> Note:
    return Note(
        pitch=pitch,
        velocity=velocity,
        start_tick=start_us // 1000,
        end_tick=(start_us + dur_us) // 1000,
        start_us=start_us,
        end_us=start_us + dur_us,
        track=track,
        channel=channel,
    )


def _build_score(notes: list[Note], tracks: tuple[TrackInfo, ...] = ()) -> NormalizedScore:
    ordered = tuple(
        sorted(notes, key=lambda n: (n.start_us, n.pitch, n.track, n.channel, n.end_us))
    )
    return NormalizedScore(
        source_sha256="a" * 64,
        midi_type=1 if len(tracks) > 1 else 0,
        ticks_per_beat=480,
        tempo_map=TempoMap(480, (TempoChange(0, 500_000),)),
        time_signatures=(TimeSignature(0, 0, 4, 4),),
        tracks=tracks,
        notes=ordered,
        duration_us=max((n.end_us for n in ordered), default=0),
        warnings=(),
    )


def _make_midi_bytes(track_notes: list[tuple[int, int, int]]) -> bytes:
    """Create a minimal single-track MIDI from (start_tick, pitch, dur_tick)."""
    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    tr.append(mido.MetaMessage("set_tempo", tempo=500_000, time=0))
    events: list[tuple[int, int, int]] = []
    for st, p, dur in track_notes:
        events.append((st, 1, p))
        events.append((st + dur, 0, p))
    events.sort(key=lambda x: (x[0], x[1]))
    cur = 0
    for t, on, p in events:
        tr.append(
            mido.Message(
                "note_on" if on else "note_off",
                note=p,
                velocity=80 if on else 0,
                time=t - cur,
            )
        )
        cur = t
    tr.append(mido.MetaMessage("end_of_track", time=0))
    mid.tracks.append(tr)
    buf = io.BytesIO()
    mid.save(file=buf)
    return buf.getvalue()


def test_floral_zither_profile_loaded_and_ordered() -> None:
    ids = list_profile_ids()
    assert ids[0] == DEFAULT_PROFILE_ID
    assert "genshin.floral_zither.v1" in ids
    zither = load_builtin_profile("genshin.floral_zither.v1")
    assert len(zither.keys) == 21
    assert zither.timing.default_key_hold_ms == 50
    assert zither.calibration_status == "unverified"


def test_detect_melody_track_prefers_high_monophonic_lead() -> None:
    notes: list[Note] = []
    for i in range(4):
        st = i * 500_000
        for p in (48, 52, 55):
            notes.append(_note(st, 300_000, p, velocity=80, track=0, channel=0))
    for i, p in enumerate((72, 74, 76, 79)):
        notes.append(_note(i * 500_000, 300_000, p, velocity=95, track=1, channel=1))
    tracks = (
        TrackInfo(0, "Accompaniment", 12, (0,)),
        TrackInfo(1, "Lead", 4, (1,)),
    )
    score = _build_score(notes, tracks)

    assert detect_melody_track(score) == 1

    prof = load_builtin_profile()
    arr = arrange(score, prof, ArrangeOptions(style=Style.MELODY, transpose=0))
    assert arr.stats["melody_track"] == 1
    assert all(e.source_track == 1 for e in arr.events)
    assert [e.mapped_pitch for e in arr.events] == [72, 74, 76, 79]


def test_arpeggiate_staggers_chords_and_validates_bounds() -> None:
    with pytest.raises(LyraError) as exc:
        ArrangeOptions(arpeggiate_ms=61).validate()
    assert exc.value.code == ErrorCode.INVALID_ARGUMENT

    notes = [
        _note(0, 300_000, 60),
        _note(0, 300_000, 64),
        _note(0, 300_000, 67),
    ]
    score = _build_score(notes)
    prof = load_builtin_profile()
    arr = arrange(score, prof, ArrangeOptions(style=Style.RICH, transpose=0, arpeggiate_ms=25))
    assert [(e.at_ms, e.mapped_pitch) for e in arr.events] == [(0, 60), (25, 64), (50, 67)]


def test_quality_scoring_and_ab_comparison() -> None:
    scale_notes = [
        _note(i * 400_000, 250_000, p)
        for i, p in enumerate((60, 62, 64, 65, 67, 69, 71, 72))
    ]
    score = _build_score(scale_notes)
    prof = load_builtin_profile()

    good_arr = arrange(score, prof, ArrangeOptions(style=Style.BALANCED, transpose=0))
    bad_arr = arrange(
        score,
        prof,
        ArrangeOptions(style=Style.BALANCED, transpose=1, semitone_policy=SemitonePolicy.DROP),
    )
    q_good = score_arrangement(score, good_arr)
    q_bad = score_arrangement(score, bad_arr)
    assert q_good.overall_score >= 95.0
    assert q_bad.overall_score < q_good.overall_score

    rep_good = build_report(score, prof, good_arr)
    rep_bad = build_report(score, prof, bad_arr)
    cmp = compare_arrangements(rep_good, rep_bad, "good", "bad")
    assert cmp["winner"] == "good"
    assert cmp["score_delta"] > 0


def test_library_v3_edit_favorite_vote_and_compare(tmp_path: Path) -> None:
    from lyraforge.library.schema import _MIGRATION_V1

    data_dir = tmp_path / "lib_m3"
    data_dir.mkdir()
    conn = sqlite3.connect(data_dir / "library.db")
    try:
        conn.executescript(_MIGRATION_V1)
        conn.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO schema_migrations VALUES (1, '2026-11-22T00:00:00Z')")
        conn.commit()
    finally:
        conn.close()

    mid_file = tmp_path / "sample.mid"
    mid_file.write_bytes(_make_midi_bytes([(0, 60, 240), (480, 64, 240), (960, 67, 240)]))

    with LibraryStore(data_dir) as store:
        assert store.schema_version == SCHEMA_VERSION
        imp = store.import_midi(mid_file, title="Arp Check")
        arr_a = store.arrange_song(
            imp.song.id,
            profile_id="genshin.floral_zither.v1",
            options=ArrangeOptions(style=Style.BALANCED, transpose=0),
            label="A版",
        )
        arr_b = store.arrange_song(
            imp.song.id,
            profile_id="genshin.floral_zither.v1",
            options=ArrangeOptions(style=Style.RICH, transpose=0, arpeggiate_ms=20),
            label="B版",
        )
        assert arr_a.score is not None and arr_a.score >= 90.0
        assert arr_a.label == "A版"

        perf = store.load_arrangement_performance(arr_a.id)
        edited_events = list(perf["events"])
        edited_events.append({"at_ms": 1500, "key_id": "high_1", "hold_ms": 45})
        child = store.save_edited_arrangement(arr_a.id, edited_events, label="人工微调")
        assert child.parent_id == arr_a.id
        assert child.label == "人工微调"
        assert child.event_count == 4
        exported_mid = store.export_arrangement(child.id, "midi")
        reparsed = parse_midi_bytes(exported_mid)
        assert len(reparsed.notes) == 4

        fav = store.set_favorite(child.id, True)
        assert fav.is_favorite is True
        voted = store.set_user_vote(child.id, 1)
        assert voted.user_vote == 1
        with pytest.raises(LyraError) as bad_vote:
            store.set_user_vote(child.id, 2)
        assert bad_vote.value.code == ErrorCode.INVALID_ARGUMENT
        with pytest.raises(LyraError) as bad_key:
            store.save_edited_arrangement(arr_a.id, [{"at_ms": 0, "key_id": "nonexistent"}])
        assert bad_key.value.code == ErrorCode.INVALID_ARGUMENT

        cmp = store.compare_arrangements(arr_a.id, arr_b.id)
        assert cmp["winner"] in {arr_a.id, arr_b.id, "tie"}
        assert "overall_score" in cmp["metrics"]
