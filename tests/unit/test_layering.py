"""Static AST layering & cross-platform dependency gates.

Enforces the architectural boundaries required for macOS Apple Silicon dev
and Windows 10/11 target compatibility:
* ``music_core`` and ``instruments`` must remain pure headless Python.
* Cross-platform ``playback`` modules (outside ``playback/windows/``) must not
  import Win32 / OS input libraries.
* Core ``pyproject.toml`` dependencies must contain no Windows-only packages.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "lyraforge"

FORBIDDEN_WIN_INPUT = {
    "ctypes",
    "win32api",
    "win32con",
    "win32gui",
    "win32process",
    "win32ui",
    "pywintypes",
    "msvcrt",
    "winsound",
    "pynput",
    "keyboard",
    "comtypes",
}

FORBIDDEN_IN_CORE = FORBIDDEN_WIN_INPUT | {
    "webview",
    "pywebview",
    "tkinter",
    "PyQt5",
    "PyQt6",
    "PySide6",
    "urllib",
    "http",
    "requests",
    "httpx",
    "aiohttp",
    "socket",
    "subprocess",
    "openai",
    "anthropic",
    "google.genai",
    "lyraforge.playback",
    "lyraforge.cli",
}

FORBIDDEN_PYPROJECT_WIN_DEPS = {"pywin32", "pypiwin32", "comtypes", "pynput", "keyboard"}


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
            imports.add(node.module.split(".")[0])
    return imports


def test_music_core_has_no_forbidden_imports() -> None:
    for py_file in (SRC / "music_core").rglob("*.py"):
        imps = _imported_roots(py_file)
        hits = imps & FORBIDDEN_IN_CORE
        assert not hits, f"{py_file.relative_to(ROOT)} imports forbidden modules: {sorted(hits)}"


def test_instruments_has_no_forbidden_imports() -> None:
    for py_file in (SRC / "instruments").rglob("*.py"):
        imps = _imported_roots(py_file)
        hits = imps & FORBIDDEN_IN_CORE
        assert not hits, f"{py_file.relative_to(ROOT)} imports forbidden modules: {sorted(hits)}"


def test_errors_is_pure_stdlib() -> None:
    imps = _imported_roots(SRC / "errors.py")
    assert not any(i.startswith("lyraforge") or i in {"mido", "jsonschema"} for i in imps)


def test_cross_platform_playback_isolates_windows_apis() -> None:
    playback_dir = SRC / "playback"
    for py_file in playback_dir.rglob("*.py"):
        if "windows" in py_file.relative_to(playback_dir).parts:
            continue
        imps = _imported_roots(py_file)
        hits = imps & FORBIDDEN_WIN_INPUT
        assert not hits, (
            f"Cross-platform playback file {py_file.relative_to(ROOT)} "
            f"imports Windows/input modules: {sorted(hits)}"
        )


def test_library_and_preview_have_no_windows_or_gui_imports() -> None:
    forbidden = FORBIDDEN_WIN_INPUT | {
        "webview",
        "pywebview",
        "tkinter",
        "PyQt5",
        "PyQt6",
        "PySide6",
    }
    for pkg in ("library", "preview", "api", "media", "transcribers", "agent", "sources"):
        for py_file in (SRC / pkg).rglob("*.py"):
            imps = _imported_roots(py_file)
            hits = imps & forbidden
            assert not hits, (
                f"{py_file.relative_to(ROOT)} imports forbidden modules: {sorted(hits)}"
            )


def test_agent_and_sources_never_import_playback() -> None:
    for pkg in ("agent", "sources"):
        for py_file in (SRC / pkg).rglob("*.py"):
            imps = _imported_roots(py_file)
            bad = [
                i for i in imps
                if i == "lyraforge.playback" or i.startswith("lyraforge.playback.")
            ]
            assert not bad, f"{py_file.relative_to(ROOT)} must never import lyraforge.playback"


def test_desktop_has_no_windows_input_imports() -> None:
    for py_file in (SRC / "desktop").rglob("*.py"):
        imps = _imported_roots(py_file)
        hits = imps & FORBIDDEN_WIN_INPUT
        assert not hits, (
            f"{py_file.relative_to(ROOT)} imports forbidden Windows/input modules: {sorted(hits)}"
        )


def test_secrets_cross_platform_has_no_win32_imports() -> None:
    imps = _imported_roots(SRC / "secrets.py")
    hits = imps & FORBIDDEN_WIN_INPUT
    assert not hits, f"secrets.py imports forbidden Windows/input modules: {sorted(hits)}"


def test_mcp_has_no_windows_input_imports() -> None:
    for py_file in (SRC / "mcp").rglob("*.py"):
        imps = _imported_roots(py_file)
        hits = imps & FORBIDDEN_WIN_INPUT
        assert not hits, (
            f"{py_file.relative_to(ROOT)} imports forbidden Windows/input modules: {sorted(hits)}"
        )
        bad_pb = [i for i in imps if i == "lyraforge.playback.windows" or ".windows" in i]
        assert not bad_pb, (
            f"{py_file.relative_to(ROOT)} must never import Windows playback drivers: {bad_pb}"
        )


def test_pyproject_core_dependencies_have_no_windows_only_packages() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    for dep in deps:
        pkg = dep.split("==")[0].split(">=")[0].split("<")[0].split(";")[0].strip().lower()
        assert pkg not in FORBIDDEN_PYPROJECT_WIN_DEPS, (
            f"Windows-only dependency {pkg!r} must not be in core [project].dependencies"
        )
