"""Rule-based arrangement quality scoring and A/B comparison (PROJECT_SPEC §4.3)."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from lyraforge.music_core.arranger import Adjustment, Arrangement, detect_melody_track
from lyraforge.music_core.models import NormalizedScore, Note


def _sign(delta: int) -> int:
    if delta > 0:
        return 1
    if delta < 0:
        return -1
    return 0


def _cluster_onsets(times: list[int], window_ms: int) -> list[int]:
    if not times:
        return []
    ordered = sorted(times)
    clusters = [ordered[0]]
    for t in ordered[1:]:
        if t - clusters[-1] > window_ms:
            clusters.append(t)
    return clusters


def _top_voice_points(notes: list[Note], speed: Fraction, bin_ms: int) -> list[tuple[int, int]]:
    bins: dict[int, tuple[int, int]] = {}
    for n in notes:
        t_ms = round(Fraction(n.start_us, 1000) / speed)
        bucket = t_ms // max(1, bin_ms)
        prev = bins.get(bucket)
        if prev is None or n.pitch > prev[1]:
            bins[bucket] = (t_ms, n.pitch)
    return [bins[k] for k in sorted(bins)]


def _nearest_within(sorted_times: list[int], target: int, tol: int) -> int | None:
    if not sorted_times:
        return None
    pos = bisect_left(sorted_times, target)
    best: int | None = None
    best_dist = tol + 1
    for idx in (pos - 1, pos):
        if 0 <= idx < len(sorted_times):
            dist = abs(sorted_times[idx] - target)
            if dist <= tol and dist < best_dist:
                best = sorted_times[idx]
                best_dist = dist
    return best


@dataclass(frozen=True, slots=True)
class QualityBreakdown:
    overall_score: float
    melody_preservation: float
    rhythmic_fidelity: float
    pitch_contour_preservation: float
    harmonic_coherence: float
    missing_note_penalty: float
    dense_key_conflict_penalty: float
    large_leap_penalty: float
    melody_track: int | None
    warnings: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "overall_score": self.overall_score,
            "melody_preservation": self.melody_preservation,
            "rhythmic_fidelity": self.rhythmic_fidelity,
            "pitch_contour_preservation": self.pitch_contour_preservation,
            "harmonic_coherence": self.harmonic_coherence,
            "missing_note_penalty": self.missing_note_penalty,
            "dense_key_conflict_penalty": self.dense_key_conflict_penalty,
            "large_leap_penalty": self.large_leap_penalty,
            "melody_track": self.melody_track,
            "warnings": list(self.warnings),
        }


def score_arrangement(score: NormalizedScore, arr: Arrangement) -> QualityBreakdown:
    """Compute interpretable fidelity and playability metrics for an Arrangement."""
    opts = arr.options
    speed = Fraction(opts.speed).limit_denominator(10_000)
    include = set(opts.include_tracks) if opts.include_tracks is not None else None
    considered = [
        n
        for n in score.notes
        if not (opts.exclude_percussion and n.is_percussion)
        and (include is None or n.track in include)
    ]
    if not considered or not arr.events:
        return QualityBreakdown(
            overall_score=0.0,
            melody_preservation=0.0,
            rhythmic_fidelity=0.0,
            pitch_contour_preservation=0.0,
            harmonic_coherence=0.0,
            missing_note_penalty=1.0,
            dense_key_conflict_penalty=0.0,
            large_leap_penalty=0.0,
            melody_track=None,
            warnings=("no_playable_events",),
        )

    melody_track = arr.stats.get("melody_track")
    if melody_track is None and "melody_track" not in arr.stats:
        melody_track = detect_melody_track(score)
    tracks_present = {n.track for n in considered}
    multi_track = len(tracks_present) > 1 and melody_track in tracks_present

    ev_times = sorted(e.at_ms for e in arr.events)
    tol = max(45, opts.chord_window_ms + opts.arpeggiate_ms * 4 + 30)

    # 1. Melody preservation
    if multi_track and melody_track is not None:
        src_mel = [n for n in considered if n.track == melody_track]
        ev_mel = [e for e in arr.events if e.source_track == melody_track]
        raw_cov = min(1.0, len(ev_mel) / max(1, len(src_mel)))
        sub_frac = sum(
            1 for e in ev_mel if Adjustment.SEMITONE_SUBSTITUTED in e.adjustments
        ) / max(1, len(ev_mel))
        melody_preservation = round(raw_cov * (1.0 - 0.15 * sub_frac), 4)
        src_line = sorted(
            ((round(Fraction(n.start_us, 1000) / speed), n.pitch) for n in src_mel),
            key=lambda x: (x[0], -x[1]),
        )
        # Collapse simultaneous notes in melody track to top line
        dedup_line: list[tuple[int, int]] = []
        for t_ms, p in src_line:
            if dedup_line and abs(t_ms - dedup_line[-1][0]) <= 20:
                if p > dedup_line[-1][1]:
                    dedup_line[-1] = (t_ms, p)
            else:
                dedup_line.append((t_ms, p))
        src_line = dedup_line
        ev_line = sorted((e.at_ms, e.mapped_pitch, e.source_pitch) for e in ev_mel)
    else:
        src_line = _top_voice_points(considered, speed, 25)
        matched_mel = 0
        matched_sub = 0
        for t_ms, src_p in src_line:
            near = [
                e
                for e in arr.events
                if abs(e.at_ms - t_ms) <= tol and e.source_pitch == src_p
            ]
            if near:
                matched_mel += 1
                if Adjustment.SEMITONE_SUBSTITUTED in near[0].adjustments:
                    matched_sub += 1
        sub_frac = matched_sub / max(1, matched_mel)
        melody_preservation = round(
            (matched_mel / max(1, len(src_line))) * (1.0 - 0.15 * sub_frac),
            4,
        )
        # Top mapped voice per output cluster
        ev_line = []
        for e in arr.events:
            if ev_line and abs(e.at_ms - ev_line[-1][0]) <= max(25, opts.chord_window_ms + tol):
                if e.mapped_pitch > ev_line[-1][1]:
                    ev_line[-1] = (e.at_ms, e.mapped_pitch, e.source_pitch)
            else:
                ev_line.append((e.at_ms, e.mapped_pitch, e.source_pitch))

    # 2. Rhythmic fidelity
    src_onsets = _cluster_onsets(
        [round(Fraction(n.start_us, 1000) / speed) for n in considered],
        max(20, opts.chord_window_ms),
    )
    matched_onsets = 0
    total_err = 0
    for t_ms in src_onsets:
        hit = _nearest_within(ev_times, t_ms, tol)
        if hit is not None:
            matched_onsets += 1
            total_err += abs(hit - t_ms)
    onset_cov = matched_onsets / max(1, len(src_onsets))
    onset_prec = 1.0 - (total_err / max(1, matched_onsets)) / max(1, tol)
    rhythmic_fidelity = round(max(0.0, min(1.0, onset_cov * (0.7 + 0.3 * onset_prec))), 4)

    # 3. Pitch contour preservation along melody sequence
    matched_pitches: list[tuple[int, int]] = []
    for t_ms, src_p in src_line:
        candidates = [
            e for e in arr.events if abs(e.at_ms - t_ms) <= tol and e.source_pitch == src_p
        ]
        if candidates:
            best = min(candidates, key=lambda e: abs(e.at_ms - t_ms))
            matched_pitches.append((src_p, best.mapped_pitch))
    if len(matched_pitches) < 2:
        pitch_contour_preservation = 1.0
    else:
        agree = 0.0
        steps = len(matched_pitches) - 1
        for idx in range(steps):
            d_src = _sign(matched_pitches[idx + 1][0] - matched_pitches[idx][0])
            d_out = _sign(matched_pitches[idx + 1][1] - matched_pitches[idx][1])
            if d_src == d_out:
                agree += 1.0
            elif d_src == 0 or d_out == 0:
                agree += 0.5
        pitch_contour_preservation = round(agree / steps, 4)

    # 4. Harmonic coherence
    semitone_sub = int(arr.stats.get("semitone_substituted", 0))
    purity = 1.0 - min(1.0, semitone_sub / len(arr.events))
    playable_ratio = float(arr.stats.get("playable_ratio", len(arr.events) / len(considered)))
    harmonic_coherence = round(max(0.0, min(1.0, 0.75 * purity + 0.25 * playable_ratio)), 4)

    # 5. Penalties
    n_considered = max(1, len(considered))
    missing_note_penalty = round(min(1.0, max(0.0, 1.0 - len(arr.events) / n_considered)), 4)
    dropped_map = arr.stats.get("dropped", {})
    conflicts = (
        int(dropped_map.get("repeat_too_fast", 0))
        + int(dropped_map.get("duplicate_key", 0))
        + int(dropped_map.get("polyphony_limit", 0))
    )
    conflict_ratio = min(1.0, conflicts / n_considered)
    max_kps = float(arr.stats.get("max_keys_per_second", 0))
    burst_excess = min(1.0, max(0.0, (max_kps - 12.0) / 16.0))
    dense_key_conflict_penalty = round(min(1.0, 0.7 * conflict_ratio + 0.3 * burst_excess), 4)

    if len(ev_line) < 2:
        leap_ratio = 0.0
    else:
        large_leaps = sum(
            1 for idx in range(len(ev_line) - 1) if abs(ev_line[idx + 1][1] - ev_line[idx][1]) > 12
        )
        leap_ratio = large_leaps / (len(ev_line) - 1)
    fold_ratio = int(arr.stats.get("octave_folded", 0)) / len(arr.events)
    large_leap_penalty = round(min(1.0, 0.75 * leap_ratio + 0.25 * fold_ratio), 4)

    positive = (
        0.34 * melody_preservation
        + 0.24 * rhythmic_fidelity
        + 0.22 * pitch_contour_preservation
        + 0.20 * harmonic_coherence
    )
    negative = (
        0.35 * missing_note_penalty
        + 0.20 * dense_key_conflict_penalty
        + 0.15 * large_leap_penalty
    )
    overall_score = round(max(0.0, min(1.0, positive - negative)) * 100.0, 2)

    warnings: list[str] = []
    if missing_note_penalty > 0.25:
        warnings.append("high_note_drop_rate")
    if dense_key_conflict_penalty > 0.20:
        warnings.append("dense_key_conflicts")
    if large_leap_penalty > 0.35:
        warnings.append("large_pitch_leaps")
    if semitone_sub / len(arr.events) > 0.25:
        warnings.append("many_semitone_substitutions")

    return QualityBreakdown(
        overall_score=overall_score,
        melody_preservation=melody_preservation,
        rhythmic_fidelity=rhythmic_fidelity,
        pitch_contour_preservation=pitch_contour_preservation,
        harmonic_coherence=harmonic_coherence,
        missing_note_penalty=missing_note_penalty,
        dense_key_conflict_penalty=dense_key_conflict_penalty,
        large_leap_penalty=large_leap_penalty,
        melody_track=melody_track,
        warnings=tuple(warnings),
    )


def _extract_quality(report: dict[str, Any]) -> dict[str, Any]:
    q = report.get("quality")
    if isinstance(q, dict) and "overall_score" in q:
        return q
    stats = report.get("stats") or {}
    playable = float(stats.get("playable_ratio", 0.0))
    return {
        "overall_score": round(max(0.0, min(100.0, playable * 100.0)), 2),
        "melody_preservation": playable,
        "rhythmic_fidelity": playable,
        "pitch_contour_preservation": 1.0,
        "harmonic_coherence": playable,
        "missing_note_penalty": round(max(0.0, 1.0 - playable), 4),
        "dense_key_conflict_penalty": 0.0,
        "large_leap_penalty": 0.0,
        "warnings": [],
    }


def compare_arrangements(
    report_a: dict[str, Any],
    report_b: dict[str, Any],
    id_a: str = "A",
    id_b: str = "B",
) -> dict[str, Any]:
    """Compare two arrangement reports on quality score, fidelity, and density."""
    qa = _extract_quality(report_a)
    qb = _extract_quality(report_b)
    sa = report_a.get("stats") or {}
    sb = report_b.get("stats") or {}

    score_a = float(qa.get("overall_score", 0.0))
    score_b = float(qb.get("overall_score", 0.0))
    delta = round(score_a - score_b, 2)
    if abs(delta) < 0.1:
        winner = "tie"
    elif delta > 0:
        winner = id_a
    else:
        winner = id_b

    metric_names = (
        "overall_score",
        "melody_preservation",
        "rhythmic_fidelity",
        "pitch_contour_preservation",
        "harmonic_coherence",
        "missing_note_penalty",
        "dense_key_conflict_penalty",
        "large_leap_penalty",
    )
    metrics = {
        name: {
            "a": float(qa.get(name, 0.0)),
            "b": float(qb.get(name, 0.0)),
            "delta": round(float(qa.get(name, 0.0)) - float(qb.get(name, 0.0)), 4),
        }
        for name in metric_names
    }
    metrics["playable_ratio"] = {
        "a": float(sa.get("playable_ratio", 0.0)),
        "b": float(sb.get("playable_ratio", 0.0)),
        "delta": round(
            float(sa.get("playable_ratio", 0.0)) - float(sb.get("playable_ratio", 0.0)), 4
        ),
    }
    return {
        "id_a": id_a,
        "id_b": id_b,
        "winner": winner,
        "score_a": score_a,
        "score_b": score_b,
        "score_delta": delta,
        "metrics": metrics,
        "summary": (
            f"{winner} scores higher ({score_a:.1f} vs {score_b:.1f})"
            if winner != "tie"
            else f"Tie ({score_a:.1f} vs {score_b:.1f})"
        ),
    }
