"""Share package (.lyrapack) and local library backup/restore with strict ZIP safety."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.fs import atomic_write_bytes, resolve_under
from lyraforge.instruments import load_builtin_profile
from lyraforge.library.schema import SCHEMA_VERSION
from lyraforge.media import SUPPORTED_MEDIA_EXTENSIONS
from lyraforge.music_core.canonical import pretty_json
from lyraforge.music_core.performance import validate_performance
from lyraforge.secrets import SECRET_FILENAME, is_sensitive_key

if TYPE_CHECKING:
    from lyraforge.library.store import LibraryStore

LYRAPACK_SCHEMA_VERSION = 1
_FORBIDDEN_AUDIO_EXTS = SUPPORTED_MEDIA_EXTENSIONS
_SQLITE_SIDECARS = frozenset({"library.db-wal", "library.db-shm", "library.db-journal"})
_WINDOWS_RESERVED_STEMS = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{n}" for n in range(1, 10)}
    | {f"LPT{n}" for n in range(1, 10)}
)


def _sha256_prefixed(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _validate_member_name(raw_name: str) -> str:
    norm = raw_name.replace("\\", "/")
    if (
        not norm
        or norm.startswith("/")
        or ":" in norm
        or "\x00" in norm
    ):
        raise LyraError(ErrorCode.PACKAGE_INVALID, f"unsafe ZIP path: {raw_name!r}")
    parts = PurePosixPath(norm).parts
    if any(p in {"", ".", ".."} for p in parts):
        raise LyraError(ErrorCode.PACKAGE_INVALID, f"invalid ZIP path traversal: {raw_name!r}")
    for seg in parts:
        if seg.endswith((" ", ".")) or any(ord(ch) < 32 for ch in seg):
            raise LyraError(
                ErrorCode.PACKAGE_INVALID,
                f"unsafe filename segment in ZIP: {raw_name!r}",
            )
        stem = seg.split(".", 1)[0].rstrip(" ").upper()
        if stem in _WINDOWS_RESERVED_STEMS:
            raise LyraError(
                ErrorCode.PACKAGE_INVALID,
                f"reserved Windows device name in ZIP: {raw_name!r}",
            )
    return "/".join(parts)


def _read_validated_zip_entries(
    data: bytes,
    *,
    max_files: int,
    max_uncompressed_bytes: int,
) -> dict[str, bytes]:
    if not data:
        raise LyraError(ErrorCode.PACKAGE_INVALID, "empty archive payload")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data), mode="r")
    except zipfile.BadZipFile as exc:
        raise LyraError(ErrorCode.PACKAGE_INVALID, f"invalid ZIP archive: {exc}") from exc

    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if not infos:
            raise LyraError(ErrorCode.PACKAGE_INVALID, "archive contains no files")
        if len(infos) > max_files:
            raise LyraError(
                ErrorCode.LIMIT_EXCEEDED,
                f"archive exceeds file count limit ({len(infos)} > {max_files})",
            )

        entries: dict[str, bytes] = {}
        total_bytes = 0
        for info in infos:
            mode_bits = (info.external_attr >> 16) & 0o170000
            if mode_bits == 0o120000:
                raise LyraError(
                    ErrorCode.PACKAGE_INVALID,
                    f"symlinks are forbidden in archive: {info.filename!r}",
                )
            clean_name = _validate_member_name(info.filename)
            if clean_name in entries:
                raise LyraError(
                    ErrorCode.PACKAGE_INVALID, f"duplicate archive entry: {clean_name!r}"
                )
            if info.file_size > max_uncompressed_bytes:
                raise LyraError(
                    ErrorCode.LIMIT_EXCEEDED,
                    f"archive entry exceeds size limit ({info.file_size} bytes)",
                )
            chunks: list[bytes] = []
            with zf.open(info, "r") as stream:
                while True:
                    chunk = stream.read(65_536)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if total_bytes > max_uncompressed_bytes:
                        raise LyraError(
                            ErrorCode.LIMIT_EXCEEDED,
                            f"archive exceeds uncompressed limit ({max_uncompressed_bytes} bytes)",
                        )
                    chunks.append(chunk)
            entries[clean_name] = b"".join(chunks)
    return entries


def export_lyrapack(
    store: LibraryStore,
    arrangement_id: str,
    *,
    copyright_confirmed: bool = False,
    license_notice: str = "",
) -> bytes:
    """Export a shareable ``.lyrapack`` archive (omits source audio by default)."""
    if not copyright_confirmed:
        raise LyraError(
            ErrorCode.PERMISSION_REQUIRED,
            "sharing a .lyrapack requires explicit copyright_confirmed=True confirmation",
        )

    rec = store.get_arrangement(arrangement_id)
    detail = store.get_song(rec.song_id)
    perf = store.load_arrangement_performance(arrangement_id)
    report = store.load_arrangement_report(arrangement_id)
    mid_bytes = store.export_arrangement(arrangement_id, "midi")

    perf_bytes = pretty_json(perf).encode("utf-8")
    rep_bytes = pretty_json(report).encode("utf-8")
    manifest = {
        "schema_version": LYRAPACK_SCHEMA_VERSION,
        "kind": "lyraforge.lyrapack",
        "includes_source_audio": False,
        "copyright_confirmed": True,
        "license_notice": license_notice.strip()
        or "Shared performance arrangement only (no source audio included).",
        "song": {
            "title": detail.song.title,
            "artist": detail.song.artist,
            "tags": list(detail.song.tags),
        },
        "arrangement": {
            "source_arrangement_id": rec.id,
            "profile_id": rec.profile_id,
            "style": rec.style,
            "transpose": rec.transpose,
            "speed": rec.speed,
            "score": rec.score,
            "label": rec.label,
        },
        "files": {
            "arrangement.mid": _sha256_prefixed(mid_bytes),
            "performance.json": _sha256_prefixed(perf_bytes),
            "report.json": _sha256_prefixed(rep_bytes),
        },
    }
    manifest_bytes = pretty_json(manifest).encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", manifest_bytes)
        zf.writestr("arrangement.mid", mid_bytes)
        zf.writestr("performance.json", perf_bytes)
        zf.writestr("report.json", rep_bytes)
    return buf.getvalue()


def import_lyrapack(
    store: LibraryStore,
    data: bytes,
    *,
    max_files: int = 20,
    max_uncompressed_bytes: int = 20_000_000,
) -> dict[str, Any]:
    """Safely validate and import a ``.lyrapack`` package into ``LibraryStore``."""
    entries = _read_validated_zip_entries(
        data, max_files=max_files, max_uncompressed_bytes=max_uncompressed_bytes
    )

    for name in entries:
        if Path(name).suffix.lower() in _FORBIDDEN_AUDIO_EXTS:
            raise LyraError(
                ErrorCode.PACKAGE_INVALID,
                f"share packages must not bundle source audio files ({name})",
            )

    required = ("manifest.json", "arrangement.mid", "performance.json", "report.json")
    missing = [r for r in required if r not in entries]
    if missing:
        raise LyraError(
            ErrorCode.PACKAGE_INVALID,
            f".lyrapack missing required files: {missing}",
        )

    try:
        manifest = json.loads(entries["manifest.json"].decode("utf-8"))
        perf = json.loads(entries["performance.json"].decode("utf-8"))
        report = json.loads(entries["report.json"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LyraError(ErrorCode.PACKAGE_INVALID, f"invalid JSON in .lyrapack: {exc}") from exc

    if (
        not isinstance(manifest, dict)
        or manifest.get("kind") != "lyraforge.lyrapack"
        or manifest.get("schema_version") != LYRAPACK_SCHEMA_VERSION
    ):
        raise LyraError(ErrorCode.PACKAGE_INVALID, "unsupported or malformed .lyrapack manifest")
    if manifest.get("includes_source_audio") is not False:
        raise LyraError(
            ErrorCode.PACKAGE_INVALID, "packages claiming source audio are rejected by default"
        )

    expected_hashes = manifest.get("files")
    if not isinstance(expected_hashes, dict):
        raise LyraError(ErrorCode.PACKAGE_INVALID, "manifest.files missing")
    for fname in ("arrangement.mid", "performance.json", "report.json"):
        if expected_hashes.get(fname) != _sha256_prefixed(entries[fname]):
            raise LyraError(
                ErrorCode.PACKAGE_INVALID,
                f"checksum mismatch for {fname} inside .lyrapack",
            )

    profile = load_builtin_profile(str(perf.get("instrument_profile_id", "")))
    validate_performance(perf, profile)

    song_meta = manifest.get("song") or {}
    title = str(song_meta.get("title") or "Imported LyraPack").strip() or "Imported LyraPack"
    artist = str(song_meta.get("artist") or "")
    raw_tags = song_meta.get("tags") or []
    tags = (
        [str(t).strip() for t in raw_tags if str(t).strip()]
        if isinstance(raw_tags, list)
        else []
    )

    with tempfile.TemporaryDirectory(prefix="lyraforge-pack-") as tmpdir:
        mid_path = Path(tmpdir) / "arrangement.mid"
        mid_path.write_bytes(entries["arrangement.mid"])
        imp = store.import_midi(mid_path, title=title, artist=artist, tags=tags)

    arr_meta = manifest.get("arrangement") or {}
    label = arr_meta.get("label")
    arr_rec = store.import_packaged_arrangement(
        song_id=imp.song.id,
        source_id=imp.source.id,
        perf=perf,
        report=report if isinstance(report, dict) else {},
        midi_bytes=entries["arrangement.mid"],
        label=str(label) if label else "导入分享包",
    )
    return {
        "song": store.get_song(imp.song.id).song.to_json(),
        "arrangement": arr_rec.to_json(),
        "manifest": manifest,
    }


def export_backup_zip(store: LibraryStore) -> bytes:
    """Create a consistent SQLite + artifacts backup ZIP (never includes secrets)."""
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory(prefix="lyraforge-backup-") as tmpdir:
        snap_db = Path(tmpdir) / "library.db"
        dst_conn = sqlite3.connect(snap_db)
        try:
            store._conn.backup(dst_conn)
            rows = dst_conn.execute("SELECT key FROM settings").fetchall()
            sensitive = [str(r[0]) for r in rows if is_sensitive_key(str(r[0]))]
            if sensitive:
                placeholders = ",".join("?" for _ in sensitive)
                with dst_conn:
                    dst_conn.execute(
                        f"DELETE FROM settings WHERE key IN ({placeholders})",
                        sensitive,
                    )
        finally:
            dst_conn.close()

        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(snap_db, arcname="library.db")
            file_count = 1
            root = store.data_dir.resolve()
            for item in sorted(root.rglob("*")):
                if not item.is_file():
                    continue
                rel = item.relative_to(root).as_posix()
                if (
                    rel == "library.db"
                    or rel in _SQLITE_SIDECARS
                    or rel == SECRET_FILENAME
                    or rel.endswith(".secrets.json")
                ):
                    continue
                zf.write(item, arcname=rel)
                file_count += 1
            backup_manifest = {
                "schema_version": store.schema_version,
                "kind": "lyraforge.backup",
                "file_count": file_count,
            }
            zf.writestr("backup_manifest.json", pretty_json(backup_manifest).encode("utf-8"))
    return buf.getvalue()


def _verify_sqlite_backup(db_path: Path) -> None:
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error as exc:
        raise LyraError(
            ErrorCode.PACKAGE_INVALID, f"backup library.db cannot be opened: {exc}"
        ) from exc
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchall()
        if integrity != [("ok",)]:
            raise LyraError(
                ErrorCode.PACKAGE_INVALID,
                f"SQLite integrity check failed: {integrity}",
            )
        tables = {
            str(r[0])
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        required = {"songs", "sources", "arrangements", "schema_migrations"}
        missing = sorted(required - tables)
        if missing:
            raise LyraError(
                ErrorCode.PACKAGE_INVALID,
                f"backup database missing required tables: {missing}",
            )
        row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        max_ver = int(row[0]) if row and row[0] is not None else 0
        if max_ver <= 0 or max_ver > SCHEMA_VERSION:
            raise LyraError(
                ErrorCode.PACKAGE_INVALID,
                f"incompatible backup database version {max_ver} (supported <= {SCHEMA_VERSION})",
            )
    except sqlite3.DatabaseError as exc:
        raise LyraError(
            ErrorCode.PACKAGE_INVALID, f"corrupt SQLite database in backup: {exc}"
        ) from exc
    finally:
        conn.close()


def _copy_dir_contents(
    src_dir: Path,
    dst_dir: Path,
    *,
    skip_names: frozenset[str] = frozenset(),
) -> int:
    count = 0
    for item in sorted(src_dir.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(src_dir).as_posix()
        if rel in skip_names:
            continue
        dest = resolve_under(dst_dir, rel)
        atomic_write_bytes(dest, item.read_bytes())
        count += 1
    return count


def _unlink_with_retry(path: Path, *, attempts: int = 5, delay_s: float = 0.04) -> None:
    for idx in range(attempts):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            if idx + 1 >= attempts:
                raise
            import time

            time.sleep(delay_s)


def _clear_dir_except(target_root: Path, *, keep_name: str) -> None:
    for item in sorted(target_root.rglob("*"), reverse=True):
        if item.relative_to(target_root).as_posix() == keep_name:
            continue
        if item.is_file():
            _unlink_with_retry(item)
        elif item.is_dir():
            with contextlib.suppress(OSError):
                item.rmdir()


def _verify_and_quiesce_existing_db(existing_db: Path) -> None:
    """Confirm no external reader/writer holds an active lock before DB replacement."""
    if not existing_db.is_file():
        return
    try:
        conn_chk = sqlite3.connect(existing_db, timeout=0.4)
    except sqlite3.Error as exc:
        raise LyraError(
            ErrorCode.LIBRARY_BUSY,
            f"cannot restore library: database file cannot be opened exclusively ({exc})",
        ) from exc
    try:
        conn_chk.execute("PRAGMA busy_timeout = 400")
        conn_chk.execute("BEGIN EXCLUSIVE")
        conn_chk.execute("COMMIT")
        conn_chk.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        row = conn_chk.execute("PRAGMA journal_mode = DELETE").fetchone()
        mode = str(row[0]).lower() if row and row[0] is not None else ""
        if mode != "delete":
            raise LyraError(
                ErrorCode.LIBRARY_BUSY,
                "cannot restore library: SQLite WAL is still held open by another connection",
            )
    except sqlite3.OperationalError as exc:
        raise LyraError(
            ErrorCode.LIBRARY_BUSY,
            f"cannot restore library: database is currently in use ({exc})",
        ) from exc
    finally:
        conn_chk.close()


def restore_backup_zip(
    data_dir: str | Path,
    data: bytes,
    *,
    max_files: int = 5000,
    max_uncompressed_bytes: int = 250_000_000,
) -> dict[str, Any]:
    """Safely stage, verify, and atomically restore a backup archive with rollback."""
    from lyraforge.library.store import LibraryStore
    from lyraforge.secrets import MemorySecretBackend, SecretStore

    entries = _read_validated_zip_entries(
        data, max_files=max_files, max_uncompressed_bytes=max_uncompressed_bytes
    )
    if "library.db" not in entries or "backup_manifest.json" not in entries:
        raise LyraError(
            ErrorCode.PACKAGE_INVALID, "backup archive missing library.db or backup_manifest.json"
        )
    try:
        manifest = json.loads(entries["backup_manifest.json"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LyraError(ErrorCode.PACKAGE_INVALID, f"invalid backup manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("kind") != "lyraforge.backup":
        raise LyraError(ErrorCode.PACKAGE_INVALID, "invalid backup manifest kind")
    manifest_ver = manifest.get("schema_version")
    if not isinstance(manifest_ver, int) or manifest_ver < 1 or manifest_ver > SCHEMA_VERSION:
        raise LyraError(
            ErrorCode.PACKAGE_INVALID,
            f"unsupported backup manifest schema_version {manifest_ver!r}",
        )

    target_root = Path(data_dir).expanduser().resolve()
    target_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="lyraforge-restore-stage-") as stage_tmp:
        stage_root = Path(stage_tmp) / "staged"
        stage_root.mkdir(parents=True, exist_ok=True)
        for rel_path, content in entries.items():
            if (
                rel_path == "backup_manifest.json"
                or rel_path in _SQLITE_SIDECARS
                or rel_path == SECRET_FILENAME
                or rel_path.endswith(".secrets.json")
            ):
                continue
            dest = resolve_under(stage_root, rel_path)
            atomic_write_bytes(dest, content)

        staged_db = stage_root / "library.db"
        _verify_sqlite_backup(staged_db)

        # Verify migrations & store opening in isolated staging dir before touching target_root
        staged_secrets = SecretStore(primary=MemorySecretBackend(), fallback=None)
        with LibraryStore(stage_root, secret_store=staged_secrets) as staged_store:
            staged_store.search_songs("")
            # Switch staged DB cleanly out of WAL mode so library.db is self-contained
            staged_store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            staged_store._conn.execute("PRAGMA journal_mode=DELETE")
        for sidecar in _SQLITE_SIDECARS:
            sc = stage_root / sidecar
            if sc.exists():
                sc.unlink()

        rollback_dir = target_root.parent / f".{target_root.name}.rollback-{uuid.uuid4().hex[:8]}"
        rollback_dir.mkdir(parents=True, exist_ok=True)
        try:
            # Fail fast if any connection holds an active lock/WAL on target library.db
            _verify_and_quiesce_existing_db(target_root / "library.db")
            _copy_dir_contents(
                target_root,
                rollback_dir,
                skip_names=frozenset({SECRET_FILENAME, *_SQLITE_SIDECARS}),
            )

            try:
                _clear_dir_except(target_root, keep_name=SECRET_FILENAME)
                restored = _copy_dir_contents(stage_root, target_root)
                _verify_sqlite_backup(target_root / "library.db")
                with LibraryStore(target_root) as restored_store:
                    songs = restored_store.search_songs("")
                    return {
                        "restored_files": restored,
                        "song_count": len(songs),
                        "schema_version": restored_store.schema_version,
                    }
            except PermissionError as exc:
                _clear_dir_except(target_root, keep_name=SECRET_FILENAME)
                _copy_dir_contents(rollback_dir, target_root)
                raise LyraError(
                    ErrorCode.LIBRARY_BUSY,
                    f"cannot restore library while database files are in use: {exc}",
                ) from exc
            except Exception:
                _clear_dir_except(target_root, keep_name=SECRET_FILENAME)
                _copy_dir_contents(rollback_dir, target_root)
                raise
        finally:
            shutil.rmtree(rollback_dir, ignore_errors=True)
