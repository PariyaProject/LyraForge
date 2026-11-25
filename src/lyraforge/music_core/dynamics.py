"""Musical dynamics hierarchy, cross-stem onset alignment, and phrase-level Viterbi octave DP.

Pure cross-platform stdlib module integrated with ``music_core.arranger`` to solve two
real-world problems on narrow-range, fixed-velocity game instruments (Genshin lyres):

1. Accompaniment clutter / lost dynamic hierarchy during vocal climaxes after stem merging.
2. Wide-range vocal melodies sitting too high in the chorus and too muddy/low in verses.
"""

from __future__ import annotations

import math
import statistics
from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from lyraforge.music_core.models import Note
from lyraforge.music_core.profile import InstrumentProfile


class AccompDensity(StrEnum):
    AUTO = "auto"
    MINIMAL = "minimal"
    BALANCED = "balanced"
    FULL = "full"


class PhraseOctaveMode(StrEnum):
    ORIGINAL = "original"
    SMOOTH_LIFT = "smooth_lift"
    CENTERED = "centered"


def _norm_bounds(values: Sequence[float]) -> tuple[float, float]:
    active = sorted(v for v in values if v > -55.0)
    if not active:
        return (-60.0, 0.0)
    if len(active) == 1:
        return (active[0] - 6.0, active[0] + 6.0)
    p10 = active[max(0, int((len(active) - 1) * 0.10))]
    p90 = active[min(len(active) - 1, int((len(active) - 1) * 0.90))]
    if p90 - p10 < 3.0:
        mid = 0.5 * (p10 + p90)
        return (mid - 3.0, mid + 3.0)
    return (p10, p90)


def _norm_at(values: Sequence[float], idx: int, bounds: tuple[float, float]) -> float | None:
    if not values:
        return None
    clamped_idx = max(0, min(len(values) - 1, idx))
    val = values[clamped_idx]
    if val <= -58.0:
        return 0.0
    lo_db, hi_db = bounds
    return max(0.0, min(1.0, (val - lo_db) / max(1e-6, hi_db - lo_db)))


