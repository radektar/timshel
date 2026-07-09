"""Generate the monochrome menu-bar sigil (template image) for Timshel.

Per the Claude Design app-redesign handoff (2026-07, screen F): the menu-bar
mark is the 6-bar wave **sigil** (``--logo-sygnet``), rendered as a macOS
template image — fully black pixels + alpha — so macOS tints it for the
light/dark menu bar. Runtime states (recording = +terracotta dot, indexing =
dimmed to 55%) are applied to this same template at runtime, not baked as
separate assets.

Geometry is the source-of-truth token in ``src/ui/theme.py`` (``SIGIL_BARS``),
shared with the app icon.

Usage:
  venv312/bin/python scripts/generate_menu_bar_icons.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.ui.theme import SIGIL_BARS, SIGIL_VIEWBOX  # noqa: E402

OUT_DIR = ROOT / "assets" / "menu_bar"
SS = 4  # supersample for crisp rounded bar caps at tiny sizes
PAD_RATIO = 0.06  # padding around the sigil within the icon box


def _render_sigil(px: int) -> Image.Image:
    """Solid-black wave sigil on transparent, ``px``×``px`` (template image)."""
    s = px * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = s * PAD_RATIO
    box = s - 2 * pad
    scale = box / SIGIL_VIEWBOX
    for x, y, w, h, rx in SIGIL_BARS:
        x0, y0 = pad + x * scale, pad + y * scale
        d.rounded_rectangle(
            (x0, y0, x0 + w * scale, y0 + h * scale),
            radius=rx * scale,
            fill=(0, 0, 0, 255),
        )
    return img.resize((px, px), Image.LANCZOS)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # macOS menu-bar marks are ~18pt; ship @1x and @2x template PNGs.
    for name, px in (("sigil.png", 18), ("sigil@2x.png", 36)):
        out = OUT_DIR / name
        _render_sigil(px).save(out, "PNG")
        print(f"Generated {out.relative_to(ROOT)} ({px}×{px})")


if __name__ == "__main__":
    main()
