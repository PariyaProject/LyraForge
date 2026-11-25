# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for packaging LyraForge standalone Windows & macOS bundles."""

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

web_dist = ROOT / "apps" / "desktop" / "web" / "dist"
if not (web_dist / "index.html").is_file():
    raise FileNotFoundError(
        f"Built frontend asset missing at {web_dist / 'index.html'}; "
        "run 'pnpm --dir apps/desktop/web build' before packaging."
    )

icons_dir = ROOT / "packaging" / "icons"
ICON_ICO = icons_dir / "lyraforge.ico"
ICON_ICNS = icons_dir / "lyraforge.icns"
ICON_PNG = icons_dir / "lyraforge.png"

if IS_WINDOWS and not ICON_ICO.is_file():
    raise FileNotFoundError(
        f"Windows application icon missing at {ICON_ICO}; run scripts/generate_icons.py."
    )
if IS_MACOS and not ICON_ICNS.is_file():
    raise FileNotFoundError(
        f"macOS application icon missing at {ICON_ICNS}; run scripts/generate_icons.py."
    )

datas = [
    (str(ROOT / "src" / "lyraforge" / "instruments" / "data"), "lyraforge/instruments/data"),
    (str(ROOT / "src" / "lyraforge" / "music_core" / "schemas"), "lyraforge/music_core/schemas"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "docs" / "LICENSE_AUDIT.md"), "docs"),
    (str(icons_dir), "packaging/icons"),
    (str(web_dist), "apps/desktop/web/dist"),
]

# ``lyraforge.desktop.launcher`` imports pywebview dynamically through
# ``importlib.import_module("webview")``, so PyInstaller's static module graph never
# sees it. Without these hidden imports the frozen application starts, cannot import
# the GUI host and exits instantly with ``SOURCE_UNAVAILABLE`` (no console, no window).
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
elif IS_MACOS:
    hiddenimports += ["webview.platforms.cocoa"]

exe_icon = str(ICON_ICO) if IS_WINDOWS else (str(ICON_ICNS) if IS_MACOS else None)

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
    icon=exe_icon,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    uac_admin=IS_WINDOWS,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="LyraForge",
)

if IS_MACOS:
    app = BUNDLE(
        coll,
        name="LyraForge.app",
        icon=str(ICON_ICNS),
        bundle_identifier="org.pariyaproject.lyraforge",
        info_plist={
            "CFBundleName": "LyraForge",
            "CFBundleDisplayName": "LyraForge",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "0.1.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
        },
    )

# Fail the build (instead of shipping a silently broken GUI) when required desktop
# host payloads or icon resources are missing from the collected bundle.
collected = {
    dest.replace("\\", "/") for dest, _src, _kind in (*a.datas, *a.binaries)
}
if IS_WINDOWS:
    required_payload = (
        "webview/lib/Microsoft.Web.WebView2.Core.dll",
        "webview/lib/Microsoft.Web.WebView2.WinForms.dll",
        "webview/lib/runtimes/win-x64/native/WebView2Loader.dll",
        "pythonnet/runtime/Python.Runtime.dll",
        "packaging/icons/lyraforge.ico",
    )
    missing = [name for name in required_payload if name not in collected]
    if missing:
        raise RuntimeError(
            "PyInstaller bundle is missing the desktop GUI payload: "
            + ", ".join(missing)
            + ". Install the desktop extra (uv sync --frozen --extra desktop) and rebuild."
        )
elif IS_MACOS:
    required_macos_payload = ("packaging/icons/lyraforge.icns",)
    missing_macos = [name for name in required_macos_payload if name not in collected]
    if missing_macos:
        raise RuntimeError(
            "PyInstaller macOS bundle is missing required payload: " + ", ".join(missing_macos)
        )
