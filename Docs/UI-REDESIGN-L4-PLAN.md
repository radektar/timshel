# L4 — UI redesign plan (native-premium, PyObjC)

**Status:** Proposed — pending approval
**Date:** 2026-06-15
**Decisions locked (sparring session):**
- **Stack:** polish in PyObjC, no Swift. Ships with v2.0.0 GA.
- **Dropdown:** replace the flat `NSMenu` with a custom **NSPopover** status panel.
- **Brand:** restrained — system materials + **one** accent (terracotta `#C24010`).
  Jade only for the "done/ready" status dot; gold only on the PRO badge.
  Obsidian/sage retired from UI chrome.

> Goal: stop looking like a 2009 dialog box; feel like a deliberately designed
> macOS 26 (Tahoe) menu-bar app — without a SwiftUI rewrite. This dev machine
> runs Tahoe (Darwin 25.3), so the native look is verifiable in place.

## What actually reads as "generic" today (audit)

1. Menu-bar state icons fall back to **emoji** (🟢🟡) — `recorder_idle/pending.png` don't exist.
2. Windows use hand-placed `NSMakeRect` frames — arbitrary spacing, no hierarchy.
3. **Zero** materials/vibrancy — everything flat and opaque.
4. Emoji in wizard titles (🎙️📁🔐) instead of SF Symbols.
5. The first-run wizard is a chain of `rumps.alert` — the most soulless surface.

What is **correct** and stays: the status item itself, native open/save panels,
Dark Mode + Retina support. The dropdown becomes a panel; the rest is polish.

## Design system (the foundation)

New `src/ui/style.py` — pure, testable tokens + AppKit factory helpers:

- **Color:** system semantic colors everywhere (`labelColor`, `secondaryLabelColor`,
  materials). Accent = terracotta for primary buttons / active state / PRO.
  Status dot: jade = ready/done, terracotta = error, secondaryLabel = idle.
- **Type scale:** Title 15 semibold · Body 13 regular · Caption 11 secondary.
  Logs keep SF Mono. (System font via `NSFont.systemFontOfSize:weight:`.)
- **Spacing:** 8pt grid — window padding 20, group gap 16, control gap 12, tight 8.
- **SF Symbols:** `sf_symbol(name, point, weight)` → template `NSImage`
  (`systemSymbolName:`). Always present on macOS 12+, so this also kills the
  missing-asset/emoji problem.
- **Vibrancy:** `vibrant_view(material)` → configured `NSVisualEffectView`
  (`.popover` / `.sidebar` / `.menu`, `withinWindow`, follows active state).

State → SF Symbol map (replaces all menu-bar PNGs + emoji):

| State | Symbol |
|---|---|
| idle | `waveform` |
| scanning | `magnifyingglass` |
| transcribing | `waveform.badge.mic` |
| downloading | `arrow.down.circle` |
| migrating | `arrow.triangle.2.circlepath` |
| recorder idle/pending | `externaldrive` / `externaldrive.badge.plus` |
| error | `exclamationmark.triangle` |

## Phases (each independently shippable)

### Phase 1 — Design system + tests
`src/ui/style.py` (tokens, `sf_symbol`, `vibrant_view`, label/button factories).
Pure functions (state→symbol, type scale, accent resolution) are unit-tested —
**this is also where the strategy doc's L4 "split UI logic into pure functions"
lands.** Risk: low. Unlocks every later phase.

### Phase 2 — Menu bar: SF Symbols + NSPopover panel
- `StatusPanelController` (PyObjC): `NSPopover` with a custom content view —
  status header + live progress row + recent transcriptions + footer
  (Settings / PRO / Quit). Left-click toggles the panel; **right-click keeps a
  minimal native menu** (Settings, Quit) — standard macOS pattern.
- Status-item button now renders an SF Symbol (no emoji, no missing PNGs).
- Panel **view-model is pure and tested** (what rows, what progress, what state);
  the AppKit view is a thin renderer.
- Biggest single "not a system app" win.

### Phase 3 — Windows restyle on the design system
Settings, Log viewer, Download window: wrap content in `NSVisualEffectView`,
replace `NSMakeRect` with `NSStackView` + Auto Layout, apply spacing grid + type
scale + SF Symbols. Settings tab bar → `NSToolbar`-style (classic premium prefs).

### Phase 4 — Onboarding window
Replace the `rumps.alert` wizard chain with one vibrant multi-step `NSWindow`
(progress dots, SF Symbol per step, terracotta primary button). Highest
first-impression lever; depends on Phases 1–3.

### Phase 5 — Polish & verify
Remove dead PNG menu-bar assets (now SF Symbols); build against the latest SDK;
run on Tahoe and capture before/after screenshots; refresh `test_menu_bar_icons.py`
(now tests the symbol map, not PNGs) and clear the `Pillow`/`versions_sync` items
from `READINESS-CRITERIA.md` §D while we're in here.

## Verification

Each phase: unit tests for the pure logic + launch the app on this Tahoe machine
(`python src/main.py`) and screenshot the surface. No phase merges without a
visual check, because "premium" is not unit-testable.

## Scope guard / non-goals

- No SwiftUI, no Liquid Glass internals (impossible in PyObjC; not an Apple
  requirement). Parked as a post-GA option — see BACKLOG "Native menu bar wrapper".
- No new colors beyond the locked accent decision.
- Onboarding (Phase 4) is high-value but cuttable if GA timing bites; Phases 1–3
  are the must-haves.

## Recommended order to build

1 → 2 → 3 → (4) → 5. Start with Phase 1; it's the foundation and the L4 tests.
