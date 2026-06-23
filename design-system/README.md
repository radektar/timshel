# Malinche — Design System

The shipped landing (`site/index.html`) already carried Malinche's brand: deep terracotta with
jade + gold accents on warm cream, Fraunces + Inter, pill buttons, a Mesoamerican greca motif and
film grain. This design system **captures that language as reusable tokens + components**, using the
semantic token architecture from [handhold.io](https://handhold.io/) (surface / content / border /
interactive) as the scaffolding — but the values are Malinche's own, not handhold's.

Why not handhold's literal colors? handhold's value was its **structure**, not its palette. Adopting
its muted hexes would have flattened a more distinctive, already-shipped brand. So: *handhold
architecture + Malinche values*.

## Structure

```
design-system/
  tokens.css                     # single source of truth
  foundations/
    colors.html                  # @dsCard Colors
    typography.html              # @dsCard Type
    spacing.html                 # @dsCard Spacing
    radius-elevation.html        # @dsCard Foundations
  components/
    buttons.html                 # @dsCard Components — primary / ghost / ghost-dark / input / tag
    surfaces.html                # @dsCard Components — feature step, proof, case, dark turn, signup
    brand.html                   # @dsCard Brand — logo chip, eyebrow, greca, status signals, grain
```

Every preview links `../tokens.css`. The first line of each file is a `<!-- @dsCard ... -->` marker —
that's what the Claude Design pane uses to build cards. Edit a token in `tokens.css` and every
preview (and the landing) updates.

## The character of this system

- **Warm cream, not white.** `--surface-base` is `#F4E9CF`; pure white is reserved for inputs.
- **Three accents, each with a job.** Terracotta = action; jade = "local & private"; gold = insight.
- **Serif + sans pairing.** Fraunces for display/pull-quotes, Inter for UI/body.
- **Pill geometry.** Buttons and inputs are full pills; panels step up through soft radii to 28px.
- **Craft motifs.** Greca step-frieze and film grain (`--motif-greca`, `--motif-grain`) carry the
  Mesoamerican warmth — these are what make it unmistakably Malinche.
- **Borders over shadows.** Elevation is warm-tinted and restrained.

## Landing migration

`site/index.html` no longer defines its own `:root` — it links a site-local copy `site/tokens.css`
(the site deploys from `site/` as web root, so it can't reach `../design-system/`). The copy is
byte-identical to the canonical file. Migration was value-for-value, so the landing renders exactly
as before. **When you change `design-system/tokens.css`, re-copy it to `site/tokens.css`.**

```bash
cp design-system/tokens.css site/tokens.css   # keep landing in sync
```

The component previews above mirror the landing's actual construction (button variants, feature/
proof/case cards, the dark "turn" panel, the signup block, brand marks) — so Claude Design reflects
what's really shipped, and new surfaces can be built from the same parts.

## Preview locally

```bash
open design-system/foundations/colors.html
open design-system/components/surfaces.html
```

## Sync to Claude Design

Run the `/design-sync` skill (drives the `DesignSync` tool) against a `DESIGN_SYSTEM` project on
claude.ai/design. It finalizes a plan over `design-system/**`, uploads the files, and cards build
automatically from the `@dsCard` markers. Keep syncs incremental — one component at a time.
