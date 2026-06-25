"""Tests for the gold-dot badged menu-bar icon (style.render_symbol_png dot)."""

from __future__ import annotations

import pytest

from src.ui import style

pytestmark = pytest.mark.ui

if not getattr(style, "_APPKIT_AVAILABLE", False):  # pragma: no cover - non-mac
    pytest.skip("AppKit unavailable", allow_module_level=True)


def test_plain_and_badged_both_render():
    plain = style.render_symbol_png("waveform", pixel_size=36)
    badged = style.render_symbol_png("waveform", pixel_size=36, dot=True)
    assert plain and badged
    assert isinstance(plain, bytes) and isinstance(badged, bytes)


def test_badge_changes_the_pixels():
    plain = style.render_symbol_png("waveform", pixel_size=36)
    badged = style.render_symbol_png("waveform", pixel_size=36, dot=True)
    # the gold dot + grey tone make the badged variant a different image
    assert plain != badged


def test_missing_symbol_returns_none():
    assert style.render_symbol_png("definitely.not.a.symbol.xyz", dot=True) is None
