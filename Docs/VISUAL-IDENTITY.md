# Malinche — visual identity

> The app icon and how the brand's visual language fits together. The UI design
> system (spacing, type scale, SF Symbols, materials) lives in
> [`src/ui/style.py`](../src/ui/style.py) and `src/ui/theme.py`; this doc covers
> the **mark** and the rules around it.

## The mark

A symmetric **bar waveform** on a warm cream squircle, in brand terracotta. It
extends the menu-bar `waveform` SF Symbol into the app icon, so the surface you
see hundreds of times a day and the icon in the Dock speak the same language.

It does two things at once:

- **Waveform / equalizer** — eleven flat-topped bars with a lively, dipping
  rhythm read immediately as audio. This is a transcription app; the mark says so.
- **Talud-tablero** — the bars rise to a centre apex in a stepped, terraced
  envelope, echoing Mesoamerican stepped-pyramid architecture (Templo Mayor).
  The Aztec reference lives *in the form*, not as a glued-on ornament.

There is no monogram. The name's allegory — La Malinche, the interpreter who
turned speech into understanding — is carried by the waveform-as-voice idea, not
by a literal letter.

### Construction

Generated programmatically (vector-precise, reproducible) by
[`assets/gen_icon.py`](../assets/gen_icon.py):

- **Canvas:** 1024×1024 master, supersampled 2× then downscaled (crisp edges).
- **Tile:** superellipse "squircle" (exponent 5), edge = 80.5% of canvas — the
  macOS app-icon grid, leaving transparent padding for the soft contact shadow.
- **Background:** cream, near-flat with a very subtle top-light gradient and a
  faint inner depth pass — material presence without skeuomorphic gloss.
- **Bars:** flat caps (carved-stone feel), heights
  `[0.22, 0.55, 0.38, 0.72, 0.92, 1.0, 0.92, 0.72, 0.38, 0.55, 0.22]`,
  group width 66% of the tile, gaps 66% of bar width.
- **Legibility floor:** designed to hold from 16 px up; detail that dies on
  downscale is not added.

Regenerate with `make icon` (rebuilds `icon_1024.png`, `icon.iconset/`,
`icon.icns`, and the `icon_preview.png` size montage).

## Palette

Single source of truth: [`src/ui/theme.py`](../src/ui/theme.py).

| Role | Colour | Hex |
|---|---|---|
| Primary accent / the mark | Terracotta | `#C24010` |
| Ready / success | Jade | `#057857` |
| PRO badge | Gold | `#D6B033` |
| Tile background | Cream | `#F5E9CE` |
| Dark surface (UI chrome: retired) | Obsidian | `#1A1A1F` |

**One accent rule:** terracotta is the brand. Jade is reserved for the
"ready/done" state and packaging detail; gold only marks PRO. These do **not**
go inside the mark — two colours in the waveform fragments it and dies at small
sizes (tested and rejected). The mark is monochrome terracotta.

## Where the Aztec detail lives

The *greca* (step-fret, rendered here as nested concentric squares) is the
brand's connective tissue — but it belongs on surfaces with room to breathe, not
crammed into a 32 px icon:

- **DMG installer background** — cream field, terracotta band, jade greca
  friezes ([`scripts/gen_dmg_background.py`](../scripts/gen_dmg_background.py)).
- Marketing site, headers, wordmark flourishes (future).

Keeping culture in the *system* rather than the *mark* gives a coherent,
rooted identity without sacrificing the icon's legibility.

## Usage

- **Do** use `assets/icon.icns` for the bundle (wired in `setup_app.py`) and as
  the DMG volume icon (`scripts/create_dmg.sh`).
- **Do** let the menu-bar status icons stay as SF Symbols (`waveform` family) —
  they are the mark's small-scale sibling and adapt to light/dark automatically.
- **Don't** place the waveform on busy backgrounds; it wants the cream tile or
  clear space.
- **Don't** recolour the bars or add a second colour inside the mark.
- **Don't** add a greca border/corner to the icon — it's packaging-layer only.

## Files

- `assets/gen_icon.py` — the generator (single source for the mark)
- `assets/icon_1024.png` — master
- `assets/icon.iconset/` — macOS size set (16–512 @1×/@2×)
- `assets/icon.icns` — compiled bundle + DMG volume icon
- `assets/icon_preview.png` — size-legibility montage (light + dark)
- `assets/dmg_background.png` — installer artwork (greca layer)
