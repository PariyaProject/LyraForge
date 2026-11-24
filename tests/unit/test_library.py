"""Unit tests for lyraforge.library."""

from __future__ import annotations

import shutil
import sqlite3
import wave
from pathlib import Path

import pytest

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.library import (
    DATA_DIR_ENV,
    SCHEMA_VERSION,
    LibraryStore,
    default_data_dir,
    resolve_under,
)
from lyraforge.music_core import (
    ArrangeOptions,
    arrange,
    build_performance,
    load_midi_file,
)
from lyraforge.music_core.arranger import Style
from lyraforge.playback import DryRunDriver, Player, VirtualClock
from lyraforge.preview import synthesize_performance_to_wav

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "midi"


def test_default_data_dir_respects_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "custom_lf"))
    assert default_data_dir() == tmp_path / "custom_lf"

    monkeypatch.delenv(DATA_DIR_ENV, raising=False)
    auto = default_data_dir()
    assert auto.name == "LyraForge"


def test_resolve_under_blocks_traversal(tmp_path: Path) -> None:
    ok = resolve_under(tmp_path, "songs/abc/perf.json")
    assert ok == tmp_path.resolve() / "songs" / "abc" / "perf.json"

    for bad in ("", "../escape.txt", "songs/../../etc/passwd", str(tmp_path / "abs.txt")):
        with pytest.raises(LyraError) as exc:
            resolve_under(tmp_path, bad)
        assert exc.value.code == ErrorCode.PACKAGE_INVALID