@dataclass(frozen=True, slots=True)
class StemDynamics:
    """Per-frame stem loudness envelopes extracted from separated vocal/accomp WAVs."""

    hop_ms: int
    vocal_db: tuple[float, ...]
    accomp_db: tuple[float, ...]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> StemDynamics | None:
        if not isinstance(data, Mapping):
            return None
        raw_hop = data.get("hop_ms", 500)
        try:
            hop = max(50, min(5000, int(raw_hop)))
        except (TypeError, ValueError):
            hop = 500
        vocal_raw = data.get("vocal_db") or ()
        accomp_raw = data.get("accomp_db") or ()
        try:
            vocal = tuple(float(x) for x in vocal_raw)
            accomp = tuple(float(x) for x in accomp_raw)
        except (TypeError, ValueError):
            return None
        if not vocal and not accomp:
            return None
        return cls(hop_ms=hop, vocal_db=vocal, accomp_db=accomp)

    def section_energy_at(self, at_ms: int) -> tuple[float | None, float | None]:
        """Return normalized ``(vocal_energy, accomp_energy)`` in ``[0.0, 1.0]`` at ``at_ms``."""
        idx = max(0, at_ms // self.hop_ms)
        v_e = _norm_at(self.vocal_db, idx, _norm_bounds(self.vocal_db)) if self.vocal_db else None
        a_e = (
            _norm_at(self.accomp_db, idx, _norm_bounds(self.accomp_db))
            if self.accomp_db
            else None
        )
        return v_e, a_e


def _fold_pitch_local(pitch: int, lo: int, hi: int) -> int:
    if pitch < lo:
        pitch += 12 * math.ceil((lo - pitch) / 12)
    elif pitch > hi:
        pitch -= 12 * math.ceil((pitch - hi) / 12)
    return pitch


def segment_melody_phrases(
    mel_notes: Sequence[Note],
    *,
    phrase_gap_ms: int = 450,
    max_phrase_notes: int = 18,
    sub_gap_ms: int = 220,
) -> list[list[Note]]:
    """Split a melody note sequence into coherent phrases at rests and breath boundaries."""
    ordered = sorted(mel_notes, key=lambda n: (n.start_us, -n.pitch))
    if not ordered:
        return []
    phrases: list[list[Note]] = [[ordered[0]]]
    gap_us = phrase_gap_ms * 1000
    sub_us = sub_gap_ms * 1000
    for cur in ordered[1:]:
        prev = phrases[-1][-1]
        rest_us = cur.start_us - prev.end_us
        if rest_us >= gap_us or (len(phrases[-1]) >= max_phrase_notes and rest_us >= sub_us):
            phrases.append([cur])
        else:
            phrases[-1].append(cur)
    return phrases


def optimize_phrase_octaves(
    mel_notes: Sequence[Note],
    transpose_k: int,
    profile: InstrumentProfile,
    mode: str | PhraseOctaveMode,
    *,
    has_accompaniment: bool = True,
    phrase_gap_ms: int = 450,
) -> tuple[dict[int, int], dict[str, int]]:
    """Use Viterbi DP over phrase octave shifts (-12, 0, +12) for smooth register comfort."""
    norm_mode = PhraseOctaveMode(str(mode))
    if norm_mode == PhraseOctaveMode.ORIGINAL or not mel_notes:
        return {}, {
            "phrase_count": 0,
            "phrases_shifted_up": 0,
            "phrases_shifted_down": 0,
            "phrase_shifted_notes": 0,
        }

    phrases = segment_melody_phrases(mel_notes, phrase_gap_ms=phrase_gap_ms)
    if not phrases:
        return {}, {
            "phrase_count": 0,
            "phrases_shifted_up": 0,
            "phrases_shifted_down": 0,
            "phrase_shifted_notes": 0,
        }

    lo, hi = profile.min_pitch, profile.max_pitch
    sweet_lo = lo + 12  # e.g. C4 on C3..B5 21-key lyres (mid/high clear singing row)
    sweet_hi = hi - 2   # e.g. A5
    sweet_mid = 0.5 * (sweet_lo + sweet_hi)
    shifts = (-12, 0, 12)

    def _emission_cost(phrase: Sequence[Note], offset: int) -> float:
        raw_shifted = [n.pitch + transpose_k + offset for n in phrase]
        oob = sum(1 for p in raw_shifted if p < lo or p > hi)
        folded = [_fold_pitch_local(p, lo, hi) for p in raw_shifted]

        cliff_pen = 0.0
        for idx in range(1, len(phrase)):
            if (
                phrase[idx].start_us - phrase[idx - 1].end_us <= 1_500_000
                and abs(phrase[idx].pitch - phrase[idx - 1].pitch) <= 7
                and abs(folded[idx] - folded[idx - 1]) >= 10
            ):
                cliff_pen += 40.0

        med_p = statistics.median(folded)
        cost = oob * 25.0 + cliff_pen
        if norm_mode == PhraseOctaveMode.SMOOTH_LIFT:
            if med_p < sweet_lo:
                weight = 1.8 if has_accompaniment else 1.0
                cost += len(phrase) * (sweet_lo - med_p) * weight
            if offset == 0 and oob == 0 and cliff_pen == 0.0 and sweet_lo <= med_p <= hi:
                cost -= 0.8
        else:  # PhraseOctaveMode.CENTERED
            cost += len(phrase) * abs(med_p - sweet_mid) * 0.45
            if med_p < sweet_lo:
                cost += len(phrase) * (sweet_lo - med_p) * 0.9
            if offset == 0 and oob == 0 and cliff_pen == 0.0:
                cost -= 0.2
        return cost

    def _transition_cost(
        prev_phrase: Sequence[Note],
        cur_phrase: Sequence[Note],
        o_prev: int,
        o_cur: int,
    ) -> float:
        if o_prev == o_cur:
            return 0.0
        gap_ms = max(0.0, (cur_phrase[0].start_us - prev_phrase[-1].end_us) / 1000.0)
        if gap_ms < 350.0:
            base = 90.0
        elif gap_ms < 900.0:
            base = 18.0
        else:
            base = 5.0
        prev_end = _fold_pitch_local(prev_phrase[-1].pitch + transpose_k + o_prev, lo, hi)
        cur_start = _fold_pitch_local(cur_phrase[0].pitch + transpose_k + o_cur, lo, hi)
        leap_pen = max(0, abs(cur_start - prev_end) - 12) * 1.5 if gap_ms < 900.0 else 0.0
        return base + leap_pen

    dp: list[dict[int, float]] = [{o: _emission_cost(phrases[0], o) for o in shifts}]
    back: list[dict[int, int]] = []

    for i in range(1, len(phrases)):
        cur_dp: dict[int, float] = {}
        cur_back: dict[int, int] = {}
        prev_dp = dp[-1]
        for o_cur in shifts:
            emit = _emission_cost(phrases[i], o_cur)
            best_prev = 0
            best_val = math.inf
            for o_prev in shifts:
                t_cost = _transition_cost(phrases[i - 1], phrases[i], o_prev, o_cur)
                cand_val = prev_dp[o_prev] + t_cost + emit
                if cand_val < best_val:
                    best_val = cand_val
                    best_prev = o_prev
            cur_dp[o_cur] = best_val
            cur_back[o_cur] = best_prev
        dp.append(cur_dp)
        back.append(cur_back)

    best_last = min(shifts, key=lambda o: (dp[-1][o], abs(o)))
    chosen = [best_last]
    for b_idx in range(len(back) - 1, -1, -1):
        chosen.append(back[b_idx][chosen[-1]])
    chosen.reverse()

    shift_by_id: dict[int, int] = {}
    up_count = 0
    down_count = 0
    shifted_notes = 0
    for phrase, shift_val in zip(phrases, chosen, strict=True):
        if shift_val > 0:
            up_count += 1
            shifted_notes += len(phrase)
        elif shift_val < 0:
            down_count += 1
            shifted_notes += len(phrase)
        for note in phrase:
            shift_by_id[id(note)] = shift_val

    return shift_by_id, {
        "phrase_count": len(phrases),
        "phrases_shifted_up": up_count,
        "phrases_shifted_down": down_count,
        "phrase_shifted_notes": shifted_notes,
    }


def align_accompaniment_onsets(
    mel_onsets_ms: Sequence[int],
    acc_cands: Sequence[Any],
    max_align_ms: int,
) -> int:
    """Snap solo accompaniment micro-jitter within ``max_align_ms`` to nearby melody onsets.

    Preserves genuine fast accompaniment arpeggios (onsets within 5..45 ms of a neighbor
    accompaniment event) so swept chords are never collapsed.
    """
    if max_align_ms <= 4 or not mel_onsets_ms or not acc_cands:
        return 0
    ordered_mel = sorted(mel_onsets_ms)
    acc_times = sorted({int(c.at_ms) for c in acc_cands})
    arpeggio_times: set[int] = set()
    for i in range(1, len(acc_times)):
        diff = acc_times[i] - acc_times[i - 1]
        if 5 <= diff <= 45:
            arpeggio_times.add(acc_times[i - 1])
            arpeggio_times.add(acc_times[i])

    aligned = 0
    for cand in acc_cands:
        t = int(cand.at_ms)
        if t in arpeggio_times:
            continue
        pos = bisect_left(ordered_mel, t)
        nearest: int | None = None
        best_dist = max_align_ms + 1
        for probe in (pos - 1, pos):
            if 0 <= probe < len(ordered_mel):
                d = abs(ordered_mel[probe] - t)
                if d < best_dist:
                    best_dist = d
                    nearest = ordered_mel[probe]
        if nearest is not None and 4 < best_dist <= max_align_ms:
            cand.at_ms = nearest
            aligned += 1
    return aligned


@dataclass(slots=True)
class VocalSectionProfile:
    """Moment-by-moment accompaniment rhythm gate & dynamic balance policy."""

    lo_pitch: int
    mel_onsets: tuple[int, ...]
    mel_pitches: tuple[int, ...]
    stem_dynamics: StemDynamics | None

    def vocal_energy_at(self, at_ms: int, active_mel_pitches: Sequence[int]) -> float:
        if self.stem_dynamics is not None:
            v_e, _ = self.stem_dynamics.section_energy_at(at_ms)
            if v_e is not None:
                return v_e
        # Fallback when arranged from pure MIDI without audio stems: 2s local density + register
        lo_idx = bisect_left(self.mel_onsets, at_ms - 1000)
        hi_idx = bisect_left(self.mel_onsets, at_ms + 1000)
        notes_per_sec = (hi_idx - lo_idx) / 2.0
        density_score = min(1.0, notes_per_sec / 4.5)
        if active_mel_pitches:
            pitch_norm = max(0.0, min(1.0, (max(active_mel_pitches) - (self.lo_pitch + 8)) / 22.0))
        else:
            pitch_norm = 0.35
        return max(0.0, min(1.0, 0.55 * pitch_norm + 0.45 * density_score))

    def classify_moment(
        self,
        at_ms: int,
        *,
        has_vocal_onset_now: bool,
        active_mel_pitches: Sequence[int],
        density_mode: AccompDensity,
    ) -> tuple[str, int, int]:
        """Return ``(section_label, min_accomp_interval_ms, max_accomp_voices)``."""
        if density_mode == AccompDensity.FULL:
            return ("full", 0, 99)
        if density_mode == AccompDensity.MINIMAL:
            return ("minimal", 420, 1)
        if density_mode == AccompDensity.BALANCED:
            if has_vocal_onset_now:
                return ("balanced_sync", 220, 2)
            return ("balanced_sustain", 300, 1)

        # AccompDensity.AUTO
        energy = self.vocal_energy_at(at_ms, active_mel_pitches)
        high_climax = energy >= 0.72 or (
            bool(active_mel_pitches) and max(active_mel_pitches) >= self.lo_pitch + 21
        )
        if energy < 0.45 and not high_climax:
            # Quiet verse: minimal low anchor so vocal stands crystal-clear
            return ("verse_sparse", 340, 1)
        if high_climax:
            if has_vocal_onset_now:
                # Vocal climax synced beat: solid low root+5th support without clutter
                return ("climax_sync", 180, 2)
            # Held vocal sustain during climax: strict gate against off-beat guitar/synth fills
            return ("climax_sustain", 320, 1)
        if has_vocal_onset_now:
            return ("normal_sync", 220, 2)
        return ("normal_sustain", 280, 1)


def compute_vocal_section_profile(
    mel_cands: Sequence[Any],
    lo_pitch: int,
    stem_dynamics: StemDynamics | None = None,
) -> VocalSectionProfile:
    ordered = sorted(mel_cands, key=lambda c: c.at_ms)
    return VocalSectionProfile(
        lo_pitch=lo_pitch,
        mel_onsets=tuple(int(c.at_ms) for c in ordered),
        mel_pitches=tuple(int(c.mapped) for c in ordered),
        stem_dynamics=stem_dynamics,
    )


__all__ = [
    "AccompDensity",
    "PhraseOctaveMode",
    "StemDynamics",
    "VocalSectionProfile",
    "align_accompaniment_onsets",
    "compute_vocal_section_profile",
    "optimize_phrase_octaves",
    "segment_melody_phrases",
]
