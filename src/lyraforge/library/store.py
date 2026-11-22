"""SQLite-backed cross-platform song library and file store."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.instruments import DEFAULT_PROFILE_ID, load_builtin_profile
from lyraforge.library.paths import (
    atomic_write_bytes,
    atomic_write_text,
    default_data_dir,
    resolve_under,
)
from lyraforge.library.schema import apply_migrations
from lyraforge.media import SUPPORTED_MEDIA_EXTENSIONS, MediaLimits, extract_audio_to_wav
from lyraforge.music_core.arranger import (
    Arrangement,
    ArrangeOptions,
    PerformanceEvent,
    SemitonePolicy,
    Style,
    arrange,
)
from lyraforge.music_core.canonical import pretty_json
from lyraforge.music_core.cleanup import clean_score
from lyraforge.music_core.midi_export import (
    arrangement_to_midi_bytes,
    performance_to_midi_bytes,
    score_to_midi_bytes,
)
from lyraforge.music_core.midi_import import load_midi_file, parse_midi_bytes
from lyraforge.music_core.performance import (
    build_performance,
    build_report,
    validate_performance,
)
from lyraforge.music_core.scoring import compare_arrangements as compare_reports
from lyraforge.music_core.scoring import score_arrangement
from lyraforge.playback.guards import StopToken
from lyraforge.playback.player import PlaybackResult
from lyraforge.preview.synth import DEFAULT_SAMPLE_RATE, synthesize_performance_to_wav
from lyraforge.secrets import SecretStore, default_secret_store, is_sensitive_key
from lyraforge.transcribers import (
    DEFAULT_TRANSCRIBER_ID,
    ProgressCallback,
    TranscribeOptions,
    get_transcriber,
)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class SongSummary:
    id: str
    title: str
    artist: str
    tags: tuple[str, ...]
    arrangement_count: int
    created_at: str
    updated_at: str

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "artist": self.artist,
            "tags": list(self.tags),
            "arrangement_count": self.arrangement_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class SourceRecord:
    id: str
    song_id: str
    kind: str
    original_name: str
    sha256: str
    local_path: str
    size_bytes: int
    imported_at: str

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "song_id": self.song_id,
            "kind": self.kind,
            "original_name": self.original_name,
            "sha256": self.sha256,
            "local_path": self.local_path,
            "size_bytes": self.size_bytes,
            "imported_at": self.imported_at,
        }


@dataclass(frozen=True, slots=True)
class ArrangementRecord:
    id: str
    song_id: str
    source_id: str
    profile_id: str
    profile_hash: str
    style: str
    transpose: int
    speed: float
    playable_ratio: float
    event_count: int
    duration_ms: int
    performance_path: str
    report_path: str
    preview_path: str | None
    is_favorite: bool
    created_at: str
    parent_id: str | None = None
    score: float | None = None
    user_vote: int = 0
    label: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "song_id": self.song_id,
            "source_id": self.source_id,
            "profile_id": self.profile_id,
            "profile_hash": self.profile_hash,
            "style": self.style,
            "transpose": self.transpose,
            "speed": self.speed,
            "playable_ratio": self.playable_ratio,
            "event_count": self.event_count,
            "duration_ms": self.duration_ms,
            "performance_path": self.performance_path,
            "report_path": self.report_path,
            "preview_path": self.preview_path,
            "is_favorite": self.is_favorite,
            "parent_id": self.parent_id,
            "score": self.score,
            "user_vote": self.user_vote,
            "label": self.label,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class TranscriptionRecord:
    id: str
    song_id: str
    source_id: str
    engine: str
    engine_version: str
    raw_midi_path: str
    cleaned_midi_path: str
    status: str
    note_count: int
    created_at: str

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "song_id": self.song_id,
            "source_id": self.source_id,
            "engine": self.engine,
            "engine_version": self.engine_version,
            "raw_midi_path": self.raw_midi_path,
            "cleaned_midi_path": self.cleaned_midi_path,
            "status": self.status,
            "note_count": self.note_count,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class ImportResult:
    song: SongSummary
    source: SourceRecord
    deduplicated: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "song": self.song.to_json(),
            "source": self.source.to_json(),
            "deduplicated": self.deduplicated,
        }


@dataclass(frozen=True, slots=True)
class SongDetail:
    song: SongSummary
    sources: tuple[SourceRecord, ...]
    transcriptions: tuple[TranscriptionRecord, ...]
    arrangements: tuple[ArrangementRecord, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "song": self.song.to_json(),
            "sources": [s.to_json() for s in self.sources],
            "transcriptions": [t.to_json() for t in self.transcriptions],
            "arrangements": [a.to_json() for a in self.arrangements],
        }


class LibraryStore:
    """Manages SQLite index + atomic file artifacts under ``data_dir``."""

    def __init__(
        self,
        data_dir: str | Path | None = None,
        *,
        secret_store: SecretStore | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser() if data_dir is not None else default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "library.db"
        self._secrets = secret_store or default_secret_store(self.data_dir)
        self._conn = sqlite3.connect(self.db_path)
        self.schema_version = apply_migrations(self._conn)
        self._migrate_legacy_plaintext_secrets()

    def _migrate_legacy_plaintext_secrets(self) -> None:
        rows = self._conn.execute("SELECT key, value_json FROM settings").fetchall()
        sensitive_keys: list[str] = []
        for row in rows:
            k = str(row["key"])
            if not is_sensitive_key(k):
                continue
            sensitive_keys.append(k)
            try:
                val = json.loads(row["value_json"])
            except json.JSONDecodeError:
                val = row["value_json"]
            if isinstance(val, str) and val.strip():
                self._secrets.set(k, val.strip())
        if sensitive_keys:
            placeholders = ",".join("?" for _ in sensitive_keys)
            with self._conn:
                self._conn.execute(
                    f"DELETE FROM settings WHERE key IN ({placeholders})",
                    sensitive_keys,
                )

    def __enter__(self) -> LibraryStore:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    def _row_to_source(self, row: sqlite3.Row) -> SourceRecord:
        return SourceRecord(
            id=row["id"],
            song_id=row["song_id"],
            kind=row["kind"],
            original_name=row["original_name"],
            sha256=row["sha256"],
            local_path=row["local_path"],
            size_bytes=int(row["size_bytes"]),
            imported_at=row["imported_at"],
        )

    def _row_to_arrangement(self, row: sqlite3.Row) -> ArrangementRecord:
        return ArrangementRecord(
            id=row["id"],
            song_id=row["song_id"],
            source_id=row["source_id"],
            profile_id=row["profile_id"],
            profile_hash=row["profile_hash"],
            style=row["style"],
            transpose=int(row["transpose"]),
            speed=float(row["speed"]),
            playable_ratio=float(row["playable_ratio"]),
            event_count=int(row["event_count"]),
            duration_ms=int(row["duration_ms"]),
            performance_path=row["performance_path"],
            report_path=row["report_path"],
            preview_path=row["preview_path"],
            is_favorite=bool(row["is_favorite"]),
            parent_id=row["parent_id"],
            score=float(row["score"]) if row["score"] is not None else None,
            user_vote=int(row["user_vote"]),
            label=row["label"],
            created_at=row["created_at"],
        )

    def _row_to_transcription(self, row: sqlite3.Row) -> TranscriptionRecord:
        return TranscriptionRecord(
            id=row["id"],
            song_id=row["song_id"],
            source_id=row["source_id"],
            engine=row["engine"],
            engine_version=row["engine_version"],
            raw_midi_path=row["raw_midi_path"],
            cleaned_midi_path=row["cleaned_midi_path"],
            status=row["status"],
            note_count=int(row["note_count"]),
            created_at=row["created_at"],
        )

    def _row_to_song_summary(self, row: sqlite3.Row) -> SongSummary:
        return SongSummary(
            id=row["id"],
            title=row["title"],
            artist=row["artist"],
            tags=tuple(json.loads(row["tags_json"])),
            arrangement_count=int(row["arrangement_count"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _fetch_song_summary(self, song_id: str) -> SongSummary:
        row = self._conn.execute(
            """
            SELECT s.*, (SELECT COUNT(*) FROM arrangements a WHERE a.song_id = s.id)
                   AS arrangement_count
            FROM songs s WHERE s.id = ?
            """,
            (song_id,),
        ).fetchone()
        if row is None:
            raise LyraError(ErrorCode.SOURCE_UNAVAILABLE, f"song not found: {song_id}")
        return self._row_to_song_summary(row)

    def _import_validated_source(
        self,
        *,
        src_path: Path,
        kind: str,
        sha256: str,
        raw_bytes: bytes,
        ext: str,
        title: str | None,
        artist: str,
        tags: list[str] | tuple[str, ...] | None,
    ) -> ImportResult:
        existing = self._conn.execute(
            "SELECT * FROM sources WHERE sha256 = ?", (sha256,)
        ).fetchone()
        if existing is not None:
            src_rec = self._row_to_source(existing)
            return ImportResult(
                song=self._fetch_song_summary(src_rec.song_id),
                source=src_rec,
                deduplicated=True,
            )

        song_id = str(uuid.uuid4())
        source_id = str(uuid.uuid4())
        clean_title = (title or "").strip() or src_path.stem
        clean_artist = artist.strip()
        clean_tags = sorted({t.strip() for t in (tags or ()) if t.strip()})
        rel_path = f"songs/{song_id}/source/{sha256}{ext}"
        atomic_write_bytes(resolve_under(self.data_dir, rel_path), raw_bytes)

        now = _utc_now_iso()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO songs(id, title, artist, tags_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (song_id, clean_title, clean_artist, json.dumps(clean_tags), now, now),
            )
            self._conn.execute(
                """
                INSERT INTO sources(
                    id, song_id, kind, original_name, sha256, local_path, size_bytes, imported_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    song_id,
                    kind,
                    src_path.name,
                    sha256,
                    rel_path,
                    len(raw_bytes),
                    now,
                ),
            )

        src_row = self._conn.execute(
            "SELECT * FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        assert src_row is not None
        return ImportResult(
            song=self._fetch_song_summary(song_id),
            source=self._row_to_source(src_row),
            deduplicated=False,
        )

    def import_midi(
        self,
        path: str | Path,
        *,
        title: str | None = None,
        artist: str = "",
        tags: list[str] | tuple[str, ...] | None = None,
    ) -> ImportResult:
        """Validate, copy, and index a local MIDI file with SHA256 deduplication."""
        src_path = Path(path)
        score = load_midi_file(src_path)  # validates file size, SMF header, limits before DB writes
        return self._import_validated_source(
            src_path=src_path,
            kind="midi",
            sha256=score.source_sha256,
            raw_bytes=src_path.read_bytes(),
            ext=".mid",
            title=title,
            artist=artist,
            tags=tags,
        )

    def import_audio(
        self,
        path: str | Path,
        *,
        title: str | None = None,
        artist: str = "",
        tags: list[str] | tuple[str, ...] | None = None,
        limits: MediaLimits | None = None,
    ) -> ImportResult:
        """Validate, copy, and index a local audio/video file with SHA256 deduplication."""
        src_path = Path(path)
        limits = limits or MediaLimits()
        if not src_path.is_file():
            raise LyraError(ErrorCode.SOURCE_UNAVAILABLE, f"media file not found: {src_path.name}")
        ext = src_path.suffix.lower()
        if ext not in SUPPORTED_MEDIA_EXTENSIONS:
            raise LyraError(
                ErrorCode.MEDIA_UNSUPPORTED,
                f"unsupported media extension {ext!r}",
                {"supported": sorted(SUPPORTED_MEDIA_EXTENSIONS)},
            )
        size = src_path.stat().st_size
        if size > limits.max_file_bytes:
            raise LyraError(
                ErrorCode.LIMIT_EXCEEDED,
                f"media file exceeds size limit ({size} bytes > {limits.max_file_bytes})",
            )
        raw_bytes = src_path.read_bytes()
        sha256 = hashlib.sha256(raw_bytes).hexdigest()
        return self._import_validated_source(
            src_path=src_path,
            kind="audio",
            sha256=sha256,
            raw_bytes=raw_bytes,
            ext=ext,
            title=title,
            artist=artist,
            tags=tags,
        )

    def search_songs(
        self,
        query: str = "",
        *,
        tag: str | None = None,
        favorites_only: bool = False,
    ) -> list[SongSummary]:
        """List or search songs by title, artist, tag, or favorite status."""
        conditions: list[str] = []
        params: list[Any] = []
        q = query.strip()
        if q:
            like = f"%{q}%"
            conditions.append(
                "(s.title LIKE ? COLLATE NOCASE OR s.artist LIKE ? COLLATE NOCASE "
                "OR s.tags_json LIKE ? COLLATE NOCASE)"
            )
            params.extend((like, like, like))
        t = (tag or "").strip()
        if t:
            conditions.append("s.tags_json LIKE ? COLLATE NOCASE")
            params.append(f"%{t}%")
        if favorites_only:
            conditions.append(
                "EXISTS (SELECT 1 FROM arrangements a WHERE a.song_id = s.id AND a.is_favorite = 1)"
            )
        where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self._conn.execute(
            f"""
            SELECT s.*, (SELECT COUNT(*) FROM arrangements a WHERE a.song_id = s.id)
                   AS arrangement_count
            FROM songs s
            {where_sql}
            ORDER BY s.updated_at DESC, s.title ASC
            """,
            params,
        ).fetchall()
        return [self._row_to_song_summary(r) for r in rows]

    def get_song(self, song_id: str) -> SongDetail:
        song = self._fetch_song_summary(song_id)
        src_rows = self._conn.execute(
            "SELECT * FROM sources WHERE song_id = ? ORDER BY imported_at ASC", (song_id,)
        ).fetchall()
        tr_rows = self._conn.execute(
            "SELECT * FROM transcriptions WHERE song_id = ? ORDER BY created_at DESC", (song_id,)
        ).fetchall()
        arr_rows = self._conn.execute(
            "SELECT * FROM arrangements WHERE song_id = ? ORDER BY created_at DESC", (song_id,)
        ).fetchall()
        return SongDetail(
            song=song,
            sources=tuple(self._row_to_source(r) for r in src_rows),
            transcriptions=tuple(self._row_to_transcription(r) for r in tr_rows),
            arrangements=tuple(self._row_to_arrangement(r) for r in arr_rows),
        )

    def transcribe_song(
        self,
        song_id: str,
        *,
        engine_id: str = DEFAULT_TRANSCRIBER_ID,
        options: TranscribeOptions | None = None,
        on_progress: ProgressCallback | None = None,
        stop_token: StopToken | None = None,
    ) -> TranscriptionRecord:
        """Extract audio, run the chosen transcriber, and persist raw/cleaned MIDI."""
        detail = self.get_song(song_id)
        audio_sources = [s for s in detail.sources if s.kind == "audio"]
        if not audio_sources:
            raise LyraError(
                ErrorCode.SOURCE_UNAVAILABLE, f"song {song_id} has no audio/video source"
            )
        source = audio_sources[0]
        src_audio = resolve_under(self.data_dir, source.local_path)
        transcriber = get_transcriber(engine_id)
        opts = options or TranscribeOptions()

        with tempfile.TemporaryDirectory(prefix="lyraforge-tr-") as tmpdir:
            wav_path = Path(tmpdir) / "extracted.wav"
            extract_audio_to_wav(src_audio, wav_path, stop_token=stop_token)
            res = transcriber.transcribe(
                wav_path,
                options=opts,
                on_progress=on_progress,
                stop_token=stop_token,
            )

        raw_score = parse_midi_bytes(res.midi_bytes)
        cleaned_score, _ = clean_score(raw_score)
        cleaned_bytes = score_to_midi_bytes(cleaned_score)

        tr_id = str(uuid.uuid4())
        rel_raw = f"songs/{song_id}/midis/{tr_id}/raw.mid"
        rel_cleaned = f"songs/{song_id}/midis/{tr_id}/cleaned.mid"
        atomic_write_bytes(resolve_under(self.data_dir, rel_raw), res.midi_bytes)
        atomic_write_bytes(resolve_under(self.data_dir, rel_cleaned), cleaned_bytes)

        now = _utc_now_iso()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO transcriptions(
                    id, song_id, source_id, engine, engine_version, options_json,
                    raw_midi_path, cleaned_midi_path, status, note_count, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tr_id,
                    song_id,
                    source.id,
                    res.engine_id,
                    res.engine_version,
                    json.dumps(asdict(opts), sort_keys=True),
                    rel_raw,
                    rel_cleaned,
                    "completed",
                    len(cleaned_score.notes),
                    now,
                ),
            )
            self._conn.execute("UPDATE songs SET updated_at = ? WHERE id = ?", (now, song_id))
        row = self._conn.execute("SELECT * FROM transcriptions WHERE id = ?", (tr_id,)).fetchone()
        assert row is not None
        return self._row_to_transcription(row)

    def get_arrangement(self, arrangement_id: str) -> ArrangementRecord:
        row = self._conn.execute(
            "SELECT * FROM arrangements WHERE id = ?", (arrangement_id,)
        ).fetchone()
        if row is None:
            raise LyraError(
                ErrorCode.SOURCE_UNAVAILABLE, f"arrangement not found: {arrangement_id}"
            )
        return self._row_to_arrangement(row)

    def load_arrangement_performance(self, arrangement_id: str) -> dict[str, Any]:
        rec = self.get_arrangement(arrangement_id)
        perf_path = resolve_under(self.data_dir, rec.performance_path)
        if not perf_path.is_file():
            raise LyraError(
                ErrorCode.SOURCE_UNAVAILABLE,
                f"performance artifact missing for arrangement {arrangement_id}",
            )
        try:
            doc = json.loads(perf_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LyraError(
                ErrorCode.PERFORMANCE_INVALID,
                f"stored performance is not valid JSON: {exc}",
            ) from exc
        validate_performance(doc)
        return doc

    def load_arrangement_report(self, arrangement_id: str) -> dict[str, Any]:
        rec = self.get_arrangement(arrangement_id)
        rep_path = resolve_under(self.data_dir, rec.report_path)
        if not rep_path.is_file():
            raise LyraError(
                ErrorCode.SOURCE_UNAVAILABLE,
                f"report artifact missing for arrangement {arrangement_id}",
            )
        try:
            doc = json.loads(rep_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LyraError(
                ErrorCode.PERFORMANCE_INVALID,
                f"stored report is not valid JSON: {exc}",
            ) from exc
        if not isinstance(doc, dict):
            raise LyraError(ErrorCode.PERFORMANCE_INVALID, "stored report is not a JSON object")
        return doc

    def arrange_song(
        self,
        song_id: str,
        *,
        profile_id: str = DEFAULT_PROFILE_ID,
        options: ArrangeOptions | None = None,
        parent_id: str | None = None,
        label: str | None = None,
    ) -> ArrangementRecord:
        """Create (or return existing identical) arrangement version for a song."""
        detail = self.get_song(song_id)
        if not detail.sources:
            raise LyraError(ErrorCode.SOURCE_UNAVAILABLE, f"song {song_id} has no sources")
        midi_sources = [s for s in detail.sources if s.kind == "midi"]
        if midi_sources:
            source = midi_sources[0]
            src_file = resolve_under(self.data_dir, source.local_path)
        elif detail.transcriptions:
            source = detail.sources[0]
            src_file = resolve_under(self.data_dir, detail.transcriptions[0].cleaned_midi_path)
        else:
            raise LyraError(
                ErrorCode.SOURCE_UNAVAILABLE,
                f"song {song_id} has no MIDI source or completed transcription",
            )
        score = load_midi_file(src_file)
        profile = load_builtin_profile(profile_id)
        arr = arrange(score, profile, options)
        perf = build_performance(score, profile, arr)
        validate_performance(perf, profile)
        report = build_report(score, profile, arr)

        arr_id = str(perf["arrangement_id"])
        existing = self._conn.execute(
            "SELECT * FROM arrangements WHERE id = ?", (arr_id,)
        ).fetchone()
        if existing is not None:
            return self._row_to_arrangement(existing)

        quality_doc = report.get("quality") or {}
        quality_score = (
            float(quality_doc["overall_score"]) if "overall_score" in quality_doc else None
        )
        rel_perf = f"songs/{song_id}/performance/{arr_id}.json"
        rel_rep = f"songs/{song_id}/reports/{arr_id}.json"
        rel_arr_mid = f"songs/{song_id}/midis/{arr_id}/arrangement.mid"
        atomic_write_text(resolve_under(self.data_dir, rel_perf), pretty_json(perf))
        atomic_write_text(resolve_under(self.data_dir, rel_rep), pretty_json(report))
        atomic_write_bytes(
            resolve_under(self.data_dir, rel_arr_mid),
            arrangement_to_midi_bytes(arr),
        )

        now = _utc_now_iso()
        opts = arr.options
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO arrangements(
                    id, song_id, source_id, profile_id, profile_hash, style, transpose, speed,
                    playable_ratio, event_count, duration_ms, performance_path, report_path,
                    preview_path, is_favorite, parent_id, score, user_vote, label, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 0, ?, ?)
                """,
                (
                    arr_id,
                    song_id,
                    source.id,
                    profile.id,
                    profile.hash,
                    str(opts.style),
                    arr.transpose,
                    float(opts.speed),
                    float(arr.stats["playable_ratio"]),
                    len(arr.events),
                    int(arr.stats["duration_ms"]),
                    rel_perf,
                    rel_rep,
                    None,
                    parent_id,
                    quality_score,
                    label,
                    now,
                ),
            )
            self._conn.execute(
                "UPDATE songs SET updated_at = ? WHERE id = ?", (now, song_id)
            )
        return self.get_arrangement(arr_id)

    def save_edited_arrangement(
        self,
        arrangement_id: str,
        events: list[dict[str, Any]],
        *,
        label: str | None = None,
    ) -> ArrangementRecord:
        """Persist user-edited Piano Roll events as a child arrangement version."""
        if not isinstance(events, list) or not events:
            raise LyraError(
                ErrorCode.INVALID_ARGUMENT, "edited arrangement must contain at least one event"
            )
        parent = self.get_arrangement(arrangement_id)
        parent_perf = self.load_arrangement_performance(arrangement_id)
        parent_report = self.load_arrangement_report(arrangement_id)
        profile = load_builtin_profile(parent.profile_id)

        normalized: list[dict[str, Any]] = []
        valid_adj = {"octave_folded", "semitone_substituted"}
        for idx, raw in enumerate(events):
            if not isinstance(raw, dict):
                raise LyraError(ErrorCode.INVALID_ARGUMENT, f"event[{idx}] must be an object")
            key_id = str(raw.get("key_id", ""))
            key_def = profile.key_by_id(key_id)
            if key_def is None:
                raise LyraError(
                    ErrorCode.INVALID_ARGUMENT,
                    f"unknown key_id {key_id!r} for profile {profile.id}",
                )
            at_ms = int(raw.get("at_ms", -1))
            if at_ms < 0:
                raise LyraError(ErrorCode.INVALID_ARGUMENT, f"event[{idx}].at_ms must be >= 0")
            hold_ms = int(raw.get("hold_ms", profile.timing.default_key_hold_ms))
            hold_ms = max(1, min(60_000, hold_ms))
            raw_adj = [str(a) for a in raw.get("adjustments", []) if str(a) in valid_adj]
            dedup_adj = list(dict.fromkeys(raw_adj))
            normalized.append({
                "at_ms": at_ms,
                "key_id": key_id,
                "action": "tap",
                "hold_ms": hold_ms,
                "source_pitch": max(0, min(127, int(raw.get("source_pitch", key_def.pitch)))),
                "mapped_pitch": key_def.pitch,
                "source_track": max(0, int(raw.get("source_track", 0))),
                "source_channel": max(0, min(15, int(raw.get("source_channel", 0)))),
                "velocity": max(1, min(127, int(raw.get("velocity", 96)))),
                "adjustments": dedup_adj,
            })

        normalized.sort(key=lambda e: (e["at_ms"], e["mapped_pitch"], e["key_id"]))
        duration_ms = max(e["at_ms"] + e["hold_ms"] for e in normalized)
        arr_id = str(uuid.uuid4())
        perf = json.loads(json.dumps(parent_perf))
        perf["arrangement_id"] = arr_id
        perf["events"] = normalized
        perf["duration_ms"] = duration_ms
        validate_performance(perf, profile)

        times = [int(e["at_ms"]) for e in normalized]
        best_kps = lo = 0
        for hi, t in enumerate(times):
            while t - times[lo] >= 1000:
                lo += 1
            best_kps = max(best_kps, hi - lo + 1)

        report = json.loads(json.dumps(parent_report))
        stats = dict(report.get("stats") or {})
        stats["emitted_events"] = len(normalized)
        stats["duration_ms"] = duration_ms
        stats["max_keys_per_second"] = best_kps
        stats["direct"] = sum(1 for e in normalized if not e["adjustments"])
        stats["octave_folded"] = sum(
            1 for e in normalized if "octave_folded" in e["adjustments"]
        )
        stats["semitone_substituted"] = sum(
            1 for e in normalized if "semitone_substituted" in e["adjustments"]
        )
        considered = int(stats.get("considered_notes", len(normalized)) or len(normalized))
        stats["playable_ratio"] = round(min(1.0, len(normalized) / max(1, considered)), 4)
        report["stats"] = stats
        report["edited_from"] = arrangement_id

        quality_score = parent.score
        detail = self.get_song(parent.song_id)
        src_file: Path | None = None
        for src in detail.sources:
            if src.id == parent.source_id and src.kind == "midi":
                src_file = resolve_under(self.data_dir, src.local_path)
                break
        if src_file is None and detail.transcriptions:
            src_file = resolve_under(self.data_dir, detail.transcriptions[0].cleaned_midi_path)
        if src_file is not None and src_file.is_file():
            score_doc = load_midi_file(src_file)
            tr = parent_perf.get("transform") or {}
            inc = tr.get("include_tracks")
            opts = ArrangeOptions(
                style=Style(parent.style),
                transpose=parent.transpose,
                semitone_policy=SemitonePolicy(str(tr.get("semitone_policy", "nearest"))),
                max_chord_keys=tr.get("max_chord_keys"),
                chord_window_ms=int(tr.get("chord_window_ms", 20)),
                speed=parent.speed,
                include_tracks=tuple(int(x) for x in inc) if inc is not None else None,
                exclude_percussion=bool(tr.get("exclude_percussion", True)),
                arpeggiate_ms=int(tr.get("arpeggiate_ms", 0)),
                prefer_melody_track=bool(tr.get("prefer_melody_track", True)),
            )
            perf_events = tuple(
                PerformanceEvent(
                    at_ms=e["at_ms"],
                    key_id=e["key_id"],
                    hold_ms=e["hold_ms"],
                    source_pitch=e["source_pitch"],
                    mapped_pitch=e["mapped_pitch"],
                    source_track=e["source_track"],
                    source_channel=e["source_channel"],
                    velocity=e["velocity"],
                    adjustments=tuple(e["adjustments"]),
                )
                for e in normalized
            )
            edited_arr = Arrangement(
                events=perf_events,
                dropped=(),
                transpose=parent.transpose,
                transpose_candidates=(),
                max_chord_keys=opts.effective_max_chord_keys(profile),
                options=opts,
                stats=stats,
            )
            quality_json = score_arrangement(score_doc, edited_arr).to_json()
            report["quality"] = quality_json
            quality_score = float(quality_json["overall_score"])

        rel_perf = f"songs/{parent.song_id}/performance/{arr_id}.json"
        rel_rep = f"songs/{parent.song_id}/reports/{arr_id}.json"
        rel_mid = f"songs/{parent.song_id}/midis/{arr_id}/arrangement.mid"
        atomic_write_text(resolve_under(self.data_dir, rel_perf), pretty_json(perf))
        atomic_write_text(resolve_under(self.data_dir, rel_rep), pretty_json(report))
        atomic_write_bytes(resolve_under(self.data_dir, rel_mid), performance_to_midi_bytes(perf))

        now = _utc_now_iso()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO arrangements(
                    id, song_id, source_id, profile_id, profile_hash, style, transpose, speed,
                    playable_ratio, event_count, duration_ms, performance_path, report_path,
                    preview_path, is_favorite, parent_id, score, user_vote, label, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 0, ?, ?)
                """,
                (
                    arr_id,
                    parent.song_id,
                    parent.source_id,
                    parent.profile_id,
                    parent.profile_hash,
                    parent.style,
                    parent.transpose,
                    parent.speed,
                    float(stats["playable_ratio"]),
                    len(normalized),
                    duration_ms,
                    rel_perf,
                    rel_rep,
                    None,
                    arrangement_id,
                    quality_score,
                    label or "手动编辑",
                    now,
                ),
            )
            self._conn.execute(
                "UPDATE songs SET updated_at = ? WHERE id = ?", (now, parent.song_id)
            )
        return self.get_arrangement(arr_id)

    def set_favorite(self, arrangement_id: str, is_favorite: bool) -> ArrangementRecord:
        self.get_arrangement(arrangement_id)
        with self._conn:
            self._conn.execute(
                "UPDATE arrangements SET is_favorite = ? WHERE id = ?",
                (1 if is_favorite else 0, arrangement_id),
            )
        return self.get_arrangement(arrangement_id)

    def set_user_vote(self, arrangement_id: str, vote: int) -> ArrangementRecord:
        if vote not in (-1, 0, 1):
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "user vote must be -1, 0, or 1")
        self.get_arrangement(arrangement_id)
        with self._conn:
            self._conn.execute(
                "UPDATE arrangements SET user_vote = ? WHERE id = ?",
                (vote, arrangement_id),
            )
        return self.get_arrangement(arrangement_id)

    def compare_arrangements(
        self,
        arrangement_a_id: str,
        arrangement_b_id: str,
    ) -> dict[str, Any]:
        rec_a = self.get_arrangement(arrangement_a_id)
        rec_b = self.get_arrangement(arrangement_b_id)
        rep_a = self.load_arrangement_report(arrangement_a_id)
        rep_b = self.load_arrangement_report(arrangement_b_id)
        diff = compare_reports(rep_a, rep_b, arrangement_a_id, arrangement_b_id)
        diff["a"] = rec_a.to_json()
        diff["b"] = rec_b.to_json()
        return diff

    def import_packaged_arrangement(
        self,
        *,
        song_id: str,
        source_id: str,
        perf: dict[str, Any],
        report: dict[str, Any],
        midi_bytes: bytes,
        label: str | None = None,
    ) -> ArrangementRecord:
        """Store a validated arrangement imported from a ``.lyrapack`` archive."""
        profile = load_builtin_profile(str(perf.get("instrument_profile_id", "")))
        perf_copy = json.loads(json.dumps(perf))
        arr_id = str(uuid.uuid4())
        perf_copy["song_id"] = song_id
        perf_copy["arrangement_id"] = arr_id
        validate_performance(perf_copy, profile)

        tr = perf_copy.get("transform") or {}
        stats = dict(report.get("stats") or {})
        quality = report.get("quality") or {}
        score_val = float(quality["overall_score"]) if "overall_score" in quality else None
        event_count = len(perf_copy["events"])
        duration_ms = int(perf_copy["duration_ms"])
        playable_ratio = float(stats.get("playable_ratio", 1.0))

        rel_perf = f"songs/{song_id}/performance/{arr_id}.json"
        rel_rep = f"songs/{song_id}/reports/{arr_id}.json"
        rel_mid = f"songs/{song_id}/midis/{arr_id}/arrangement.mid"
        atomic_write_text(resolve_under(self.data_dir, rel_perf), pretty_json(perf_copy))
        atomic_write_text(resolve_under(self.data_dir, rel_rep), pretty_json(report))
        atomic_write_bytes(resolve_under(self.data_dir, rel_mid), midi_bytes)

        now = _utc_now_iso()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO arrangements(
                    id, song_id, source_id, profile_id, profile_hash, style, transpose, speed,
                    playable_ratio, event_count, duration_ms, performance_path, report_path,
                    preview_path, is_favorite, parent_id, score, user_vote, label, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, 0, ?, ?)
                """,
                (
                    arr_id,
                    song_id,
                    source_id,
                    profile.id,
                    profile.hash,
                    str(tr.get("strategy", "balanced")),
                    int(tr.get("transpose_semitones", 0)),
                    float(tr.get("speed", 1.0)),
                    playable_ratio,
                    event_count,
                    duration_ms,
                    rel_perf,
                    rel_rep,
                    None,
                    score_val,
                    label or "导入分享包",
                    now,
                ),
            )
            self._conn.execute("UPDATE songs SET updated_at = ? WHERE id = ?", (now, song_id))
        return self.get_arrangement(arr_id)

    def render_preview(
        self,
        arrangement_id: str,
        *,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ) -> Path:
        """Synthesize an offline WAV preview for a stored arrangement."""
        rec = self.get_arrangement(arrangement_id)
        doc = self.load_arrangement_performance(arrangement_id)
        rel_wav = f"songs/{rec.song_id}/previews/{rec.id}.wav"
        wav_path = resolve_under(self.data_dir, rel_wav)
        synthesize_performance_to_wav(doc, wav_path, sample_rate=sample_rate)
        now = _utc_now_iso()
        with self._conn:
            self._conn.execute(
                "UPDATE arrangements SET preview_path = ? WHERE id = ?",
                (rel_wav, rec.id),
            )
            self._conn.execute(
                "UPDATE songs SET updated_at = ? WHERE id = ?", (now, rec.song_id)
            )
        return wav_path

    def record_playback_session(
        self,
        arrangement_id: str,
        mode: str,
        result: PlaybackResult,
    ) -> str:
        """Persist a playback (or dry-run) execution summary."""
        self.get_arrangement(arrangement_id)  # ensures FK target exists
        session_id = str(uuid.uuid4())
        elapsed_ms = round((result.ended_at_us - result.started_at_us) / 1000.0, 3)
        err_msg = result.error or result.release_error or result.stop_reason or ""
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO playback_sessions(
                    id, arrangement_id, mode, started_at, elapsed_ms, ended_state,
                    actions_sent, error_summary
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    arrangement_id,
                    mode,
                    _utc_now_iso(),
                    elapsed_ms,
                    str(result.state),
                    result.actions_sent,
                    err_msg,
                ),
            )
        return session_id

    def export_arrangement(
        self,
        arrangement_id: str,
        fmt: Literal["midi", "json"],
    ) -> bytes:
        """Export an arrangement as Standard MIDI (``midi``) or ``performance.json`` (``json``)."""
        rec = self.get_arrangement(arrangement_id)
        if fmt == "json":
            doc = self.load_arrangement_performance(arrangement_id)
            return pretty_json(doc).encode("utf-8")
        if fmt == "midi":
            arr_mid = resolve_under(
                self.data_dir, f"songs/{rec.song_id}/midis/{rec.id}/arrangement.mid"
            )
            if arr_mid.is_file():
                return arr_mid.read_bytes()
            doc = self.load_arrangement_performance(arrangement_id)
            return performance_to_midi_bytes(doc)
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            f"unsupported export format {fmt!r}; expected 'midi' or 'json'",
        )

    def get_settings(self) -> dict[str, Any]:
        rows = self._conn.execute(
            "SELECT key, value_json FROM settings ORDER BY key ASC"
        ).fetchall()
        out = {
            str(r["key"]): json.loads(r["value_json"])
            for r in rows
            if not is_sensitive_key(str(r["key"]))
        }
        out["llm_api_key_configured"] = self._secrets.has("llm_api_key")
        return out

    def get_secret(self, key: str) -> str | None:
        clean_key = key.strip()
        if not clean_key:
            return None
        return self._secrets.get(clean_key)

    def set_setting(self, key: str, value: Any) -> None:
        clean_key = key.strip()
        if not clean_key:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "setting key must not be empty")
        if is_sensitive_key(clean_key):
            secret_str = "" if value is None else str(value).strip()
            if secret_str:
                self._secrets.set(clean_key, secret_str)
            else:
                self._secrets.delete(clean_key)
            with self._conn:
                self._conn.execute("DELETE FROM settings WHERE key = ?", (clean_key,))
            return
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO settings(key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (clean_key, json.dumps(value, ensure_ascii=False), _utc_now_iso()),
            )
