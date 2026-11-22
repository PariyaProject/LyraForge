"""Builders for LyraForge's self-authored MIDI regression fixtures.

All musical content here was written for this project (scales, triads, test
patterns) and is not derived from any copyrighted score. Regenerate the files
with ``uv run python scripts/make_fixtures.py``; tests verify the committed
bytes match these builders exactly.
"""

from __future__ import annotations

import io
import struct
from collections.abc import Callable, Iterable

import mido

TPB = 480
Event = tuple[int, mido.Message | mido.MetaMessage]


def bpm(b: float) -> int:
    return mido.bpm2tempo(b)


def track(events: Iterable[Event], name: str | None = None) -> mido.MidiTrack:
    """Build a track from (absolute_tick, message) pairs; stable for equal ticks."""
    t = mido.MidiTrack()
    if name is not None:
        t.append(mido.MetaMessage("track_name", name=name, time=0))
    now = 0
    for tick, msg in sorted(events, key=lambda e: e[0]):
        t.append(msg.copy(time=tick - now))
        now = tick
    t.append(mido.MetaMessage("end_of_track", time=0))
    return t


def notes(seq: Iterable[tuple[int, int, int]], channel: int = 0, velocity: int = 90) -> list[Event]:
    """(start_tick, length_ticks, pitch) -> note_on/note_off events."""
    out: list[Event] = []
    for start, length, pitch in seq:
        out.append((start, mido.Message("note_on", note=pitch, velocity=velocity, channel=channel)))
        out.append((start + length,
                    mido.Message("note_off", note=pitch, velocity=0, channel=channel)))
    # note_off before note_on at equal ticks
    out.sort(key=lambda e: (e[0], 0 if e[1].type == "note_off" else 1))
    return out


def tempo(tick: int, b: float) -> Event:
    return (tick, mido.MetaMessage("set_tempo", tempo=bpm(b)))


def to_bytes(mid: mido.MidiFile) -> bytes:
    buf = io.BytesIO()
    mid.save(file=buf)
    return buf.getvalue()


def smf(type_: int, tracks: list[mido.MidiTrack], tpb: int = TPB) -> bytes:
    mid = mido.MidiFile(type=type_, ticks_per_beat=tpb)
    mid.tracks.extend(tracks)
    return to_bytes(mid)


C_MAJOR_SCALE = [60, 62, 64, 65, 67, 69, 71, 72]
D_MAJOR_SCALE = [62, 64, 66, 67, 69, 71, 73, 74]


def c_major_scale() -> bytes:
    ev = [tempo(0, 120)] + notes((i * TPB, TPB - 24, p) for i, p in enumerate(C_MAJOR_SCALE))
    return smf(0, [track(ev, "C major scale")])


def d_major_scale() -> bytes:
    ev = [tempo(0, 120)] + notes((i * TPB, TPB - 24, p) for i, p in enumerate(D_MAJOR_SCALE))
    return smf(0, [track(ev, "D major scale")])


def chords_type1() -> bytes:
    conductor = track([
        tempo(0, 100),
        (0, mido.MetaMessage("time_signature", numerator=4, denominator=4)),
    ], "conductor")
    melody = [76, 74, 72, 74, 76, 76, 76, 77, 79, 77, 76, 74, 72, 74, 76, 72]
    mel = track(notes(((i * TPB, TPB - 24, p) for i, p in enumerate(melody)), channel=0),
                "melody")
    triads = [(48, 52, 55), (53, 57, 60), (55, 59, 62), (48, 52, 55)]
    chord_ev = [(bar * 4 * TPB, 4 * TPB - 24, p) for bar, tri in enumerate(triads) for p in tri]
    acc = track(notes(chord_ev, channel=1, velocity=70), "chords")
    return smf(1, [conductor, mel, acc])


def chromatic() -> bytes:
    ev = [tempo(0, 120)] + notes((i * 240, 216, 60 + i) for i in range(13))
    return smf(0, [track(ev, "chromatic C4-C5")])


def wide_range() -> bytes:
    pitches = [21, 36, 47, 84, 96, 108, 60]
    ev = [tempo(0, 120)] + notes((i * TPB, TPB - 24, p) for i, p in enumerate(pitches))
    return smf(0, [track(ev, "wide range")])


