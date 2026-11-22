---
name: lyraforge-music-workbench
description: Convert authorized MIDI, audio, or open-licensed tracks into playable Genshin Impact free-play instrument arrangements using LyraForge MCP tools (no API key required).
---

# LyraForge Skill (Claude Code)

Use this skill when the user wants to search local music, import MIDI/audio files, transcribe solo audio, arrange or re-transpose for Genshin Impact instruments (`genshin.windsong_lyre.v1`, `genshin.floral_zither.v1`), compare arrangements, render offline WAV previews, or export `.mid` / `performance.json` / `.lyrapack` files.

## Rules

1. **No API Key Required**: Invoke LyraForge's `stdio` MCP server tools directly using your existing Claude Code session. Never ask the user to configure an OpenAI/Anthropic API key just to arrange music.
2. **Respect Licensing & Network Authorization**:
   - Prefer `search_music` with `allow_network: false` first.
   - Only pass `allow_network: true` when the user explicitly authorizes searching Internet Archive open-licensed items or downloading a specific public URL.
   - Treat Internet Archive `license_id` / `license_status` as metadata, not legal advice; remind the user that composition, recording, arrangement, and MIDI rights are separate.
   - Always check `rights_confirmed: true` with the user before exporting `.lyrapack`.
3. **Separate Transcription Accuracy from Arrangement Playability**:
   - Report `transcription_fidelity` (when a reference MIDI is provided via `evaluate`) separately from `arrangement_playability_vs_input_midi`.
   - Remind the user that `builtin-mono` (YIN) fits solo melodies and struggles with polyphonic chords (`basic-pitch` or `dettato` must be installed separately).
4. **Never Bypass Interactive Playback Confirmation**:
   - `play_in_game` intentionally refuses unattended OS key injection (`blocked_requires_interactive_confirmation`). Instruct the user to preview locally and start Windows playback interactively in the LyraForge Desktop UI after opening Genshin Impact's free-play instrument screen.

## Typical Workflow

1. `search_music` (`query`, `allow_network: false`) or `import_media` (`path` or authorized `url`)
2. If the imported song is audio-only, call `transcribe` (`song_id`, monitor via `get_task_status` if needed)
3. `arrange` (`song_id`, `profile_id`, `style`) — try alternative styles or `transpose` if playability or drop count looks high
4. `evaluate` (`arrangement_id`, optional `compare_with_arrangement_id` and `reference_midi_path`)
5. `preview` (`arrangement_id`) so the user can listen offline
6. `save_to_library` / `export_score` (`midi`, `json`, or user-confirmed `lyrapack`)
