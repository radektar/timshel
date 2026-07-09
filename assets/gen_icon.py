#!/usr/bin/env python3
"""Generate the Timshel app icon — the mesh sigil on an obsidian squircle.

Follows the Claude Design app-redesign handoff (2026-07): the app mark is the
6-bar wave **sigil** (``--logo-sygnet``) filled with the warm **mesh** gradient
(``--logo-mesh``: gold · blue · jade · peach over a warm base), on the obsidian
``#141414`` tile. Geometry + mesh stops are the source-of-truth tokens in
``src/ui/theme.py`` (``SIGIL_BARS`` / ``MESH_STOPS``), mirroring the handoff.

Outputs:
  assets/icon_1024.png    — 1024×1024 master
  assets/icon.iconset/*   — full macOS size set (16–512 @1×/@2×)
  assets/icon.icns        — compiled bundle icon (py2app + DMG volicon)
  assets/icon_preview.png — montage at 512/128/64/32/16 on light + dark

Usage:
  venv312/bin/python assets/gen_icon.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.ui.theme import MESH_BASE, MESH_STOPS, SIGIL_BARS, SIGIL_VIEWBOX, _hex_to_rgb  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

# --- Colours (from the handoff tokens) -------------------------------------
OBSIDIAN = tuple(int(c * 255) for c in _hex_to_rgb("#141414")) + (255,)  # tile

# --- Geometry --------------------------------------------------------------
SIZE = 1024            # final master edge
SS = 2                 # supersample factor for crisp squircle + bar caps
TILE_RATIO = 0.805     # rounded square edge as a fraction of the canvas (macOS grid)
SQUIRCLE_N = 5.0       # superellipse exponent → continuous "squircle" corner
MARK_RATIO = 0.60      # sigil bounding box as a fraction of the tile edge


def _render_mesh(size: int, ox: float, oy: float, mark_edge: float) -> Image.Image:
    """The ``--logo-mesh`` gradient rendered over the mark box (RGB image).

    Each stop is an elliptical radial (centre + x/y radii, color at 0 → transparent
    at ``stop``), painted bottom-up so the first CSS-listed stop ends on top.
    Percentages are relative to the mark box, matching the handoff token.
    """
    yy, xx = np.mgrid[0:size, 0:size].astype("float64")
    xn = (xx + 0.5 - ox) / mark_edge
    yn = (yy + 0.5 - oy) / mark_edge

    img = np.ones((size, size, 3), dtype="float64") * (np.array(_hex_to_rgb(MESH_BASE)) * 255.0)
    for cx, cy, rx, ry, stop, hexc in reversed(MESH_STOPS):
        col = np.array(_hex_to_rgb(hexc)) * 255.0
        d = np.sqrt(((xn - cx) / rx) ** 2 + ((yn - cy) / ry) ** 2)
        a = np.clip(1.0 - d / stop, 0.0, 1.0) ** 1.35
        a = a[..., None]
        img = img * (1.0 - a) + col * a
    return Image.fromarray(img.clip(0, 255).astype("uint8"), "RGB")


def _sigil_mask(size: int, mark_edge: float) -> Image.Image:
    """Alpha mask of the 6-bar wave sigil, centred, scaled to ``mark_edge``."""
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    scale = mark_edge / SIGIL_VIEWBOX
    ox = oy = (size - mark_edge) / 2.0
    for x, y, w, h, rx in SIGIL_BARS:
        x0, y0 = ox + x * scale, oy + y * scale
        d.rounded_rectangle(
            (x0, y0, x0 + w * scale, y0 + h * scale), radius=rx * scale, fill=255
        )
    return mask


def _squircle_mask(size, edge, n=SQUIRCLE_N):
    """Anti-aliased superellipse (squircle) alpha mask, centred (vectorised)."""
    a = edge / 2.0
    yy, xx = np.mgrid[0:size, 0:size].astype("float64")
    nx = (xx + 0.5 - size / 2.0) / a
    ny = (yy + 0.5 - size / 2.0) / a
    r = np.abs(nx) ** n + np.abs(ny) ** n
    # Soft ~1px edge across the superellipse boundary (r == 1).
    edge_px = 2.0 / a
    alpha = np.clip((1.0 - r) / edge_px + 0.5, 0.0, 1.0)
    return Image.fromarray((alpha * 255).astype("uint8"), "L")


def build_master() -> Image.Image:
    """Render the 1024 master (supersampled, then downscaled).

    Obsidian squircle tile → the mesh gradient, clipped to the 6-bar wave sigil.
    """
    s = SIZE * SS
    edge = s * TILE_RATIO
    sq = _squircle_mask(s, edge)

    # 1. Obsidian tile clipped to the squircle.
    tile = Image.new("RGBA", (s, s), OBSIDIAN)
    tile.putalpha(sq)

    # 2. The mesh, clipped to the sigil, over the tile.
    mark_edge = edge * MARK_RATIO
    ox = oy = (s - mark_edge) / 2.0
    mesh = _render_mesh(s, ox, oy, mark_edge).convert("RGBA")
    mesh.putalpha(_sigil_mask(s, mark_edge))
    out = Image.alpha_composite(tile, mesh)

    return out.resize((SIZE, SIZE), Image.LANCZOS)


# macOS iconset members: (filename, pixel edge)
ICONSET = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]


def build_iconset(master: Image.Image, iconset_dir: Path):
    iconset_dir.mkdir(parents=True, exist_ok=True)
    for name, edge in ICONSET:
        img = master if edge == SIZE else master.resize((edge, edge), Image.LANCZOS)
        img.save(iconset_dir / name, format="PNG")


def build_preview(master: Image.Image, out: Path):
    """Montage at decreasing sizes on light + dark to judge small-size legibility."""
    sizes = [512, 128, 64, 32, 16]
    pad = 24
    cell = 512 + pad * 2
    width = sum(s for s in sizes) + pad * (len(sizes) + 1)
    width = max(width, cell)
    strip_h = 512 + pad * 2
    canvas = Image.new("RGBA", (width, strip_h * 2), (255, 255, 255, 255))
    # bottom strip dark
    dark = Image.new("RGBA", (width, strip_h), (30, 30, 34, 255))
    canvas.paste(dark, (0, strip_h))
    for strip, _bg in ((0, None), (strip_h, None)):
        x = pad
        baseline = strip + strip_h - pad
        for s in sizes:
            img = master.resize((s, s), Image.LANCZOS)
            canvas.alpha_composite(img, (x, baseline - s))
            x += s + pad
    canvas.convert("RGB").save(out, format="PNG")


def main() -> int:
    master = build_master()

    master_path = ASSETS / "icon_1024.png"
    master.save(master_path, format="PNG")
    print(f"  wrote {master_path.relative_to(ROOT)} (1024×1024)")

    iconset_dir = ASSETS / "icon.iconset"
    build_iconset(master, iconset_dir)
    print(f"  wrote {iconset_dir.relative_to(ROOT)}/ ({len(ICONSET)} sizes)")

    icns = ASSETS / "icon.icns"
    r = subprocess.run(
        ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"  iconutil failed: {r.stderr.strip()}", file=sys.stderr)
        return 1
    print(f"  wrote {icns.relative_to(ROOT)}")

    preview = ASSETS / "icon_preview.png"
    build_preview(master, preview)
    print(f"  wrote {preview.relative_to(ROOT)} (light + dark montage)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
