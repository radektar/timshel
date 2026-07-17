#!/usr/bin/env python3
"""Generate DMG installer background — redesign language (paper surface).

Output:
  assets/dmg_background.png   — 600×400 PNG used by scripts/create_dmg.sh

Design (matches the app-redesign system, not the legacy aztec look):
  • Field: light paper gradient (theme panel family) — Finder draws icon
    labels in the SYSTEM appearance colour (black in light mode), so the
    background must be light; a dark field makes labels unreadable.
  • §05 hairlines top/bottom in ink at low alpha
  • A quiet ink chevron between the app icon (175,190) and Applications
    (425,190). No sigil — the app icon already carries the mark.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

WIDTH, HEIGHT = 600, 400
SS = 2  # supersample for crisp lines

# theme.py paper family
PANEL_TOP = (0xF7, 0xF4, 0xEC, 255)
PANEL_BOTTOM = (0xEC, 0xEA, 0xE3, 255)
INK = (0x1A, 0x1A, 0x1A)


def lerp(a, b, t):
    return a + (b - a) * t


def vertical_gradient(size, top, bottom):
    img = Image.new("RGBA", size, top)
    px = img.load()
    w, h = size
    for y in range(h):
        t = y / max(1, h - 1)
        c = tuple(int(lerp(top[i], bottom[i], t)) for i in range(4))
        for x in range(w):
            px[x, y] = c
    return img


def draw_arrow(draw: ImageDraw.ImageDraw, cx: int, cy: int, length: int, color, width: int):
    """The standard DMG drag arrow: a horizontal shaft with a solid head."""
    head_l = int(length * 0.38)
    head_h = int(head_l * 0.9)
    x0 = cx - length // 2
    x1 = cx + length // 2
    shaft_end = x1 - head_l
    draw.line((x0, cy, shaft_end, cy), fill=color, width=width)
    draw.polygon(
        [(shaft_end, cy - head_h // 2), (x1, cy), (shaft_end, cy + head_h // 2)],
        fill=color,
    )


def main() -> int:
    w, h = WIDTH * SS, HEIGHT * SS
    base = vertical_gradient((w, h), PANEL_TOP, PANEL_BOTTOM)
    draw = ImageDraw.Draw(base)

    # The one conventional cue: an arrow on the drag path (icons at 175/425,
    # y=190). Nothing else — a plain, standard macOS installer window.
    # ImageDraw pisze RGBA wprost (bez blendu) — kolor podajemy już zmieszany
    # z tłem: ink @ ~35% nad panelem ≈ neutralny szary.
    draw_arrow(draw, w // 2, 190 * SS, 70 * SS, (168, 165, 158, 255), 7 * SS)

    out = ASSETS / "dmg_background.png"
    base.resize((WIDTH, HEIGHT), Image.LANCZOS).convert("RGB").save(
        out, format="PNG", optimize=True
    )
    print(f"  wrote {out} ({WIDTH}x{HEIGHT})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
