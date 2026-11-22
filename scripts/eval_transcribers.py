"""Reproducible transcriber availability probe & multi-track WAV benchmark (FIX-007)."""

from __future__ import annotations

import array
import json
import math
import shutil
import tempfile
import time
import wave
from pathlib import Path
from typing import Any

from lyraforge.instruments import load_builtin_profile
from lyraforge.music_core import ArrangeOptions, arrange, clean_score, score_arrangement
from lyraforge.music_core.arranger import Style
from lyraforge.music_core.midi_import import parse_midi_bytes
from lyraforge.transcribers import TranscribeOptions, get_transcriber, list_transcribers


def _render_harmonic_wav(
    path: Path,
    events: list[tuple[int, int, int]],
    *,
    sample_rate: int = 22050,
) -> int:
    """Synthesize multi-harmonic plucked/piano-like audio from (start_ms, dur_ms, pitch)."""
    total_ms = max(st + dur for st, dur, _ in events) + 200
    n_samples = int(sample_rate * total_ms / 1000.0)
    buf = [0.0] * n_samples
    for st_ms, dur_ms, pitch in events:
        freq = 440.0 * (2.0 ** ((pitch - 69) / 12.0))
        i0 = int(st_ms * sample_rate / 1000.0)
        n_note = max(1, int(dur_ms * sample_rate / 1000.0))
        for i in range(n_note):
            idx = i0 + i
            if idx >= n_samples:
                break
            t = i / sample_rate
            attack = min(1.0, t / 0.008)
            decay = math.exp(-3.2 * (i / n_note))
            sig = (
                0.70 * math.sin(2.0 * math.pi * freq * t)
                + 0.22 * math.sin(2.0 * math.pi * 2.0 * freq * t)
                + 0.08 * math.sin(2.0 * math.pi * 3.0 * freq * t)
            )
            buf[idx] += 0.28 * attack * decay * sig

    peak = max((abs(x) for x in buf), default=1.0)
    scale = 0.85 / peak if peak > 0.85 else 1.0
    pcm = array.array(
        "h",
        (max(-32767, min(32767, int(round(x * scale * 32767)))) for x in buf),
    )
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return total_ms


def _onset_pitch_metrics(
    ref_events: list[tuple[int, int, int]],
    pred_notes: tuple[Any, ...],
) -> dict[str, float]:
    matched_pred: set[int] = set()
    tp = 0
    for st_ms, _dur, ref_p in ref_events:
        for idx, n in enumerate(pred_notes):
            if idx in matched_pred:
                continue
            pred_ms = n.start_us / 1000.0
            if abs(pred_ms - st_ms) <= 120.0 and abs(n.pitch - ref_p) <= 1:
                matched_pred.add(idx)
                tp += 1
                break
    prec = tp / max(1, len(pred_notes))
    rec = tp / max(1, len(ref_events))
    f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
    return {
        "true_positives": tp,
        "precision": round(prec, 4),
        "recall": round(rec, 4),
        "f1": round(f1, 4),
    }


def main() -> None:
    ffmpeg_path = shutil.which("ffmpeg")
    engines = [m.to_json() for m in list_transcribers()]

    fixtures: dict[str, list[tuple[int, int, int]]] = {
        "solo_melody": [
            (0, 350, 72),
            (400, 350, 74),
            (800, 350, 76),
            (1200, 350, 79),
            (1600, 350, 81),
            (2000, 350, 79),
            (2400, 350, 76),
            (2800, 450, 72),
        ],
        "polyphonic_piano_chords": [
            (0, 500, 60), (0, 500, 64), (0, 500, 67),
            (600, 500, 65), (600, 500, 69), (600, 500, 72),
            (1200, 500, 67), (1200, 500, 71), (1200, 500, 74),
            (1800, 550, 60), (1800, 550, 64), (1800, 550, 67),
        ],
        "dense_multi_register": [
            (0, 300, 48), (0, 300, 72),
            (320, 260, 55), (320, 260, 76),
            (640, 260, 53), (640, 260, 79),
            (960, 260, 55), (960, 260, 81),
            (1280, 260, 52), (1280, 260, 77),
            (1600, 260, 50), (1600, 260, 74),
            (1920, 260, 55), (1920, 260, 76),
            (2240, 400, 48), (2240, 400, 72),
        ],
    }

    profile = load_builtin_profile()
    benchmarks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="lyraforge-eval-") as tmpdir:
        for eng in engines:
            if not eng["available"]:
                benchmarks.append({
                    "engine_id": eng["id"],
                    "available": False,
                    "status": "blocked_missing_dependency",
                    "reason": "not installed in current macOS environment",
                })
                continue

            transcriber = get_transcriber(eng["id"])
            for case_name, ref_notes in fixtures.items():
                wav_path = Path(tmpdir) / f"{case_name}.wav"
                _render_harmonic_wav(wav_path, ref_notes)
                t0 = time.monotonic()
                tr = transcriber.transcribe(wav_path, TranscribeOptions())
                elapsed_ms = round((time.monotonic() - t0) * 1000.0, 2)
                raw_score = parse_midi_bytes(tr.midi_bytes)
                cleaned, _clean_stats = clean_score(raw_score)
                arr = arrange(cleaned, profile, ArrangeOptions(style=Style.BALANCED))
                qual = score_arrangement(cleaned, arr)
                benchmarks.append({
                    "engine_id": eng["id"],
                    "case": case_name,
                    "ref_note_count": len(ref_notes),
                    "raw_note_count": len(raw_score.notes),
                    "cleaned_note_count": len(cleaned.notes),
                    "arranged_event_count": len(arr.events),
                    "playable_ratio": arr.stats["playable_ratio"],
                    "overall_score": qual.overall_score,
                    "elapsed_ms": elapsed_ms,
                    "accuracy": _onset_pitch_metrics(ref_notes, cleaned.notes),
                })

    report = {
        "ffmpeg_available": ffmpeg_path is not None,
        "ffmpeg_path": ffmpeg_path,
        "engines": engines,
        "benchmarks": benchmarks,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
