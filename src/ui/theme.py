"""Aztec earth-tone palette used as accents across the Timshel UI."""

from __future__ import annotations

try:
    from AppKit import NSColor
    _APPKIT_AVAILABLE = True
except ImportError:
    NSColor = None  # type: ignore[assignment]
    _APPKIT_AVAILABLE = False


def _rgb(r: float, g: float, b: float, a: float = 1.0):
    if not _APPKIT_AVAILABLE:
        return None
    return NSColor.colorWithRed_green_blue_alpha_(r, g, b, a)


# Hex codes kept here for documentation and tests; NSColor instances are lazy.
HEX = {
    "terracotta": "#C24010",
    "jade":       "#057857",
    "obsidian":   "#1A1A1F",
    "gold":       "#D6B033",
    "sage_ink":   "#2E4D47",
}


def terracotta():
    """Errors and destructive actions."""
    return _rgb(0.76, 0.25, 0.06)


def jade():
    """Success states (idle/ready, completed transcription)."""
    return _rgb(0.02, 0.47, 0.34)


def obsidian():
    """Dark surface tone for accent panels."""
    return _rgb(0.10, 0.10, 0.12)


def gold():
    """PRO badge accent."""
    return _rgb(0.84, 0.69, 0.20)


def sage_ink():
    """Muted secondary text."""
    return _rgb(0.18, 0.30, 0.28)
