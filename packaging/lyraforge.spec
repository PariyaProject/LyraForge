# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for packaging LyraForge Windows/desktop standalone bundle."""

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent

datas = [
    (str(ROOT / "src" / "lyraforge" / "instruments" / "data"), "lyraforge/instruments/data"),
    (str(ROOT / "src" / "lyraforge" / "music_core" / "schemas"), "lyraforge/music_core/schemas"),
]
web_dist = ROOT / "apps" / "desktop" / "web" / "dist"
if web_dist.is_dir():
    datas.append((str(web_dist), "apps/desktop/web/dist"))

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
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.lifespan.on",
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
