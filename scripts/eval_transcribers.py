"""Reproducible transcriber availability probe & separated fidelity/playability benchmark."""

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
from lyraforge.music_core import (
    ArrangeOptions,
    arrange,
    clean_score,
    evaluate_arrangement_against_reference,
    evaluate_transcription_against_reference,
    load_midi_file,
    score_arrangement,
)
from lyraforge.music_core.arranger import Style
from lyraforge.music_core.midi_import import parse_midi_bytes
from lyraforge.transcribers import TranscribeOptions, get_transcriber, list_transcribers

ROOT_DIR = Path(__file__).resolve().parents[1]
MIDI_FIXTURES = ROOT_DIR / "tests" / "fixtures" / "midi"


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


def _events_from_midi_fixture(name: str) -> list[tuple[int, int, int]]:
    score = load_midi_file(MIDI_FIXTURES / name)
    return [
        (
            round(n.start_us / 1000.0),
            max(80, round((n.end_us - n.start_us) / 1000.0)),
            n.pitch,
        )
        for n in score.notes
        if not n.is_percussion
    ]


def main() -> None:
    ffmpeg_path = shutil.which("ffmpeg")
    engines = [m.to_json() for m in list_transcribers()]

    fixtures: dict[str, tuple[str, list[tuple[int, int, int]]]] = {
        "solo_melody": (
            "synthetic_harmonic_wav",
            [
                (0, 350, 72),
                (400, 350, 74),
                (800, 350, 76),
                (1200, 350, 79),
                (1600, 350, 81),
                (2000, 350, 79),
                (2400, 350, 76),
                (2800, 450, 72),
            ],
        ),
        "polyphonic_piano_chords": (
            "synthetic_harmonic_wav",
            [
                (0, 500, 60), (0, 500, 64), (0, 500, 67),
                (600, 500, 65), (600, 500, 69), (600, 500, 72),
                (1200, 500, 67), (1200, 500, 71), (1200, 500, 74),
                (1800, 550, 60), (1800, 550, 64), (1800, 550, 67),
            ],
        ),
        "dense_multi_register": (
            "synthetic_harmonic_wav",
            [
                (0, 300, 48), (0, 300, 72),
                (320, 260, 55), (320, 260, 76),
                (640, 260, 53), (640, 260, 79),
                (960, 260, 55), (960, 260, 81),
                (1280, 260, 52), (1280, 260, 77),
                (1600, 260, 50), (1600, 260, 74),
                (1920, 260, 55), (1920, 260, 76),
                (2240, 400, 48), (2240, 400, 72),
            ],
        ),
    }
    if (MIDI_FIXTURES / "c_major_scale.mid").is_file():
        fixtures["fixture_c_major_scale_wav"] = (
            "committed_midi_rendered_wav",
            _events_from_midi_fixture("c_major_scale.mid"),
        )
    if (MIDI_FIXTURES / "chords_type1.mid").is_file():
        fixtures["fixture_chords_type1_wav"] = (
            "committed_midi_rendered_wav",
            _events_from_midi_fixture("chords_type1.mid"),
        )

    profile = load_builtin_profile()
    benchmarks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="lyraforge-eval-") as tmpdir:
        for eng in engines:
            if not eng["available"]:
                benchmarks.append({
                    "engine_id": eng["id"],
                    "available": False,
                    "status": "unavailable_missing_dependency",
                    "reason": "not installed in current macOS environment",
                })
                continue

            transcriber = get_transcriber(eng["id"])
            for case_name, (source_kind, ref_notes) in fixtures.items():
                wav_path = Path(tmpdir) / f"{case_name}.wav"
                _render_harmonic_wav(wav_path, ref_notes)
                t0 = time.monotonic()
                tr = transcriber.transcribe(wav_path, TranscribeOptions())
                elapsed_ms = round((time.monotonic() - t0) * 1000.0, 2)
                raw_score = parse_midi_bytes(tr.midi_bytes)
                cleaned, _clean_stats = clean_score(raw_score)
                arr = arrange(cleaned, profile, ArrangeOptions(style=Style.BALANCED))
                qual = score_arrangement(cleaned, arr)
                ref_pairs = [(st_ms, pitch) for st_ms, _dur, pitch in ref_notes]
                tf = evaluate_transcription_against_reference(
                    ref_pairs, cleaned.notes, onset_tol_ms=120, pitch_tol_semitones=1
                )
                e2e = evaluate_arrangement_against_reference(ref_pairs, arr, onset_tol_ms=120)
                benchmarks.append({
                    "engine_id": eng["id"],
                    "case": case_name,
                    "source_kind": source_kind,
                    "raw_note_count": len(raw_score.notes),
                    "cleaned_note_count": len(cleaned.notes),
                    "elapsed_ms": elapsed_ms,
                    "transcription_fidelity": tf.to_json(),
                    "arrangement_playability_vs_transcribed_midi": {
                        "playable_ratio": arr.stats["playable_ratio"],
                        "arrangement_playability_score": qual.overall_score,
                        "melody_preservation": qual.melody_preservation,
                        "note": (
                            "Measures how well arranged events fit the instrument relative to "
                            "transcribed MIDI—NOT original audio accuracy."
                        ),
                    },
                    "end_to_end_vs_reference": e2e,
                    "subjective_preview_quality": "unrated_manual_listening_required",
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
