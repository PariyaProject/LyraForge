"""Security & secret hygiene tests for FIX-002 (credentials) and FIX-005 (SSRF/DNS pinning)."""

from __future__ import annotations

import io
import json
import os
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lyraforge.agent.llm import OpenAICompatibleLLMProvider
from lyraforge.api import SESSION_TOKEN_HEADER, create_app
from lyraforge.errors import ErrorCode, LyraError
from lyraforge.library import LibraryStore, export_backup_zip, export_lyrapack
from lyraforge.secrets import (
    SECRET_FILENAME,
    FileRestrictedSecretBackend,
    MacOSKeychainBackend,
    MemorySecretBackend,
    SecretStore,
    WindowsCredentialBackend,
    is_sensitive_key,
    redact_secret,
)
from lyraforge.sources.url import (
    DirectUrlSourceAdapter,
    _SafeRedirectHandler,
    resolve_public_http_url,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "midi"


def test_secret_backends_env_precedence_and_redaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert is_sensitive_key("llm_api_key")
    assert is_sensitive_key("MY_SECRET_TOKEN")
    assert not is_sensitive_key("default_style")

    # macOS Keychain backend sends secret over stdin, NEVER in argv
    seen_calls: list[tuple[list[str], str | None]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        seen_calls.append((cmd, kwargs.get("input")))
        if "add-generic-password" in str(kwargs.get("input")):
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if "find-generic-password" in cmd:
            return SimpleNamespace(returncode=0, stdout="sk-kc-value\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    kc = MacOSKeychainBackend("LyraForgeTest", run_fn=fake_run)
    kc.set("llm_api_key", "sk-kc-value")
    assert all("sk-kc-value" not in arg for arg in seen_calls[0][0])
    assert seen_calls[0][1] is not None and "add-generic-password" in seen_calls[0][1]
    assert kc.get("llm_api_key") == "sk-kc-value"
    kc.delete("llm_api_key")

    # Mocked Windows Credential Manager bridge
    stored: dict[str, str] = {}
    win_ops = SimpleNamespace(
        read_credential_win32=lambda t: stored.get(t),
        write_credential_win32=lambda t, _u, v: stored.__setitem__(t, v),
        delete_credential_win32=lambda t: stored.pop(t, None),
    )
    wcred = WindowsCredentialBackend("LyraForgeTest", ops=win_ops)
    wcred.set("llm_api_key", "sk-win-123")
    assert wcred.get("llm_api_key") == "sk-win-123"
    wcred.delete("llm_api_key")
    assert wcred.get("llm_api_key") is None

    # Fallback restricted file permissions + env var precedence
    file_backend = FileRestrictedSecretBackend(tmp_path / SECRET_FILENAME)
    store = SecretStore(primary=MemorySecretBackend(), fallback=file_backend)
    store.set("llm_api_key", "sk-primary-secret")
    assert store.get("llm_api_key") == "sk-primary-secret"
    monkeypatch.setenv("LYRAFORGE_LLM_API_KEY", "sk-env-override")
    assert store.get("llm_api_key") == "sk-env-override"

    file_backend.set("only_file", "val-file")
    if os.name == "posix":
        assert (file_backend.path.stat().st_mode & 0o777) == 0o600

    assert "sk-secret" not in redact_secret(
        "Bearer sk-secret failed with sk-secret", ("sk-secret",)
    )


def test_library_secrets_excluded_from_sqlite_api_backup_and_lyrapack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LYRAFORGE_SECRET_BACKEND", "file")
    data_dir = tmp_path / "sec_data"

    # Seed legacy SQLite with plaintext llm_api_key before opening LibraryStore
    with LibraryStore(data_dir) as seed:
        seed.set_setting("default_style", "rich")
    conn = sqlite3.connect(data_dir / "library.db")
    try:
        conn.execute(
            "INSERT INTO settings(key, value_json, updated_at) VALUES (?, ?, ?)",
            ("llm_api_key", json.dumps("sk-legacy-plaintext-999"), "2026-11-22T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()

    with LibraryStore(data_dir) as store:
        # Legacy plaintext key must be migrated out of SQLite into SecretStore
        assert store.get_secret("llm_api_key") == "sk-legacy-plaintext-999"
        settings = store.get_settings()
        assert settings["default_style"] == "rich"
        assert settings["llm_api_key_configured"] is True
        assert "llm_api_key" not in settings

        raw_rows = store._conn.execute("SELECT key, value_json FROM settings").fetchall()
        assert all("sk-legacy-plaintext-999" not in str(r["value_json"]) for r in raw_rows)

        # Updating key never stores plaintext in SQLite
        store.set_setting("llm_api_key", "sk-live-secret-888")
        assert store.get_secret("llm_api_key") == "sk-live-secret-888"

        imp = store.import_midi(FIXTURE_DIR / "c_major_scale.mid", title="Safe Song")
        arr = store.arrange_song(imp.song.id)
        pack_bytes = export_lyrapack(store, arr.id, copyright_confirmed=True)
        assert b"sk-live-secret-888" not in pack_bytes
        assert b"sk-legacy-plaintext-999" not in pack_bytes

        # Even if someone forcibly injects a sensitive row before backup, backup scrubs it
        with store._conn:
            store._conn.execute(
                "INSERT INTO settings(key, value_json, updated_at) VALUES (?, ?, ?)",
                ("injected_token", json.dumps("tok-hidden-777"), "2026-11-22T00:00:00Z"),
            )
        backup_bytes = export_backup_zip(store)

    # Confirm backup ZIP neither contains .lyraforge.secrets.json nor scrubbed tokens
    import zipfile

    with zipfile.ZipFile(io.BytesIO(backup_bytes), "r") as zf:
        assert SECRET_FILENAME not in zf.namelist()
        snap_path = tmp_path / "inspected_backup.db"
        snap_path.write_bytes(zf.read("library.db"))
    bconn = sqlite3.connect(snap_path)
    try:
        rows = bconn.execute("SELECT key, value_json FROM settings").fetchall()
        joined = repr(rows)
        assert "sk-live-secret-888" not in joined
        assert "tok-hidden-777" not in joined
    finally:
        bconn.close()

    # FastAPI /v1/settings hides API key value and reports configured flag only
    token = "tok-sec"
    client = TestClient(create_app(data_dir=data_dir, session_token=token))
    headers = {SESSION_TOKEN_HEADER: token}
    got = client.get("/v1/settings", headers=headers)
    assert got.status_code == 200
    assert got.json()["settings"]["llm_api_key_configured"] is True
    assert "sk-live-secret-888" not in got.text

    # OpenAI-compatible provider redacts secrets on error
    class _ErrOpener:
        def open(self, _req: Any, timeout: float = 15.0) -> Any:
            _ = timeout
            raise urllib.error.URLError("bad Bearer sk-live-secret-888")

    prov = OpenAICompatibleLLMProvider(
        base_url="http://127.0.0.1:11434/v1",
        api_key="sk-live-secret-888",
        model="qwen2.5",
        opener=_ErrOpener(),
    )
    with pytest.raises(LyraError) as exc:
        prov.parse_intent("test")
    assert "sk-live-secret-888" not in exc.value.message


def test_url_dns_pinning_redirect_caps_and_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Reject embedded credentials and IPv4-mapped loopback
    for bad in (
        "https://user:pass@93.184.216.34/a.mid",
        "http://[::ffff:127.0.0.1]/a.mid",
        "http://100.64.0.1/a.mid",
    ):
        with pytest.raises(LyraError) as exc:
            resolve_public_http_url(bad)
        assert exc.value.code == ErrorCode.INVALID_ARGUMENT

    # Redirect target to private loopback must be blocked
    redir = _SafeRedirectHandler(max_redirects=3)
    req = urllib.request.Request("https://93.184.216.34/a.mid")
    with pytest.raises(LyraError) as redir_exc:
        redir.redirect_request(req, None, 302, "Found", {}, "http://127.0.0.1/secret.mid")
    assert redir_exc.value.code == ErrorCode.INVALID_ARGUMENT

    # Redirect count over max_redirects must raise LIMIT_EXCEEDED
    req_limit = urllib.request.Request("https://93.184.216.34/a.mid")
    req_limit._lyraforge_redirects = 3  # type: ignore[attr-defined]
    with pytest.raises(LyraError) as cap_exc:
        redir.redirect_request(req_limit, None, 302, "Found", {}, "https://93.184.216.34/b.mid")
    assert cap_exc.value.code == ErrorCode.LIMIT_EXCEEDED

    # DNS rebinding TOCTOU: resolve -> 93.184.216.34; later getaddrinfo would return 127.0.0.1
    dns_calls = 0

    def fake_getaddrinfo(host: str, port: int, **_kw: Any) -> list[Any]:
        nonlocal dns_calls
        _ = (host, port)
        dns_calls += 1
        ip = "93.184.216.34" if dns_calls == 1 else "127.0.0.1"
        return [(2, 1, 6, "", (ip, 80))]

    monkeypatch.setattr("lyraforge.sources.url.socket.getaddrinfo", fake_getaddrinfo)
    connected_addrs: list[tuple[str, int]] = []

    def fake_create_connection(addr: tuple[str, int], *_args: Any, **_kw: Any) -> Any:
        connected_addrs.append(addr)
        raise OSError("stop before live network IO")

    monkeypatch.setattr("lyraforge.sources.url.socket.create_connection", fake_create_connection)
    dl_pin_dir = tmp_path / "dl_pin"
    dl_pin_dir.mkdir()
    real_adapter = DirectUrlSourceAdapter()
    with pytest.raises(LyraError) as pin_exc:
        real_adapter.fetch("http://rebind.example.com/song.mid", dl_pin_dir, user_authorized=True)
    assert pin_exc.value.code == ErrorCode.SOURCE_UNAVAILABLE
    with pytest.raises(LyraError) as pin_tls_exc:
        real_adapter.fetch("https://93.184.216.34/song.mid", dl_pin_dir, user_authorized=True)
    assert pin_tls_exc.value.code == ErrorCode.SOURCE_UNAVAILABLE
    # If later DNS rebinds to loopback 127.0.0.1, resolve_public_http_url rejects before connect
    with pytest.raises(LyraError) as rebind_exc:
        real_adapter.fetch("http://rebind.example.com/song.mid", dl_pin_dir, user_authorized=True)
    assert rebind_exc.value.code == ErrorCode.INVALID_ARGUMENT
    # Sockets connected strictly to pinned public IP, NEVER 127.0.0.1
    assert connected_addrs == [("93.184.216.34", 80), ("93.184.216.34", 443)]
    assert list(dl_pin_dir.iterdir()) == []

    # Interrupted/failing download leaves zero partial files in dest_dir
    class _BrokenStreamOpener:
        def open(self, _req: Any, timeout: float = 15.0) -> Any:
            _ = timeout
            raise TimeoutError("simulated read timeout")

    dl_dir = tmp_path / "dl"
    dl_dir.mkdir()
    adapter = DirectUrlSourceAdapter(opener=_BrokenStreamOpener())
    with pytest.raises(LyraError) as dl_exc:
        adapter.fetch("https://93.184.216.34/demo.mid", dl_dir, user_authorized=True)
    assert dl_exc.value.code == ErrorCode.SOURCE_UNAVAILABLE
    assert list(dl_dir.iterdir()) == []
