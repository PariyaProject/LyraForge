"""Reproducible 5-category audio transcription & separated quality benchmark."""

from __future__ import annotations

import array
import json
import math
import shutil
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lyraforge.instruments import load_builtin_profile
from lyraforge.library import LibraryStore
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
from lyraforge.music_core.models import Note
from lyraforge.transcribers import TranscribeOptions, get_transcriber, list_transcribers

ROOT_DIR = Path(__file__).resolve().parents[1]
MIDI_FIXTURES = ROOT_DIR / "tests" / "fixtures" / "midi"


@dataclass(frozen=True)
class SynthNoteSpec:
    start_ms: int
    dur_ms: int
    pitch: int
    role: str = "lead"  # "lead" | "piano" | "vocal" | "pad" | "bass" | "perc"
    gain: float = 0.28


def _render_mixed_wav(
    path: Path,
    events: list[SynthNoteSpec],
    *,
    sample_rate: int = 22050,
) -> int:
    """Synthesize multi-role deterministic WAV (piano, vibrato vocal, pad, bass, click)."""
    total_ms = max(e.start_ms + e.dur_ms for e in events) + 220
    n_samples = int(sample_rate * total_ms / 1000.0)
    buf = [0.0] * n_samples

    for ev in events:
        i0 = int(ev.start_ms * sample_rate / 1000.0)
        n_note = max(1, int(ev.dur_ms * sample_rate / 1000.0))
        if ev.role == "perc":
            # Short unpitched percussive transient (~35 ms) using deterministic pseudo-noise
            n_hit = min(n_note, int(0.035 * sample_rate))
            for i in range(n_hit):
                idx = i0 + i
                if idx >= n_samples:
                    break
                t = i / sample_rate
                env = math.exp(-85.0 * t)
                click = math.sin(2.0 * math.pi * 175.0 * math.exp(-22.0 * t) * t)
                hiss = math.sin((i * 19.37) ** 1.03)
                buf[idx] += ev.gain * env * (0.75 * click + 0.25 * hiss)
            continue

        freq = 440.0 * (2.0 ** ((ev.pitch - 69) / 12.0))
        for i in range(n_note):
            idx = i0 + i
            if idx >= n_samples:
                break
            t = i / sample_rate
            ratio = i / max(1, n_note)
            if ev.role == "vocal":
                attack = min(1.0, t / 0.045)
                release = min(1.0, (n_note - i) / max(1, int(0.04 * sample_rate)))
                vib = 1.0 + 0.0045 * math.sin(2.0 * math.pi * 5.2 * t)
                f = freq * vib
                sig = (
                    0.56 * math.sin(2.0 * math.pi * f * t)
                    + 0.27 * math.sin(2.0 * math.pi * 2.0 * f * t + 0.3)
                    + 0.12 * math.sin(2.0 * math.pi * 3.0 * f * t)
                    + 0.05 * math.sin(2.0 * math.pi * 4.0 * f * t)
                )
                env = attack * release
            elif ev.role == "pad":
                attack = min(1.0, t / 0.08)
                release = min(1.0, (n_note - i) / max(1, int(0.08 * sample_rate)))
                sig = 0.85 * math.sin(2.0 * math.pi * freq * t) + 0.15 * math.sin(
                    4.0 * math.pi * freq * t
                )
                env = attack * release
            elif ev.role == "bass":
                attack = min(1.0, t / 0.012)
                decay = math.exp(-2.2 * ratio)
                sig = 0.80 * math.sin(2.0 * math.pi * freq * t) + 0.20 * math.sin(
                    4.0 * math.pi * freq * t
                )
                env = attack * decay
            else:
                attack = min(1.0, t / 0.008)
                decay = math.exp(-3.2 * ratio)
                sig = (
                    0.70 * math.sin(2.0 * math.pi * freq * t)
                    + 0.22 * math.sin(2.0 * math.pi * 2.0 * freq * t)
                    + 0.08 * math.sin(2.0 * math.pi * 3.0 * freq * t)
                )
                env = attack * decay
            buf[idx] += ev.gain * env * sig

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


