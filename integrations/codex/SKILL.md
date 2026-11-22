---
name: lyraforge-music-workbench
description: Arrange authorized MIDI/audio for Genshin Impact free-play instruments using LyraForge MCP tools without an external API key.
---

# LyraForge Skill (Codex CLI)

Use LyraForge's configured `lyraforge` MCP server (`lyraforge mcp`) inside your existing Codex CLI session.

## Guidelines

- Prefer local library/folders (`search_music` with `allow_network: false`) before requesting user authorization (`allow_network: true`) for Internet Archive open-licensed items or direct public URLs.
- Always explain that `arrangement_playability_vs_input_midi` measures instrument key fit rather than original-audio transcription accuracy; pass `reference_midi_path` to `evaluate` whenever ground-truth MIDI is available.
- Confirm `rights_confirmed: true` explicitly with the user before exporting `.lyrapack` share packages.
- Do not attempt to trigger OS keyboard input automatically: `play_in_game` stays gated so the user triggers playback interactively inside the LyraForge desktop workbench.
