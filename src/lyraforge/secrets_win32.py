"""Isolated Windows Credential Manager bridge (lazy Win32 advapi32 ctypes on win32)."""

from __future__ import annotations

import sys

from lyraforge.errors import ErrorCode, LyraError

_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2


def read_credential_win32(target_name: str) -> str | None:  # pragma: no cover - Windows OS call
    if sys.platform != "win32":
        raise LyraError(ErrorCode.INVALID_ARGUMENT, "Windows Credential Manager requires Windows")
    import ctypes
    from ctypes import wintypes

    class _CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    pcred = ctypes.POINTER(_CREDENTIAL)()
    ok = advapi32.CredReadW(
        ctypes.c_wchar_p(target_name),
        _CRED_TYPE_GENERIC,
        0,
        ctypes.byref(pcred),
    )
    if not ok:
        err = ctypes.get_last_error()
        if err == 1168:  # ERROR_NOT_FOUND
            return None
        raise OSError(f"CredReadW failed (win32 error={err})")
    try:
        cred = pcred.contents
        raw = bytes(cred.CredentialBlob[: cred.CredentialBlobSize])
        return raw.decode("utf-16-le")
    finally:
        advapi32.CredFree(pcred)


def write_credential_win32(
    target_name: str,
    username: str,
    secret: str,
) -> None:  # pragma: no cover - Windows OS call
    if sys.platform != "win32":
        raise LyraError(ErrorCode.INVALID_ARGUMENT, "Windows Credential Manager requires Windows")
    import ctypes
    from ctypes import wintypes

    class _CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    raw = secret.encode("utf-16-le")
    buf = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    cred = _CREDENTIAL(
        Flags=0,
        Type=_CRED_TYPE_GENERIC,
        TargetName=target_name,
        Comment=None,
        LastWritten=wintypes.FILETIME(),
        CredentialBlobSize=len(raw),
        CredentialBlob=buf,
        Persist=_CRED_PERSIST_LOCAL_MACHINE,
        AttributeCount=0,
        Attributes=None,
        TargetAlias=None,
        UserName=username,
    )
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    ok = advapi32.CredWriteW(ctypes.byref(cred), 0)
    if not ok:
        err = ctypes.get_last_error()
        raise OSError(f"CredWriteW failed (win32 error={err})")


def delete_credential_win32(target_name: str) -> None:  # pragma: no cover - Windows OS call
    if sys.platform != "win32":
        raise LyraError(ErrorCode.INVALID_ARGUMENT, "Windows Credential Manager requires Windows")
    import ctypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    ok = advapi32.CredDeleteW(ctypes.c_wchar_p(target_name), _CRED_TYPE_GENERIC, 0)
    if not ok:
        err = ctypes.get_last_error()
        if err != 1168:  # ERROR_NOT_FOUND
            raise OSError(f"CredDeleteW failed (win32 error={err})")
