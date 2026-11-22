"""Headless music domain core.

Layering rule (enforced by tests/unit/test_layering.py): this package must not
import GUI, OS input, network, subprocess or LLM modules, nor
``lyraforge.playback`` / ``lyraforge.cli``.
"""

from lyraforge.music_core.arranger import (
    ARRANGER_VERSION,
    Arrangement,
    ArrangeOptions,
    arrange,
    detect_melody_track,
)
from lyraforge.music_core.cleanup import CleanupOptions, clean_score
from lyraforge.music_core.midi_export import (
    arrangement_to_midi_bytes,
    performance_to_midi_bytes,
    score_to_midi_bytes,
)
from lyraforge.music_core.midi_import import ImportLimits, load_midi_file, parse_midi_bytes
from lyraforge.music_core.models import NormalizedScore, Note, TimeSignature, TrackInfo
from lyraforge.music_core.performance import build_performance, validate_performance
from lyraforge.music_core.profile import InstrumentProfile, KeyDef, profile_from_dict
from lyraforge.music_core.scoring import (
    QualityBreakdown,
    TranscriptionAccuracy,
    compare_arrangements,
    evaluate_arrangement_against_reference,
    evaluate_events_against_reference,
    evaluate_transcription_against_reference,
    score_arrangement,
)
from lyraforge.music_core.tempo import TempoChange, TempoMap

__all__ = [
    "ARRANGER_VERSION",
    "ArrangeOptions",
    "Arrangement",
    "CleanupOptions",
    "ImportLimits",
    "InstrumentProfile",
    "KeyDef",
    "NormalizedScore",
    "Note",
    "QualityBreakdown",
    "TempoChange",
    "TempoMap",
    "TimeSignature",
    "TrackInfo",
    "TranscriptionAccuracy",
    "arrange",
    "arrangement_to_midi_bytes",
    "build_performance",
    "clean_score",
    "compare_arrangements",
    "detect_melody_track",
    "evaluate_arrangement_against_reference",
    "evaluate_events_against_reference",
    "evaluate_transcription_against_reference",
    "load_midi_file",
    "parse_midi_bytes",
    "performance_to_midi_bytes",
    "profile_from_dict",
    "score_arrangement",
    "score_to_midi_bytes",
    "validate_performance",
]
