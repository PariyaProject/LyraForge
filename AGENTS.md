# LyraForge — Workspace rules for Google Antigravity CLI

## Mission
Build a real, independent Windows desktop product that converts user-authorized audio/video/MIDI to playable in-game instrument arrangements, previews/edits/stores them locally, and supports explicitly user-triggered keyboard-only playback in Genshin Impact's **free instrument interface**. This is **not** a falling-note minigame bot. Read `docs/PROJECT_SPEC.md` fully before planning changes.

## Mandatory development process
1. Milestones M0–M5 in `docs/PROJECT_SPEC.md` have been implemented as vertical slices (with real-machine Windows in-game playback and optional external transcribers awaiting environment verification). Check `docs/PROGRESS.md` and `docs/PROJECT_SPEC.md` before planning fixes or new features; build incrementally without unrequested large-scale rewrites.
2. Before each implementation, inspect the repository and draft a short plan: files, interfaces, tests, legal/security issues and acceptance criteria. Then write and test real code.
3. Maintain `docs/ARCHITECTURE.md`, `docs/PROGRESS.md`, `docs/ROADMAP.md`, `docs/LICENSE_AUDIT.md`, `docs/TEST_PLAN.md`, `README.md`, and `docs/adr/` as needed. Record the upstream dependency version/commit and license before incorporating code, models, soundfonts or scores.
4. Never fabricate passing test results. Execute tests; clearly label macOS DryRun verification vs. unverified Windows real-machine in-game verification or missing external tools (`ffmpeg`, `basic-pitch`, `dettato`). Never claim UI or playback features are verified if only placeholders exist or real hardware was not tested.
5. Implement small vertical slices. Prefer pure functions, typed schemas, dependency inversion, fixtures created by us, reproducible builds and pinned dependencies.

## Tech defaults (may change only with a documented ADR)
- Python 3.11/3.12 + `uv` + `pytest` + `ruff`; TypeScript + Vue 3 + Vite + `pnpm` (`packageManager`-pinned) for the desktop UI (`apps/desktop/web`); FastAPI + PyWebView host (`apps/desktop`); SQLite for metadata and files on disk for audio/MIDI/preview/performance; OS Keychain / Windows Credential Manager (`lyraforge.secrets`) or env vars for API keys (never persisted plaintext in SQLite or backups/shares).
- Keep domain `music_core` headless and reusable by both CLI and desktop UI. No GUI, platform input, network, subprocess or LLM imports in `music_core` (enforced by `tests/unit/test_layering.py`).
- Separate interfaces for SourceAdapter, Transcriber, Arranger, InstrumentProfile, LLMProvider and PlaybackDriver.
- MIDI parsing/export uses `mido` with exact rational tempo conversion (`Fraction`), validated JSON performance schema, DryRun driver for macOS/CI, and isolated Win32 `SendInput` driver for Windows 10/11. Audio transcription provides built-in pure-Python YIN (`builtin-mono`) plus optional isolated `basic-pitch` / `dettato` subprocess runners (`ADR-0001`).
- Runtime product **must not depend on Antigravity CLI**. The CLI is a coding tool, not an assumed shipping model API. If experimenting with `agy -p`, isolate it as optional, off by default, and verify permissions/terms.

## Safety and licensing (non-negotiable)
- Never read, inject, alter game memory, hook the game process or bypass anti-cheat. Only controlled Windows keyboard simulation on explicit user action; stop and release keys when focus changes.
- Do not silently start game playback, scrape credentials, bypass paywalls/DRM or download from sources without rights/consent.
- All network/download/install/deletion/upload/public-share actions require conscious scope and user authorization. Keep external data and LLM output untrusted.
- Do not copy GPL-3.0 source from Genshin Music Studio or AutoMidiPlayer into a differently licensed codebase without discussing GPL obligations. MIT/Apache dependencies still need attribution; evaluate model weights and dataset terms separately.
- Never bundle unlicensed game samples, commercial recordings or community scores without permission. Share packages omit source audio by default.
- Do not require admin rights, disabling Defender, or blanket security exclusions.

## Quality gates
- Test broken inputs, tempo changes, multiple tracks, dense chords, missing semitones, repeated keys, multi-octave pitch, empty MIDI, instrument mapping and all failure-path key releases.
- Model workloads must be cancellable; UI must remain responsive; persisted songs must survive application restart.
- Main branches must remain buildable. Write migrations and schema versions, avoid hidden breaking changes.
- Keep source citations/links in docs and package licenses where applicable.

## Current repository status & maintenance rules
- **License**: GNU General Public License v3.0 (`GPL-3.0`, see `LICENSE` and `docs/LICENSE_AUDIT.md`). Keep copyright notices and third-party license attributions intact; do not replace GPL-3.0 without explicit owner approval.
- **Development vs. Target Environment**: Active development runs on macOS Apple Silicon (DryRun playback/testing); primary release target is Windows 10/11 (`SendInput` free-instrument playback, Windows Credential Manager, PyInstaller bundle in `.github/workflows/ci.yml`).
- **Verification Gate**: Before reporting any change complete, run `pnpm --dir apps/desktop/web install --frozen-lockfile && make check` (`ruff`, `pytest --cov-fail-under=80`, `vitest`, `vite build`, `make smoke`) and record any items still requiring Windows real-machine or external dependency verification honestly.
- **Security & Privacy Invariants**: API keys must use OS Keychain / Windows Credential Manager (`src/lyraforge/secrets.py`, `secrets_win32.py`) or `LYRAFORGE_*` environment variables, never plaintext SQLite, backups, logs, or `.lyrapack` share packages. External URLs/search require explicit `allow_network=True` user authorization and must pass DNS-pinned SSRF checks (`src/lyraforge/sources/url.py`).
