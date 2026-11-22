"""Offline pure-Python monophonic YIN pitch tracker (zero external ML deps).

Explicit scope: designed for solo monophonic melodies (e.g. solo lyre/piano
lines and test verification). Polyphonic mixes should use ``basic-pitch`` or an
isolated multi-instrument transcriber.
"""

from __future__ import annotations

import array
import io
import math
import operator
import sys
import tempfile
import wave
from pathlib import Path

import mido

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.media.extract import extract_audio_to_wav
from lyraforge.music_core.midi_import import parse_midi_bytes
from lyraforge.music_core.tempo import DEFAULT_US_PER_BEAT
from lyraforge.playback.guards import StopToken
from lyraforge.transcribers.base import (
    ModelInfo,
    ProgressCallback,
    TranscribeOptions,
    TranscriptionResult,
)

ENGINE_VERSION = "0.1.0"
_INTERNAL_RATE = 11_025
_HOP_S = 0.020
_WINDOW_SAMPLES = 256
_YIN_THRESHOLD = 0.18
_EXPORT_TPB = 500  # 1 tick == 1 ms at 120 BPM


def _midi_to_hz(pitch: int) -> float:
    return 440.0 * (2.0 ** ((pitch - 69) / 12.0))


def _hz_to_midi(hz: float) -> int:
    return round(69.0 + 12.0 * math.log2(hz / 440.0))


def _load_mono_11k(audio_path: Path) -> list[float]:
    with tempfile.TemporaryDirectory(prefix="lyraforge-mono-") as tmpdir:
        norm_wav = Path(tmpdir) / "mono.wav"
        extract_audio_to_wav(audio_path, norm_wav, sample_rate=_INTERNAL_RATE)
        with wave.open(str(norm_wav), "rb") as wf:
            raw = wf.readframes(wf.getnframes())
    pcm = array.array("h")
    pcm.frombytes(raw)
    if sys.byteorder != "little":
        pcm.byteswap()
    return [s / 32768.0 for s in pcm]


def _yin_pitch_hz(
    frame: list[float],
    sample_rate: int,
    min_lag: int,
    max_lag: int,
) -> float | None:
    w = _WINDOW_SAMPLES
    if len(frame) < w + max_lag + 1:
        return None
    seg0 = frame[:w]
    mul = operator.mul
    e0 = sum(map(mul, seg0, seg0))
    if e0 <= 1e-12:
        return None

    prefix_sq = [0.0] * (len(frame) + 1)
    acc = 0.0
    for idx, val in enumerate(frame):
        acc += val * val
        prefix_sq[idx + 1] = acc

    cmndf: list[float] = [1.0] * (max_lag + 1)
    running_sum = 0.0
    for tau in range(1, max_lag + 1):
        seg_tau = frame[tau : tau + w]
        e_tau = prefix_sq[tau + w] - prefix_sq[tau]
        dot = sum(map(mul, seg0, seg_tau))
        diff = max(0.0, e0 + e_tau - 2.0 * dot)
        running_sum += diff
        cmndf[tau] = (diff * tau / running_sum) if running_sum > 1e-12 else 1.0

    chosen: int | None = None
    for tau in range(min_lag, max_lag + 1):
        if cmndf[tau] < _YIN_THRESHOLD:
            while tau + 1 <= max_lag and cmndf[tau + 1] < cmndf[tau]:
                tau += 1
            chosen = tau
            break
    if chosen is None:
        best_tau = min(range(min_lag, max_lag + 1), key=cmndf.__getitem__)
        if cmndf[best_tau] > 0.35:
            return None
        chosen = best_tau

    # Parabolic interpolation around chosen lag
    if min_lag < chosen < max_lag:
        s0, s1, s2 = cmndf[chosen - 1], cmndf[chosen], cmndf[chosen + 1]
        denom = 2.0 * (2.0 * s1 - s2 - s0)
        if abs(denom) > 1e-12:
            better = chosen + (s2 - s0) / denom
            if min_lag <= better <= max_lag:
                return sample_rate / better
    return sample_rate / chosen


def _median_smooth(pitches: list[int | None]) -> list[int | None]:
    out = list(pitches)
    for i in range(1, len(pitches) - 1):
        win = [p for p in (pitches[i - 1], pitches[i], pitches[i + 1]) if p is not None]
        if pitches[i] is not None and len(win) == 3:
            win.sort()
            out[i] = win[1]
    return out


