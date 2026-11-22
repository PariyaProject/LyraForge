"""Standard MIDI File import -> NormalizedScore.

Handles SMF type 0/1, global tempo maps (tempo events in any track), time
signatures, note-on velocity 0 as note-off, overlapping same-pitch notes
(FIFO pairing), unterminated notes and defensive size / note-count limits.
Every failure surfaces as ``LyraError`` with a stable code.
"""

from __future__ import annotations

import hashlib
import io
import struct
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

import mido

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.music_core.models import NormalizedScore, Note, TimeSignature, TrackInfo
from lyraforge.music_core.tempo import TempoChange, TempoMap


@dataclass(frozen=True)
class ImportLimits:
    max_file_bytes: int = 8 * 1024 * 1024
    max_notes: int = 200_000
    max_duration_us: int = 60 * 60 * 1_000_000  # 1 hour


def load_midi_file(path: str | Path, limits: ImportLimits | None = None) -> NormalizedScore:
    limits = limits or ImportLimits()
    p = Path(path)
    if not p.is_file():
        raise LyraError(ErrorCode.SOURCE_UNAVAILABLE, f"MIDI file not found: {p.name}")
    size = p.stat().st_size
    if size > limits.max_file_bytes:
        raise LyraError(
            ErrorCode.LIMIT_EXCEEDED,
            f"MIDI file too large ({size} bytes > {limits.max_file_bytes})",
            {"size": size, "limit": limits.max_file_bytes},
        )
    return parse_midi_bytes(p.read_bytes(), limits)


def _read_header(data: bytes) -> tuple[int, int, int]:
    if len(data) < 14 or data[:4] != b"MThd":
        raise LyraError(ErrorCode.MEDIA_DECODE_FAILED, "not a Standard MIDI File (missing MThd)")
    (hlen,) = struct.unpack(">I", data[4:8])
    if hlen < 6:
        raise LyraError(ErrorCode.MEDIA_DECODE_FAILED, "corrupt MIDI header length")
    fmt, ntrks, division = struct.unpack(">HHH", data[8:14])
    return fmt, ntrks, division


def parse_midi_bytes(data: bytes, limits: ImportLimits | None = None) -> NormalizedScore:
    limits = limits or ImportLimits()
    if len(data) > limits.max_file_bytes:
        raise LyraError(ErrorCode.LIMIT_EXCEEDED, "MIDI data too large",
                        {"size": len(data), "limit": limits.max_file_bytes})
    sha = hashlib.sha256(data).hexdigest()
    fmt, _ntrks, division = _read_header(data)
    if fmt == 2:
        raise LyraError(
            ErrorCode.MEDIA_UNSUPPORTED,
            "SMF type 2 (independent sequences) is not supported",
        )
    if fmt not in (0, 1):
        raise LyraError(ErrorCode.MEDIA_DECODE_FAILED, f"unknown SMF format {fmt}")
    if division & 0x8000:
        raise LyraError(ErrorCode.MEDIA_UNSUPPORTED, "SMPTE time division is not supported")
    if division == 0:
        raise LyraError(ErrorCode.MEDIA_DECODE_FAILED, "ticks_per_beat is 0")

    try:
        mid = mido.MidiFile(file=io.BytesIO(data), clip=False)
    except Exception as exc:  # mido raises OSError/EOFError/ValueError/KeyError/IndexError
        raise LyraError(
            ErrorCode.MEDIA_DECODE_FAILED,
            f"cannot parse MIDI: {type(exc).__name__}" + (f": {exc}" if str(exc) else ""),
        ) from exc

    tpb = division
    warnings: list[str] = []
    tempo_changes: list[TempoChange] = []
    ts_raw: list[tuple[int, int, int]] = []
    # raw notes: (start_tick, end_tick, pitch, velocity, track, channel)
    raw_notes: list[tuple[int, int, int, int, int, int]] = []
    track_meta: list[tuple[str, set[int], int]] = []
    max_tick = 0
    unmatched_offs = 0
    unterminated = 0

    for ti, track in enumerate(mid.tracks):
        name = ""
        channels: set[int] = set()
        open_notes: dict[tuple[int, int], deque[tuple[int, int]]] = defaultdict(deque)
        count = 0
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.is_meta:
                if msg.type == "set_tempo":
                    if fmt == 1 and ti != 0:
                        warnings.append(
                            f"set_tempo found in track {ti} (expected track 0); applied globally"
                        )
                    tempo_changes.append(TempoChange(tick, msg.tempo))
                elif msg.type == "time_signature":
                    ts_raw.append((tick, msg.numerator, msg.denominator))
                elif msg.type == "track_name" and not name:
                    name = msg.name
                continue
            if msg.type == "note_on" and msg.velocity > 0:
                open_notes[(msg.channel, msg.note)].append((tick, msg.velocity))
                channels.add(msg.channel)
            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                q = open_notes.get((msg.channel, msg.note))
                if q:
                    start, vel = q.popleft()
                    raw_notes.append((start, tick, msg.note, vel, ti, msg.channel))
                    count += 1
                    if len(raw_notes) > limits.max_notes:
                        raise LyraError(ErrorCode.LIMIT_EXCEEDED,
                                        f"too many notes (> {limits.max_notes})",
                                        {"limit": limits.max_notes})
                else:
                    unmatched_offs += 1
        # close unterminated notes at end of track
        for (ch, pitch), q in sorted(open_notes.items()):
            while q:
                start, vel = q.popleft()
                raw_notes.append((start, tick, pitch, vel, ti, ch))
                count += 1
                unterminated += 1
        max_tick = max(max_tick, tick)
        track_meta.append((name, channels, count))

    if len(raw_notes) > limits.max_notes:
        raise LyraError(ErrorCode.LIMIT_EXCEEDED, f"too many notes (> {limits.max_notes})",
                        {"limit": limits.max_notes})
    if unmatched_offs:
        warnings.append(f"{unmatched_offs} note-off event(s) without matching note-on ignored")
    if unterminated:
        warnings.append(f"{unterminated} unterminated note(s) closed at end of track")

    tempo_map = TempoMap(tpb, tempo_changes)
    notes = [
        Note(pitch=p, velocity=v, start_tick=s, end_tick=e,
             start_us=tempo_map.tick_to_us(s), end_us=tempo_map.tick_to_us(e),
             track=t, channel=c)
        for (s, e, p, v, t, c) in raw_notes
    ]
    notes.sort(key=lambda n: (n.start_us, n.pitch, n.track, n.channel, n.end_us))
    duration_us = tempo_map.tick_to_us(max_tick)
    if notes:
        duration_us = max(duration_us, max(n.end_us for n in notes))
    if duration_us > limits.max_duration_us:
        raise LyraError(ErrorCode.LIMIT_EXCEEDED, "MIDI duration exceeds limit",
                        {"duration_us": duration_us, "limit": limits.max_duration_us})

    time_sigs = tuple(
        TimeSignature(tick=t, at_us=tempo_map.tick_to_us(t), numerator=n, denominator=d)
        for (t, n, d) in sorted(ts_raw)
    )
    tracks = tuple(
        TrackInfo(index=i, name=name, note_count=cnt, channels=tuple(sorted(chs)))
        for i, (name, chs, cnt) in enumerate(track_meta)
    )
    return NormalizedScore(
        source_sha256=sha,
        midi_type=fmt,
        ticks_per_beat=tpb,
        tempo_map=tempo_map,
        time_signatures=time_sigs,
        tracks=tracks,
        notes=tuple(notes),
        duration_us=duration_us,
        warnings=tuple(dict.fromkeys(warnings)),  # de-duplicate, keep order
    )
