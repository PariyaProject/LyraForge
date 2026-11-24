"""Isolated subprocess adapter for SwiftF0 ONNX monophonic vocal F0 + DP note segmentation (MIT)."""

from __future__ import annotations

import sys
from pathlib import Path

from lyraforge.playback.guards import StopToken
from lyraforge.transcribers._subprocess import (
    probe_installed_version,
    resolve_runner,
    run_isolated_transcriber,
)
from lyraforge.transcribers.base import (
    ModelInfo,
    ProgressCallback,
    TranscribeOptions,
    TranscriptionResult,
)

SWIFT_F0_PYTHON_ENV = "LYRAFORGE_SWIFT_F0_PYTHON"
SWIFT_F0_CLI_ENV = "LYRAFORGE_SWIFT_F0_BIN"

_MODEL_FMIN = 46.875
_MODEL_FMAX = 2093.75

_SWIFT_F0_RUN_SCRIPT = r"""
import math, pathlib, sys, wave
import mido
import numpy as np
from swift_f0 import SwiftF0, segment_notes

wav_path, out_mid_path = sys.argv[1], sys.argv[2]
fmin = float(sys.argv[3])
fmax = float(sys.argv[4])
pitch_hold_ms = float(sys.argv[5])
min_pitch = int(sys.argv[6])
max_pitch = int(sys.argv[7])


def _read_mono_wav_16k(path: str) -> np.ndarray:
    with wave.open(path, "rb") as wf:
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    if sw == 2:
        arr = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sw == 4:
        arr = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    elif sw == 1:
        arr = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"unsupported WAV sample width: {sw}")
    if ch > 1:
        arr = arr.reshape(-1, ch).mean(axis=1)
    if sr != 16000 and arr.size > 1:
        n_out = max(1, int(round(arr.size * 16000.0 / sr)))
        x_old = np.linspace(0.0, 1.0, arr.size, endpoint=False)
        x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
        arr = np.interp(x_new, x_old, arr).astype(np.float32)
    return arr


mono = _read_mono_wav_16k(wav_path)
mid = mido.MidiFile(type=0, ticks_per_beat=500)
trk = mido.MidiTrack()
trk.append(mido.MetaMessage("track_name", name="Vocal Lead", time=0))
trk.append(mido.MetaMessage("set_tempo", tempo=500_000, time=0))

if mono.size >= 160 and float(np.max(np.abs(mono))) > 1e-6:
    detector = SwiftF0()
    result = detector.detect(mono, 16000, fmin=fmin, fmax=fmax)
    notes = segment_notes(result, pitch_hold_ms=pitch_hold_ms)
    voiced = result.pitch_hz > 0
    if bool(np.any(voiced)):
        ref_db = float(np.percentile(result.loudness_db[voiced], 90))
    else:
        ref_db = -20.0

    events = []
    ts = result.timestamps
    for note in notes:
        i0 = int(np.searchsorted(ts, note.start, side="left"))
        i1 = int(np.searchsorted(ts, note.end, side="right"))
        i1 = max(i0 + 1, min(len(ts), i1))
        seg_db = float(np.median(result.loudness_db[i0:i1])) if i0 < len(ts) else ref_db
        seg_conf = float(np.median(result.confidence[i0:i1])) if i0 < len(ts) else 1.0
        if seg_db < ref_db - 28.0 or seg_conf < 0.42:
            continue
        midi_pitch = int(round(69.0 + 12.0 * math.log2(note.pitch_hz / 440.0)))
        if not (min_pitch <= midi_pitch <= max_pitch):
            continue
        vel = max(28, min(118, int(round(96.0 + (seg_db - ref_db) * 2.5))))
        s_ms = max(0, int(round(note.start * 1000.0)))
        e_ms = max(s_ms + 15, int(round(note.end * 1000.0)))
        events.append((s_ms, 1, midi_pitch, vel))
        events.append((e_ms, 0, midi_pitch, 0))

    events.sort(key=lambda item: (item[0], item[1], item[2]))
    now = 0
    for tick, is_on, pitch, vel in events:
        delta = max(0, tick - now)
        trk.append(
            mido.Message("note_on" if is_on else "note_off", note=pitch, velocity=vel, time=delta)
        )
        now = tick

trk.append(mido.MetaMessage("end_of_track", time=0))
mid.tracks.append(trk)
pathlib.Path(out_mid_path).parent.mkdir(parents=True, exist_ok=True)
mid.save(out_mid_path)
"""