class BuiltinMonoTranscriber:
    """Deterministic pure-Python YIN monophonic audio-to-MIDI transcriber."""

    id = "builtin-mono"

    def probe(self) -> ModelInfo:
        return ModelInfo(
            id=self.id,
            display_name="内置单音旋律识别 (YIN)",
            available=True,
            license="Self-authored (Project internal)",
            scope_note="纯 Python 离线单音旋律识别；适合独奏/测试，复杂混音建议使用 Basic Pitch。",
            details={"sample_rate": _INTERNAL_RATE, "version": ENGINE_VERSION},
        )

    def transcribe(
        self,
        audio_path: Path,
        options: TranscribeOptions | None = None,
        on_progress: ProgressCallback | None = None,
        stop_token: StopToken | None = None,
    ) -> TranscriptionResult:
        opts = options or TranscribeOptions()
        opts.validate()
        if stop_token is not None and stop_token.stopped:
            raise LyraError(ErrorCode.PLAYBACK_ABORTED, "transcription cancelled")

        samples = _load_mono_11k(Path(audio_path))
        hop = max(1, round(_INTERNAL_RATE * _HOP_S))
        max_lag = min(
            len(samples) - _WINDOW_SAMPLES - 2,
            int(_INTERNAL_RATE / _midi_to_hz(opts.min_pitch)) + 1,
        )
        min_lag = max(2, int(_INTERNAL_RATE / _midi_to_hz(opts.max_pitch)))
        frame_len = _WINDOW_SAMPLES + max_lag + 2

        if len(samples) < frame_len or max_lag <= min_lag:
            raise LyraError(ErrorCode.NO_PLAYABLE_NOTES, "audio is too short to detect notes")

        n_frames = max(1, (len(samples) - frame_len) // hop + 1)
        raw_pitches: list[int | None] = []
        rms_values: list[float] = []

        for idx in range(n_frames):
            if stop_token is not None and stop_token.stopped:
                raise LyraError(ErrorCode.PLAYBACK_ABORTED, "transcription cancelled")
            start = idx * hop
            frame = samples[start : start + frame_len]
            rms = math.sqrt(sum(x * x for x in frame[:_WINDOW_SAMPLES]) / _WINDOW_SAMPLES)
            rms_values.append(rms)
            if rms < opts.onset_rms_threshold:
                raw_pitches.append(None)
            else:
                hz = _yin_pitch_hz(frame, _INTERNAL_RATE, min_lag, max_lag)
                if hz is None:
                    raw_pitches.append(None)
                else:
                    pitch = _hz_to_midi(hz)
                    raw_pitches.append(
                        pitch if opts.min_pitch <= pitch <= opts.max_pitch else None
                    )
            if on_progress is not None and (idx % 25 == 0 or idx == n_frames - 1):
                on_progress((idx + 1) / n_frames, "analyzing pitch")

        smoothed = _median_smooth(raw_pitches)
        min_frames = max(1, math.ceil((opts.min_note_ms / 1000.0) / _HOP_S))

        notes_ms: list[tuple[int, int, int, int]] = []  # (start_ms, end_ms, pitch, velocity)
        seg_start: int | None = None
        seg_pitch: int | None = None
        seg_peak_rms = 0.0

        def _flush(end_idx: int) -> None:
            if seg_start is None or seg_pitch is None:
                return
            if end_idx - seg_start >= min_frames:
                start_ms = round(seg_start * _HOP_S * 1000)
                end_ms = round(end_idx * _HOP_S * 1000)
                vel = max(35, min(120, round(seg_peak_rms * 360)))
                notes_ms.append((start_ms, max(start_ms + 1, end_ms), seg_pitch, vel))

        for i, p in enumerate(smoothed):
            prev_rms = rms_values[i - 1] if i > 0 else 0.0
            reattack = (
                p is not None
                and seg_pitch == p
                and seg_start is not None
                and i - seg_start >= 3
                and prev_rms > 0
                and rms_values[i] > prev_rms * 1.45
                and rms_values[i] > opts.onset_rms_threshold * 1.5
            )
            if p != seg_pitch or reattack:
                _flush(i)
                if p is not None:
                    seg_start = i
                    seg_pitch = p
                    seg_peak_rms = rms_values[i]
                else:
                    seg_start = None
                    seg_pitch = None
                    seg_peak_rms = 0.0
            elif p is not None:
                seg_peak_rms = max(seg_peak_rms, rms_values[i])
        _flush(len(smoothed))

        if not notes_ms:
            raise LyraError(ErrorCode.NO_PLAYABLE_NOTES, "no notes detected in audio")

        mid = mido.MidiFile(type=0, ticks_per_beat=_EXPORT_TPB)
        trk = mido.MidiTrack()
        trk.append(mido.MetaMessage("track_name", name=self.id, time=0))
        trk.append(mido.MetaMessage("set_tempo", tempo=DEFAULT_US_PER_BEAT, time=0))

        events: list[tuple[int, int, mido.Message]] = []
        for s_ms, e_ms, pitch, vel in notes_ms:
            events.append((s_ms, 1, mido.Message("note_on", note=pitch, velocity=vel, channel=0)))
            events.append((e_ms, 0, mido.Message("note_off", note=pitch, velocity=0, channel=0)))
        events.sort(key=lambda it: (it[0], it[1]))
        now = 0
        for tick, _ord, msg in events:
            trk.append(msg.copy(time=max(0, tick - now)))
            now = max(now, tick)
        trk.append(mido.MetaMessage("end_of_track", time=0))
        mid.tracks.append(trk)

        buf = io.BytesIO()
        mid.save(file=buf)
        midi_bytes = buf.getvalue()
        score = parse_midi_bytes(midi_bytes)
        return TranscriptionResult(
            engine_id=self.id,
            engine_version=ENGINE_VERSION,
            midi_bytes=midi_bytes,
            note_count=len(score.notes),
            duration_ms=round(score.duration_us / 1000),
            warnings=(
                "builtin-mono tracks monophonic pitch only; polyphonic chords are approximated.",
            ),
        )
