"""Unit tests for the design-system module (`src/ui/style.py`).

This is the L4 "split UI logic into pure functions" layer: the tokens and the
status→symbol / status→role maps are pure and fully tested here, so the menu bar
and the status panel render from verified data instead of scattered if-chains.

The AppKit-dependent factories are smoke-tested only when AppKit is present
(it is on a Mac dev box); the pure logic runs everywhere.
"""

from __future__ import annotations

import pytest

from src.app_status import AppStatus
from src.ui import style

# --------------------------------------------------------------------------- #
# Spacing grid.
# --------------------------------------------------------------------------- #


def test_spacing_is_on_a_4pt_grid_and_ascending():
    assert list(style.SPACING) == sorted(style.SPACING)
    assert all(value % 4 == 0 for value in style.SPACING)
    # The canonical tokens are wired through.
    assert style.SPACE_PADDING == 20
    assert style.SPACE_TIGHT == 8


# --------------------------------------------------------------------------- #
# Type scale.
# --------------------------------------------------------------------------- #


def test_type_scale_has_core_styles_with_sane_values():
    for name in ("headline", "title", "body", "caption"):
        assert name in style.TYPE_SCALE
        size, weight = style.TYPE_SCALE[name]
        assert 10.0 <= size <= 20.0
        assert weight in style._FONT_WEIGHTS
    # Hierarchy: headline larger than body larger than caption.
    assert style.TYPE_SCALE["headline"][0] > style.TYPE_SCALE["body"][0]
    assert style.TYPE_SCALE["body"][0] > style.TYPE_SCALE["caption"][0]


# --------------------------------------------------------------------------- #
# Status → SF Symbol (completeness + validity).
# --------------------------------------------------------------------------- #


def test_every_status_has_a_symbol():
    assert set(style.STATUS_SYMBOLS) == set(
        AppStatus
    ), "STATUS_SYMBOLS must cover every AppStatus exactly"


@pytest.mark.parametrize("status", list(AppStatus))
def test_symbol_names_are_valid_sf_symbol_tokens(status):
    name = style.symbol_name_for_status(status)
    assert name, f"{status} has an empty symbol"
    # SF Symbol names are dot-separated lowercase identifiers.
    assert all(part and part.replace(".", "").isascii() for part in [name])
    assert " " not in name and name == name.lower()


def test_no_emoji_in_symbol_map():
    """The whole point of F-L4: no emoji fallbacks any more."""
    for name in style.STATUS_SYMBOLS.values():
        assert name.isascii(), f"symbol {name!r} is not a plain SF Symbol token"


# --------------------------------------------------------------------------- #
# Status → role (the restrained colour model).
# --------------------------------------------------------------------------- #


def test_every_status_has_a_known_role():
    valid = {"ready", "active", "error"}
    for status in AppStatus:
        assert style.role_for_status(status) in valid


def test_role_assignments_are_semantic():
    assert style.role_for_status(AppStatus.IDLE) == "ready"
    assert style.role_for_status(AppStatus.RECORDER_IDLE) == "ready"
    assert style.role_for_status(AppStatus.TRANSCRIBING) == "active"
    assert style.role_for_status(AppStatus.SCANNING) == "active"
    assert style.role_for_status(AppStatus.ERROR) == "error"


# --------------------------------------------------------------------------- #
# Weight mapping.
# --------------------------------------------------------------------------- #


def test_font_weights_are_ordered():
    w = style._FONT_WEIGHTS
    assert w["regular"] < w["semibold"] < w["bold"]


# --------------------------------------------------------------------------- #
# AppKit factories — only when AppKit is available (Mac dev box).
# --------------------------------------------------------------------------- #

requires_appkit = pytest.mark.skipif(
    not style._APPKIT_AVAILABLE, reason="requires AppKit (PyObjC)"
)


@requires_appkit
def test_sf_symbol_returns_template_image():
    image = style.sf_symbol("gearshape", point=15.0, weight="regular")
    assert image is not None
    assert image.isTemplate()


@requires_appkit
@pytest.mark.parametrize("status", list(AppStatus))
def test_status_symbol_resolves_for_every_status(status):
    # Every name in the map must be a real symbol on this OS (catches typos).
    assert (
        style.status_symbol(status) is not None
    ), f"SF Symbol {style.symbol_name_for_status(status)!r} not found on this macOS"


@requires_appkit
def test_color_for_role_distinguishes_states():
    ready = style.color_for_role("ready")
    active = style.color_for_role("active")
    error = style.color_for_role("error")
    assert ready is not None and active is not None and error is not None
    # ready (jade) and active (terracotta) must be different colours.
    assert ready != active


@requires_appkit
def test_system_font_and_vibrant_view_build():
    assert style.system_font("title") is not None
    assert style.vibrant_view(material="popover") is not None


def test_helpers_are_appkit_optional():
    """Without AppKit the factories return None instead of raising."""
    if style._APPKIT_AVAILABLE:
        pytest.skip("AppKit present; None-path covered by import-guard design")
    assert style.sf_symbol("gearshape") is None
    assert style.system_font("body") is None
    assert style.vibrant_view() is None
