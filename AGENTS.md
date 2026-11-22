# LyraForge — Workspace rules for Google Antigravity CLI

## Mission
Build a real, independent Windows desktop product that converts user-authorized audio/video/MIDI to playable in-game instrument arrangements, previews/edits/stores them locally, and supports explicitly user-triggered keyboard-only playback in Genshin Impact's **free instrument interface**. This is **not** a falling-note minigame bot. Read `docs/PROJECT_SPEC.md` fully before planning changes.

## Mandatory development process
1. Follow milestones M0→M1→M2→M3→M4→M5 in `docs/PROJECT_SPEC.md`; **do not attempt the whole roadmap in one pass**. Start with a reproducible CLI proof of MIDI-to-performance events and DryRun.
2. Before each implementation, inspect the repository and draft a short plan: files, interfaces, tests, legal/security issues and acceptance criteria. Then write and test real code.
3. Maintain `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/LICENSE_AUDIT.md`, `docs/TEST_PLAN.md`, `README.md`, and `docs/adr/` as needed. Record the upstream dependency version/commit and license before incorporating code, models, soundfonts or scores.
4. Never fabricate passing test results. Execute tests; identify what needs manual in-game verification. Never say UI is functional if only static placeholders exist.
5. Implement small vertical slices. Prefer pure functions, typed schemas, dependency inversion, fixtures created by us, reproducible builds and pinned dependencies.

## Tech defaults (may change only with a documented ADR)
- Python 3.11/3.12 + uv + pytest; TypeScript + Vue3 + Vite for the planned UI; PyWebView Windows host; SQLite for metadata; files on disk for audio/MIDI/preview/performance.
- Keep domain `music_core` headless and reusable by both CLI and desktop UI. No GUI, platform input or LLM imports in the core.
- Separate interfaces for SourceAdapter, Transcriber, Arranger, InstrumentProfile, LLMProvider and PlaybackDriver.
- First pass: `mido` / `pretty_midi`, correct tempo conversion, validated JSON schema and a DryRun driver. Only after proof, build real Windows playback.
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

## Initial task
**M0 only.** Read the PRD, validate external tool licenses and Windows availability, initialize the minimal repository, create our own MIDI fixtures, implement import → normalized notes → instrument profile → deterministic playable events JSON and DryRun tests; report the verification and the exact next M1 task. Do not call any network model or touch the game automatically during M0.
