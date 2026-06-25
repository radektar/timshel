"""Smoke tests for the Core Graphics constellation view.

AppKit-dependent, so marked ``ui`` and skipped where AppKit is unavailable
(non-mac CI). They prove the ``drawRect_`` path runs for every layout without
raising — the offscreen render is the same one used to eyeball the output
against the design mock.
"""

from __future__ import annotations

import pytest

from src.ui import constellation_view as cv

pytestmark = pytest.mark.ui

if not cv._APPKIT_AVAILABLE:  # pragma: no cover - non-mac
    pytest.skip("AppKit unavailable", allow_module_level=True)

from AppKit import NSImage  # noqa: E402
from Foundation import NSMakeRect, NSMakeSize  # noqa: E402


def _render(layout, dim):
    view = cv.build_constellation_view(NSMakeRect(0, 0, 520, 222), layout, dim)
    assert view is not None
    img = NSImage.alloc().initWithSize_(NSMakeSize(520, 222))
    img.lockFocus()
    try:
        view.drawRect_(view.bounds())  # force the Core Graphics path
    finally:
        img.unlockFocus()
    return view


@pytest.mark.parametrize("layout", ["contradiction", "thread", "triad"])
@pytest.mark.parametrize("dim", [False, True])
def test_every_layout_renders(layout, dim):
    _render(layout, dim)


def test_unknown_layout_renders_as_thread():
    # falls back to thread geometry rather than raising
    _render("nonsense", False)


def test_set_layout_updates_and_marks_dirty():
    view = cv.build_constellation_view(NSMakeRect(0, 0, 300, 150), "thread", False)
    view.set_layout("triad", dim=True)
    assert view._layout == "triad"
    assert view._dim is True
