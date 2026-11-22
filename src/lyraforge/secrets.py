"""Cross-platform credential storage (env + OS keychain/CredMan + restricted fallback)."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

from lyraforge.fs import atomic_write_text

_SENSITIVE_KEY_RE = re.compile(r"(api[_-]?key|secret|token|password)", re.IGNORECASE)
_NOT_FOUND_RC = 44  # macOS security errSecItemNotFound
SECRET_FILENAME = ".lyraforge.secrets.json"


def is_sensitive_key(key: str) -> bool:
    """Return True if a setting key must never be stored plaintext in SQLite/backups."""
    return bool(_SENSITIVE_KEY_RE.search(key.strip()))


def redact_secret(text: str, secrets: Iterable[str]) -> str:
    """Mask any known secret values inside diagnostic text or exception strings."""
    cleaned = text
    for sec in secrets:
        val = (sec or "").strip()
        if len(val) >= 4:
            cleaned = cleaned.replace(val, "***REDACTED***")
    cleaned = re.sub(r"(Bearer\s+)[A-Za-z0-9._\-+=]+", r"\1***REDACTED***", cleaned)
    return cleaned


class SecretBackendUnavailable(RuntimeError):
    """Raised when an OS keychain/credential backend cannot operate in this session."""


class SecretBackend(Protocol):
    backend_id: str

    def get(self, name: str) -> str | None:
        ...

    def set(self, name: str, value: str) -> None:
        ...

    def delete(self, name: str) -> None:
        ...


class MemorySecretBackend:
    """In-memory backend for unit tests or ephemeral sessions."""

    backend_id = "memory"

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._data: dict[str, str] = dict(initial or {})

    def get(self, name: str) -> str | None:
        return self._data.get(name)

    def set(self, name: str, value: str) -> None:
        self._data[name] = value

    def delete(self, name: str) -> None:
        self._data.pop(name, None)


class FileRestrictedSecretBackend:
    """Fallback local secrets JSON (`0600`) outside SQLite and always excluded from backups."""

    backend_id = "restricted-file"

    def __init__(self, path: Path) -> None:
        self.path = path

    def _read_map(self) -> dict[str, str]:
        if not self.path.is_file():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(k): str(v) for k, v in raw.items() if isinstance(v, str)}

    def _write_map(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, json.dumps(data, ensure_ascii=False, sort_keys=True))
        if os.name == "posix":
            os.chmod(self.path, 0o600)

    def get(self, name: str) -> str | None:
        return self._read_map().get(name)

    def set(self, name: str, value: str) -> None:
        data = self._read_map()
        data[name] = value
        self._write_map(data)

    def delete(self, name: str) -> None:
        data = self._read_map()
        if name in data:
            del data[name]
            self._write_map(data)


class MacOSKeychainBackend:
    """macOS Keychain backend using ``/usr/bin/security -i`` (stdin avoids argv leakage)."""

    backend_id = "macos-keychain"

    def __init__(
        self,
        service: str = "LyraForge",
        *,
        run_fn: Any | None = None,
    ) -> None:
        self.service = service
        self._run = run_fn or subprocess.run

    def _check_account(self, name: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9._:@-]", "_", name.strip())
        if not safe:
            raise ValueError("secret account name must not be empty")
        return safe

    def get(self, name: str) -> str | None:
        account = self._check_account(name)
        proc = self._run(
            ["/usr/bin/security", "find-generic-password", "-s", self.service, "-a", account, "-w"],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode == 0:
            val = proc.stdout.rstrip("\r\n")
            return val if val else None
        if proc.returncode == _NOT_FOUND_RC:
            return None
        raise SecretBackendUnavailable(
            f"macOS keychain lookup failed (rc={proc.returncode})"
        )

    def set(self, name: str, value: str) -> None:
        account = self._check_account(name)
        clean = value.replace("\r", "").replace("\n", "")
        hex_val = clean.encode("utf-8").hex()
        cmd = f"add-generic-password -U -s {self.service} -a {account} -X {hex_val}\n"
        proc = self._run(
            ["/usr/bin/security", "-i"],
            input=cmd,
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise SecretBackendUnavailable(
                f"macOS keychain store failed (rc={proc.returncode})"
            )

    def delete(self, name: str) -> None:
        account = self._check_account(name)
        proc = self._run(
            ["/usr/bin/security", "delete-generic-password", "-s", self.service, "-a", account],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode not in (0, _NOT_FOUND_RC):
            raise SecretBackendUnavailable(
                f"macOS keychain delete failed (rc={proc.returncode})"
            )


class WindowsCredentialBackend:
    """Windows Credential Manager backend delegating to isolated Win32 bindings."""

    backend_id = "windows-credential-manager"

    def __init__(self, target_prefix: str = "LyraForge", *, ops: Any | None = None) -> None:
        self.target_prefix = target_prefix
        self._ops = ops

    def _ops_mod(self) -> Any:
        if self._ops is not None:
            return self._ops
        from lyraforge import secrets_win32

        return secrets_win32

    def _target(self, name: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9._:@-]", "_", name.strip())
        return f"{self.target_prefix}/{safe}"

    def get(self, name: str) -> str | None:
        try:
            return self._ops_mod().read_credential_win32(self._target(name))
        except Exception as exc:
            raise SecretBackendUnavailable(str(exc)) from exc

    def set(self, name: str, value: str) -> None:
        try:
            self._ops_mod().write_credential_win32(self._target(name), name, value)
        except Exception as exc:
            raise SecretBackendUnavailable(str(exc)) from exc

    def delete(self, name: str) -> None:
        try:
            self._ops_mod().delete_credential_win32(self._target(name))
        except Exception as exc:
            raise SecretBackendUnavailable(str(exc)) from exc


class SecretStore:
    """Unified secret resolver: env var override -> OS credential store -> restricted fallback."""

    def __init__(
        self,
        primary: SecretBackend | None = None,
        fallback: SecretBackend | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback

    @staticmethod
    def env_var_for(name: str) -> str:
        clean = re.sub(r"[^A-Za-z0-9]+", "_", name.strip()).upper()
        return f"LYRAFORGE_{clean}"

    def get(self, name: str) -> str | None:
        env_val = os.environ.get(self.env_var_for(name), "").strip()
        if env_val:
            return env_val
        if self.primary is not None:
            try:
                val = self.primary.get(name)
                if val:
                    return val
            except SecretBackendUnavailable:
                pass
        if self.fallback is not None:
            val = self.fallback.get(name)
            if val:
                return val
        return None

    def set(self, name: str, value: str) -> str:
        clean = value.strip()
        if not clean:
            self.delete(name)
            return "deleted"
        if self.primary is not None:
            try:
                self.primary.set(name, clean)
                if self.fallback is not None:
                    self.fallback.delete(name)
                return self.primary.backend_id
            except SecretBackendUnavailable:
                pass
        if self.fallback is not None:
            self.fallback.set(name, clean)
            return self.fallback.backend_id
        raise SecretBackendUnavailable("no secret storage backend available")

    def delete(self, name: str) -> None:
        if self.primary is not None:
            with contextlib.suppress(SecretBackendUnavailable):
                self.primary.delete(name)
        if self.fallback is not None:
            self.fallback.delete(name)

    def has(self, name: str) -> bool:
        return bool(self.get(name))


def default_secret_store(data_dir: Path) -> SecretStore:
    """Create platform-appropriate secret store scoped cleanly to ``data_dir``."""
    scope = hashlib.sha256(str(data_dir.expanduser().resolve()).encode("utf-8")).hexdigest()[:12]
    fallback = FileRestrictedSecretBackend(data_dir / SECRET_FILENAME)
    mode = os.environ.get("LYRAFORGE_SECRET_BACKEND", "").strip().lower()
    if mode == "memory":
        return SecretStore(primary=MemorySecretBackend(), fallback=None)
    if mode == "file":
        return SecretStore(primary=None, fallback=fallback)
    if sys.platform == "darwin":
        return SecretStore(
            primary=MacOSKeychainBackend(service=f"LyraForge.{scope}"),
            fallback=fallback,
        )
    if sys.platform == "win32":
        return SecretStore(
            primary=WindowsCredentialBackend(target_prefix=f"LyraForge.{scope}"),
            fallback=fallback,
        )
    return SecretStore(primary=None, fallback=fallback)
