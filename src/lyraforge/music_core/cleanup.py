"""Deterministic MIDI cleanup (de-glitching, optional quantization, deduplication)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.music_core.models import NormalizedScore, Note, TrackInfo


@dataclass(frozen=True, slots=True)
class CleanupOptions:
    min_note_ms: int = 35
    quantize_ms: int | None = None

    def validate(self) -> None:
        if self.min_note_ms < 0:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "min_note_ms must be >= 0")
        if self.quantize_ms is not None and self.quantize_ms <= 0:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "quantize_ms must be > 0")


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
    best_by_key: dict[tuple[int, int, int, int], Note] = {}

    for n in score.notes:
        if n.duration_us <= 0 or n.duration_us < min_us:
            removed_short += 1
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
    removed_dups = (len(score.notes) - removed_short) - len(cleaned_notes)

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
    stats = {
        "input_notes": len(score.notes),
        "kept_notes": len(cleaned_notes),
        "removed_short_notes": removed_short,
        "removed_duplicates": removed_dups,
    }
    return cleaned, stats
