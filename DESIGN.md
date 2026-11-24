# Design: LyraForge Studio

The locked desktop design system for `apps/desktop/web`. Every future UI change and every agent session must follow this specification and read `apps/desktop/web/src/styles/tokens.css` as the single source of truth.

## 1. System Direction
- **Genre / Scope**: `atmospheric` · `app screen` (`--scope app`)
- **Theme Reference**: Hallmark `Darkroom` (dealt `2/3`, seed `desktop-music-transcription-piano-d68c·700e5137·2026-11-24·r0`), adapted for a professional desktop DAW and free-play instrument workbench (**Studio Obsidian + Warm Amber Safelight**)
- **Posture**: `restrained` (amber accent kept strictly under ~5% of viewport as primary CTA, active playhead, selected state, and focus signal)
- **Axes**: `dark / grotesk-sans / chromatic-amber` · `still` motion

## 2. Tokens (`apps/desktop/web/src/styles/tokens.css`)
All colors use OKLCH with subtle warm obsidian tint (`hue ~55–78`). **Never** place raw hex, `rgb()`, `rgba()`, or `oklch()` literals in `global.css`, `.vue` `<style>` blocks, or inline `:style` attributes.

```css
:root {
  color-scheme: dark;

  /* Neutral Obsidian Surfaces */
  --color-paper: oklch(12.5% 0.008 55);
  --color-paper-2: oklch(16% 0.008 55);
  --color-paper-3: oklch(20.5% 0.009 55);
  --color-paper-4: oklch(25% 0.010 55);

  /* Fibre-White Ink Ladder */
  --color-ink: oklch(93% 0.010 78);
  --color-ink-2: oklch(81% 0.011 72);
  --color-muted: oklch(67% 0.011 65);

  /* Structural Rules & Field Edges */
  --color-rule: oklch(27% 0.009 55);
  --color-rule-strong: oklch(36% 0.011 58);
  --color-field-edge: oklch(44% 0.012 60);

  /* Warm Studio Amber Safelight */
  --color-accent: oklch(75% 0.155 68);
  --color-accent-hover: oklch(80% 0.155 70);
  --color-accent-active: oklch(68% 0.145 64);
  --color-accent-deep: oklch(24% 0.045 64);
  --color-accent-border: oklch(48% 0.105 64);
  --color-accent-ink: oklch(13% 0.010 55);
  --color-focus: oklch(82% 0.16 74);

  /* Semantic Statuses */
  --color-ok: oklch(74% 0.13 158);
  --color-ok-surface: oklch(21% 0.04 158);
  --color-ok-border: oklch(42% 0.08 158);
  --color-warn: oklch(78% 0.14 82);
  --color-warn-surface: oklch(22% 0.045 78);
  --color-warn-border: oklch(46% 0.095 78);
  --color-danger: oklch(64% 0.19 25);
  --color-danger-hover: oklch(69% 0.19 25);
  --color-danger-ink: oklch(96% 0.008 25);
  --color-danger-surface: oklch(21% 0.06 25);
  --color-danger-border: oklch(45% 0.13 25);

  /* Piano Roll & 21-Key Instrument */
  --color-note-kept: oklch(73% 0.135 68);
  --color-note-kept-ink: oklch(13% 0.010 55);
  --color-note-kept-edge: oklch(84% 0.10 72);
  --color-note-adjusted: oklch(68% 0.12 225);
  --color-note-adjusted-ink: oklch(13% 0.010 225);
  --color-note-selected: oklch(90% 0.09 82);
  --color-note-selected-ink: oklch(13% 0.010 55);
  --color-note-selected-ring: oklch(75% 0.155 68);
  --color-lane-alt: oklch(14% 0.008 55);
  --color-grid-line: oklch(22% 0.008 55);
  --color-grid-major: oklch(30% 0.009 55);
  --color-octave-high: oklch(75% 0.155 68);
  --color-octave-mid: oklch(67% 0.011 65);
  --color-octave-low: oklch(66% 0.10 225);

  /* Spacing (Strict 4px Scale + 2px hairline nudge) */
  --space-3xs: 2px;
  --space-2xs: 4px;
  --space-xs: 8px;
  --space-sm: 12px;
  --space-md: 16px;
  --space-lg: 24px;
  --space-xl: 32px;

  /* Radii & Typography */
  --radius-xs: 2px;
  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-pill: 999px;
}
```

