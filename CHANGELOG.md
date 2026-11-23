# Changelog

All notable user-facing changes to LyraForge are documented in this file.

## [Unreleased] — 0.1.0-alpha

### Added
- **Configurable global hotkeys for playback (default unbound)**: `start` / `pause` / `resume` / `stop` (and `next` / `previous` once a queue exists) can be assigned user shortcuts such as `Ctrl+Alt+F9`; registration uses the Windows `RegisterHotKey` API, conflicts are reported per action, and the settings page persists them. Nothing is bound until the user sets it.
- **Configurable game process allowlist**: `windows_allowed_processes` defaults to `GenshinImpact.exe, YuanShen.exe` and can be edited in settings, alongside the existing window-title fallback.
- **Built-in one-click arrangement presets**: five validated presets per instrument (melody first, balanced, rich, slow practice, lively) exposed as buttons in the arrange studio and via `lyraforge presets list` / `GET /v1/presets`; the default workflow never calls an agent or an API.
- **Vintage Lyre (老旧的诗琴) profile**: a third 21-key instrument preset with the community-documented C Dorian / C Phrygian pitch mapping (distinct from the C major lyres), marked `unverified` until in-game calibration.
- **In-app one-click toolchain installer**: `lyraforge tools status|install` and a desktop settings card install FFmpeg, Basic Pitch and dettato on demand into `%LOCALAPPDATA%\LyraForge\tools` (or the platform equivalent). Downloads come from PyPI with SHA-256 verification; `uv` is bootstrapped from its verified wheel and manages an isolated CPython plus per-engine virtualenvs. No registry, PATH or user environment changes are made — LyraForge injects the managed paths into its child processes at startup, and explicit user environment variables still win (`src/lyraforge/toolchain/*`, `src/lyraforge/api/tool_service.py`, `apps/desktop/web/src/views/SettingsView.vue`).
- **Cross-platform music core & arranger**: Headless MIDI import/export, tempo map handling, melody prioritization, chord arpeggiation, playable-range folding/transposition, built-in 21-key presets (*Windsong Lyre* and *Floral Zither*), and separated arrangement playability vs. audio transcription fidelity scoring.
- **Audio & media transcription pipeline**: Pure-Python offline monophonic YIN transcriber (`builtin-mono`), WAV normalization, optional user-configured `ffmpeg` media extraction (`.mp3`, `.flac`, `.m4a`, `.ogg`, `.mp4`, `.mkv`, `.webm`), and isolated subprocess adapters for `basic-pitch` and `dettato`.
- **Desktop Workbench (Vue 3 + PyWebView)**: Six-view Studio Dark interface (Home, Library, Transcribe, Arrange Studio with interactive DAW Piano Roll, Playback console, Settings & MCP integration) with a persistent bottom transport bar for offline plucked-lyre WAV previewing.
- **SQLite Library, `.lyrapack` & Backup/Restore**: Content deduplication, exact JSON1 tag filtering, favorites/version branching, rights-confirmed `.lyrapack` sharing (audio-free and secret-free), and transactional ZIP backup/restore with rollback recovery.
- **Zero-API-Key AI & MCP Integration**: Built-in deterministic `RuleBasedLLMProvider`, optional private OpenAI-compatible HTTP endpoint support, and a standard `stdio` MCP server (`lyraforge mcp`, 10 typed tools) with integration templates under `integrations/` and hard confirmation gating on `play_in_game`.
- **Cross-platform CI & GitHub Releases automation**: Added Windows portable ZIP packaging, post-extraction `LyraForge.exe --self-check`, `SHA256SUMS.txt` checksum generation, rolling `dev-latest` + immutable `dev-YYYYMMDD-<sha7>` experimental pre-releases on `main`, and isolated SemVer (`vX.Y.Z`) release channels (`packaging/lyraforge.spec`, `scripts/build_windows.ps1`, `scripts/release_helper.py`, `.github/workflows/ci.yml`).

