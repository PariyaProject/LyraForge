"""Deterministic MIDI cleanup, vocal vibrato smoothing, and stem score merging."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.music_core.models import (
    PERCUSSION_CHANNEL,
    NormalizedScore,
    Note,
    TrackInfo,
)
from lyraforge.music_core.tempo import DEFAULT_US_PER_BEAT, TempoChange, TempoMap

_EXPORT_TPB = 500  # 1 tick == 1 ms at 120 BPM (matches midi_export.EXPORT_TPB)
_HARMONIC_INTERVALS = frozenset({12, 19, 24})


@dataclass(frozen=True, slots=True)
class CleanupOptions:
    min_note_ms: int = 35
    quantize_ms: int | None = None
    merge_vibrato_gap_ms: int = 0
    min_velocity: int = 0
    same_pitch_merge_gap_ms: int | None = None
    vibrato_max_detour_ms: int = 90
    vibrato_max_semitones: int = 1
    prune_harmonic_ghosts: bool = False
    repair_octave_glitches: bool = False
    absorb_portamento_ms: int = 0
    preserve_ornaments_ms: int = 0

    def validate(self) -> None:
        if self.min_note_ms < 0:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "min_note_ms must be >= 0")
        if self.quantize_ms is not None and self.quantize_ms <= 0:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "quantize_ms must be > 0")
        if self.merge_vibrato_gap_ms < 0:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "merge_vibrato_gap_ms must be >= 0")
        if not 0 <= self.min_velocity <= 127:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "min_velocity must be within [0, 127]")
        if self.same_pitch_merge_gap_ms is not None and self.same_pitch_merge_gap_ms < 0:
            raise LyraError(
                ErrorCode.INVALID_ARGUMENT, "same_pitch_merge_gap_ms must be >= 0"
            )
        if self.vibrato_max_detour_ms < 0:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "vibrato_max_detour_ms must be >= 0")
        if not 1 <= self.vibrato_max_semitones <= 4:
            raise LyraError(
                ErrorCode.INVALID_ARGUMENT, "vibrato_max_semitones must be within [1, 4]"
            )
        if self.absorb_portamento_ms < 0:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "absorb_portamento_ms must be >= 0")
        if self.preserve_ornaments_ms < 0:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "preserve_ornaments_ms must be >= 0")


VOCAL_CLEANUP_PRESETS: tuple[str, ...] = ("off", "light", "standard", "strong")


def vocal_cleanup_options(preset: str = "standard", *, min_note_ms: int = 45) -> CleanupOptions:
    """Build vocal stem cleanup options for a named preset ('off'|'light'|'standard'|'strong')."""
    key = (preset or "standard").strip().lower()
    if key == "off":
        return CleanupOptions(min_note_ms=min_note_ms)
    if key == "light":
        return CleanupOptions(
            min_note_ms=max(min_note_ms, 35),
            merge_vibrato_gap_ms=45,
            same_pitch_merge_gap_ms=15,
            vibrato_max_detour_ms=120,
            vibrato_max_semitones=1,
            prune_harmonic_ghosts=True,
            repair_octave_glitches=False,
            absorb_portamento_ms=0,
            min_velocity=12,
            preserve_ornaments_ms=35,
        )
    if key == "standard":
        return CleanupOptions(
            min_note_ms=max(min_note_ms, 45),
            merge_vibrato_gap_ms=70,
            same_pitch_merge_gap_ms=18,
            vibrato_max_detour_ms=260,
            vibrato_max_semitones=2,
            prune_harmonic_ghosts=True,
            repair_octave_glitches=True,
            absorb_portamento_ms=55,
            min_velocity=15,
            preserve_ornaments_ms=40,
        )
    if key == "strong":
        return CleanupOptions(
            min_note_ms=max(min_note_ms, 65),
            merge_vibrato_gap_ms=95,
            same_pitch_merge_gap_ms=22,
            vibrato_max_detour_ms=340,
            vibrato_max_semitones=2,
            prune_harmonic_ghosts=True,
            repair_octave_glitches=True,
            absorb_portamento_ms=80,
            min_velocity=22,
            preserve_ornaments_ms=0,
        )
    raise LyraError(
        ErrorCode.INVALID_ARGUMENT,
        f"unknown vocal cleanup preset: {preset!r}",
        {"available": list(VOCAL_CLEANUP_PRESETS)},
    )


def _merge_span(a: Note, b: Note, *, pitch: int | None = None, velocity: int | None = None) -> Note:
    start_us = min(a.start_us, b.start_us)
    end_us = max(a.end_us, b.end_us)
    return Note(
        pitch=a.pitch if pitch is None else pitch,
        velocity=max(a.velocity, b.velocity) if velocity is None else velocity,
        start_tick=min(a.start_tick, b.start_tick),
        end_tick=max(a.end_tick, b.end_tick),
        start_us=start_us,
        end_us=end_us,
        track=a.track,
        channel=a.channel,
    )


def _prune_harmonic_ghosts(lane: list[Note]) -> tuple[list[Note], int]:
    """Remove quieter simultaneous +12/+19/+24 harmonic overtones in a vocal lane."""
    ordered = sorted(lane, key=lambda n: (n.start_us, n.pitch, -n.duration_us))
    drop: set[int] = set()
    for i, cand in enumerate(ordered):
        for j, anchor in enumerate(ordered):
            if i == j or j in drop:
                continue
            if cand.pitch - anchor.pitch not in _HARMONIC_INTERVALS:
                continue
            if anchor.end_us <= cand.start_us:
                continue
            if anchor.start_us >= cand.end_us:
                break
            overlap = min(anchor.end_us, cand.end_us) - max(anchor.start_us, cand.start_us)
            significant_overlap = overlap >= max(20_000, round(0.5 * cand.duration_us))
            quiet_simultaneous_overtone = (
                overlap >= 20_000 and cand.velocity <= anchor.velocity - 15
            )
            if not (significant_overlap or quiet_simultaneous_overtone):
                continue
            if cand.velocity <= anchor.velocity + 5 or (
                cand.duration_us <= round(0.6 * anchor.duration_us)
                and cand.velocity <= anchor.velocity + 8
            ):
                drop.add(i)
                break
    kept = [n for i, n in enumerate(ordered) if i not in drop]
    return kept, len(drop)


def _repair_octave_glitches(lane: list[Note], max_gap_us: int) -> tuple[list[Note], int]:
    """Suppress short isolated +-12 semitone pitch jumps caused by octave errors."""
    ordered = sorted(lane, key=lambda n: (n.start_us, n.end_us, n.pitch))
    if len(ordered) < 3:
        return ordered, 0
    gap_tol = max(max_gap_us, 45_000)
    out: list[Note] = []
    repaired = 0
    idx = 0
    while idx < len(ordered):
        cur = ordered[idx]
        if out and idx + 1 < len(ordered) and cur.duration_us <= 140_000:
            prev = out[-1]
            nxt = ordered[idx + 1]
            if (
                abs(cur.pitch - prev.pitch) == 12
                and cur.start_us - prev.end_us <= gap_tol
                and nxt.start_us - cur.end_us <= gap_tol
                and abs(nxt.pitch - prev.pitch) <= 3
            ):
                if nxt.pitch == prev.pitch:
                    out[-1] = Note(
                        pitch=prev.pitch,
                        velocity=max(prev.velocity, cur.velocity, nxt.velocity),
                        start_tick=prev.start_tick,
                        end_tick=max(prev.end_tick, cur.end_tick, nxt.end_tick),
                        start_us=prev.start_us,
                        end_us=max(prev.end_us, cur.end_us, nxt.end_us),
                        track=prev.track,
                        channel=prev.channel,
                    )
                    repaired += 1
                    idx += 2
                    continue
                if cur.duration_us <= 85_000:
                    repaired += 1
                    idx += 1
                    continue
                fixed_pitch = prev.pitch
                out.append(
                    Note(
                        pitch=fixed_pitch,
                        velocity=cur.velocity,
                        start_tick=cur.start_tick,
                        end_tick=cur.end_tick,
                        start_us=cur.start_us,
                        end_us=cur.end_us,
                        track=cur.track,
                        channel=cur.channel,
                    )
                )
                repaired += 1
                idx += 1
                continue
        out.append(cur)
        idx += 1
    return out, repaired


def _merge_vocal_vibrato_lane(
    lane: list[Note],
    *,
    gap_ms: int,
    same_pitch_gap_ms: int,
    detour_max_ms: int,
    max_semitones: int,
) -> tuple[list[Note], int]:
    """Coalesce overlapping and sequential vibrato detours while preserving repeated syllables."""
    if len(lane) < 2:
        return lane, 0
    max_gap_us = gap_ms * 1000
    same_gap_us = same_pitch_gap_ms * 1000
    detour_max_us = detour_max_ms * 1000
    ordered = sorted(lane, key=lambda n: (n.start_us, n.end_us, n.pitch))
    merged_count = 0

    # 1. Resolve overlapping vibrato oscillations cleanly before sequential chain matching.
    if gap_ms > 0:
        no_ov: list[Note] = []
        for idx, cur in enumerate(ordered):
            if no_ov:
                prev = no_ov[-1]
                diff = abs(cur.pitch - prev.pitch)
                if cur.start_us < prev.end_us and 1 <= diff <= max_semitones:
                    returns = (
                        idx + 1 < len(ordered)
                        and ordered[idx + 1].pitch == prev.pitch
                        and ordered[idx + 1].start_us - cur.end_us <= max_gap_us
                    )
                    if (
                        prev.duration_us < 120_000
                        and cur.duration_us >= prev.duration_us * 2
                        and not returns
                    ):
                        # Short onset wobble preceding sustained target note -> keep target pitch
                        no_ov[-1] = _merge_span(prev, cur, pitch=cur.pitch, velocity=cur.velocity)
                        merged_count += 1
                        continue
                    if (
                        cur.duration_us <= detour_max_us
                        or cur.end_us <= prev.end_us + 80_000
                        or returns
                    ):
                        no_ov[-1] = _merge_span(prev, cur, pitch=prev.pitch)
                        merged_count += 1
                        continue
                    # True legato pitch change: trim overlap so phrasing remains clean
                    trimmed_end = max(prev.start_us + 20_000, cur.start_us)
                    if trimmed_end < prev.end_us:
                        no_ov[-1] = Note(
                            pitch=prev.pitch,
                            velocity=prev.velocity,
                            start_tick=prev.start_tick,
                            end_tick=prev.end_tick,
                            start_us=prev.start_us,
                            end_us=trimmed_end,
                            track=prev.track,
                            channel=prev.channel,
                        )
            no_ov.append(cur)
        ordered = no_ov

        # 2. Collapse sequential A -> short B (±1..max_semitones) -> A vibrato oscillation chains.
        deglitched: list[Note] = []
        idx = 0
        while idx < len(ordered):
            cur = ordered[idx]
            if deglitched and idx + 1 < len(ordered) and cur.duration_us <= detour_max_us:
                prev = deglitched[-1]
                nxt = ordered[idx + 1]
                if (
                    nxt.pitch == prev.pitch
                    and 1 <= abs(cur.pitch - prev.pitch) <= max_semitones
                    and cur.start_us - prev.end_us <= max_gap_us
                    and nxt.start_us - cur.end_us <= max_gap_us
                ):
                    deglitched[-1] = Note(
                        pitch=prev.pitch,
                        velocity=max(prev.velocity, cur.velocity, nxt.velocity),
                        start_tick=prev.start_tick,
                        end_tick=max(prev.end_tick, nxt.end_tick),
                        start_us=prev.start_us,
                        end_us=max(prev.end_us, nxt.end_us),
                        track=prev.track,
                        channel=prev.channel,
                    )
                    merged_count += 2
                    idx += 2
                    continue
            deglitched.append(cur)
            idx += 1
        ordered = deglitched

    # 3. Join ONLY micro-dropouts on same pitch (preserving distinct repeated syllables).
    if same_gap_us > 0:
        collapsed: list[Note] = []
        for cur in ordered:
            if collapsed and collapsed[-1].pitch == cur.pitch:
                prev = collapsed[-1]
                gap_us = cur.start_us - prev.end_us
                both_full_articulated = (
                    gap_us >= -15_000
                    and prev.duration_us >= 130_000
                    and cur.duration_us >= 130_000
                    and cur.velocity >= max(65, prev.velocity - 18)
                )
                if gap_us <= same_gap_us and not both_full_articulated:
                    collapsed[-1] = _merge_span(prev, cur, pitch=prev.pitch)
                    merged_count += 1
                    continue
            collapsed.append(cur)
        ordered = collapsed

    return ordered, merged_count


def _absorb_portamento_scoops(lane: list[Note], max_scoop_ms: int) -> tuple[list[Note], int]:
    """Absorb short monotonic portamento transitions or quiet onset scoops into target notes."""
    if max_scoop_ms <= 0 or len(lane) < 2:
        return lane, 0
    max_scoop_us = max_scoop_ms * 1000
    ordered = sorted(lane, key=lambda n: (n.start_us, n.end_us, n.pitch))
    out: list[Note] = []
    absorbed = 0
    idx = 0
    while idx < len(ordered):
        cur = ordered[idx]
        if idx + 1 < len(ordered) and cur.duration_us <= max_scoop_us:
            nxt = ordered[idx + 1]
            diff = abs(nxt.pitch - cur.pitch)
            gap_to_nxt = nxt.start_us - cur.end_us
            if nxt.duration_us >= 150_000 and -20_000 <= gap_to_nxt <= 25_000 and 1 <= diff <= 2:
                prev = out[-1] if out else None
                monotonic = (
                    prev is not None
                    and cur.start_us - prev.end_us <= 40_000
                    and (
                        (prev.pitch < cur.pitch < nxt.pitch)
                        or (prev.pitch > cur.pitch > nxt.pitch)
                    )
                )
                quiet_scoop = cur.duration_us <= 45_000 and cur.velocity <= nxt.velocity - 8
                if monotonic or quiet_scoop:
                    absorbed += 1
                    idx += 1
                    continue
        out.append(cur)
        idx += 1
    return out, absorbed


def _is_preserved_ornament(lane: list[Note], idx: int, preserve_ms: int) -> bool:
    if preserve_ms <= 0:
        return False
    cur = lane[idx]
    if cur.duration_us < preserve_ms * 1000 or cur.velocity < 75:
        return False
    if idx + 1 < len(lane):
        nxt = lane[idx + 1]
        if (
            nxt.duration_us >= 140_000
            and -15_000 <= nxt.start_us - cur.end_us <= 35_000
            and 1 <= abs(nxt.pitch - cur.pitch) <= 4
        ):
            return True
    return False


def _clean_vocal_score(
    score: NormalizedScore,
    options: CleanupOptions,
) -> tuple[NormalizedScore, dict[str, int]]:
    min_us = options.min_note_ms * 1000
    q_us = options.quantize_ms * 1000 if options.quantize_ms is not None else None

    removed_short = 0
    removed_low_velocity = 0
    best_by_key: dict[tuple[int, int, int, int], Note] = {}

    for n in score.notes:
        if n.duration_us <= 0:
            removed_short += 1
            continue
        if n.velocity < options.min_velocity:
            removed_low_velocity += 1
            continue
        start_us = round(n.start_us / q_us) * q_us if q_us is not None else n.start_us
        end_us = start_us + n.duration_us
        cand = Note(
            pitch=n.pitch,
            velocity=n.velocity,
            start_tick=n.start_tick,
            end_tick=n.end_tick,
            start_us=start_us,
            end_us=end_us,
            track=n.track,
            channel=n.channel,
        )
        dedup_key = (cand.start_us, cand.pitch, cand.track, cand.channel)
        prev = best_by_key.get(dedup_key)
        if prev is None or (cand.velocity, cand.duration_us) > (prev.velocity, prev.duration_us):
            best_by_key[dedup_key] = cand

    deduped = sorted(
        best_by_key.values(),
        key=lambda n: (n.start_us, n.pitch, n.track, n.channel, n.end_us),
    )
    removed_dups = len(score.notes) - removed_short - removed_low_velocity - len(deduped)

    by_lane: dict[tuple[int, int], list[Note]] = defaultdict(list)
    for note in deduped:
        by_lane[(note.track, note.channel)].append(note)

    same_gap_ms = (
        options.same_pitch_merge_gap_ms
        if options.same_pitch_merge_gap_ms is not None
        else min(options.merge_vibrato_gap_ms, 20)
    )
    removed_harmonic_ghosts = 0
    repaired_octave_glitches = 0
    merged_vibrato = 0
    absorbed_portamento = 0
    final_notes: list[Note] = []

    for lane_notes in by_lane.values():
        lane = list(lane_notes)
        if options.prune_harmonic_ghosts:
            lane, n_ghost = _prune_harmonic_ghosts(lane)
            removed_harmonic_ghosts += n_ghost
        if options.repair_octave_glitches:
            lane, n_oct = _repair_octave_glitches(lane, options.merge_vibrato_gap_ms * 1000)
            repaired_octave_glitches += n_oct
        if options.merge_vibrato_gap_ms > 0 or same_gap_ms > 0:
            lane, n_vib = _merge_vocal_vibrato_lane(
                lane,
                gap_ms=options.merge_vibrato_gap_ms,
                same_pitch_gap_ms=same_gap_ms,
                detour_max_ms=options.vibrato_max_detour_ms,
                max_semitones=options.vibrato_max_semitones,
            )
            merged_vibrato += n_vib
        if options.prune_harmonic_ghosts:
            lane, n_ghost2 = _prune_harmonic_ghosts(lane)
            removed_harmonic_ghosts += n_ghost2
        if options.absorb_portamento_ms > 0:
            lane, n_port = _absorb_portamento_scoops(lane, options.absorb_portamento_ms)
            absorbed_portamento += n_port

        # Filter short remnants strictly AFTER vibrato/scoop merging so held phrases aren't lost
        lane_sorted = sorted(lane, key=lambda n: (n.start_us, n.pitch, n.end_us))
        for idx, note in enumerate(lane_sorted):
            if note.duration_us < min_us and not _is_preserved_ornament(
                lane_sorted, idx, options.preserve_ornaments_ms
            ):
                removed_short += 1
                continue
            final_notes.append(note)

    final_notes.sort(key=lambda n: (n.start_us, n.pitch, n.track, n.channel, n.end_us))
    counts: dict[int, int] = defaultdict(int)
    chans: dict[int, set[int]] = defaultdict(set)
    for n in final_notes:
        counts[n.track] += 1
        chans[n.track].add(n.channel)

    tracks = tuple(
        TrackInfo(
            index=t.index,
            name=t.name,
            note_count=counts.get(t.index, 0),
            channels=tuple(sorted(chans.get(t.index, set()))),
        )
        for t in score.tracks
    )
    duration_us = max((n.end_us for n in final_notes), default=0)
    cleaned = NormalizedScore(
        source_sha256=score.source_sha256,
        midi_type=score.midi_type,
        ticks_per_beat=score.ticks_per_beat,
        tempo_map=score.tempo_map,
        time_signatures=score.time_signatures,
        tracks=tracks,
        notes=tuple(final_notes),
        duration_us=duration_us,
        warnings=score.warnings,
    )
    stats: dict[str, int] = {
        "input_notes": len(score.notes),
        "kept_notes": len(final_notes),
        "removed_short_notes": removed_short,
        "removed_duplicates": removed_dups,
        "removed_low_velocity": removed_low_velocity,
        "merged_vibrato": merged_vibrato,
    }
    if removed_harmonic_ghosts:
        stats["removed_harmonic_ghosts"] = removed_harmonic_ghosts
    if repaired_octave_glitches:
        stats["repaired_octave_glitches"] = repaired_octave_glitches
    if absorbed_portamento:
        stats["absorbed_portamento"] = absorbed_portamento
    return cleaned, stats


def clean_score(
    score: NormalizedScore,
    options: CleanupOptions | None = None,
) -> tuple[NormalizedScore, dict[str, int]]:
    """Return a de-glitched, deduplicated copy of ``score`` plus cleanup stats."""
    options = options or CleanupOptions()
    options.validate()

    vocal_passes_active = any(
        (
            options.merge_vibrato_gap_ms > 0,
            options.prune_harmonic_ghosts,
            options.repair_octave_glitches,
            options.absorb_portamento_ms > 0,
        )
    )
    if vocal_passes_active:
        return _clean_vocal_score(score, options)

    min_us = options.min_note_ms * 1000
    q_us = options.quantize_ms * 1000 if options.quantize_ms is not None else None

    removed_short = 0
    removed_low_velocity = 0
    best_by_key: dict[tuple[int, int, int, int], Note] = {}

    for n in score.notes:
        if n.duration_us <= 0 or n.duration_us < min_us:
            removed_short += 1
            continue
        if n.velocity < options.min_velocity:
            removed_low_velocity += 1
            continue
        start_us = round(n.start_us / q_us) * q_us if q_us is not None else n.start_us
        end_us = start_us + max(n.duration_us, min_us)
        cand = Note(
            pitch=n.pitch,
            velocity=n.velocity,
            start_tick=n.start_tick,
            end_tick=n.end_tick,
            start_us=start_us,
            end_us=end_us,
            track=n.track,
            channel=n.channel,
        )
        dedup_key = (cand.start_us, cand.pitch, cand.track, cand.channel)
        prev = best_by_key.get(dedup_key)
        if prev is None or (cand.velocity, cand.duration_us) > (prev.velocity, prev.duration_us):
            best_by_key[dedup_key] = cand

    cleaned_notes = sorted(
        best_by_key.values(),
        key=lambda n: (n.start_us, n.pitch, n.track, n.channel, n.end_us),
    )
    removed_dups = (
        len(score.notes) - removed_short - removed_low_velocity - len(cleaned_notes)
    )

    counts: dict[int, int] = defaultdict(int)
    chans: dict[int, set[int]] = defaultdict(set)
    for n in cleaned_notes:
        counts[n.track] += 1
        chans[n.track].add(n.channel)

    tracks = tuple(
        TrackInfo(
            index=t.index,
            name=t.name,
            note_count=counts.get(t.index, 0),
            channels=tuple(sorted(chans.get(t.index, set()))),
        )
        for t in score.tracks
    )
    duration_us = max((n.end_us for n in cleaned_notes), default=0)

    cleaned = NormalizedScore(
        source_sha256=score.source_sha256,
        midi_type=score.midi_type,
        ticks_per_beat=score.ticks_per_beat,
        tempo_map=score.tempo_map,
        time_signatures=score.time_signatures,
        tracks=tracks,
        notes=tuple(cleaned_notes),
        duration_us=duration_us,
        warnings=score.warnings,
    )
    stats: dict[str, int] = {
        "input_notes": len(score.notes),
        "kept_notes": len(cleaned_notes),
        "removed_short_notes": removed_short,
        "removed_duplicates": removed_dups,
    }
    if options.min_velocity > 0 or removed_low_velocity > 0:
        stats["removed_low_velocity"] = removed_low_velocity
    return cleaned, stats


def _pick_non_perc_channel(preferred: int, used: set[int]) -> int:
    pool = [ch for ch in range(16) if ch != PERCUSSION_CHANNEL]
    if preferred != PERCUSSION_CHANNEL and 0 <= preferred <= 15 and preferred not in used:
        used.add(preferred)
        return preferred
    for ch in pool:
        if ch not in used:
            used.add(ch)
            return ch
    fallback = preferred if (preferred != PERCUSSION_CHANNEL and 0 <= preferred <= 15) else 0
    return fallback


def merge_stem_scores(stems: Sequence[tuple[str, NormalizedScore, int]]) -> NormalizedScore:
    """Merge stem scores (e.g. Vocal Lead + Accompaniment) into one multi-track score."""
    merged_notes: list[Note] = []
    merged_tracks: list[TrackInfo] = []
    warnings: list[str] = []
    used_channels: set[int] = set()
    next_track_idx = 0

    for base_name, stem_score, preferred_channel in stems:
        warnings.extend(stem_score.warnings)
        by_track: dict[int, list[Note]] = defaultdict(list)
        for note in stem_score.notes:
            by_track[note.track].append(note)
        if not by_track:
            continue

        orig_names = {t.index: (t.name or "").strip() for t in stem_score.tracks}
        multi = len(by_track) > 1
        clean_base = base_name.strip()

        for src_track_idx in sorted(by_track):
            t_notes = by_track[src_track_idx]
            is_perc = all(n.is_percussion for n in t_notes)
            out_channel = (
                PERCUSSION_CHANNEL
                if is_perc
                else _pick_non_perc_channel(preferred_channel, used_channels)
            )
            orig_name = orig_names.get(src_track_idx, "")
            if not multi:
                track_name = clean_base or orig_name or f"track_{next_track_idx}"
            elif orig_name and not orig_name.lower().startswith("track_"):
                track_name = f"{clean_base}: {orig_name}" if clean_base else orig_name
            else:
                track_name = f"{clean_base or 'track'} #{src_track_idx}"

            for note in t_notes:
                start_us = max(0, note.start_us)
                end_us = max(start_us + 1000, note.end_us)
                start_tick = round(start_us / 1000)
                end_tick = max(start_tick + 1, round(end_us / 1000))
                merged_notes.append(
                    Note(
                        pitch=note.pitch,
                        velocity=note.velocity,
                        start_tick=start_tick,
                        end_tick=end_tick,
                        start_us=start_us,
                        end_us=end_us,
                        track=next_track_idx,
                        channel=out_channel,
                    )
                )

            merged_tracks.append(
                TrackInfo(
                    index=next_track_idx,
                    name=track_name,
                    note_count=len(t_notes),
                    channels=(out_channel,),
                )
            )
            next_track_idx += 1

    merged_notes.sort(key=lambda n: (n.start_us, n.pitch, n.track, n.channel, n.end_us))
    duration_us = max((n.end_us for n in merged_notes), default=0)
    digest_payload = json.dumps(
        {
            "tracks": [[t.index, t.name, list(t.channels)] for t in merged_tracks],
            "notes": [
                [n.start_us, n.end_us, n.pitch, n.velocity, n.track, n.channel]
                for n in merged_notes
            ],
        },
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    source_sha256 = hashlib.sha256(digest_payload).hexdigest()

    return NormalizedScore(
        source_sha256=source_sha256,
        midi_type=1 if len(merged_tracks) > 1 else 0,
        ticks_per_beat=_EXPORT_TPB,
        tempo_map=TempoMap(_EXPORT_TPB, [TempoChange(0, DEFAULT_US_PER_BEAT)]),
        time_signatures=(),
        tracks=tuple(merged_tracks),
        notes=tuple(merged_notes),
        duration_us=duration_us,
        warnings=tuple(dict.fromkeys(warnings)),
    )
