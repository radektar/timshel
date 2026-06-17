#!/usr/bin/env python3
"""Generate the Malinche app icon — a clean terracotta waveform on a cream squircle.

The mark extends the menu-bar ``waveform`` SF Symbol into the app icon: a
symmetric bar waveform (low → high → low), centred on a warm cream tile, in the
brand terracotta. No skeuomorphic gradient, no monogram — it matches the
restrained macOS-native language of the L4 UI redesign.

Outputs (Track A of the visual-identity refresh):
  assets/icon_1024.png    — 1024×1024 master (also re-runnable from theme colours)
  assets/icon.iconset/*   — full macOS size set (16–512 @1×/@2×)
  assets/icon.icns        — compiled bundle icon (py2app + DMG volicon)
  assets/icon_preview.png — side-by-side montage at 512/128/64/32/16 on light+dark

Colours are sourced from src/ui/theme.py (single source of truth), mirroring
scripts/gen_dmg_background.py.

Usage:
  venv312/bin/python assets/gen_icon.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

# --- Brand colours (sync with src/ui/theme.py HEX) -------------------------
TERRACOTTA = (194, 64, 16, 255)   # #C24010 — the mark
JADE = (5, 120, 87, 255)          # #057857 — reserved accent (off by default)
CREAM_TOP = (250, 242, 221, 255)  # subtle top lightening
CREAM_BOTTOM = (242, 228, 198, 255)

# --- Geometry --------------------------------------------------------------
SIZE = 1024            # final master edge
SS = 2                 # supersample factor for crisp squircle + bar caps
TILE_RATIO = 0.805     # rounded square edge as a fraction of the canvas (macOS grid)
SQUIRCLE_N = 5.0       # superellipse exponent → continuous "squircle" corner

# Waveform: 11 flat-topped bars — a lively audio rhythm (internal dips) inside a
# pyramidal envelope, so it reads as both an equalizer and a talud-tablero
# (Aztec stepped pyramid). Flat tops = carved stone; the dips = audio.
BAR_HEIGHTS = [0.22, 0.55, 0.38, 0.72, 0.92, 1.0, 0.92, 0.72, 0.38, 0.55, 0.22]
GROUP_WIDTH_RATIO = 0.66   # bar group width as fraction of the tile edge
BAR_MAX_HALF_RATIO = 0.34  # tallest bar half-height as fraction of the tile edge
GAP_RATIO = 0.66           # gap width as a fraction of bar width
CAP_RATIO = 0.0            # bar-cap radius as a fraction of bar width (0 = flat/stepped)

JADE_BASELINE = False      # subtle jade axis under the bars — restrained: off


def lerp(a, b, t):
    return a + (b - a) * t


def _vertical_gradient(size, top, bottom):
    img = Image.new("RGBA", (size, size), top)
    px = img.load()
    for y in range(size):
        t = y / max(1, size - 1)
        c = tuple(int(lerp(top[i], bottom[i], t)) for i in range(4))
        for x in range(size):
            px[x, y] = c
    return img


def _squircle_mask(size, edge, n=SQUIRCLE_N):
    """Anti-aliased superellipse (squircle) alpha mask, centred."""
    mask = Image.new("L", (size, size), 0)
    px = mask.load()
    cx = cy = size / 2.0
    a = edge / 2.0
    # Soft 1px edge via distance to the superellipse boundary.
    for y in range(size):
        ny = (y + 0.5 - cy)
        for x in range(size):
            nx = (x + 0.5 - cx)
            r = (abs(nx / a) ** n + abs(ny / a) ** n)
            if r <= 1.0:
                px[x, y] = 255
    return mask


def _draw_waveform(draw: ImageDraw.ImageDraw, size, edge):
    cx = cy = size / 2.0
    group_w = edge * GROUP_WIDTH_RATIO
    n = len(BAR_HEIGHTS)
    # group_w = n*bar + (n-1)*gap ; gap = GAP_RATIO*bar
    bar_w = group_w / (n + (n - 1) * GAP_RATIO)
    gap = bar_w * GAP_RATIO
    max_half = edge * BAR_MAX_HALF_RATIO
    cap = bar_w * CAP_RATIO

    start_x = cx - group_w / 2.0

    if JADE_BASELINE:
        bl_w = max(2.0, bar_w * 0.22)
        draw.rounded_rectangle(
            (start_x, cy - bl_w / 2, start_x + group_w, cy + bl_w / 2),
            radius=bl_w / 2, fill=JADE,
        )

    for i, h in enumerate(BAR_HEIGHTS):
        x0 = start_x + i * (bar_w + gap)
        x1 = x0 + bar_w
        half = max_half * h
        box = (x0, cy - half, x1, cy + half)
        if cap >= 1:
            draw.rounded_rectangle(box, radius=cap, fill=TERRACOTTA)
        else:
            draw.rectangle(box, fill=TERRACOTTA)


def build_master() -> Image.Image:
    """Render the 1024 master (supersampled, then downscaled)."""
    s = SIZE * SS
    edge = s * TILE_RATIO

    # 1. Cream tile clipped to the squircle.
    tile = _vertical_gradient(s, CREAM_TOP, CREAM_BOTTOM)
    mask = _squircle_mask(s, edge)
    tile.putalpha(mask)

    # 2. Very subtle inner depth: faint top highlight + bottom shade.
    depth = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    dd = ImageDraw.Draw(depth)
    off = (s - edge) / 2.0
    dd.rounded_rectangle(
        (off, off, s - off, off + edge * 0.5),
        radius=edge * 0.22, fill=(255, 255, 255, 26),
    )
    dd.rounded_rectangle(
        (off, off + edge * 0.55, s - off, s - off),
        radius=edge * 0.22, fill=(60, 40, 20, 16),
    )
    depth = depth.filter(ImageFilter.GaussianBlur(radius=s * 0.03))
    depth.putalpha(Image.composite(depth.getchannel("A"), Image.new("L", (s, s), 0), mask))
    tile = Image.alpha_composite(tile, depth)

    # 3. The waveform mark.
    mark = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    _draw_waveform(ImageDraw.Draw(mark), s, edge)
    tile = Image.alpha_composite(tile, mark)

    # 4. Soft contact shadow beneath the tile, within the transparent padding.
    shadow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle(
        (off, off + edge * 0.04, s - off, s - off + edge * 0.04),
        radius=edge * 0.22, fill=(20, 14, 8, 70),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=s * 0.02))
    out = Image.alpha_composite(shadow, tile)

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