def repeated_notes() -> bytes:
    fast = [(i * 24, 12, 64) for i in range(8)]  # 25 ms apart @120bpm
    slow = [(960 + i * 120, 60, 64) for i in range(8)]  # 62.5 ms apart
    ev = [tempo(0, 120)] + notes(fast + slow)
    return smf(0, [track(ev, "repeated E4")])


def tempo_changes() -> bytes:
    conductor = track([tempo(0, 120), tempo(1920, 60), tempo(3840, 180)], "conductor")
    mel = track(notes((i * TPB, 240, 60) for i in range(12)), "pulse")
    return smf(1, [conductor, mel])


def triplets() -> bytes:
    pitches = [67, 69, 71, 72, 74, 76]
    ev = [tempo(0, 120)] + notes((i * 160, 150, p) for i, p in enumerate(pitches))
    return smf(0, [track(ev, "triplet eighths")])


def dense_chords() -> bytes:
    conductor = track([tempo(0, 120)], "conductor")
    big = [60, 64, 67, 72, 76, 79]
    a = notes([(0, 900, p) for p in big] + [(960, 900, p) for p in big])
    # duplicates of C4 and G4 at the same instant on another track + humanized cluster
    dup = notes([(0, 400, 60), (0, 400, 67), (1920, 400, 60), (1929, 400, 64), (1939, 400, 67),
                 (1948, 400, 72)], channel=1, velocity=60)
    return smf(1, [conductor, track(a, "big chords"), track(dup, "doubling")])


def percussion() -> bytes:
    conductor = track([tempo(0, 120)], "conductor")
    mel = track(notes((i * TPB, TPB - 24, p) for i, p in enumerate([60, 64, 67, 72])), "melody")
    drums = track(notes([(i * TPB, 60, d) for i, d in enumerate([36, 42, 38, 42])], channel=9),
                  "drums")
    return smf(1, [conductor, mel, drums])


def empty() -> bytes:
    return smf(0, [track([tempo(0, 120)], "empty")])


def overlap_edge() -> bytes:
    """Overlapping same pitch, velocity-0 note-off, stray note-off, unterminated note."""
    on = lambda n, v=90: mido.Message("note_on", note=n, velocity=v)  # noqa: E731
    off = lambda n: mido.Message("note_off", note=n, velocity=0)  # noqa: E731
    ev: list[Event] = [
        tempo(0, 120),
        (0, on(60)), (240, on(60)), (480, off(60)), (720, off(60)),
        (960, on(62)), (1200, on(62, 0)),
        (1300, off(65)),
        (1440, on(67)),
        (1920, mido.MetaMessage("marker", text="end")),
    ]
    return smf(0, [track(ev, "edge cases")])


# ---- intentionally broken / unsupported files -------------------------------------------

def not_midi() -> bytes:
    return b"This is not a MIDI file.\n"


def truncated() -> bytes:
    return c_major_scale()[:30]


def corrupt_track_length() -> bytes:
    header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, TPB)
    return header + b"MTrk" + struct.pack(">I", 1000) + b"\x00\x90\x3c"


def type2() -> bytes:
    data = bytearray(c_major_scale())
    data[8:10] = struct.pack(">H", 2)
    return bytes(data)


def smpte_division() -> bytes:
    data = bytearray(c_major_scale())
    data[12:14] = bytes([0xE7, 0x28])  # -25 fps, 40 ticks/frame
    return bytes(data)


FIXTURES: dict[str, Callable[[], bytes]] = {
    "c_major_scale.mid": c_major_scale,
    "d_major_scale.mid": d_major_scale,
    "chords_type1.mid": chords_type1,
    "chromatic.mid": chromatic,
    "wide_range.mid": wide_range,
    "repeated_notes.mid": repeated_notes,
    "tempo_changes.mid": tempo_changes,
    "triplets.mid": triplets,
    "dense_chords.mid": dense_chords,
    "percussion.mid": percussion,
    "empty.mid": empty,
    "overlap_edge.mid": overlap_edge,
    "broken/not_midi.mid": not_midi,
    "broken/truncated.mid": truncated,
    "broken/corrupt_track_length.mid": corrupt_track_length,
    "broken/type2.mid": type2,
    "broken/smpte_division.mid": smpte_division,
}

VALID_FIXTURES = [n for n in FIXTURES if not n.startswith("broken/") and n != "empty.mid"]