`@media (forced-colors: active)` maps all surface, text, border, accent, and focus tokens to CSS system color keywords (`Canvas`, `CanvasText`, `Highlight`, `HighlightText`, `ButtonFace`, `ButtonText`, `GrayText`).

## 3. Typography
- **Offline UI Stack (`--font-sans`)**: `"Segoe UI Variable Text", "Segoe UI", "PingFang SC", "Microsoft YaHei UI", "Microsoft YaHei", -apple-system, BlinkMacSystemFont, system-ui, sans-serif` (zero external font network requests; renders crisp CJK + Latin on Windows 10/11 WebView2 and macOS WKWebView).
- **Mono Stack (`--font-mono`)**: `"Cascadia Mono", "JetBrains Mono", Consolas, ui-monospace, SFMono-Regular, Menlo, monospace` — strictly reserved for timecodes, MIDI pitches, keycaps, file paths, and MCP code snippets (Gate 64).
- **Weights**: Strictly **3 weights** (`400`, `500`, `600`).
- **Minimum Size**: `12px` (`0.75rem`) minimum across all visible text, badges, captions, and controls (`body` at `14px`).
- **Headings & Figures**: `text-wrap: balance` + `overflow-wrap: break-word; min-inline-size: 0;` on headings; `font-variant-numeric: tabular-nums` on all numeric metrics, progress, and timecodes.

## 4. Layout, Surface Ladder & Anti-Slop Invariants
- **Desktop Frame**: Locked `100dvh` (`overflow-x: clip` on `html`/`body`), left navigation rail (`208px`, collapsing to `60px` at `<=1080px`), 44px top context bar, main workspace, 52px persistent bottom audio transport dock. Full-bleed workspaces (`StudioView`, `LibraryView`) mount flush (`studio-flush`) with independent pane scrollbars (`scrollbar-width: auto` + `scrollbar-color`).
- **Surface Ladder**: `Canvas (--color-paper)` -> `1px Hairline Rule (--color-rule)` -> `Tinted Pane (--color-paper-2)` -> `Control Surface (--color-paper-3)`.
  - **Zero nested cards**: Never place a bordered box or stat card inside another card or pane. Use `<dl class="metric-strip">` separated by `1px` vertical rules, or hairline-divided table/list rows.
  - **Zero middle-dot meta chains**: Never join 3+ metadata items with `·` (use `.meta-row` flex containers with subtle hairline dividers).
  - **Zero en/em dashes (`–` / `—`) in UI copy**: Use commas, colons, parentheses, or `~` for numeric ranges.
  - **Zero gradients & glow shadows**: Flat tonal hierarchy; `--shadow-overlay` reserved solely for modal `<dialog>` and `QueueDrawer` without pairing a heavy blur with a bright border.
- **Piano Roll Priority**: `StudioView` places the 21-key Piano Roll at the center of the viewport (`>= 50%` viewport height on `1440×900` and visible immediately above the fold on `1280×720`), with a collapsible right inspector (`300px`) and toggleable bottom 21-key tactile keyboard dock.

## 5. Controls, Interaction & Windows WebView2 Adaptation
- **Buttons**: One filled amber primary button (`primary` / `btn-primary`) per primary task; secondary actions use `--color-paper-3`; quiet actions use `ghost`; stop/delete use `--color-danger`. Height `32px` (compact DAW/toolbar) or `36px` (standard forms).
- **Eight States**: Every control implements hover (`--color-paper-4` / `--color-accent-hover`), instant `:focus-visible` (`2px solid var(--color-focus)`), `:active:not(:disabled)` (`translateY(1px)`), three-channel `:disabled` (`opacity: 0.55; cursor: not-allowed;` + native `disabled`), inline loading/progress, error, and result state. Zero `transition: all`.
- **IME & Windows DPI**: Single-line Enter handlers (`HomeView`, `LibraryView`, `TranscribeView`) always guard against `event.isComposing || event.keyCode === 229`. All views target `1280×720`, `1366×768`, `1440×900`, and `1920×1080` at 100%–150% Windows DPI with zero horizontal overflow and safe `min-inline-size: 0` wrapping for long CJK/English track titles and local file paths.
- **Native Overlays**: `AboutDialog` uses `<dialog showModal()>` with `closedby="any"` + outside-pointer fallback and `overscroll-behavior: contain`. `QueueDrawer` closes on `Escape`, backdrop click, and explicit close button.

## 6. Exports
`apps/desktop/web/src/styles/tokens.css` is the canonical token file consumed by `apps/desktop/web/src/styles/global.css` and all `.vue` views and components.
