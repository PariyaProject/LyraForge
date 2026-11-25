"""Offline audio preview synthesis (cross-platform, zero external audio deps)."""

from lyraforge.preview.synth import (
    DEFAULT_SAMPLE_RATE,
    VALID_TIMBRES,
    resolve_timbre,
    synthesize_performance,
    synthesize_performance_to_wav,
)

__all__ = [
    "DEFAULT_SAMPLE_RATE",
    "VALID_TIMBRES",
    "resolve_timbre",
    "synthesize_performance",
    "synthesize_performance_to_wav",
]
