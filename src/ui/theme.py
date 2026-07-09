"""Design tokens for the Timshel UI — single source of truth.

Reconciled to the Claude Design app-redesign handoff (2026-07,
``design-system/app-redesign-2026-07/tokens.css``). Three accent roles are
enforced hard across the redesign (handoff §7):

- **terracotta** — user actions (CTA, selected checkbox, active pull row)
- **jade** — "stays local" (Zachowaj, local markers, index banner)
- **gold** — insight / synthesis / text leaving for the cloud

Hex codes are the reference; NSColor instances are built lazily so this module
imports cleanly off-Mac (tests, asset generators).
"""

from __future__ import annotations

try:
    from AppKit import NSColor
    _APPKIT_AVAILABLE = True
except ImportError:
    NSColor = None  # type: ignore[assignment]
    _APPKIT_AVAILABLE = False


def _hex_to_rgb(hex_str: str) -> tuple:
    h = hex_str.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _rgb(r: float, g: float, b: float, a: float = 1.0):
    if not _APPKIT_AVAILABLE:
        return None
    return NSColor.colorWithRed_green_blue_alpha_(r, g, b, a)


def color(name: str, a: float = 1.0):
    """NSColor for a token in :data:`HEX` (or None off-Mac)."""
    r, g, b = _hex_to_rgb(HEX[name])
    return _rgb(r, g, b, a)


# --------------------------------------------------------------------------- #
# Tokens (source of truth). Grouped by role.
# --------------------------------------------------------------------------- #
HEX = {
    # Accent — terracotta (action). Dark/native family + paper marketing tone.
    "terracotta":         "#C24010",  # base (dark/native action)
    "terracotta_hover":   "#D9542A",  # hover / lit
    "terracotta_pressed": "#9A3009",  # pressed
    "terracotta_paper":   "#AC4B16",  # Poppy — paper/marketing only
    # Accent — jade (local).
    "jade":       "#46B17E",  # dark surface
    "jade_text":  "#8BE0B5",  # jade text on dark
    "jade_ink":   "#1E7A52",  # jade on light
    # Accent — gold (insight / to-cloud).
    "gold":       "#D6B033",
    "gold_glow":  "#F4DD8E",
    "gold_cloud": "#E7B45C",
    # Paper / native surfaces.
    "paper":    "#FFFFFF",
    "panel":    "#F3F1EB",
    "panel_2":  "#ECEAE3",
    "ink":      "#1A1A1A",
    "ink_soft": "#6E6A64",
    "obsidian": "#141414",  # app-icon tile
    # Dark window (Konstelacja) text.
    "window_hi":   "#FAF3E2",
    "window_body": "#C9BBA6",
    # Back-compat alias (older code/tests referenced sage_ink).
    "sage_ink": "#2E4D47",
}

# App-icon mesh (--logo-mesh): gold · blue · jade · peach over a warm base.
# Each stop: (center_x, center_y, radius_x, radius_y, transparent_at, hex) as
# fractions of the mark box. Listed top-to-bottom as in the CSS (first on top).
MESH_STOPS = [
    (0.22, 0.26, 0.58, 0.64, 0.60, "#F2C879"),  # gold
    (0.80, 0.18, 0.54, 0.60, 0.58, "#7FA0F7"),  # blue
    (0.64, 0.90, 0.60, 0.72, 0.62, "#5BC495"),  # jade
    (0.38, 0.70, 0.70, 0.80, 0.70, "#EE9F7E"),  # peach
]
MESH_BASE = "#F4D9A8"

# App sigil (--logo-sygnet): 6 rounded bars = a wave. viewBox 0 0 22 22.
# (x, y, w, h, rx) — the deployable-asset source of the icon + menu-bar mark.
SIGIL_BARS = [
    (2.1, 8.95, 1.8, 4.10, 0.9),
    (5.3, 5.60, 1.8, 10.80, 0.9),
    (8.5, 2.00, 1.8, 18.00, 0.9),
    (11.7, 6.65, 1.8, 8.70, 0.9),
    (14.9, 4.05, 1.8, 13.90, 0.9),
    (18.1, 8.15, 1.8, 5.70, 0.9),
]
SIGIL_VIEWBOX = 22.0


# --------------------------------------------------------------------------- #
# Lazy NSColor accessors (back-compat API).
# --------------------------------------------------------------------------- #
def terracotta():
    """User actions / destructive (base terracotta)."""
    return color("terracotta")


def jade():
    """Local / success states."""
    return color("jade")


def obsidian():
    """App-icon tile / darkest surface."""
    return color("obsidian")


def gold():
    """Insight / synthesis / to-cloud accent."""
    return color("gold")


def sage_ink():
    """Muted secondary text (back-compat)."""
    return color("sage_ink")
