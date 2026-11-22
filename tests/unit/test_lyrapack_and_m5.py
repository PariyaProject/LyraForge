"""Unit and integration tests for M5 .lyrapack packaging, ZIP security, filters, and backup."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from lyraforge.cli import EXIT_OK, main
from lyraforge.errors import ErrorCode, LyraError
from lyraforge.instruments import load_builtin_profile
from lyraforge.library import (
    LibraryStore,
    export_backup_zip,
    export_lyrapack,
    import_lyrapack,
    restore_backup_zip,
)
from lyraforge.music_core import ArrangeOptions, arrange, build_performance, load_midi_file
from lyraforge.music_core.arranger import Style
from lyraforge.preview import synthesize_performance_to_wav

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "midi"


def test_lyrapack_rights_gate_omits_source_audio_and_roundtrips(
    tmp_path: Path, capsys: Any
) -> None:
    prof = load_builtin_profile()
    score = load_midi_file(FIXTURE_DIR / "c_major_scale.mid")
    perf = build_performance(score, prof, arrange(score, prof))
    wav_file = tmp_path / "audio_source.wav"
    synthesize_performance_to_wav(perf, wav_file)

    src_dir = tmp_path / "src_lib"
    dst_dir = tmp_path / "dst_lib"
    with LibraryStore(src_dir) as store:
        imp = store.import_audio(wav_file, title="Audio Origin", artist="LyraUser", tags=["lyre"])
        store.transcribe_song(imp.song.id, engine_id="builtin-mono")
        arr = store.arrange_song(imp.song.id, options=ArrangeOptions(style=Style.MELODY))

        # Refuses export unless copyright_confirmed=True
        with pytest.raises(LyraError) as perm_exc:
            export_lyrapack(store, arr.id, copyright_confirmed=False)
        assert perm_exc.value.code == ErrorCode.PERMISSION_REQUIRED

        pack_bytes = export_lyrapack(
            store,
            arr.id,
            copyright_confirmed=True,
            license_notice="Self-created audio test fixture.",
        )

    # Verify archive never contains source audio (.wav)
    with zipfile.ZipFile(io.BytesIO(pack_bytes), "r") as zf:
        names = set(zf.namelist())
        assert names == {"manifest.json", "arrangement.mid", "performance.json", "report.json"}
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["includes_source_audio"] is False
        assert manifest["copyright_confirmed"] is True

    # Import into a fresh library and verify song + arrangement round-trip cleanly
    with LibraryStore(dst_dir) as dst_store:
        imported = import_lyrapack(dst_store, pack_bytes)
        assert imported["song"]["title"] == "Audio Origin"
        arr_id = imported["arrangement"]["id"]
        loaded = dst_store.load_arrangement_performance(arr_id)
        assert loaded["arrangement_id"] == arr_id
        assert len(loaded["events"]) == arr.event_count

    # CLI pack export / import + library backup smoke
    pack_path = tmp_path / "cli_out.lyrapack"
    backup_path = tmp_path / "cli_backup.zip"
    assert (
        main([
            "pack",
            "export",
            arr.id,
            "-o",
            str(pack_path),
            "--confirm-rights",
            "--data-dir",
            str(src_dir),
        ])
        == EXIT_OK
    )
    capsys.readouterr()
    assert pack_path.is_file()

    assert (
        main(["library", "backup", "-o", str(backup_path), "--data-dir", str(src_dir)]) == EXIT_OK
    )
    capsys.readouterr()
    assert backup_path.is_file()

    cli_import_dir = tmp_path / "cli_imp_lib"
    assert main(["pack", "import", str(pack_path), "--data-dir", str(cli_import_dir)]) == EXIT_OK
    out = json.loads(capsys.readouterr().out)
    assert out["song"]["title"] == "Audio Origin"


def test_lyrapack_rejects_malicious_zips_and_tampered_audio(tmp_path: Path) -> None:
    with LibraryStore(tmp_path / "sec_lib") as store:
        # 1. Corrupt non-ZIP
        with pytest.raises(LyraError) as bad_zip:
            import_lyrapack(store, b"not-a-zip")
        assert bad_zip.value.code == ErrorCode.PACKAGE_INVALID

        # 2. Path traversal entry
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../evil.txt", b"pwn")
        with pytest.raises(LyraError) as trav:
            import_lyrapack(store, buf.getvalue())
        assert trav.value.code == ErrorCode.PACKAGE_INVALID

        # 3. Symlink entry
        buf_sym = io.BytesIO()
        with zipfile.ZipFile(buf_sym, "w") as zf:
            zi = zipfile.ZipInfo("link.txt")
            zi.create_system = 3
            zi.external_attr = 0o120777 << 16
            zf.writestr(zi, b"/etc/passwd")
        with pytest.raises(LyraError) as sym:
            import_lyrapack(store, buf_sym.getvalue())
        assert sym.value.code == ErrorCode.PACKAGE_INVALID

        # 4. Forbidden bundled raw audio
        buf_aud = io.BytesIO()
        with zipfile.ZipFile(buf_aud, "w") as zf:
            zf.writestr("secret.mp3", b"ID3...")
        with pytest.raises(LyraError) as aud:
            import_lyrapack(store, buf_aud.getvalue())
        assert aud.value.code == ErrorCode.PACKAGE_INVALID

        # 5. Uncompressed byte limit (zip-bomb defense)
        buf_big = io.BytesIO()
        with zipfile.ZipFile(buf_big, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", b"{" + b" " * 1024 + b"}")
        with pytest.raises(LyraError) as bomb:
            import_lyrapack(store, buf_big.getvalue(), max_uncompressed_bytes=128)
        assert bomb.value.code == ErrorCode.LIMIT_EXCEEDED

        # 6. Checksum tampering
        imp = store.import_midi(FIXTURE_DIR / "c_major_scale.mid", title="Hash Check")
        arr = store.arrange_song(imp.song.id)
        good_pack = export_lyrapack(store, arr.id, copyright_confirmed=True)
        tampered = io.BytesIO()
        with (
            zipfile.ZipFile(io.BytesIO(good_pack), "r") as zin,
            zipfile.ZipFile(tampered, "w") as zout,
        ):
            for item in zin.infolist():
                payload = zin.read(item.filename)
                if item.filename == "manifest.json":
                    m = json.loads(payload.decode("utf-8"))
                    m["files"]["performance.json"] = "sha256:" + ("0" * 64)
                    payload = json.dumps(m).encode("utf-8")
                zout.writestr(item.filename, payload)
        with pytest.raises(LyraError) as tamper_exc:
            import_lyrapack(store, tampered.getvalue())
        assert tamper_exc.value.code == ErrorCode.PACKAGE_INVALID


def test_library_tag_favorite_filters_and_backup_restore(tmp_path: Path) -> None:
    lib_dir = tmp_path / "orig"
    restore_dir = tmp_path / "restored"

    mid_a = (FIXTURE_DIR / "c_major_scale.mid").read_bytes()
    mid_b = (FIXTURE_DIR / "chords_type1.mid").read_bytes()
    assert hashlib.sha256(mid_a).hexdigest() != hashlib.sha256(mid_b).hexdigest()

    p_a = tmp_path / "a.mid"
    p_b = tmp_path / "b.mid"
    p_a.write_bytes(mid_a)
    p_b.write_bytes(mid_b)

    with LibraryStore(lib_dir) as store:
        imp_a = store.import_midi(p_a, title="Favorited Waltz", tags=["waltz", "favtag"])
        imp_b = store.import_midi(p_b, title="Other Etude", tags=["etude"])
        arr_a = store.arrange_song(imp_a.song.id)
        store.arrange_song(imp_b.song.id)
        store.set_favorite(arr_a.id, True)

        assert len(store.search_songs(tag="favtag")) == 1
        favs = store.search_songs(favorites_only=True)
        assert [s.id for s in favs] == [imp_a.song.id]

        backup_bytes = export_backup_zip(store)

    res = restore_backup_zip(restore_dir, backup_bytes)
    assert res["song_count"] == 2
    with LibraryStore(restore_dir) as restored:
        restored_favs = restored.search_songs(favorites_only=True)
        assert len(restored_favs) == 1
        assert restored_favs[0].title == "Favorited Waltz"
        assert restored.load_arrangement_performance(arr_a.id)["arrangement_id"] == arr_a.id
