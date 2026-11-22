"""Legal source discovery and authorized acquisition adapters."""

from lyraforge.sources.base import SourceAdapter, SourceCandidate
from lyraforge.sources.local import (
    ALLOWED_SOURCE_EXTENSIONS,
    MIDI_EXTENSIONS,
    LocalLibrarySourceAdapter,
)
from lyraforge.sources.online import (
    LicenseClassification,
    OpenMusicCatalogSourceAdapter,
    classify_license_url,
    rank_candidates,
)
from lyraforge.sources.url import (
    DirectUrlSourceAdapter,
    resolve_public_http_url,
    validate_public_http_url,
)

__all__ = [
    "ALLOWED_SOURCE_EXTENSIONS",
    "DirectUrlSourceAdapter",
    "LicenseClassification",
    "LocalLibrarySourceAdapter",
    "MIDI_EXTENSIONS",
    "OpenMusicCatalogSourceAdapter",
    "SourceAdapter",
    "SourceCandidate",
    "classify_license_url",
    "rank_candidates",
    "resolve_public_http_url",
    "validate_public_http_url",
]
