"""Immutable domain models for normalized scores."""

from __future__ import annotations

from dataclasses import dataclass

from lyraforge.music_core.tempo import TempoMap

PERCUSSION_CHANNEL = 9  # GM channel 10 (0-based 9)


@dataclass(frozen=True, slots=True)
class Note:
    pitch: int
    velocity: int
    start_tick: int
    end_tick: int
    start_us: int
    end_us: int
    track: int
    channel: int

    @property
    def duration_us(self) -> int:
        return self.end_us - self.start_us

    @property
    def is_percussion(self) -> bool:
        return self.channel == PERCUSSION_CHANNEL


@dataclass(frozen=True, slots=True)
class TimeSignature:
    tick: int
    at_us: int
    numerator: int
    denominator: int


@dataclass(frozen=True, slots=True)
class TrackInfo:
    index: int
    name: str
    note_count: int
    channels: tuple[int, ...]


@dataclass(frozen=True)
class NormalizedScore:
    source_sha256: str
    midi_type: int
    ticks_per_beat: int
    tempo_map: TempoMap
    time_signatures: tuple[TimeSignature, ...]
    tracks: tuple[TrackInfo, ...]
    notes: tuple[Note, ...]  # sorted by (start_us, pitch, track, channel, end_us)
    duration_us: int
    warnings: tuple[str, ...]

    def summary(self) -> dict[str, object]:
        return {
            "sha256": self.source_sha256,
            "midi_type": self.midi_type,
            "ticks_per_beat": self.ticks_per_beat,
            "track_count": len(self.tracks),
            "note_count": len(self.notes),
            "duration_ms": round(self.duration_us / 1000),
            "tempo_map": self.tempo_map.to_json(),
            "time_signatures": [
                {"tick": t.tick, "at_ms": round(t.at_us / 1000), "numerator": t.numerator,
                 "denominator": t.denominator}
                for t in self.time_signatures
            ],
            "tracks": [
                {"index": t.index, "name": t.name, "note_count": t.note_count,
                 "channels": list(t.channels)}
                for t in self.tracks
            ],
            "pitch_range": (
                [min(n.pitch for n in self.notes), max(n.pitch for n in self.notes)]
                if self.notes else None
            ),
            "warnings": list(self.warnings),
        }
