"""Exact tick -> microsecond conversion for SMF tempo maps.

Segment start times are kept as exact ``Fraction``s so that long files with many
tempo changes do not accumulate rounding drift; only the final value is rounded
(Python ``round`` = round-half-to-even, deterministic across platforms).
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from fractions import Fraction

DEFAULT_US_PER_BEAT = 500_000  # 120 BPM, SMF default when no set_tempo precedes a note


@dataclass(frozen=True, slots=True)
class TempoChange:
    tick: int
    us_per_beat: int

    @property
    def bpm(self) -> float:
        return 60_000_000 / self.us_per_beat


class TempoMap:
    def __init__(self, ticks_per_beat: int, changes: list[TempoChange] | tuple[TempoChange, ...]):
        if ticks_per_beat <= 0:
            raise ValueError("ticks_per_beat must be positive")
        self.ticks_per_beat = ticks_per_beat
        # Stable sort by tick; when several changes share a tick the last one wins.
        by_tick: dict[int, TempoChange] = {}
        for ch in sorted(changes, key=lambda c: c.tick):
            if ch.tick < 0 or ch.us_per_beat <= 0:
                raise ValueError(f"invalid tempo change {ch!r}")
            by_tick[ch.tick] = ch
        if 0 not in by_tick:
            by_tick[0] = TempoChange(0, DEFAULT_US_PER_BEAT)
        self.changes: tuple[TempoChange, ...] = tuple(by_tick[t] for t in sorted(by_tick))
        self._ticks = [c.tick for c in self.changes]
        starts: list[Fraction] = []
        acc = Fraction(0)
        for i, ch in enumerate(self.changes):
            if i > 0:
                prev = self.changes[i - 1]
                acc += Fraction((ch.tick - prev.tick) * prev.us_per_beat, ticks_per_beat)
            starts.append(acc)
        self._starts = starts

    def tick_to_us_exact(self, tick: int) -> Fraction:
        if tick < 0:
            raise ValueError("tick must be >= 0")
        i = bisect_right(self._ticks, tick) - 1
        ch = self.changes[i]
        return self._starts[i] + Fraction((tick - ch.tick) * ch.us_per_beat, self.ticks_per_beat)

    def tick_to_us(self, tick: int) -> int:
        return round(self.tick_to_us_exact(tick))

    def to_json(self) -> list[dict[str, int | float]]:
        return [
            {
                "tick": c.tick,
                "at_ms": round(self._starts[i] / 1000),
                "us_per_beat": c.us_per_beat,
                "bpm": round(c.bpm, 6),
            }
            for i, c in enumerate(self.changes)
        ]