def _events_from_midi_fixture(name: str) -> list[SynthNoteSpec]:
    score = load_midi_file(MIDI_FIXTURES / name)
    return [
        SynthNoteSpec(
            start_ms=round(n.start_us / 1000.0),
            dur_ms=max(80, round((n.end_us - n.start_us) / 1000.0)),
            pitch=n.pitch,
            role="piano" if not n.is_percussion else "perc",
            gain=0.26,
        )
        for n in score.notes
        if not n.is_percussion
    ]


def _duration_and_miss_metrics(
    ref_specs: list[SynthNoteSpec],
    detected: tuple[Note, ...],
    *,
    onset_tol_ms: int = 120,
) -> dict[str, Any]:
    pred = [
        (round(n.start_us / 1000.0), max(1, round((n.end_us - n.start_us) / 1000.0)), n.pitch)
        for n in detected
    ]
    used: set[int] = set()
    dur_errors: list[int] = []
    matched = 0
    for r in ref_specs:
        best_idx: int | None = None
        best_dt = onset_tol_ms + 1
        for idx, (pm, _pd, pp) in enumerate(pred):
            if idx in used:
                continue
            dt = abs(pm - r.start_ms)
            if dt <= onset_tol_ms and abs(pp - r.pitch) <= 1 and dt < best_dt:
                best_dt = dt
                best_idx = idx
        if best_idx is not None:
            used.add(best_idx)
            matched += 1
            dur_errors.append(abs(pred[best_idx][1] - r.dur_ms))
    return {
        "missed_notes": max(0, len(ref_specs) - matched),
        "spurious_notes": max(0, len(pred) - matched),
        "mean_duration_error_ms": (
            round(sum(dur_errors) / len(dur_errors), 2) if dur_errors else None
        ),
    }


