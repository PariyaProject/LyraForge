#!/usr/bin/env bash
set -euo pipefail

echo "[1/4] Building Vue 3 frontend..."
pnpm --dir apps/desktop/web install --frozen-lockfile
pnpm --dir apps/desktop/web build

echo "[2/4] Syncing desktop runtime (macOS)..."
uv sync --frozen --extra desktop

echo "[3/4] Packaging LyraForge.app bundle..."
uv run --with pyinstaller pyinstaller --noconfirm --clean packaging/lyraforge.spec

APP_BIN="dist/LyraForge.app/Contents/MacOS/LyraForge"
APP_ICON="dist/LyraForge.app/Contents/Resources/lyraforge.icns"
if [[ ! -x "$APP_BIN" ]]; then
  echo "Expected macOS executable missing at $APP_BIN" >&2
  exit 1
fi
if [[ ! -f "$APP_ICON" ]]; then
  echo "Expected macOS .icns icon missing at $APP_ICON" >&2
  exit 1
fi

echo "[4/4] Running headless frozen bundle self-check (assets + Cocoa GUI host)..."
"$APP_BIN" --self-check --check-gui
echo "Done: dist/LyraForge.app"