def _midi_to_hz(pitch: int) -> float:
    return 440.0 * (2.0 ** ((pitch - 69) / 12.0))


def _effective_freq_bounds(opts: TranscribeOptions) -> tuple[float, float]:
    raw_lo = (
        opts.min_frequency_hz
        if opts.min_frequency_hz is not None
        else _midi_to_hz(opts.min_pitch)
    )
    raw_hi = (
        opts.max_frequency_hz
        if opts.max_frequency_hz is not None
        else _midi_to_hz(opts.max_pitch)
    )
    fmin = max(_MODEL_FMIN, min(_MODEL_FMAX * 0.85, float(raw_lo)))
    fmax = max(fmin * 1.15, min(_MODEL_FMAX, float(raw_hi)))
    return fmin, fmax


def _resolve_runner() -> list[str] | None:
    return resolve_runner(
        python_env=SWIFT_F0_PYTHON_ENV,
        python_module_args=["-m", "swift_f0"],
        cli_env=SWIFT_F0_CLI_ENV,
        binary_name="swift-f0",
    )


class SwiftF0SubprocessTranscriber:
    """Runs SwiftF0 ONNX + DP note segmentation in an isolated subprocess (monophonic vocals)."""

    id = "swift-f0"

    def probe(self) -> ModelInfo:
        runner = _resolve_runner()
        return ModelInfo(
            id=self.id,
            display_name="SwiftF0 人声 F0 转谱 (隔离进程 · 仅单音人声)",
            available=runner is not None,
            license="MIT",
            scope_note=(
                "专用于干人声/纯独唱的高精度 F0 提取与动态规划音符切分（CPU 极速、"
                "0.13 MB 内置 ONNX 模型；不支持多音和弦伴奏）。"
            ),
            details={
                "runner": runner,
                "python_env": SWIFT_F0_PYTHON_ENV,
                "cli_env": SWIFT_F0_CLI_ENV,
                "polyphonic": False,
                "supported_options": [
                    "min_pitch",
                    "max_pitch",
                    "min_note_ms",
                    "min_frequency_hz",
                    "max_frequency_hz",
                ],
                "platform": sys.platform,
            },
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
        runner = _resolve_runner()
        fmin, fmax = _effective_freq_bounds(opts)
        pitch_hold_ms = float(max(35, min(120, opts.min_note_ms)))

        def _build_cmd(base: list[str], wav_in: Path, out_dir: Path) -> list[str]:
            out_mid = out_dir / "swift_f0.mid"
            if len(base) >= 3 and base[1] == "-m":
                return [
                    base[0],
                    "-c",
                    _SWIFT_F0_RUN_SCRIPT,
                    str(wav_in),
                    str(out_mid),
                    f"{fmin:.2f}",
                    f"{fmax:.2f}",
                    f"{pitch_hold_ms:.1f}",
                    str(opts.min_pitch),
                    str(opts.max_pitch),
                ]
            return [*base, str(wav_in), str(out_mid)]

        res = run_isolated_transcriber(
            engine_id=self.id,
            display_name="SwiftF0",
            runner=runner,
            missing_hint=(
                f"SwiftF0 is not installed; configure {SWIFT_F0_PYTHON_ENV} "
                "or install 'swift-f0' in Settings -> Toolchain"
            ),
            audio_path=audio_path,
            build_cmd=_build_cmd,
            options=opts,
            on_progress=on_progress,
            stop_token=stop_token,
            timeout_per_audio_second=1.0,
            timeout_slack_s=60.0,
            sample_rate=16_000,
            engine_version=probe_installed_version(runner, "swift-f0"),
        )
        return TranscriptionResult(
            engine_id=res.engine_id,
            engine_version=res.engine_version,
            midi_bytes=res.midi_bytes,
            note_count=res.note_count,
            duration_ms=res.duration_ms,
            warnings=(
                "swift-f0 tracks monophonic vocal/solo F0 only; "
                "polyphonic chords are not represented.",
            ),
        )
