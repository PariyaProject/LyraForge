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
_VIBRATO_MAX_DETOUR_US = 90_000


@dataclass(frozen=True, slots=True)
class CleanupOptions:
    min_note_ms: int = 35
    quantize_ms: int | None = None
    merge_vibrato_gap_ms: int = 0
    min_velocity: int = 0

    def validate(self) -> None:
        if self.min_note_ms < 0:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "min_note_ms must be >= 0")
        if self.quantize_ms is not None and self.quantize_ms <= 0:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "quantize_ms must be > 0")
        if self.merge_vibrato_gap_ms < 0:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "merge_vibrato_gap_ms must be >= 0")
        if not 0 <= self.min_velocity <= 127:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "min_velocity must be within [0, 127]")


def _merge_vocal_vibrato(notes: list[Note], gap_ms: int) -> tuple[list[Note], int]:
    """Collapse short 1-semitone vibrato detours (A->B->A) and tiny same-pitch gaps."""
    if gap_ms <= 0 or len(notes) < 2:
        return notes, 0
    max_gap_us = gap_ms * 1000
    by_lane: dict[tuple[int, int], list[Note]] = defaultdict(list)
    for note in notes:
        by_lane[(note.track, note.channel)].append(note)

    merged_out: list[Note] = []
    merged_count = 0

    for lane_notes in by_lane.values():
        ordered = sorted(lane_notes, key=lambda n: (n.start_us, n.end_us, n.pitch))

        # Pass 1: collapse A -> short B (±1 semitone) -> A vibrato oscillation chains.
        deglitched: list[Note] = []
        idx = 0
        while idx < len(ordered):
            cur = ordered[idx]
            if (
                deglitched
                and idx + 1 < len(ordered)
                and cur.duration_us <= _VIBRATO_MAX_DETOUR_US
            ):
                prev = deglitched[-1]
                nxt = ordered[idx + 1]
                if (
                    nxt.pitch == prev.pitch
                    and abs(cur.pitch - prev.pitch) == 1
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

        # Pass 2: join consecutive same-pitch notes separated by <= gap_ms.
        collapsed: list[Note] = []
        for cur in deglitched:
            if (
                collapsed
                and collapsed[-1].pitch == cur.pitch
                and cur.start_us - collapsed[-1].end_us <= max_gap_us
            ):
                prev = collapsed[-1]
                collapsed[-1] = Note(
                    pitch=prev.pitch,
                    velocity=max(prev.velocity, cur.velocity),
                    start_tick=prev.start_tick,
                    end_tick=max(prev.end_tick, cur.end_tick),
                    start_us=prev.start_us,
                    end_us=max(prev.end_us, cur.end_us),
                    track=prev.track,
                    channel=prev.channel,
                )
                merged_count += 1
            else:
                collapsed.append(cur)
        merged_out.extend(collapsed)

    merged_out.sort(key=lambda n: (n.start_us, n.pitch, n.track, n.channel, n.end_us))
    return merged_out, merged_count


def clean_score(
    score: NormalizedScore,
    options: CleanupOptions | None = None,
) -> tuple[NormalizedScore, dict[str, int]]:
    """Return a de-glitched, deduplicated copy of ``score`` plus cleanup stats."""
    options = options or CleanupOptions()
    options.validate()

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

    merged_vibrato = 0
    if options.merge_vibrato_gap_ms > 0:
        cleaned_notes, merged_vibrato = _merge_vocal_vibrato(
            cleaned_notes, options.merge_vibrato_gap_ms
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
    if options.merge_vibrato_gap_ms > 0 or merged_vibrato > 0:
        stats["merged_vibrato"] = merged_vibrato
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
