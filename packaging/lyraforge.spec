# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for packaging LyraForge Windows/desktop standalone bundle."""

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent

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

a = Analysis(
    [str(ROOT / "apps" / "desktop" / "main.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[
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
    ],
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
