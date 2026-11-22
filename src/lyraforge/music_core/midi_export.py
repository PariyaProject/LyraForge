"""Export NormalizedScore and Arrangement to Standard MIDI Files (SMF)."""

from __future__ import annotations

import io
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

import mido

from lyraforge.music_core.arranger import Arrangement
from lyraforge.music_core.models import NormalizedScore
from lyraforge.music_core.tempo import DEFAULT_US_PER_BEAT

EXPORT_TPB = 500  # At 120 BPM (500_000 us/beat), 1 tick == exactly 1 ms


def _build_track(
    abs_events: list[tuple[int, int, mido.Message | mido.MetaMessage]],
    *,
    name: str | None = None,
) -> mido.MidiTrack:
    track = mido.MidiTrack()
    if name:
        track.append(mido.MetaMessage("track_name", name=name, time=0))
    now = 0
    for tick, _order, msg in sorted(abs_events, key=lambda item: (item[0], item[1])):
        delta = max(0, tick - now)
        track.append(msg.copy(time=delta))
        now = max(now, tick)
    track.append(mido.MetaMessage("end_of_track", time=0))
    return track


def score_to_midi_bytes(score: NormalizedScore) -> bytes:
    """Serialize a ``NormalizedScore`` to SMF Type 1 preserving tracks and channels."""
    mid = mido.MidiFile(type=1, ticks_per_beat=EXPORT_TPB)
    conductor_events: list[tuple[int, int, mido.Message | mido.MetaMessage]] = [
        (0, 0, mido.MetaMessage("set_tempo", tempo=DEFAULT_US_PER_BEAT)),
    ]
    for ts in score.time_signatures:
        tick = max(0, round(ts.at_us / 1000))
        conductor_events.append(
            (
                tick,
                1,
                mido.MetaMessage(
                    "time_signature",
                    numerator=ts.numerator,
                    denominator=ts.denominator,
                ),
            )
        )
    mid.tracks.append(_build_track(conductor_events, name="conductor"))

    by_track: dict[int, list[tuple[int, int, mido.Message | mido.MetaMessage]]] = defaultdict(list)
    for n in score.notes:
        start_tick = max(0, round(n.start_us / 1000))
        end_tick = max(start_tick + 1, round(n.end_us / 1000))
        by_track[n.track].append(
            (
                start_tick,
                1,
                mido.Message("note_on", note=n.pitch, velocity=n.velocity, channel=n.channel),
            )
        )
        by_track[n.track].append(
            (end_tick, 0, mido.Message("note_off", note=n.pitch, velocity=0, channel=n.channel))
        )

    track_names = {t.index: t.name for t in score.tracks}
    for tid in sorted(by_track):
        mid.tracks.append(_build_track(by_track[tid], name=track_names.get(tid) or f"track_{tid}"))

    buf = io.BytesIO()
    mid.save(file=buf)
    return buf.getvalue()


def _simple_events_to_midi_bytes(note_tuples: Iterable[tuple[int, int, int, int]]) -> bytes:
    mid = mido.MidiFile(type=0, ticks_per_beat=EXPORT_TPB)
    events: list[tuple[int, int, mido.Message | mido.MetaMessage]] = [
        (0, 0, mido.MetaMessage("set_tempo", tempo=DEFAULT_US_PER_BEAT)),
    ]
    for at_ms, hold_ms, pitch, velocity in note_tuples:
        start_tick = max(0, at_ms)
        end_tick = max(start_tick + 1, at_ms + hold_ms)
        events.append(
            (start_tick, 1, mido.Message("note_on", note=pitch, velocity=velocity, channel=0))
        )
        events.append((end_tick, 0, mido.Message("note_off", note=pitch, velocity=0, channel=0)))
    mid.tracks.append(_build_track(events, name="arrangement"))
    buf = io.BytesIO()
    mid.save(file=buf)
    return buf.getvalue()


def arrangement_to_midi_bytes(arr: Arrangement) -> bytes:
    """Serialize an ``Arrangement`` to SMF Type 0 playable MIDI."""
    return _simple_events_to_midi_bytes(
        (ev.at_ms, ev.hold_ms, ev.mapped_pitch, ev.velocity) for ev in arr.events
    )


def performance_to_midi_bytes(doc: Mapping[str, Any]) -> bytes:
    """Serialize a validated ``performance.json`` mapping to SMF Type 0 MIDI."""
    return _simple_events_to_midi_bytes(
        (int(ev["at_ms"]), int(ev["hold_ms"]), int(ev["mapped_pitch"]), int(ev["velocity"]))
        for ev in doc["events"]
    )
