# Changelog

All notable user-facing changes to LyraForge are documented in this file.

## [Unreleased] — 0.1.0-alpha

### Added
- **Cross-platform music core & arranger**: Headless MIDI import/export, tempo map handling, melody prioritization, chord arpeggiation, playable-range folding/transposition, built-in 21-key presets (*Windsong Lyre* and *Floral Zither*), and separated arrangement playability vs. audio transcription fidelity scoring.
- **Audio & media transcription pipeline**: Pure-Python offline monophonic YIN transcriber (`builtin-mono`), WAV normalization, optional user-configured `ffmpeg` media extraction (`.mp3`, `.flac`, `.m4a`, `.ogg`, `.mp4`, `.mkv`, `.webm`), and isolated subprocess adapters for `basic-pitch` and `dettato`.
- **Desktop Workbench (Vue 3 + PyWebView)**: Six-view Studio Dark interface (Home, Library, Transcribe, Arrange Studio with interactive DAW Piano Roll, Playback console, Settings & MCP integration) with a persistent bottom transport bar for offline plucked-lyre WAV previewing.
- **SQLite Library, `.lyrapack` & Backup/Restore**: Content deduplication, exact JSON1 tag filtering, favorites/version branching, rights-confirmed `.lyrapack` sharing (audio-free and secret-free), and transactional ZIP backup/restore with rollback recovery.
- **Zero-API-Key AI & MCP Integration**: Built-in deterministic `RuleBasedLLMProvider`, optional private OpenAI-compatible HTTP endpoint support, and a standard `stdio` MCP server (`lyraforge mcp`, 10 typed tools) with integration templates under `integrations/` and hard confirmation gating on `play_in_game`.
- **Cross-platform CI & Windows packaging spec**: Automated macOS and Windows test workflows plus `packaging/lyraforge.spec` / `scripts/build_windows.ps1` for portable Windows builds.

### Reliability & Security Highlights
- OS-native API key storage (macOS Keychain, Windows Credential Manager, or `0o600` local secret file) with plaintext SQLite migration and redaction across logs, errors, backups, and share packages.
- DNS-pinned SSRF protections for authorized direct-URL downloads and strict Creative Commons / Public Domain URL classification for open catalog queries (rejecting `NoDerivatives`).
- Hardened concurrent preview WAV rendering using isolated per-request temporary synthesis and atomic publish replacement so cancelled renders never remove another request's published preview.
- Hardened bounded subprocess execution with process-group/tree cleanup, crash-safe `.restore-txn.json` backup restore transactions, active MCP task non-eviction, cooperative cancellation, and deadlock-free log/pipe drain cleanup.

### Known Alpha Limitations
- Windows 10/11 real-machine Genshin Impact playback (`WindowsKeyboardDriver` + `ForegroundWindowGuard`) remains **unverified on live game hardware** (`calibration.status = "unverified"`).
- Complex polyphonic/vocal music transcription requires optional external `ffmpeg` + `basic-pitch` or `dettato` configuration and manual Piano Roll editing.
- No formal Stable GitHub Release or signed installer has been cut yet.
