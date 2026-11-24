"""Rule-based and music-theory 21-key arrangers: NormalizedScore + InstrumentProfile -> key events.

Supports extensible arrangement strategies via ``list_arranger_strategies()``:
* ``classic`` — Original deterministic baseline arranger (preserved verbatim).
* ``vocal_lead`` — Music-theory vocal-first arranger with weighted transposition,
  asymmetric-scale folding checks, accompaniment pitch ceiling, psychoacoustic
  anti-clash semitone handling, vocal ducking and interlude handoff.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction
from typing import Any

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.music_core.models import NormalizedScore, Note, TrackInfo
from lyraforge.music_core.profile import InstrumentProfile

ARRANGER_VERSION = "0.1.0"

MAX_SUBSTITUTION_SEMITONES = 2
_CONSONANT_INTERVALS = frozenset({0, 3, 4, 5, 7, 8, 9})


class Style(StrEnum):
    MELODY = "melody"
    BALANCED = "balanced"
    RICH = "rich"


STYLE_MAX_CHORD_KEYS: dict[Style, int] = {Style.MELODY: 1, Style.BALANCED: 3, Style.RICH: 6}


class SemitonePolicy(StrEnum):
    NEAREST = "nearest"
    DROP = "drop"


class TimingMode(StrEnum):
    ADAPTED = "adapted"
    STRICT_FIDELITY = "strict_fidelity"


class Adjustment(StrEnum):
    OCTAVE_FOLDED = "octave_folded"
    SEMITONE_SUBSTITUTED = "semitone_substituted"


class DropReason(StrEnum):
    OUT_OF_RANGE = "out_of_range"
    SEMITONE_DROPPED = "semitone_dropped"
    DUPLICATE_KEY = "duplicate_key"
    POLYPHONY_LIMIT = "polyphony_limit"
    REPEAT_TOO_FAST = "repeat_too_fast"


@dataclass(frozen=True, slots=True)
class ArrangerStrategyInfo:
    id: str
    display_name: str
    description: str
    recommended_for: str

    def to_json(self) -> dict[str, str]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "description": self.description,
            "recommended_for": self.recommended_for,
        }


_STRATEGIES: dict[str, ArrangerStrategyInfo] = {}


def register_arranger_strategy(info: ArrangerStrategyInfo) -> None:
    """Register or update an arrangement strategy metadata descriptor."""
    _STRATEGIES[info.id] = info


def list_arranger_strategies() -> list[ArrangerStrategyInfo]:
    """Return all registered arrangement strategies in registration order."""
    return list(_STRATEGIES.values())


def get_arranger_strategy(strategy_id: str) -> ArrangerStrategyInfo:
    info = _STRATEGIES.get(strategy_id)
    if info is None:
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            f"unknown arranger strategy: {strategy_id!r}",
            {"available": sorted(_STRATEGIES)},
        )
    return info


register_arranger_strategy(
    ArrangerStrategyInfo(
        id="classic",
        display_name="经典基线（原算法）",
        description="保留原始全局均衡移调与高音优先和弦裁剪逻辑，适合纯钢琴、独奏与现成精选 MIDI。",
        recommended_for="纯器乐 / 独奏 / 精选 MIDI",
    )
)
register_arranger_strategy(
    ArrangerStrategyInfo(
        id="vocal_lead",
        display_name="主旋律优先 · 音乐学增强",
        description=(
            "以人声/主旋律为最高权重移调并自动校准非对称音阶；"
            "伴奏限制低于主旋律且回避二度撞音，人声段伴奏让路、前奏/间奏自动放开。"
        ),
        recommended_for="人声流行歌 / 分轨转录 / 复杂混音",
    )
)


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
    arranger_strategy: str = "classic"
    melody_track: int | None = None
    vocal_ducking: bool = True
    melody_ceiling: bool = True
    anti_clash_semitones: bool = True
    timing_mode: str = TimingMode.ADAPTED

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
        if self.arranger_strategy not in _STRATEGIES:
            problems.append(f"unknown arranger_strategy: {self.arranger_strategy!r}")
        if self.melody_track is not None and self.melody_track < 0:
            problems.append("melody_track must be >= 0")
        if self.timing_mode not in {m.value for m in TimingMode}:
            problems.append(f"unknown timing_mode: {self.timing_mode!r}")
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
    above_melody: bool = False


def _fold_pitch_to_range(pitch: int, lo: int, hi: int) -> tuple[int, list[str]]:
    adj: list[str] = []
    if pitch < lo:
        pitch += 12 * math.ceil((lo - pitch) / 12)
        adj.append(Adjustment.OCTAVE_FOLDED)
    elif pitch > hi:
        pitch -= 12 * math.ceil((pitch - hi) / 12)
        adj.append(Adjustment.OCTAVE_FOLDED)
    return pitch, adj


def _transpose_cost(notes: list[Note], k: int, pitch_set: frozenset[int],
                    pcs: frozenset[int]) -> int:
    cost = 0
    for n in notes:
        p = n.pitch + k
        if p in pitch_set:
            continue
        cost += 1 if (p % 12) in pcs else 2
    return cost


def _weighted_transpose_cost(
    weighted_notes: Sequence[tuple[Note, int, bool]],
    k: int,
    pitch_set: frozenset[int],
    lo: int,
    hi: int,
) -> int:
    cost = 0
    for n, weight, is_mel in weighted_notes:
        p = n.pitch + k
        if p in pitch_set:
            continue
        folded, _ = _fold_pitch_to_range(p, lo, hi)
        if lo <= folded <= hi and folded in pitch_set:
            cost += weight
        else:
            cost += weight * (3 if is_mel else 2)
    return cost


def _check_cancel(is_cancelled: Callable[[], bool] | None) -> None:
    if is_cancelled is not None and is_cancelled():
        raise LyraError(ErrorCode.PLAYBACK_ABORTED, "arrangement cancelled")


def _search_transpose(
    notes: list[Note],
    profile: InstrumentProfile,
    search: int,
    *,
    is_cancelled: Callable[[], bool] | None = None,
) -> tuple[int, tuple[tuple[int, int], ...]]:
    pitch_set = frozenset(profile.pitches)
    pcs = frozenset(p % 12 for p in pitch_set)
    scored_list: list[tuple[int, int]] = []
    for k in range(-search, search + 1):
        _check_cancel(is_cancelled)
        scored_list.append((k, _transpose_cost(notes, k, pitch_set, pcs)))
    scored = sorted(scored_list, key=lambda kc: (kc[1], abs(kc[0]), kc[0]))
    return scored[0][0], tuple(scored[:5])


def _search_transpose_vocal_lead(
    notes: list[Note],
    profile: InstrumentProfile,
    search: int,
    *,
    melody_track: int | None,
    multi_track: bool,
    speed: Fraction,
    is_cancelled: Callable[[], bool] | None = None,
) -> tuple[int, tuple[tuple[int, int], ...]]:
    pitch_set = frozenset(profile.pitches)
    lo, hi = profile.min_pitch, profile.max_pitch
    weighted: list[tuple[Note, int, bool]] = []
    mel_seq: list[Note] = []
    acc_count = 0
    if multi_track and melody_track is not None:
        mel_seq = sorted(
            (n for n in notes if n.track == melody_track),
            key=lambda n: (n.start_us, n.pitch),
        )
        mel_count = len(mel_seq)
        acc_count = len(notes) - mel_count
        mel_weight = max(4, round(3 * acc_count / max(1, mel_count))) if acc_count > 0 else 4
        for n in notes:
            is_mel = n.track == melody_track
            weighted.append((n, mel_weight if is_mel else 1, is_mel))
    else:
        mel_weight = 3
        bucket_peak: dict[int, int] = {}
        for n in notes:
            bucket = _scale_ms(n.start_us, speed) // 120
            prev = bucket_peak.get(bucket)
            if prev is None or n.pitch > prev:
                bucket_peak[bucket] = n.pitch
        for n in notes:
            bucket = _scale_ms(n.start_us, speed) // 120
            is_peak = n.pitch == bucket_peak.get(bucket)
            weighted.append((n, 3 if is_peak else 1, is_peak))

    scored_list: list[tuple[int, int]] = []
    for k in range(-search, search + 1):
        _check_cancel(is_cancelled)
        cost = _weighted_transpose_cost(weighted, k, pitch_set, lo, hi)
        if len(mel_seq) >= 2:
            prev_f, _ = _fold_pitch_to_range(mel_seq[0].pitch + k, lo, hi)
            if acc_count > 0 and mel_seq[0].pitch + k < lo + 7:
                cost += 1
            for idx_m in range(1, len(mel_seq)):
                prev_raw = mel_seq[idx_m - 1]
                cur_raw = mel_seq[idx_m]
                cur_f, _ = _fold_pitch_to_range(cur_raw.pitch + k, lo, hi)
                if acc_count > 0 and cur_raw.pitch + k < lo + 7:
                    cost += 1
                if (
                    cur_raw.start_us - prev_raw.end_us <= 1_500_000
                    and abs(cur_raw.pitch - prev_raw.pitch) <= 7
                    and abs(cur_f - prev_f) >= 10
                ):
                    cost += mel_weight * 2
                prev_f = cur_f
        scored_list.append((k, cost))
    scored = sorted(scored_list, key=lambda kc: (kc[1], abs(kc[0]), kc[0]))
    return scored[0][0], tuple(scored[:5])


_EXPLICIT_VOCAL_HINTS = ("vocal", "voice", "singer", "lyric")
_EXPLICIT_MELODY_HINTS = ("melody", "lead", "solo", "main")
_MELODY_INSTRUMENT_HINTS = ("flute", "violin", "sax", "oboe", "trumpet")
_STRICT_ACCOMP_HINTS = ("accomp", "backing")
_OTHER_ACCOMP_HINTS = ("bass", "chord", "drum", "perc", "pad", "rhythm")


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
        is_strict_accomp = any(h in name for h in _STRICT_ACCOMP_HINTS)
        is_other_accomp = any(h in name for h in _OTHER_ACCOMP_HINTS)
        if any(h in name for h in _EXPLICIT_VOCAL_HINTS):
            name_bonus = 0.75
        elif any(h in name for h in _EXPLICIT_MELODY_HINTS) and not is_strict_accomp:
            name_bonus = 0.50
        elif (
            any(h in name for h in _MELODY_INSTRUMENT_HINTS)
            and not is_strict_accomp
            and not is_other_accomp
        ):
            name_bonus = 0.35
        else:
            name_bonus = 0.0
        if is_strict_accomp:
            name_bonus -= 0.35
        elif is_other_accomp:
            name_bonus -= 0.15
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


def _map_notes_classic(
    notes: list[Note],
    k: int,
    speed: Fraction,
    profile: InstrumentProfile,
    options: ArrangeOptions,
    dropped: list[DroppedNote],
    is_cancelled: Callable[[], bool] | None,
) -> list[_Cand]:
    lo, hi = profile.min_pitch, profile.max_pitch
    available = profile.pitches
    cands: list[_Cand] = []
    for n in notes:
        _check_cancel(is_cancelled)
        at_ms = _scale_ms(n.start_us, speed)
        p, adj = _fold_pitch_to_range(n.pitch + k, lo, hi)
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
    return cands


def _build_melody_windows(
    mel_cands: Sequence[_Cand],
) -> tuple[list[tuple[int, int, int]], list[int], list[int]]:
    windows = sorted(
        (
            (c.at_ms - 40, max(c.at_ms + c.dur_ms, c.at_ms + 220), c.mapped)
            for c in mel_cands
        ),
        key=lambda w: (w[0], w[1]),
    )
    pairs = sorted((c.at_ms, max(c.at_ms + c.dur_ms, c.at_ms + 120)) for c in mel_cands)
    onsets: list[int] = []
    end_prefix_max: list[int] = []
    running_end = 0
    for onset, end_ms in pairs:
        onsets.append(onset)
        running_end = max(running_end, end_ms)
        end_prefix_max.append(running_end)
    return windows, onsets, end_prefix_max


def _active_melody_pitches_at(
    windows: Sequence[tuple[int, int, int]],
    at_ms: int,
    cursor: int,
) -> tuple[list[int], int]:
    while cursor < len(windows) and windows[cursor][1] < at_ms:
        cursor += 1
    pitches: list[int] = []
    idx = cursor
    while idx < len(windows) and windows[idx][0] <= at_ms:
        if at_ms <= windows[idx][1]:
            pitches.append(windows[idx][2])
        idx += 1
    return pitches, cursor


def _map_notes_vocal_lead(
    notes: list[Note],
    k: int,
    speed: Fraction,
    profile: InstrumentProfile,
    options: ArrangeOptions,
    melody_track: int | None,
    use_melody_priority: bool,
    dropped: list[DroppedNote],
    is_cancelled: Callable[[], bool] | None,
) -> tuple[list[_Cand], list[tuple[int, int, int]], list[int], list[int]]:
    if not (use_melody_priority and melody_track is not None):
        return (
            _map_notes_classic(notes, k, speed, profile, options, dropped, is_cancelled),
            [],
            [],
            [],
        )

    lo, hi = profile.min_pitch, profile.max_pitch
    available = profile.pitches
    mel_notes = sorted(
        (n for n in notes if n.track == melody_track),
        key=lambda n: (n.start_us, -n.pitch),
    )
    acc_notes = sorted(
        (n for n in notes if n.track != melody_track),
        key=lambda n: (n.start_us, n.pitch),
    )

    mel_cands: list[_Cand] = []
    prev_mel_pitch: int | None = None
    for n in mel_notes:
        _check_cancel(is_cancelled)
        at_ms = _scale_ms(n.start_us, speed)
        p, adj = _fold_pitch_to_range(n.pitch + k, lo, hi)
        if not lo <= p <= hi:
            dropped.append(DroppedNote(at_ms, n.pitch, None, n.track, DropReason.OUT_OF_RANGE))
            continue
        key = profile.key_for_pitch(p)
        if key is None:
            sub_cands = [c for c in available if abs(c - p) <= MAX_SUBSTITUTION_SEMITONES]
            if options.semitone_policy == SemitonePolicy.DROP or not sub_cands:
                dropped.append(DroppedNote(at_ms, n.pitch, p, n.track, DropReason.SEMITONE_DROPPED))
                continue
            p = min(
                sub_cands,
                key=lambda c: (
                    abs(c - p),
                    abs(c - prev_mel_pitch) if prev_mel_pitch is not None else 0,
                    c,
                ),
            )
            adj.append(Adjustment.SEMITONE_SUBSTITUTED)
            key = profile.key_for_pitch(p)
            assert key is not None
        prev_mel_pitch = p
        mel_cands.append(
            _Cand(n, p, key.key_id, at_ms, _scale_ms(n.duration_us, speed), tuple(adj))
        )

    windows, mel_onsets, mel_end_prefix_max = _build_melody_windows(mel_cands)
    cursor = 0
    acc_cands: list[_Cand] = []

    for n in acc_notes:
        _check_cancel(is_cancelled)
        at_ms = _scale_ms(n.start_us, speed)
        active_pitches, cursor = _active_melody_pitches_at(windows, at_ms, cursor)
        active_max = max(active_pitches) if active_pitches else None

        p, adj = _fold_pitch_to_range(n.pitch + k, lo, hi)
        if not lo <= p <= hi:
            dropped.append(DroppedNote(at_ms, n.pitch, None, n.track, DropReason.OUT_OF_RANGE))
            continue

        if options.melody_ceiling and active_max is not None and p >= active_max:
            shifted = False
            while p >= active_max and p - 12 >= lo:
                p -= 12
                shifted = True
            if shifted and Adjustment.OCTAVE_FOLDED not in adj:
                adj.append(Adjustment.OCTAVE_FOLDED)

        above_mel = bool(options.melody_ceiling and active_max is not None and p >= active_max)
        key = profile.key_for_pitch(p)
        if key is None:
            sub_cands = [c for c in available if abs(c - p) <= MAX_SUBSTITUTION_SEMITONES]
            if options.semitone_policy == SemitonePolicy.DROP or not sub_cands:
                dropped.append(DroppedNote(at_ms, n.pitch, p, n.track, DropReason.SEMITONE_DROPPED))
                continue
            if options.anti_clash_semitones and active_pitches:
                non_clashing = [
                    c for c in sub_cands
                    if not any(abs(c - mp) in (1, 2) for mp in active_pitches)
                ]
                sub_cands = non_clashing
            if options.melody_ceiling and active_max is not None and sub_cands:
                below = [c for c in sub_cands if c < active_max]
                if below:
                    sub_cands = below
                elif options.anti_clash_semitones and active_max > lo + 5:
                    sub_cands = []
            if not sub_cands:
                dropped.append(DroppedNote(at_ms, n.pitch, p, n.track, DropReason.SEMITONE_DROPPED))
                continue
            p = min(sub_cands, key=lambda c: (abs(c - p), c))
            adj.append(Adjustment.SEMITONE_SUBSTITUTED)
            key = profile.key_for_pitch(p)
            assert key is not None
            above_mel = bool(
                options.melody_ceiling and active_max is not None and p >= active_max
            )

        acc_cands.append(
            _Cand(
                n,
                p,
                key.key_id,
                at_ms,
                _scale_ms(n.duration_us, speed),
                tuple(adj),
                above_melody=above_mel,
            )
        )

    return [*mel_cands, *acc_cands], windows, mel_onsets, mel_end_prefix_max


def _pick_balanced_voices(
    cluster: Sequence[_Cand],
    limit: int,
    *,
    consonant_ref: int | None = None,
) -> list[_Cand]:
    if len(cluster) <= limit:
        return list(cluster)
    if limit <= 0:
        return []
    bass = min(cluster, key=lambda c: (c.mapped, c.at_ms))
    picked = [bass]
    remaining = [c for c in cluster if c is not bass]
    if consonant_ref is not None:
        remaining.sort(
            key=lambda c: (
                0 if ((consonant_ref - c.mapped) % 12) in _CONSONANT_INTERVALS else 1,
                -c.mapped,
                -c.note.velocity,
                c.at_ms,
            )
        )
    else:
        remaining.sort(key=lambda c: (-c.mapped, -c.note.velocity, c.at_ms))
    for cand in remaining:
        if len(picked) >= limit:
            break
        picked.append(cand)
    return picked


_CHORD_SIMULTANEOUS_TOLERANCE_MS = 4


def _cluster_end(
    deduped: list[_Cand],
    start_idx: int,
    chord_window_ms: int,
    *,
    strict_fidelity: bool,
) -> int:
    start = deduped[start_idx].at_ms
    if strict_fidelity or chord_window_ms <= 0:
        j = start_idx + 1
        while j < len(deduped) and deduped[j].at_ms == start:
            j += 1
        return j
    track_first_at: dict[int, int] = {deduped[start_idx].note.track: start}
    j = start_idx + 1
    while j < len(deduped):
        cand = deduped[j]
        if cand.at_ms - start > chord_window_ms:
            break
        prev_first = track_first_at.get(cand.note.track)
        if (
            prev_first is not None
            and cand.at_ms - prev_first > _CHORD_SIMULTANEOUS_TOLERANCE_MS
        ):
            break
        track_first_at.setdefault(cand.note.track, cand.at_ms)
        j += 1
    return j


def _apply_arpeggiate(kept_cluster: list[_Cand], arpeggiate_ms: int) -> int:
    """Stagger simultaneous sub-chords without reordering rapid sequential arpeggios."""
    if arpeggiate_ms <= 0 or len(kept_cluster) <= 1:
        return 0
    ordered = sorted(kept_cluster, key=lambda c: (c.at_ms, c.mapped, c.key_id))
    staggered = 0
    idx_s = 0
    while idx_s < len(ordered):
        sub_base = ordered[idx_s].at_ms
        sub_end = idx_s + 1
        while (
            sub_end < len(ordered)
            and ordered[sub_end].at_ms - sub_base <= _CHORD_SIMULTANEOUS_TOLERANCE_MS
        ):
            sub_end += 1
        if sub_end - idx_s > 1:
            sub = sorted(
                ordered[idx_s:sub_end], key=lambda c: (c.mapped, c.at_ms, c.key_id)
            )
            for off_idx, cand in enumerate(sub):
                next_ms = sub_base + off_idx * arpeggiate_ms
                if next_ms != cand.at_ms:
                    cand.at_ms = next_ms
                    staggered += 1
        idx_s = sub_end
    return staggered


def _select_vocal_lead_clusters(
    deduped: list[_Cand],
    *,
    max_chord: int,
    profile: InstrumentProfile,
    options: ArrangeOptions,
    melody_track: int | None,
    use_melody_priority: bool,
    mel_windows: Sequence[tuple[int, int, int]],
    mel_onsets: Sequence[int],
    mel_end_prefix_max: Sequence[int],
    dropped: list[DroppedNote],
    is_cancelled: Callable[[], bool] | None,
) -> tuple[list[_Cand], int]:
    limited: list[_Cand] = []
    arpeggiated_events = 0
    cursor = 0
    prev_mel_pitch: int | None = None
    lo = profile.min_pitch
    strict = options.timing_mode == TimingMode.STRICT_FIDELITY

    i = 0
    while i < len(deduped):
        _check_cancel(is_cancelled)
        start = deduped[i].at_ms
        j = _cluster_end(deduped, i, options.chord_window_ms, strict_fidelity=strict)
        cluster = deduped[i:j]

        clash_ids: set[int] = set()
        if use_melody_priority and melody_track is not None:
            mel_in = sorted(
                (c for c in cluster if c.note.track == melody_track),
                key=lambda c: (-c.mapped, c.at_ms),
            )
            acc_in = [c for c in cluster if c.note.track != melody_track]
            active_win_pitches, cursor = _active_melody_pitches_at(mel_windows, start, cursor)
            active_refs = [c.mapped for c in mel_in] or active_win_pitches

            pos = bisect_left(mel_onsets, start)
            if pos > 0 and pos - 1 < len(mel_end_prefix_max):
                since_prev = start - mel_end_prefix_max[pos - 1]
            elif pos > 0:
                since_prev = start - mel_onsets[pos - 1]
            else:
                since_prev = math.inf
            until_next = mel_onsets[pos] - start if pos < len(mel_onsets) else math.inf
            is_interlude = (
                not mel_in
                and not active_win_pitches
                and (not mel_onsets or (since_prev >= 350 and until_next >= 250))
            )

            if is_interlude:
                cap = (
                    min(2, profile.polyphony_limit or 2)
                    if options.style == Style.MELODY
                    else max_chord
                )
                by_pitch = sorted(cluster, key=lambda c: (-c.mapped, c.at_ms))
                priority = [by_pitch[0]]
                if len(by_pitch) > 1:
                    priority.append(by_pitch[-1])
                priority.extend(by_pitch[1:-1])
                kept_cluster = priority[:cap]
            else:
                kept_mel = mel_in[:max_chord]
                clean_acc: list[_Cand] = []
                ceiling_blocked: list[_Cand] = []
                ref_max = max(active_refs) if active_refs else None
                for c in acc_in:
                    if options.anti_clash_semitones:
                        has_m2 = any(abs(c.mapped - mp) == 1 for mp in active_refs)
                        has_sub_m2_or_m2plus = (
                            Adjustment.SEMITONE_SUBSTITUTED in c.adj
                            and any(abs(c.mapped - mp) == 2 for mp in active_refs)
                        )
                        has_cluster_m2 = any(
                            abs(c.mapped - mp) == 2 for mp in active_refs
                        ) and any(abs(c.mapped - other.mapped) == 1 for other in clean_acc)
                        if has_m2 or has_sub_m2_or_m2plus or has_cluster_m2:
                            clash_ids.add(id(c))
                            continue
                    if options.melody_ceiling and (
                        c.above_melody or (ref_max is not None and c.mapped >= ref_max)
                    ):
                        ceiling_blocked.append(c)
                        continue
                    clean_acc.append(c)

                rem = max_chord - len(kept_mel)
                if options.vocal_ducking:
                    if options.style == Style.MELODY:
                        acc_budget = 0
                    elif options.style == Style.BALANCED:
                        acc_budget = min(rem, 2)
                    else:
                        acc_budget = rem
                else:
                    acc_budget = rem

                # When vocal drops into bottom fifth (<= lo + 5), keep up to 1 consonant
                # fifth/octave note above vocal if all accompaniment below was filtered.
                if (
                    acc_budget > 0
                    and not clean_acc
                    and ceiling_blocked
                    and ref_max is not None
                    and ref_max <= lo + 5
                ):
                    gentle = [
                        c for c in ceiling_blocked
                        if (c.mapped - ref_max) in (7, 12, 19)
                        and Adjustment.SEMITONE_SUBSTITUTED not in c.adj
                    ]
                    if gentle:
                        clean_acc.append(min(gentle, key=lambda c: c.mapped))

                primary_ref = active_refs[0] if active_refs else None
                kept_acc = _pick_balanced_voices(
                    clean_acc, acc_budget, consonant_ref=primary_ref
                )
                kept_cluster = [*kept_mel, *kept_acc]
        else:
            # Single-track vocal_lead: track melodic contour continuity + clean accompaniment below
            if len(cluster) == 1:
                kept_cluster = list(cluster)
                if prev_mel_pitch is None or cluster[0].mapped >= lo + 7:
                    prev_mel_pitch = cluster[0].mapped
            else:
                def _lead_score(
                    cand: _Cand, prev: int | None = prev_mel_pitch
                ) -> tuple[float, int]:
                    pitch_term = (cand.mapped / 127.0) * 0.55
                    vel_term = (cand.note.velocity / 127.0) * 0.10
                    cont = 0.0
                    if prev is not None:
                        dist = abs(cand.mapped - prev)
                        cont = 0.35 if dist <= 7 else max(0.0, 0.25 - dist * 0.02)
                    return (round(pitch_term + vel_term + cont, 6), cand.mapped)

                lead = max(cluster, key=_lead_score)
                prev_mel_pitch = lead.mapped
                if max_chord <= 1:
                    kept_cluster = [lead]
                else:
                    others: list[_Cand] = []
                    for c in cluster:
                        if c is lead:
                            continue
                        if options.anti_clash_semitones and (
                            abs(c.mapped - lead.mapped) == 1
                            or (
                                Adjustment.SEMITONE_SUBSTITUTED in c.adj
                                and abs(c.mapped - lead.mapped) == 2
                            )
                        ):
                            clash_ids.add(id(c))
                            continue
                        if options.melody_ceiling and c.mapped > lead.mapped:
                            continue
                        others.append(c)
                    kept_acc = _pick_balanced_voices(
                        others, max_chord - 1, consonant_ref=lead.mapped
                    )
                    kept_cluster = [lead, *kept_acc]

        keep_ids = {id(c) for c in kept_cluster}
        for c in cluster:
            if id(c) in keep_ids:
                limited.append(c)
            else:
                reason = (
                    DropReason.SEMITONE_DROPPED
                    if id(c) in clash_ids
                    else DropReason.POLYPHONY_LIMIT
                )
                dropped.append(
                    DroppedNote(c.at_ms, c.note.pitch, c.mapped, c.note.track, reason)
                )
        arpeggiated_events += _apply_arpeggiate(kept_cluster, options.arpeggiate_ms)
        i = j

    return limited, arpeggiated_events


def arrange(
    score: NormalizedScore,
    profile: InstrumentProfile,
    options: ArrangeOptions | None = None,
    *,
    is_cancelled: Callable[[], bool] | None = None,
) -> Arrangement:
    _check_cancel(is_cancelled)
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
    if options.melody_track is not None and options.melody_track in distinct_tracks:
        melody_track: int | None = options.melody_track
    else:
        melody_track = _detect_melody_track_from_notes(notes, score.tracks)

    use_melody_priority = (
        options.prefer_melody_track
        and melody_track is not None
        and len(distinct_tracks) > 1
    )
    vocal_lead_mode = options.arranger_strategy == "vocal_lead"

    # 2. transposition
    if options.transpose is None:
        if vocal_lead_mode:
            k, candidates = _search_transpose_vocal_lead(
                notes,
                profile,
                options.transpose_search,
                melody_track=melody_track,
                multi_track=use_melody_priority,
                speed=speed,
                is_cancelled=is_cancelled,
            )
        else:
            k, candidates = _search_transpose(
                notes, profile, options.transpose_search, is_cancelled=is_cancelled
            )
    else:
        _check_cancel(is_cancelled)
        k = options.transpose
        pitch_set = frozenset(profile.pitches)
        pcs = frozenset(p % 12 for p in pitch_set)
        candidates = ((k, _transpose_cost(notes, k, pitch_set, pcs)),)

    # 3-4. range folding + semitone handling
    if vocal_lead_mode:
        cands, mel_windows, mel_onsets, mel_end_prefix_max = _map_notes_vocal_lead(
            notes,
            k,
            speed,
            profile,
            options,
            melody_track,
            use_melody_priority,
            dropped,
            is_cancelled,
        )
    else:
        cands = _map_notes_classic(notes, k, speed, profile, options, dropped, is_cancelled)
        mel_windows, mel_onsets, mel_end_prefix_max = [], [], []

    cands.sort(key=lambda c: (c.at_ms, c.mapped, c.note.track, c.note.channel, c.note.pitch))

    # 5. same key, same millisecond -> keep best
    groups: dict[tuple[int, str], list[_Cand]] = defaultdict(list)
    for c in cands:
        groups[(c.at_ms, c.key_id)].append(c)
    deduped: list[_Cand] = []
    for c in cands:
        _check_cancel(is_cancelled)
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

    # 6. chord limit per onset cluster (+ optional simultaneous-chord arpeggiation)
    arpeggiated_events = 0
    strict = options.timing_mode == TimingMode.STRICT_FIDELITY
    if vocal_lead_mode:
        limited, arpeggiated_events = _select_vocal_lead_clusters(
            deduped,
            max_chord=max_chord,
            profile=profile,
            options=options,
            melody_track=melody_track,
            use_melody_priority=use_melody_priority,
            mel_windows=mel_windows,
            mel_onsets=mel_onsets,
            mel_end_prefix_max=mel_end_prefix_max,
            dropped=dropped,
            is_cancelled=is_cancelled,
        )
    else:
        limited = []
        i = 0
        while i < len(deduped):
            _check_cancel(is_cancelled)
            j = _cluster_end(deduped, i, options.chord_window_ms, strict_fidelity=strict)
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
            arpeggiated_events += _apply_arpeggiate(kept_cluster, options.arpeggiate_ms)
            limited.extend(kept_cluster)
            i = j

    if options.arpeggiate_ms > 0 or vocal_lead_mode:
        limited.sort(key=lambda c: (c.at_ms, c.mapped, c.note.track, c.note.channel, c.note.pitch))

    # 6b. optional calibrated minimum inter-key interval enforcement (adapted mode only)
    inter_key_adjusted = 0
    if not strict and timing.min_inter_key_interval_ms > 0 and limited:
        prev_orig_at = limited[0].at_ms
        prev_out_at = limited[0].at_ms
        for cand in limited[1:]:
            orig_at = cand.at_ms
            if orig_at == prev_orig_at:
                cand.at_ms = prev_out_at
                if cand.at_ms != orig_at:
                    inter_key_adjusted += 1
            else:
                min_allowed = prev_out_at + timing.min_inter_key_interval_ms
                if orig_at < min_allowed:
                    cand.at_ms = min_allowed
                    inter_key_adjusted += 1
                prev_orig_at = orig_at
                prev_out_at = cand.at_ms
        if inter_key_adjusted:
            limited.sort(
                key=lambda c: (c.at_ms, c.mapped, c.note.track, c.note.channel, c.note.pitch)
            )

    # 7. deterministic same-key retrigger guard (prefer melody track over accompaniment)
    if strict:
        min_same_interval = min(
            timing.min_same_key_interval_ms,
            max(1, timing.min_key_hold_ms + timing.min_key_release_gap_ms),
        )
    else:
        min_same_interval = timing.min_same_key_interval_ms
    key_history: dict[str, list[int]] = defaultdict(list)
    kept_slots: list[_Cand | None] = []
    melody_retrigger_replacements = 0
    for c in limited:  # already time-ordered
        _check_cancel(is_cancelled)
        hist = key_history[c.key_id]
        if hist:
            prev_slot = hist[-1]
            prev_cand = kept_slots[prev_slot]
            assert prev_cand is not None
            if c.at_ms - prev_cand.at_ms < min_same_interval:
                prev_before_ok = (
                    len(hist) < 2
                    or (c.at_ms - kept_slots[hist[-2]].at_ms) >= min_same_interval  # type: ignore[union-attr]
                )
                c_is_mel = (
                    use_melody_priority
                    and melody_track is not None
                    and c.note.track == melody_track
                )
                prev_is_mel = (
                    use_melody_priority
                    and melody_track is not None
                    and prev_cand.note.track == melody_track
                )
                if c_is_mel and not prev_is_mel and prev_before_ok:
                    dropped.append(
                        DroppedNote(
                            prev_cand.at_ms,
                            prev_cand.note.pitch,
                            prev_cand.mapped,
                            prev_cand.note.track,
                            DropReason.REPEAT_TOO_FAST,
                        )
                    )
                    kept_slots[prev_slot] = None
                    hist.pop()
                    slot = len(kept_slots)
                    kept_slots.append(c)
                    hist.append(slot)
                    melody_retrigger_replacements += 1
                    continue
                dropped.append(
                    DroppedNote(
                        c.at_ms,
                        c.note.pitch,
                        c.mapped,
                        c.note.track,
                        DropReason.REPEAT_TOO_FAST,
                    )
                )
                continue
        slot = len(kept_slots)
        kept_slots.append(c)
        hist.append(slot)
    kept = [c for c in kept_slots if c is not None]

    # 8. hold & release-gap computation (respecting trigger_mode & min_key_release_gap_ms)
    next_at: dict[int, int] = {}
    following: dict[str, int] = {}
    for idx in range(len(kept) - 1, -1, -1):
        c = kept[idx]
        if c.key_id in following:
            next_at[idx] = following[c.key_id]
        following[c.key_id] = c.at_ms
    events: list[PerformanceEvent] = []
    hold_shortened_for_retrigger = 0
    one_shot_tap = timing.trigger_mode == "one_shot" and not profile.supports_sustain
    release_gap = timing.min_key_release_gap_ms
    for idx, c in enumerate(kept):
        _check_cancel(is_cancelled)
        if one_shot_tap:
            hold = min(max(c.dur_ms, timing.min_key_hold_ms), timing.default_key_hold_ms)
        else:
            hold = min(max(c.dur_ms, timing.min_key_hold_ms), timing.max_key_hold_ms)
        if idx in next_at:
            gap = next_at[idx] - c.at_ms
            max_hold = gap - release_gap if gap > release_gap else max(1, gap // 2)
            if max_hold < hold:
                hold = max_hold
                hold_shortened_for_retrigger += 1
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
        "arranger_strategy": options.arranger_strategy,
        "timing_mode": str(options.timing_mode),
        "timing_adjustments": {
            "arpeggiated_events": arpeggiated_events,
            "melody_retrigger_replacements": melody_retrigger_replacements,
            "hold_shortened_for_retrigger": hold_shortened_for_retrigger,
            "inter_key_adjusted": inter_key_adjusted,
            "min_same_key_interval_ms": min_same_interval,
            "min_key_release_gap_ms": release_gap,
            "min_inter_key_interval_ms": timing.min_inter_key_interval_ms,
            "trigger_mode": timing.trigger_mode,
            "timing_provisional": timing.provisional,
        },
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
