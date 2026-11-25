"""Reproducible musical dynamics benchmark comparing classic, vocal_lead, and vocal_dynamic."""

from __future__ import annotations

import statistics
from typing import Any

from lyraforge.instruments import load_builtin_profile
from lyraforge.music_core import (
    ArrangeOptions,
    NormalizedScore,
    Note,
    StemDynamics,
    TempoChange,
    TempoMap,
    TrackInfo,
    arrange,
    score_arrangement,
)
from lyraforge.music_core.arranger import Style


def _make_score(notes: list[Note], tracks: tuple[TrackInfo, ...]) -> NormalizedScore:
    ordered = sorted(notes, key=lambda n: (n.start_us, n.pitch, n.track, n.channel, n.end_us))
    return NormalizedScore(
        source_sha256="b" * 64,
        midi_type=1,
        ticks_per_beat=500,
        tempo_map=TempoMap(500, [TempoChange(0, 500_000)]),
        time_signatures=(),
        tracks=tracks,
        notes=tuple(ordered),
        duration_us=max((n.end_us for n in ordered), default=0),
        warnings=(),
    )


def _note(ms: int, dur_ms: int, pitch: int, *, track: int, vel: int = 96) -> Note:
    return Note(
        pitch=pitch,
        velocity=vel,
        start_tick=ms,
        end_tick=ms + dur_ms,
        start_us=ms * 1000,
        end_us=(ms + dur_ms) * 1000,
        track=track,
        channel=track,
    )


def _scenario_climax_plus_offset() -> tuple[NormalizedScore, StemDynamics]:
    """Scenario 1: Vocal climax + dense 16th accompaniment + 25 ms cross-stem jitter."""
    tracks = (
        TrackInfo(index=0, name="Vocals", note_count=12, channels=(0,)),
        TrackInfo(index=1, name="Guitar", note_count=33, channels=(1,)),
    )
    melody = [
        _note(i * 400, 320, 72 + (i % 4) * 2, track=0, vel=112)
        for i in range(12)
    ]
    # Dense 16th accompaniment shifted +25 ms from beat + one 15 ms arpeggio sweep at 4800 ms
    accomp = [
        _note(i * 150 + 25, 130, 55 + (i % 3) * 4, track=1, vel=88)
        for i in range(30)
    ] + [
        _note(4800, 180, 48, track=1, vel=80),
        _note(4815, 180, 52, track=1, vel=80),
        _note(4830, 180, 55, track=1, vel=80),
    ]
    # 500ms frames over ~5.5s: vocal climax loud (-8 dBFS) vs busy accomp (-14 dBFS)
    dyn = StemDynamics(
        hop_ms=500,
        vocal_db=(-18.0, -16.0, -8.0, -7.5, -8.0, -8.5, -8.0, -7.5, -9.0, -10.0, -14.0),
        accomp_db=(-16.0, -15.0, -13.0, -12.5, -13.0, -13.5, -14.0, -13.0, -14.0, -15.0, -16.0),
    )
    return _make_score(melody + accomp, tracks), dyn


def _scenario_muddy_verse_high_chorus() -> tuple[NormalizedScore, StemDynamics]:
    """Scenario 2: Low verse C3..G3 + mid guitar + bright chorus G4..E5."""
    tracks = (
        TrackInfo(index=0, name="Vocals", note_count=16, channels=(0,)),
        TrackInfo(index=1, name="Piano", note_count=16, channels=(1,)),
    )
    verse_pitches = [48, 50, 52, 53, 55, 53, 52, 50]
    chorus_pitches = [67, 69, 71, 72, 74, 76, 74, 72]
    notes: list[Note] = []
    for idx, p in enumerate(verse_pitches):
        notes.append(_note(idx * 400, 320, p, track=0, vel=85))
    # Breath gap 800 ms, then bright chorus starting at 4000 ms
    for idx, p in enumerate(chorus_pitches):
        notes.append(_note(4000 + idx * 400, 320, p, track=0, vel=112))
    # Mid-register piano accompaniment spanning 0..7200 ms
    for i in range(16):
        notes.append(_note(i * 450, 300, 55 + (i % 3) * 2, track=1, vel=84))
    dyn = StemDynamics(
        hop_ms=500,
        vocal_db=(
            -22.0, -21.0, -20.0, -21.0, -22.0, -23.0, -35.0,
            -10.0, -8.0, -8.5, -9.0, -9.0, -9.5, -10.0,
        ),
        accomp_db=(
            -16.0, -15.5, -16.0, -15.5, -16.0, -16.0, -15.0,
            -14.0, -14.5, -14.0, -14.5, -15.0, -15.0, -15.0,
        ),
    )
    return _make_score(notes, tracks), dyn


