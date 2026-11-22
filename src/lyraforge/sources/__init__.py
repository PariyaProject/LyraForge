"""Legal source discovery and authorized acquisition adapters."""

from lyraforge.sources.base import SourceAdapter, SourceCandidate
from lyraforge.sources.local import (
    ALLOWED_SOURCE_EXTENSIONS,
    MIDI_EXTENSIONS,
    LocalLibrarySourceAdapter,
)
from lyraforge.sources.url import DirectUrlSourceAdapter, validate_public_http_url

__all__ = [
    "ALLOWED_SOURCE_EXTENSIONS",
    "DirectUrlSourceAdapter",
    "LocalLibrarySourceAdapter",
    "MIDI_EXTENSIONS",
    "SourceAdapter",
    "SourceCandidate",
    "validate_public_http_url",
]
