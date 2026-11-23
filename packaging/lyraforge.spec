# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for packaging LyraForge Windows/desktop standalone bundle."""

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
IS_WINDOWS = sys.platform == "win32"

web_dist = ROOT / "apps" / "desktop" / "web" / "dist"
if not (web_dist / "index.html").is_file():
    raise FileNotFoundError(
        f"Built frontend asset missing at {web_dist / 'index.html'}; "
        "run 'pnpm --dir apps/desktop/web build' before packaging."
    )

datas = [
    (str(ROOT / "src" / "lyraforge" / "instruments" / "data"), "lyraforge/instruments/data"),
    (str(ROOT / "src" / "lyraforge" / "music_core" / "schemas"), "lyraforge/music_core/schemas"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "docs" / "LICENSE_AUDIT.md"), "docs"),
    (str(web_dist), "apps/desktop/web/dist"),
]

# ``lyraforge.desktop.launcher`` imports pywebview dynamically through
# ``importlib.import_module("webview")``, so PyInstaller's static module graph never
# sees it. Without these hidden imports the frozen application starts, cannot import
# the GUI host and exits instantly with ``SOURCE_UNAVAILABLE`` (no console, no window).
# Listing ``webview`` also activates pywebview's and pythonnet's bundled PyInstaller
# hooks, which ship the WebView2 interop DLLs and the .NET runtime payload.
hiddenimports = [
    "lyraforge.playback.windows.driver",
    "lyraforge.playback.windows.win32_types",
    "lyraforge.playback.windows.window_guard",
    "lyraforge.secrets_win32",
    "multipart",
    "python_multipart",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "webview",
    "webview._version",
]
if IS_WINDOWS:
    # pywebview resolves its Windows backend (pythonnet + WebView2) at runtime, so the
    # backend module and the CLR bridge must be pinned explicitly for the frozen build.
    hiddenimports += ["webview.platforms.edgechromium", "clr"]

a = Analysis(
    [str(ROOT / "apps" / "desktop" / "main.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LyraForge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="LyraForge",
)

# Fail the build (instead of shipping a silently broken GUI) when the GUI host payload
# is missing from the collected bundle.
if IS_WINDOWS:
    collected = {
        dest.replace("\\", "/") for dest, _src, _kind in (*a.datas, *a.binaries)
    }
    required_payload = (
        "webview/lib/Microsoft.Web.WebView2.Core.dll",
        "webview/lib/Microsoft.Web.WebView2.WinForms.dll",
        "webview/lib/runtimes/win-x64/native/WebView2Loader.dll",
        "pythonnet/runtime/Python.Runtime.dll",
    )
    missing = [name for name in required_payload if name not in collected]
    if missing:
        raise RuntimeError(
            "PyInstaller bundle is missing the desktop GUI host payload: "
            + ", ".join(missing)
            + ". Install the desktop extra (uv sync --frozen --extra desktop) and rebuild."
        )
