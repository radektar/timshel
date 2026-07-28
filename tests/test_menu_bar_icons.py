"""Menu-bar status icons.

The old shipped ``assets/menu_bar/*.png`` set was retired in the L4 redesign:
icons are now rendered at runtime from SF Symbols via
``style.render_symbol_png`` (see ``src/menu_app.py::_resolve_icon_paths``). SF
Symbols are guaranteed on macOS 12+, which also retires the missing-PNG / emoji
fallback. These tests exercise that real mechanism instead of stale assets, so
they need no Pillow and no checked-in PNGs.
"""

from __future__ import annotations

import pytest

from src.app_status import AppStatus
from src.ui import style

requires_appkit = pytest.mark.skipif(
    not style._APPKIT_AVAILABLE, reason="SF Symbol rendering requires AppKit (PyObjC)"
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@requires_appkit
@pytest.mark.parametrize("status", list(AppStatus))
def test_every_status_renders_a_valid_png(status):
    """Each status maps to an SF Symbol that rasterises to a real PNG."""
    png = style.render_symbol_png(
        style.symbol_name_for_status(status), point=15.0, pixel_size=36
    )
    assert png is not None, f"no icon rendered for {status}"
    assert png[:8] == PNG_MAGIC, f"{status} icon is not a PNG"
    # Catch empty/blown-up renders the way the old size guard did.
    assert 100 < len(png) < 20_000, f"{status} icon size suspicious: {len(png)} bytes"


@requires_appkit
@pytest.mark.parametrize("status", list(AppStatus))
def test_rendered_icon_is_rgba_template(status):
    """Icons must be RGBA with an alpha channel so they adopt the menu-bar tint.

    A template glyph keeps its colour black and carries shape in the alpha
    channel; an opaque or non-alpha image would render as a fixed blob that
    ignores light/dark mode. ``render_symbol_png`` builds template PNGs by
    construction (``setTemplate_(True)`` + a single black draw); this verifies
    the rasterised output kept that structure.
    """
    from AppKit import NSBitmapImageRep
    from Foundation import NSData

    png = style.render_symbol_png(
        style.symbol_name_for_status(status), point=15.0, pixel_size=36
    )
    assert png is not None

    data = NSData.dataWithBytes_length_(png, len(png))
    rep = NSBitmapImageRep.imageRepWithData_(data)
    assert rep is not None, f"{status} icon failed to decode"
    assert rep.hasAlpha(), f"{status} icon has no alpha channel"
    assert (
        rep.samplesPerPixel() == 4
    ), f"{status} icon is not RGBA (samples/pixel={rep.samplesPerPixel()})"
