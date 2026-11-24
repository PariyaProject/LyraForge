$ErrorActionPreference = "Stop"

# Windows 10/11 portable bundle build script (LyraForge.exe embeds uac_admin=True, so step 4 runs cleanly in an elevated shell and prompts UAC otherwise)
Write-Host "[1/3] Building Vue 3 frontend..."
pnpm --dir apps/desktop/web install --frozen-lockfile
pnpm --dir apps/desktop/web build

Write-Host "[2/3] Syncing desktop runtime..."
uv sync --frozen --extra desktop

Write-Host "[3/3] Packaging standalone LyraForge bundle..."
uv run --with pyinstaller pyinstaller --noconfirm --clean packaging/lyraforge.spec
if (-not (Test-Path -LiteralPath "dist/LyraForge/LyraForge.exe")) {
    throw "Expected dist/LyraForge/LyraForge.exe was not generated."
}
Write-Host "[4/4] Running headless frozen bundle self-check (assets + GUI host)..."
& "dist/LyraForge/LyraForge.exe" --self-check --check-gui
if ($LASTEXITCODE -ne 0) {
    throw "LyraForge.exe --self-check --check-gui failed with exit code $LASTEXITCODE"
}
Write-Host "Done: dist/LyraForge/LyraForge.exe"
