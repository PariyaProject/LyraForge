---
name: lyraforge-music-workbench
description: Control LyraForge local music search, transcription, Genshin instrument arrangement, A/B scoring, WAV preview, and score export via MCP.
---

# LyraForge Skill (Antigravity)

Use the `lyraforge` MCP tools from Antigravity to orchestrate LyraForge locally using your existing client session (no extra LLM API key needed in LyraForge).

## Safe Tool Sequence

1. `search_music` / `import_media` (`allow_network: false` by default; ask user before setting `allow_network: true`).
2. `transcribe` for audio/video items -> `arrange` -> `evaluate` (keep transcription fidelity and arrangement playability clearly separated).
3. `preview` (render offline WAV) -> `save_to_library` -> `export_score` (`rights_confirmed: true` required for `.lyrapack`).
4. Never automate OS game key injection through MCP; `play_in_game` intentionally returns a confirmation gate directing the user to the desktop UI.
