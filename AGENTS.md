# LyraForge — Maintainer Rules (`AGENTS.md`)

> Detailed playbook: [docs/MAINTAINER_WORKFLOW.md](docs/MAINTAINER_WORKFLOW.md) · AI/MCP: [docs/AI_INTEGRATION.md](docs/AI_INTEGRATION.md)

## 1. Mission & Non-Negotiable Constraints
- Build an independent desktop product that converts user-authorized audio/video/MIDI into playable arrangements for Genshin Impact's **free-play instrument interface** (NOT a falling-note minigame bot). Read `docs/PROJECT_SPEC.md` and `docs/PROGRESS.md` before changes.
- **License**: **GNU GPL-3.0** (`LICENSE`, `docs/LICENSE_AUDIT.md`) is final per owner decision. Never replace GPL-3.0 or bypass third-party attribution/model license boundaries.
- **Game & Data Safety**: Never read/inject/alter game memory, hook processes, or bypass anti-cheat/DRM. Windows `SendInput` requires explicit interactive user confirmation and focus loss/ESC key release; MCP `play_in_game` stays blocked/gated.
- **No Unfounded Claims**: Only report tests/benchmarks/CI observed after the final edit. Distinguish macOS DryRun/unit checks, GitHub CI (`macos-latest`/`windows-latest`), unverified Windows real-machine Genshin Impact playback, and missing external tools (`ffmpeg`, `basic-pitch`, `dettato`).

## 2. Architecture & Security Invariants
- Keep `src/lyraforge/music_core` headless & pure cross-platform (enforced by `tests/unit/test_layering.py`). Isolate Win32 APIs strictly in `playback/windows/` and `secrets_win32.py`.
- Runtime app must **never** require paid API keys or Antigravity CLI. Support Layer 1 (100% offline + deterministic `RuleBasedLLMProvider`), Layer 2 (`lyraforge mcp` + `integrations/` Skills in user's own subscribed client without touching OAuth tokens), and optional Layer 3 OpenAI-compatible HTTP endpoints.
- Store HTTP API keys only in OS Keychain / Credential Manager / `0o600` `.lyraforge.secrets.json` / `LYRAFORGE_*` env vars — never plaintext in SQLite, backups, `.lyrapack`, logs, or errors.
- External downloads require `allow_network=True`, DNS-pinned SSRF checks (`sources/url.py`), and auditable CC/PD URL classification (`sources/online.py`; never weak substrings; reject `NoDerivatives`).
- Keep audio transcription accuracy (`transcription_fidelity` vs ground truth) strictly separated from `arrangement_playability_vs_input_midi`.
- **UI Design System Rule**: All desktop frontend work (`apps/desktop/web`) must follow [DESIGN.md](DESIGN.md): use `tokens.css` OKLCH color/spacing tokens only (no literal colors or off-4px spacing), keep the flat hairline surface ladder (no nested cards or middle-dot meta strings), preserve Piano Roll primary viewport priority, and validate with Hallmark `sloplint --scope app`.
- **Documentation Rule**: README.md is the public-facing product homepage, not a development log. Keep detailed implementation status in docs/PROGRESS.md, test metrics in docs/TEST_REPORT.md, roadmap items in docs/ROADMAP.md, and user-facing release changes in CHANGELOG.md. Update README only when product features, user workflows, installation instructions, compatibility, screenshots, or important limitations materially change. Do not append routine review reports, internal bug tracking, CI logs, or temporary development status to README.

## 3. Startup Check (Every New Session)
1. Read `AGENTS.md`, `docs/PROJECT_SPEC.md`, `docs/PROGRESS.md`, and open tasks (`docs/NEXT.md` if present).
2. Inspect local & remote truth (never trust stale caches):
   - `git status --short --branch && git fetch origin --prune && git log -n 6 --oneline`
   - `gh auth status` (if unauthenticated/insufficient scope, ask the user once to run `gh auth login`; never handle/print tokens)
   - `gh pr list --repo PariyaProject/LyraForge --state open` & `uv run python scripts/check_ci.py --sha origin/main`
3. Pick the highest-priority unblocked item: **Security / Data Loss > CI Green > Core Usability > Recognition/Arrangement Quality > Feature Extensions**. Do not stop after one subtask while authorized goal work remains.

## 4. Standard Maintainer Loop (Pre-Authorized Routine Dev)
1. Branch cleanly from `main` using `feat/...` or `fix/...` (preserve uncommitted user work; never `git reset --hard` dirty files).
2. Implement small, testable vertical slices; update tests & docs as needed.
3. Run full local verification after final edits:
   - `pnpm --dir apps/desktop/web install --frozen-lockfile && make check`
   - Re-run `uv run python scripts/eval_transcribers.py` when transcriber/scoring logic changes.
4. Commit clean tracked files only (zero secrets, no temp artifacts), `git push -u origin <branch>`, and create/update a PR with `gh pr create`.
5. Watch real GitHub Actions CI via `uv run python scripts/check_ci.py --sha HEAD --watch` (never declare CI green from local tests alone). On failure, read `--log-failed`, fix, push, and re-verify (max 3 rounds before logging a reproducible blocker Issue/doc note).
6. When PR CI is green and repository branch protections permit, complete authorized squash-merge via `gh pr merge --squash --delete-branch`, update `main`, verify post-merge `main` CI passes (`scripts/check_ci.py --sha main --watch`), update `docs/PROGRESS.md` with exact SHA, PR URL, CI Run URL, and verification output, then move to the next task or report completion.

## 5. High-Risk Actions Requiring Explicit User Confirmation
- Changing license terms, publishing sensitive/private data, deleting user/tracked data destructively, bypassing branch protections or force-pushing, incurring paid API/CI billing, sharing personal OAuth credentials, executing real in-game OS playback, or cutting a formal public stable Release.
- Any user-approved recurring/unattended scheduler must document auth origin, cost caps, pause/kill switch, and retry bounds, and never store personal OAuth sessions in public CI.
