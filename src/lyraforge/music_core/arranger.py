"""Rule-based baseline arranger: NormalizedScore + InstrumentProfile -> key events.

Pipeline (PROJECT_SPEC §4.2, baseline subset), every step deterministic:

1. Track filter (drop GM percussion channel by default, optional track whitelist).
2. Global transposition: fixed, or auto-search minimizing an integer cost
   (0 = direct key, 1 = needs octave fold, 2 = chromatic note missing on the
   instrument); ties broken by smallest |k|, then lowest k. Uniform
   transposition preserves every interval, so it cannot make a melody "out of
   tune" relative to itself; the semitone cost prevents choosing a key that
   forces many substitutions.
3. Range: out-of-range notes are folded by whole octaves (recorded).
4. Missing semitones: ``nearest`` (tie -> lower pitch, max 2 semitones) or ``drop``.
5. Same key at the same millisecond -> keep one (unadjusted, louder, longer first).
6. Chord limit per onset cluster (``chord_window_ms``): keep highest, then
   lowest, then remaining from high to low.
7. Same-key retrigger faster than ``min_same_key_interval_ms`` -> dropped.
8. Tap events with hold clamped to profile timing and never overlapping the
   next press of the same key.

Every dropped or altered note is recorded so previews can show what changed.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction
from typing import Any

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.music_core.models import NormalizedScore, Note, TrackInfo
from lyraforge.music_core.profile import InstrumentProfile

ARRANGER_VERSION = "0.1.0"

MAX_SUBSTITUTION_SEMITONES = 2


class Style(StrEnum):
    MELODY = "melody"
    BALANCED = "balanced"
    RICH = "rich"


STYLE_MAX_CHORD_KEYS: dict[Style, int] = {Style.MELODY: 1, Style.BALANCED: 3, Style.RICH: 6}


class SemitonePolicy(StrEnum):
    NEAREST = "nearest"
    DROP = "drop"


class Adjustment(StrEnum):
    OCTAVE_FOLDED = "octave_folded"
    SEMITONE_SUBSTITUTED = "semitone_substituted"


class DropReason(StrEnum):
    OUT_OF_RANGE = "out_of_range"
    SEMITONE_DROPPED = "semitone_dropped"
    DUPLICATE_KEY = "duplicate_key"
    POLYPHONY_LIMIT = "polyphony_limit"
    REPEAT_TOO_FAST = "repeat_too_fast"


@dataclass(frozen=True)
class ArrangeOptions:
    style: Style = Style.BALANCED
    transpose: int | None = None  # None -> automatic search
    transpose_search: int = 24
    semitone_policy: SemitonePolicy = SemitonePolicy.NEAREST
    max_chord_keys: int | None = None  # None -> style default
    chord_window_ms: int = 20
    speed: float = 1.0
    include_tracks: tuple[int, ...] | None = None
    exclude_percussion: bool = True
    arpeggiate_ms: int = 0
    prefer_melody_track: bool = True

    def validate(self) -> None:
        problems: list[str] = []
        if self.transpose is not None and not -48 <= self.transpose <= 48:
            problems.append("transpose must be within [-48, 48]")
        if not 0 <= self.transpose_search <= 48:
            problems.append("transpose_search must be within [0, 48]")
        if self.max_chord_keys is not None and not 1 <= self.max_chord_keys <= 32:
            problems.append("max_chord_keys must be within [1, 32]")
        if not 0 <= self.chord_window_ms <= 200:
            problems.append("chord_window_ms must be within [0, 200]")
        if not (isinstance(self.speed, (int, float)) and math.isfinite(self.speed)
                and 0.25 <= self.speed <= 4.0):
            problems.append("speed must be a finite number within [0.25, 4.0]")
        if self.include_tracks is not None and any(t < 0 for t in self.include_tracks):
            problems.append("include_tracks must be non-negative")
        if not 0 <= self.arpeggiate_ms <= 60:
            problems.append("arpeggiate_ms must be within [0, 60]")
        if problems:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "invalid arrange options",
                            {"problems": problems})

    def effective_max_chord_keys(self, profile: InstrumentProfile) -> int:
        limit = self.max_chord_keys or STYLE_MAX_CHORD_KEYS[Style(self.style)]
        if profile.polyphony_limit is not None:
            limit = min(limit, profile.polyphony_limit)
        return limit


@dataclass(frozen=True, slots=True)
class PerformanceEvent:
    at_ms: int
    key_id: str
    hold_ms: int
    source_pitch: int
    mapped_pitch: int
    source_track: int
    source_channel: int
    velocity: int
    adjustments: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "at_ms": self.at_ms,
            "key_id": self.key_id,
            "action": "tap",
            "hold_ms": self.hold_ms,
            "source_pitch": self.source_pitch,
            "mapped_pitch": self.mapped_pitch,
            "source_track": self.source_track,
            "source_channel": self.source_channel,
            "velocity": self.velocity,
            "adjustments": list(self.adjustments),
        }


@dataclass(frozen=True, slots=True)
class DroppedNote:
    at_ms: int
    source_pitch: int
    mapped_pitch: int | None
    source_track: int
    reason: str

    def to_json(self) -> dict[str, Any]:
        return {"at_ms": self.at_ms, "source_pitch": self.source_pitch,
                "mapped_pitch": self.mapped_pitch, "source_track": self.source_track,
                "reason": self.reason}


@dataclass(frozen=True)
class Arrangement:
    events: tuple[PerformanceEvent, ...]
    dropped: tuple[DroppedNote, ...]
    transpose: int
    transpose_candidates: tuple[tuple[int, int], ...]  # (semitones, cost), best first
    max_chord_keys: int
    options: ArrangeOptions
    stats: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class _Cand:
    note: Note
    mapped: int
    key_id: str
    at_ms: int
    dur_ms: int
    adj: tuple[str, ...]


def _transpose_cost(notes: list[Note], k: int, pitch_set: frozenset[int],
                    pcs: frozenset[int]) -> int:
    cost = 0
    for n in notes:
        p = n.pitch + k
        if p in pitch_set:
            continue
        cost += 1 if (p % 12) in pcs else 2
    return cost


def _search_transpose(notes: list[Note], profile: InstrumentProfile,
                      search: int) -> tuple[int, tuple[tuple[int, int], ...]]:
    pitch_set = frozenset(profile.pitches)
    pcs = frozenset(p % 12 for p in pitch_set)
    scored = sorted(
        ((k, _transpose_cost(notes, k, pitch_set, pcs)) for k in range(-search, search + 1)),
        key=lambda kc: (kc[1], abs(kc[0]), kc[0]),
    )
    return scored[0][0], tuple(scored[:5])


_MELODY_NAME_HINTS = ("melody", "lead", "vocal", "voice", "solo", "flute", "violin", "main")
_ACCOMP_NAME_HINTS = ("bass", "chord", "accomp", "drum", "perc", "pad", "rhythm")


def _detect_melody_track_from_notes(
    notes: list[Note],
    tracks: tuple[TrackInfo, ...],
) -> int | None:
    by_track: dict[int, list[Note]] = defaultdict(list)
    for n in notes:
        if not n.is_percussion:
            by_track[n.track].append(n)
    if not by_track:
        return None
    if len(by_track) == 1:
        return next(iter(by_track))

    track_names = {t.index: (t.name or "").lower() for t in tracks}
    max_notes = max(len(t_notes) for t_notes in by_track.values())
    best_track: int | None = None
    best_key: tuple[float, int, int] = (-1.0, 0, 0)

    for track_id, t_notes in by_track.items():
        mean_pitch = sum(n.pitch for n in t_notes) / len(t_notes)
        mean_vel = sum(n.velocity for n in t_notes) / len(t_notes)
        onsets = sorted(n.start_us // 20_000 for n in t_notes)
        unique_onsets = len(set(onsets))
        avg_poly = len(t_notes) / max(1, unique_onsets)
        presence = min(1.0, len(t_notes) / max(1, max_notes))
        mono_weight = min(1.0, len(t_notes) / 4.0)
        name = track_names.get(track_id, "")
        name_bonus = 0.15 if any(h in name for h in _MELODY_NAME_HINTS) else 0.0
        if any(h in name for h in _ACCOMP_NAME_HINTS):
            name_bonus -= 0.10
        score_val = (
            (mean_pitch / 127.0) * 0.40
            + (1.0 / avg_poly) * 0.30 * mono_weight
            + presence * 0.20
            + (mean_vel / 127.0) * 0.10
            + name_bonus
        )
        rank = (round(score_val, 6), len(t_notes), -track_id)
        if best_track is None or rank > best_key:
            best_track = track_id
            best_key = rank
    return best_track


def detect_melody_track(score: NormalizedScore) -> int | None:
    """Identify the track index most likely carrying the lead melody."""
    return _detect_melody_track_from_notes(list(score.notes), score.tracks)


def _scale_ms(us: int, speed: Fraction) -> int:
    return round(Fraction(us, 1000) / speed)


def arrange(score: NormalizedScore, profile: InstrumentProfile,
            options: ArrangeOptions | None = None) -> Arrangement:
    options = options or ArrangeOptions()
    options.validate()
    speed = Fraction(options.speed).limit_denominator(10_000)
    max_chord = options.effective_max_chord_keys(profile)
    timing = profile.timing
    dropped: list[DroppedNote] = []

    # 1. track filter
    notes: list[Note] = []
    excluded_percussion = excluded_tracks = 0
    include = set(options.include_tracks) if options.include_tracks is not None else None
    for n in score.notes:
        if options.exclude_percussion and n.is_percussion:
            excluded_percussion += 1
        elif include is not None and n.track not in include:
            excluded_tracks += 1
        else:
            notes.append(n)
    if not notes:
        raise LyraError(ErrorCode.NO_PLAYABLE_NOTES,
                        "no pitched notes left after track/percussion filtering",
                        {"input_notes": len(score.notes),
                         "excluded_percussion": excluded_percussion,
                         "excluded_tracks": excluded_tracks})

    distinct_tracks = {n.track for n in notes}
    melody_track = _detect_melody_track_from_notes(notes, score.tracks)

    # 2. transposition
    if options.transpose is None:
        k, candidates = _search_transpose(notes, profile, options.transpose_search)
    else:
        k = options.transpose
        pitch_set = frozenset(profile.pitches)
        pcs = frozenset(p % 12 for p in pitch_set)
        candidates = ((k, _transpose_cost(notes, k, pitch_set, pcs)),)

    # 3-4. range folding + semitone handling
    lo, hi = profile.min_pitch, profile.max_pitch
    available = profile.pitches
    cands: list[_Cand] = []
    for n in notes:
        at_ms = _scale_ms(n.start_us, speed)
        p = n.pitch + k
        adj: list[str] = []
        if p < lo:
            p += 12 * math.ceil((lo - p) / 12)
            adj.append(Adjustment.OCTAVE_FOLDED)
        elif p > hi:
            p -= 12 * math.ceil((p - hi) / 12)
            adj.append(Adjustment.OCTAVE_FOLDED)
        if not lo <= p <= hi:
            dropped.append(DroppedNote(at_ms, n.pitch, None, n.track, DropReason.OUT_OF_RANGE))
            continue
        key = profile.key_for_pitch(p)
        if key is None:
            nearest = min(available, key=lambda c: (abs(c - p), c))
            if (options.semitone_policy == SemitonePolicy.DROP
                    or abs(nearest - p) > MAX_SUBSTITUTION_SEMITONES):
                dropped.append(DroppedNote(at_ms, n.pitch, p, n.track, DropReason.SEMITONE_DROPPED))
                continue
            p = nearest
            adj.append(Adjustment.SEMITONE_SUBSTITUTED)
            key = profile.key_for_pitch(p)
            assert key is not None
        cands.append(_Cand(n, p, key.key_id, at_ms, _scale_ms(n.duration_us, speed), tuple(adj)))

    cands.sort(key=lambda c: (c.at_ms, c.mapped, c.note.track, c.note.channel, c.note.pitch))

    use_melody_priority = (
        options.prefer_melody_track
        and melody_track is not None
        and len(distinct_tracks) > 1
    )

    # 5. same key, same millisecond -> keep best
    groups: dict[tuple[int, str], list[_Cand]] = defaultdict(list)
    for c in cands:
        groups[(c.at_ms, c.key_id)].append(c)
    deduped: list[_Cand] = []
    for c in cands:
        g = groups[(c.at_ms, c.key_id)]
        best = min(
            g,
            key=lambda x: (
                len(x.adj) > 0,
                0 if (use_melody_priority and x.note.track == melody_track) else 1,
                -x.note.velocity,
                -x.dur_ms,
                x.note.track,
                x.note.channel,
                x.note.pitch,
            ),
        )
        if c is best:
            deduped.append(c)
        else:
            dropped.append(DroppedNote(c.at_ms, c.note.pitch, c.mapped, c.note.track,
                                       DropReason.DUPLICATE_KEY))

    # 6. chord limit per onset cluster (+ optional arpeggiation stagger)
    limited: list[_Cand] = []
    i = 0
    while i < len(deduped):
        start = deduped[i].at_ms
        j = i
        while j < len(deduped) and deduped[j].at_ms - start <= options.chord_window_ms:
            j += 1
        cluster = deduped[i:j]
        if len(cluster) <= max_chord:
            kept_cluster = list(cluster)
        else:
            if use_melody_priority:
                mel_cands = sorted(
                    (c for c in cluster if c.note.track == melody_track),
                    key=lambda c: (-c.mapped, c.at_ms),
                )
                other_cands = sorted(
                    (c for c in cluster if c.note.track != melody_track),
                    key=lambda c: (-c.mapped, c.at_ms),
                )
                priority = list(mel_cands)
                if other_cands:
                    priority.append(other_cands[-1])
                    if len(other_cands) > 1:
                        priority.append(other_cands[0])
                        priority.extend(other_cands[1:-1])
            else:
                by_pitch = sorted(cluster, key=lambda c: (-c.mapped, c.at_ms))
                priority = [by_pitch[0]]
                if len(by_pitch) > 1:
                    priority.append(by_pitch[-1])
                priority.extend(by_pitch[1:-1])
            keep = {id(c) for c in priority[:max_chord]}
            kept_cluster = []
            for c in cluster:
                if id(c) in keep:
                    kept_cluster.append(c)
                else:
                    dropped.append(DroppedNote(c.at_ms, c.note.pitch, c.mapped, c.note.track,
                                               DropReason.POLYPHONY_LIMIT))
        if options.arpeggiate_ms > 0 and len(kept_cluster) > 1:
            kept_cluster.sort(key=lambda c: (c.mapped, c.at_ms, c.key_id))
            base_at = min(c.at_ms for c in kept_cluster)
            for idx_arp, cand in enumerate(kept_cluster):
                cand.at_ms = base_at + idx_arp * options.arpeggiate_ms
        limited.extend(kept_cluster)
        i = j

    if options.arpeggiate_ms > 0:
        limited.sort(key=lambda c: (c.at_ms, c.mapped, c.note.track, c.note.channel, c.note.pitch))

    # 7. same-key retrigger guard
    last_at: dict[str, int] = {}
    kept: list[_Cand] = []
    for c in limited:  # already time-ordered
        prev = last_at.get(c.key_id)
        if prev is not None and c.at_ms - prev < timing.min_same_key_interval_ms:
            dropped.append(DroppedNote(c.at_ms, c.note.pitch, c.mapped, c.note.track,
                                       DropReason.REPEAT_TOO_FAST))
            continue
        last_at[c.key_id] = c.at_ms
        kept.append(c)

    # 8. hold computation (never overlapping the next press of the same key)
    next_at: dict[int, int] = {}
    following: dict[str, int] = {}
    for idx in range(len(kept) - 1, -1, -1):
        c = kept[idx]
        if c.key_id in following:
            next_at[idx] = following[c.key_id]
        following[c.key_id] = c.at_ms
    events: list[PerformanceEvent] = []
    for idx, c in enumerate(kept):
        hold = min(max(c.dur_ms, timing.min_key_hold_ms), timing.max_key_hold_ms)
        if idx in next_at:
            hold = min(hold, next_at[idx] - c.at_ms)
        events.append(PerformanceEvent(
            at_ms=c.at_ms, key_id=c.key_id, hold_ms=hold, source_pitch=c.note.pitch,
            mapped_pitch=c.mapped, source_track=c.note.track, source_channel=c.note.channel,
            velocity=c.note.velocity, adjustments=c.adj,
        ))
    events.sort(key=lambda e: (e.at_ms, e.mapped_pitch, e.key_id))

    if not events:
        raise LyraError(ErrorCode.NO_PLAYABLE_NOTES, "no notes could be mapped to the instrument",
                        {"considered_notes": len(notes)})

    dropped.sort(key=lambda d: (d.at_ms, d.source_pitch, d.source_track, d.reason))
    reasons = Counter(d.reason for d in dropped)
    considered = len(notes)
    chord_sizes = Counter(e.at_ms for e in events)
    stats: dict[str, Any] = {
        "input_notes": len(score.notes),
        "excluded_percussion": excluded_percussion,
        "excluded_tracks": excluded_tracks,
        "considered_notes": considered,
        "emitted_events": len(events),
        "direct": sum(1 for e in events if not e.adjustments),
        "octave_folded": sum(1 for e in events if Adjustment.OCTAVE_FOLDED in e.adjustments),
        "semitone_substituted": sum(
            1 for e in events if Adjustment.SEMITONE_SUBSTITUTED in e.adjustments),
        "dropped": {r.value: reasons.get(r.value, 0) for r in DropReason},
        "playable_ratio": round(len(events) / considered, 4),
        "unchanged_ratio": round(sum(1 for e in events if not e.adjustments) / considered, 4),
        "max_chord_size": max(chord_sizes.values()),
        "max_keys_per_second": _max_in_window([e.at_ms for e in events], 1000),
        "duration_ms": max(e.at_ms + e.hold_ms for e in events),
        "melody_track": melody_track,
    }
    return Arrangement(
        events=tuple(events), dropped=tuple(dropped), transpose=k,
        transpose_candidates=tuple(candidates), max_chord_keys=max_chord,
        options=options, stats=stats,
    )


def _max_in_window(times: list[int], window_ms: int) -> int:
    best = 0
    lo = 0
    for hi, t in enumerate(times):
        while t - times[lo] >= window_ms:
            lo += 1
        best = max(best, hi - lo + 1)
    return best