def _scenario_verse_climax_interlude() -> tuple[NormalizedScore, StemDynamics]:
    """Scenario 3: Quiet verse (0-2s), Vocal Climax (2-5s), Instrumental Interlude (5-7.5s)."""
    tracks = (
        TrackInfo(index=0, name="Vocals", note_count=10, channels=(0,)),
        TrackInfo(index=1, name="Strings", note_count=26, channels=(1,)),
    )
    notes: list[Note] = []
    # Verse: sparse melody 0..1600ms
    for i in range(3):
        notes.append(_note(i * 600, 400, 62 + i * 2, track=0, vel=82))
    # Climax: active high vocal 2000..4800ms
    for i in range(7):
        notes.append(_note(2000 + i * 400, 340, 72 + (i % 4) * 2, track=0, vel=115))
    # Dense accompaniment across all 7.5s (no vocal after 4800ms)
    for i in range(26):
        notes.append(_note(i * 280, 200, 48 + (i % 4) * 2, track=1, vel=88))
    dyn = StemDynamics(
        hop_ms=500,
        vocal_db=(
            -24.0, -23.0, -22.0, -24.0,   # 0..2s quiet verse
            -8.0, -7.5, -7.0, -8.0, -8.5, -9.0,  # 2..5s climax
            -58.0, -58.0, -58.0, -58.0, -58.0,   # 5..7.5s interlude (vocal silent)
        ),
        accomp_db=(
            -20.0, -19.0, -20.0, -20.0,
            -14.0, -14.0, -13.5, -14.0, -14.0, -15.0,
            -11.0, -10.5, -10.0, -11.0, -11.5,
        ),
    )
    return _make_score(notes, tracks), dyn


def run_benchmark() -> list[dict[str, Any]]:
    profile = load_builtin_profile("genshin.windsong_lyre.v1")
    scenarios = [
        ("1_climax_plus_offset", *_scenario_climax_plus_offset()),
        ("2_muddy_verse_high_chorus", *_scenario_muddy_verse_high_chorus()),
        ("3_verse_climax_interlude", *_scenario_verse_climax_interlude()),
    ]
    strategies = ("classic", "vocal_lead", "vocal_dynamic")
    results: list[dict[str, Any]] = []

    for name, score, dyn in scenarios:
        for strat in strategies:
            arr = arrange(
                score,
                profile,
                ArrangeOptions(
                    style=Style.BALANCED,
                    arranger_strategy=strat,
                ),
                stem_dynamics=dyn,
            )
            mel_events = [e for e in arr.events if e.source_track == 0]
            acc_events = [e for e in arr.events if e.source_track != 0]
            quality = score_arrangement(score, arr)
            # Verse pitches in scenario 2 are < 3200 ms; climax in scenario 3 is 2000..4800ms
            verse_mel_pitches = [e.mapped_pitch for e in mel_events if e.at_ms < 3200]
            climax_acc = [e for e in acc_events if 2000 <= e.at_ms <= 4800]
            interlude_acc = [e for e in acc_events if e.at_ms >= 5000]
            stats_dyn = arr.stats.get("dynamics_adjustments") or {}
            row = {
                "scenario": name,
                "strategy": strat,
                "mel_events": len(mel_events),
                "acc_events": len(acc_events),
                "climax_acc": len(climax_acc),
                "interlude_acc": len(interlude_acc),
                "verse_med_pitch": (
                    round(statistics.median(verse_mel_pitches), 1)
                    if verse_mel_pitches
                    else None
                ),
                "acc_thinned": stats_dyn.get("accomp_thinned", 0),
                "aligned": stats_dyn.get("cross_stem_aligned", 0),
                "phrases_up": stats_dyn.get("phrases_shifted_up", 0),
                "overall_score": round(quality.overall_score, 1),
            }
            results.append(row)
    return results


def main() -> None:
    rows = run_benchmark()
    print("LyraForge Musical Dynamics Benchmark (windsong_lyre 21-key)")
    print(
        f"{'Scenario':28s} {'Strategy':14s} {'Mel':>4s} {'Acc':>4s} "
        f"{'ClimaxAcc':>9s} {'InterAcc':>8s} {'VerseMed':>8s} "
        f"{'Thin':>5s} {'Align':>5s} {'Up':>3s} {'Score':>6s}"
    )
    print("-" * 105)
    for r in rows:
        vm = "-" if r["verse_med_pitch"] is None else f"{r['verse_med_pitch']:.1f}"
        sc = "-" if r["overall_score"] is None else f"{r['overall_score']:.1f}"
        print(
            f"{r['scenario']:28s} {r['strategy']:14s} {r['mel_events']:4d} {r['acc_events']:4d} "
            f"{r['climax_acc']:9d} {r['interlude_acc']:8d} {vm:>8s} "
            f"{r['acc_thinned']:5d} {r['aligned']:5d} {r['phrases_up']:3d} {sc:>6s}"
        )


if __name__ == "__main__":
    main()