def test_import_dedup_and_broken_midi_rejected_cleanly(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    with LibraryStore(data_dir) as store:
        assert store.schema_version == SCHEMA_VERSION
        res1 = store.import_midi(
            FIXTURE_DIR / "c_major_scale.mid",
            title="C Major Test",
            artist="LyraForge",
            tags=["scale", "beginner"],
        )
        assert not res1.deduplicated
        assert res1.song.title == "C Major Test"
        assert res1.song.tags == ("beginner", "scale")

        # Re-importing identical MIDI bytes deduplicates cleanly
        copy_path = tmp_path / "same_song_renamed.mid"
        shutil.copyfile(FIXTURE_DIR / "c_major_scale.mid", copy_path)
        res2 = store.import_midi(copy_path, title="Ignored Duplicate")
        assert res2.deduplicated
        assert res2.song.id == res1.song.id
        assert res2.source.id == res1.source.id

        # Broken MIDI fails before modifying DB or storing files
        with pytest.raises(LyraError) as exc:
            store.import_midi(FIXTURE_DIR / "broken" / "not_midi.mid")
        assert exc.value.code == ErrorCode.MEDIA_DECODE_FAILED
        assert len(store.search_songs()) == 1


def test_multi_version_arrangements_restart_persistence_and_deleted_original(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    ext_midi = tmp_path / "temp_external.mid"
    shutil.copyfile(FIXTURE_DIR / "chords_type1.mid", ext_midi)

    with LibraryStore(data_dir) as store:
        imp = store.import_midi(ext_midi, title="Chords Demo", artist="UnitTest", tags=["triad"])
        song_id = imp.song.id

        # Delete external original file right after import; library keeps its own copy
        ext_midi.unlink()

        arr_mel = store.arrange_song(song_id, options=ArrangeOptions(style=Style.MELODY))
        arr_bal = store.arrange_song(song_id, options=ArrangeOptions(style=Style.BALANCED))
        assert arr_mel.id != arr_bal.id
        assert arr_mel.style == "melody"
        assert arr_bal.style == "balanced"

        # Repeating identical options returns existing arrangement id without overwriting
        arr_bal_again = store.arrange_song(song_id, options=ArrangeOptions(style=Style.BALANCED))
        assert arr_bal_again.id == arr_bal.id

        wav_path = store.render_preview(arr_bal.id)
        assert wav_path.is_file()
        with wave.open(str(wav_path), "rb") as wf:
            assert wf.getnframes() > 0

    # Simulate full app restart by opening a brand new LibraryStore instance
    with LibraryStore(data_dir) as store2:
        found = store2.search_songs("triad")
        assert len(found) == 1
        assert found[0].id == song_id
        assert found[0].arrangement_count == 2

        detail = store2.get_song(song_id)
        assert len(detail.sources) == 1
        assert len(detail.arrangements) == 2

        perf_doc = store2.load_arrangement_performance(arr_bal.id)
        clock = VirtualClock()
        driver = DryRunDriver(clock)
        res = Player(driver, clock).play(perf_doc["events"])
        session_id = store2.record_playback_session(arr_bal.id, "dry-run:virtual", res)
        assert session_id

    # Verify SQLite WAL persisted playback_sessions row
    conn = sqlite3.connect(data_dir / "library.db")
    try:
        cnt = conn.execute("SELECT COUNT(*) FROM playback_sessions").fetchone()[0]
        assert cnt == 1
    finally:
        conn.close()


def test_missing_song_or_arrangement_raises_source_unavailable(tmp_path: Path) -> None:
    with LibraryStore(tmp_path / "data") as store:
        with pytest.raises(LyraError) as exc1:
            store.get_song("nonexistent-song")
        assert exc1.value.code == ErrorCode.SOURCE_UNAVAILABLE

        with pytest.raises(LyraError) as exc2:
            store.get_arrangement("nonexistent-arr")
        assert exc2.value.code == ErrorCode.SOURCE_UNAVAILABLE


def test_v1_to_v2_migration_and_audio_transcribe_arrange_flow(tmp_path: Path) -> None:
    from lyraforge.instruments import load_builtin_profile
    from lyraforge.library.schema import _MIGRATION_V1

    data_dir = tmp_path / "migrated_data"
    data_dir.mkdir()
    conn = sqlite3.connect(data_dir / "library.db")
    try:
        conn.executescript(_MIGRATION_V1)
        conn.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO schema_migrations VALUES (1, '2026-11-22T00:00:00Z')")
        conn.commit()
    finally:
        conn.close()

    prof = load_builtin_profile()
    score = load_midi_file(FIXTURE_DIR / "c_major_scale.mid")
    perf = build_performance(score, prof, arrange(score, prof))
    wav_src = tmp_path / "solo.wav"
    synthesize_performance_to_wav(perf, wav_src)

    with LibraryStore(data_dir) as store:
        assert store.schema_version == SCHEMA_VERSION
        imp = store.import_audio(wav_src, title="Solo WAV", artist="M2Test")
        assert imp.source.kind == "audio"
        assert not imp.deduplicated

        # Arranging before transcribing raises clear SOURCE_UNAVAILABLE
        with pytest.raises(LyraError) as exc_untranscribed:
            store.arrange_song(imp.song.id)
        assert exc_untranscribed.value.code == ErrorCode.SOURCE_UNAVAILABLE

        tr = store.transcribe_song(imp.song.id, engine_id="builtin-mono")
        assert tr.status == "completed"
        assert tr.note_count >= 6
        assert (data_dir / tr.raw_midi_path).is_file()
        assert (data_dir / tr.cleaned_midi_path).is_file()

        arr_rec = store.arrange_song(imp.song.id, options=ArrangeOptions(style=Style.MELODY))
        assert arr_rec.event_count >= 6

        detail = store.get_song(imp.song.id)
        assert len(detail.transcriptions) == 1
        assert len(detail.arrangements) == 1

        arr_mid_bytes = store.export_arrangement(arr_rec.id, "midi")
        arr_json_bytes = store.export_arrangement(arr_rec.id, "json")
        assert arr_mid_bytes.startswith(b"MThd")
        assert b"lyraforge.performance" in arr_json_bytes

        store.set_setting("default_style", "melody")
        store.set_setting("windows_allowed_titles", "Genshin Impact, 原神")

    with LibraryStore(data_dir) as store2:
        settings = store2.get_settings()
        assert settings["default_style"] == "melody"
        assert settings["windows_allowed_titles"] == "Genshin Impact, 原神"

        # Deleting parent clears child parent_id & removes generated artifacts
        detail2 = store2.get_song(imp.song.id)
        orig_id = detail2.arrangements[0].id
        perf = store2.load_arrangement_performance(orig_id)
        edited = store2.save_edited_arrangement(orig_id, perf["events"][:2], label="Trimmed")
        orig_perf_path = data_dir / detail2.arrangements[0].performance_path
        orig_rep_path = data_dir / detail2.arrangements[0].report_path
        orig_mid_dir = data_dir / f"songs/{imp.song.id}/midis/{orig_id}"
        assert orig_perf_path.is_file()
        assert orig_mid_dir.is_dir()

        del_res = store2.delete_arrangement(orig_id)
        assert del_res == {"deleted": True, "arrangement_id": orig_id, "song_id": imp.song.id}
        assert not orig_perf_path.exists()
        assert not orig_rep_path.exists()
        assert not orig_mid_dir.exists()

        remaining = store2.get_song(imp.song.id).arrangements
        assert [a.id for a in remaining] == [edited.id]
        assert remaining[0].parent_id is None

        with pytest.raises(LyraError) as exc_missing:
            store2.delete_arrangement(orig_id)
        assert exc_missing.value.code == ErrorCode.SOURCE_UNAVAILABLE
