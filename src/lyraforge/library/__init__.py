"""Cross-platform local SQLite song library and file artifact store."""

from lyraforge.library.packaging import (
    export_backup_zip,
    export_lyrapack,
    import_lyrapack,
    restore_backup_zip,
)
from lyraforge.library.paths import (
    DATA_DIR_ENV,
    atomic_write_bytes,
    atomic_write_text,
    default_data_dir,
    resolve_under,
)
from lyraforge.library.schema import SCHEMA_VERSION
from lyraforge.library.store import (
    ArrangementRecord,
    ImportResult,
    LibraryStore,
    SongDetail,
    SongSummary,
    SourceRecord,
    TranscriptionRecord,
)

__all__ = [
    "ArrangementRecord",
    "DATA_DIR_ENV",
    "ImportResult",
    "LibraryStore",
    "SCHEMA_VERSION",
    "SongDetail",
    "SongSummary",
    "SourceRecord",
    "TranscriptionRecord",
    "atomic_write_bytes",
    "atomic_write_text",
    "default_data_dir",
    "export_backup_zip",
    "export_lyrapack",
    "import_lyrapack",
    "resolve_under",
    "restore_backup_zip",
]