def main() -> None:
    ffmpeg_path = shutil.which("ffmpeg")
    engines = [m.to_json() for m in list_transcribers()]

    fixtures: dict[str, tuple[str, str, list[SynthNoteSpec]]] = {
        "solo_melody": (
            "单音旋律",
            "synthetic_harmonic_wav",
            [
                SynthNoteSpec(0, 350, 72, "lead", 0.30),
                SynthNoteSpec(400, 350, 74, "lead", 0.30),
                SynthNoteSpec(800, 350, 76, "lead", 0.30),
                SynthNoteSpec(1200, 350, 79, "lead", 0.30),
                SynthNoteSpec(1600, 350, 81, "lead", 0.30),
                SynthNoteSpec(2000, 350, 79, "lead", 0.30),
                SynthNoteSpec(2400, 350, 76, "lead", 0.30),
                SynthNoteSpec(2800, 450, 72, "lead", 0.30),
            ],
        ),
        "solo_piano_arpeggio": (
            "钢琴独奏（双手主旋律+琶音）",
            "synthetic_piano_wav",
            [
                # Bar 1: RH E5-G5 melody + LH C4-G4-C5 arpeggio
                SynthNoteSpec(0, 620, 76, "lead", 0.28),
                SynthNoteSpec(0, 220, 60, "piano", 0.18),
                SynthNoteSpec(240, 220, 67, "piano", 0.18),
                SynthNoteSpec(480, 220, 72, "piano", 0.18),
                SynthNoteSpec(720, 480, 79, "lead", 0.28),
                SynthNoteSpec(720, 220, 62, "piano", 0.18),
                SynthNoteSpec(960, 220, 69, "piano", 0.18),
                SynthNoteSpec(1200, 520, 76, "lead", 0.28),
                SynthNoteSpec(1200, 220, 64, "piano", 0.18),
                SynthNoteSpec(1440, 220, 67, "piano", 0.18),
                SynthNoteSpec(1680, 520, 72, "lead", 0.28),
            ],
        ),
        "polyphonic_piano_chords": (
            "和弦及多声部",
            "synthetic_harmonic_wav",
            [
                SynthNoteSpec(0, 500, 60, "piano", 0.22),
                SynthNoteSpec(0, 500, 64, "piano", 0.22),
                SynthNoteSpec(0, 500, 67, "lead", 0.26),
                SynthNoteSpec(600, 500, 65, "piano", 0.22),
                SynthNoteSpec(600, 500, 69, "piano", 0.22),
                SynthNoteSpec(600, 500, 72, "lead", 0.26),
                SynthNoteSpec(1200, 500, 67, "piano", 0.22),
                SynthNoteSpec(1200, 500, 71, "piano", 0.22),
                SynthNoteSpec(1200, 500, 74, "lead", 0.26),
                SynthNoteSpec(1800, 550, 60, "piano", 0.22),
                SynthNoteSpec(1800, 550, 64, "piano", 0.22),
                SynthNoteSpec(1800, 550, 67, "lead", 0.26),
            ],
        ),
        "vocal_with_accompaniment": (
            "人声与伴奏混合",
            "synthetic_vocal_pad_mix",
            [
                # Soft pad chord bed + formant vibrato vocal line
                SynthNoteSpec(0, 1200, 48, "pad", 0.14),
                SynthNoteSpec(0, 1200, 60, "pad", 0.12),
                SynthNoteSpec(0, 1200, 64, "pad", 0.12),
                SynthNoteSpec(0, 450, 72, "vocal", 0.30),
                SynthNoteSpec(500, 500, 74, "vocal", 0.30),
                SynthNoteSpec(1250, 1200, 53, "pad", 0.14),
                SynthNoteSpec(1250, 1200, 65, "pad", 0.12),
                SynthNoteSpec(1250, 1200, 69, "pad", 0.12),
                SynthNoteSpec(1250, 450, 76, "vocal", 0.30),
                SynthNoteSpec(1750, 550, 79, "vocal", 0.30),
            ],
        ),
        "multi_instrument_complex": (
            "多乐器复杂编曲",
            "synthetic_multi_instrument_mix",
            [
                SynthNoteSpec(0, 650, 48, "bass", 0.24),
                SynthNoteSpec(0, 650, 60, "pad", 0.14),
                SynthNoteSpec(0, 30, 36, "perc", 0.18),
                SynthNoteSpec(0, 360, 72, "lead", 0.26),
                SynthNoteSpec(400, 260, 76, "lead", 0.26),
                SynthNoteSpec(400, 30, 38, "perc", 0.15),
                SynthNoteSpec(700, 650, 55, "bass", 0.24),
                SynthNoteSpec(700, 650, 62, "pad", 0.14),
                SynthNoteSpec(700, 360, 79, "lead", 0.26),
                SynthNoteSpec(1100, 320, 76, "lead", 0.26),
                SynthNoteSpec(1450, 650, 53, "bass", 0.24),
                SynthNoteSpec(1450, 650, 65, "pad", 0.14),
                SynthNoteSpec(1450, 360, 81, "lead", 0.26),
                SynthNoteSpec(1850, 420, 79, "lead", 0.26),
            ],
        ),
    }
    if (MIDI_FIXTURES / "c_major_scale.mid").is_file():
        fixtures["fixture_c_major_scale_wav"] = (
            "单音旋律 (MIDI夹具)",
            "committed_midi_rendered_wav",
            _events_from_midi_fixture("c_major_scale.mid"),
        )
    if (MIDI_FIXTURES / "chords_type1.mid").is_file():
        fixtures["fixture_chords_type1_wav"] = (
            "和弦与多音轨 (MIDI夹具)",
            "committed_midi_rendered_wav",
            _events_from_midi_fixture("chords_type1.mid"),
        )

    profile = load_builtin_profile()
    benchmarks: list[dict[str, Any]] = []
    pipeline_roundtrip: dict[str, Any] = {}

    with tempfile.TemporaryDirectory(prefix="lyraforge-eval-") as tmpdir:
        tmp_root = Path(tmpdir)
        for eng in engines:
            if not eng["available"]:
                benchmarks.append({
                    "engine_id": eng["id"],
                    "available": False,
                    "status": "unavailable_missing_dependency",
                    "reason": "not installed in current host environment",
                    "details": eng.get("details", {}),
                })
                continue

            transcriber = get_transcriber(eng["id"])
            for case_name, (category, source_kind, specs) in fixtures.items():
                wav_path = tmp_root / f"{case_name}.wav"
                _render_mixed_wav(wav_path, specs)
                t0 = time.monotonic()
                tr = transcriber.transcribe(wav_path, TranscribeOptions())
                elapsed_ms = round((time.monotonic() - t0) * 1000.0, 2)
                raw_score = parse_midi_bytes(tr.midi_bytes)
                cleaned, _clean_stats = clean_score(raw_score)
                arr = arrange(cleaned, profile, ArrangeOptions(style=Style.BALANCED))
                qual = score_arrangement(cleaned, arr)

                pitched_specs = [s for s in specs if s.role != "perc"]
                lead_specs = [
                    s for s in pitched_specs if s.role in {"lead", "vocal"}
                ] or pitched_specs
                ref_all_pairs = [(s.start_ms, s.pitch) for s in pitched_specs]
                ref_lead_pairs = [(s.start_ms, s.pitch) for s in lead_specs]

                tf_all = evaluate_transcription_against_reference(
                    ref_all_pairs, cleaned.notes, onset_tol_ms=120, pitch_tol_semitones=1
                )
                tf_lead = evaluate_transcription_against_reference(
                    ref_lead_pairs, cleaned.notes, onset_tol_ms=120, pitch_tol_semitones=1
                )
                dur_miss = _duration_and_miss_metrics(
                    pitched_specs, cleaned.notes, onset_tol_ms=120
                )
                e2e_all = evaluate_arrangement_against_reference(
                    ref_all_pairs, arr, onset_tol_ms=120
                )
                e2e_lead = evaluate_arrangement_against_reference(
                    ref_lead_pairs, arr, onset_tol_ms=120
                )
                benchmarks.append({
                    "engine_id": eng["id"],
                    "case": case_name,
                    "category": category,
                    "source_kind": source_kind,
                    "raw_note_count": len(raw_score.notes),
                    "cleaned_note_count": len(cleaned.notes),
                    "elapsed_ms": elapsed_ms,
                    "transcription_fidelity": {
                        **tf_all.to_json(),
                        **dur_miss,
                        "lead_melody_recall": tf_lead.recall,
                        "lead_melody_f1": tf_lead.f1,
                    },
                    "arrangement_playability_vs_transcribed_midi": {
                        "playable_ratio": arr.stats["playable_ratio"],
                        "arrangement_playability_score": qual.overall_score,
                        "melody_preservation": qual.melody_preservation,
                        "note": (
                            "Measures playability relative to transcribed MIDI—"
                            "NOT original audio transcription fidelity."
                        ),
                    },
                    "end_to_end_vs_reference": {
                        **e2e_all,
                        "lead_pitch_recall": e2e_lead["reference_pitch_recall"],
                    },
                    "subjective_preview_quality": "unrated_manual_listening_required",
                })

        # Verify workflow roundtrip: import -> transcribe -> arrange -> preview -> edit -> save
        rt_wav = tmp_root / "roundtrip_solo.wav"
        _render_mixed_wav(rt_wav, fixtures["solo_melody"][2])
        with LibraryStore(tmp_root / "roundtrip_db") as store:
            imp = store.import_audio(rt_wav, title="Roundtrip Acceptance", tags=["eval"])
            tr_rec = store.transcribe_song(imp.song.id, engine_id="builtin-mono")
            arr_rec = store.arrange_song(imp.song.id, options=ArrangeOptions(style=Style.BALANCED))
            wav_out = store.render_preview(arr_rec.id)
            perf_doc = store.load_arrangement_performance(arr_rec.id)
            edited_events = list(perf_doc["events"])
            edited_events[0] = {**edited_events[0], "at_ms": int(edited_events[0]["at_ms"]) + 20}
            edited_rec = store.save_edited_arrangement(
                arr_rec.id, edited_events, label="评测精修保存版"
            )
            wav_edited = store.render_preview(edited_rec.id)
            pipeline_roundtrip = {
                "ok": wav_out.is_file() and wav_edited.is_file() and edited_rec.event_count >= 6,
                "transcribed_notes": tr_rec.note_count,
                "arranged_events": arr_rec.event_count,
                "preview_wav_bytes": wav_out.stat().st_size,
                "edited_arrangement_id": edited_rec.id,
                "edited_preview_wav_bytes": wav_edited.stat().st_size,
            }

    report = {
        "ffmpeg_available": ffmpeg_path is not None,
        "ffmpeg_path": ffmpeg_path,
        "engines": engines,
        "benchmarks": benchmarks,
        "pipeline_roundtrip": pipeline_roundtrip,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