### Changed
- **AI/Agent is now clearly optional**: the desktop navigation, home page, transcribe view and settings put the preset-driven offline workflow first; MCP / HTTP LLM integration moved into collapsed "advanced (optional)" sections, and README no longer presents AI as a prerequisite.

### Fixed
- **Windows playback started with a false `focus_lost`**: playback used to check the foreground window immediately after the in-app start click, so LyraForge's own window failed the check. Starting now enters a `waiting_focus` phase (default 10 s) and only sends keys after the game is foreground; timeouts report the actual foreground process/title without sending anything.
- **Game detection no longer depends on the window title**: the guard matches the foreground process (`GenshinImpact.exe` / `YuanShen.exe`) first, with title matching kept only as a fallback, so localized titles and fullscreen/borderless modes work.
- **UIPI permission mismatch is explained and recoverable**: when the game runs elevated and LyraForge does not, playback is blocked with an actionable message and a desktop button to relaunch LyraForge as administrator, instead of silently dropping synthetic input.
- **External transcription engines were unusable on Windows**: the Basic Pitch adapter invoked the removed `basic_pitch.inference` module (0.4.x uses `basic_pitch.predict`), child Python tools inherited the Chinese-Windows `cp936` codec and crashed on emoji progress output, and dettato was passed a file path where its CLI expects an output directory. All three are fixed and verified end-to-end with real `basic-pitch` 0.4.0 and `dettato` 2.0.0 (`src/lyraforge/transcribers/*`, `src/lyraforge/media/subprocess_utils.py`); [DEVELOPMENT.md](docs/DEVELOPMENT.md) now documents the verified isolated-environment recipe (`numpy<2`, `setuptools<81`).
- **Windows portable build could not open its desktop window**: the PyInstaller bundle omitted the dynamically imported PyWebView GUI host (pywebview, pythonnet and the WebView2 interop DLLs), so `LyraForge.exe` exited within a second without showing anything. The frozen bundle now pins `webview`/`clr`/`webview.platforms.edgechromium` and fails the build if the GUI payload is missing (`packaging/lyraforge.spec`).
- **`--self-check` never exercised the GUI host**: CI now runs `LyraForge.exe --self-check --check-gui`, and a frozen bundle always requires the GUI import, so a packaging regression fails the release gate instead of the user's desktop (`src/lyraforge/cli.py`, `.github/workflows/ci.yml`).
- **Fatal startup failures are no longer silent**: startup errors are appended with a traceback to `%LOCALAPPDATA%\LyraForge\logs\startup.log` and shown in a native error dialog on Windows/macOS (`src/lyraforge/startup_report.py`, `apps/desktop/main.py`).
- **Portable ZIP usability**: the release archive now carries `README.txt` with extraction/launch steps and the startup-log location, and packaging validation rejects archives without the WebView2/pythonnet payload (`scripts/release_helper.py`).

### Reliability & Security Highlights
- OS-native API key storage (macOS Keychain, Windows Credential Manager, or `0o600` local secret file) with plaintext SQLite migration and redaction across logs, errors, backups, and share packages.
- DNS-pinned SSRF protections for authorized direct-URL downloads and strict Creative Commons / Public Domain URL classification for open catalog queries (rejecting `NoDerivatives`).
- Hardened concurrent preview WAV rendering using isolated per-request temporary synthesis and atomic publish replacement so cancelled renders never remove another request's published preview.
- Hardened bounded subprocess execution with process-group/tree cleanup, crash-safe `.restore-txn.json` backup restore transactions, active MCP task non-eviction, cooperative cancellation, and deadlock-free log/pipe drain cleanup.

### Known Alpha Limitations
- Windows 10/11 real-machine Genshin Impact playback (`WindowsKeyboardDriver` + `ForegroundWindowGuard`) remains **unverified on live game hardware** (`calibration.status = "unverified"`).
- Complex polyphonic/vocal music transcription requires optional external `ffmpeg` + `basic-pitch` or `dettato` configuration and manual Piano Roll editing.
- No formal Stable GitHub Release or signed installer has been cut yet.
