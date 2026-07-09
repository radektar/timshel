"""Native type ramp for the Konstelacja window — derived from the redesign handoff.

The handoff (§6/§8) specifies the window's type in CSS px. This module maps each
text style to native AppKit: SF Pro via ``NSFont.systemFont(ofSize:weight:)``
(which auto-selects the SF Pro **Text vs Display** optical cut by size — the
20 pt threshold the design request asks about is handled by the system, not us),
SF Mono via ``monospacedSystemFont``. Tracking (the CSS ``em`` letter-spacing)
becomes ``NSKern`` in points (size × em); line-height becomes
``NSParagraphStyle.lineHeightMultiple``.

CSS px are treated as points @1x (Retina scales pt→device automatically) — the
one confirmation still pending from Claude Design; if it comes back different we
change the numbers here, not the call sites.

``SPEC`` is pure data (testable off-Mac). ``attributes(style)`` returns the
NSAttributedString attribute dict when AppKit is present, else ``None``.
"""

from __future__ import annotations

from typing import Dict, Optional

from src.ui import theme

try:
    from AppKit import (
        NSColor,
        NSFont,
        NSFontWeightBold,
        NSFontWeightMedium,
        NSFontWeightRegular,
        NSForegroundColorAttributeName,
        NSKernAttributeName,
        NSFontAttributeName,
        NSParagraphStyleAttributeName,
        NSMutableParagraphStyle,
    )
    _APPKIT = True
except ImportError:  # off-Mac (tests, tooling)
    _APPKIT = False

# Weight keys → CSS weight → NSFontWeight constant (resolved lazily on Mac).
_WEIGHTS = {"regular": 400, "medium": 500, "bold": 700}


def _ns_weight(key: str):
    return {
        "regular": NSFontWeightRegular,
        "medium": NSFontWeightMedium,
        "bold": NSFontWeightBold,
    }[key]


# --------------------------------------------------------------------------- #
# The ramp. Each style:
#   size_pt, weight, tracking_em, line_height (multiple), color (token, alpha),
#   mono (SF Mono), uppercase (a UI hint — the caller uppercases the string).
# Sizes/leading/tracking are the handoff §8 window values.
# --------------------------------------------------------------------------- #
SPEC: Dict[str, dict] = {
    # Reader
    "thesis":        dict(size=24.0, weight="medium",  track=-0.012, lh=1.30, color=("window_hi", 1.0)),
    "question_title":dict(size=23.0, weight="medium",  track=-0.012, lh=1.25, color=("window_hi", 1.0)),
    "eyebrow":       dict(size=11.0, weight="medium",  track=0.10,   lh=1.0,  color=("gold", 1.0), upper=True),
    # Rail
    "rail_title":    dict(size=12.5, weight="bold",    track=0.0,    lh=1.15, color=("window_hi", 1.0)),
    "rail_snippet":  dict(size=11.5, weight="regular", track=0.0,    lh=1.25, color=("window_hi", 0.55)),
    "collapsed_h":   dict(size=10.5, weight="medium",  track=0.10,   lh=1.0,  color=("window_hi", 0.55), upper=True),
    # Chips / buttons
    "chip":          dict(size=12.5, weight="regular", track=0.0,    lh=1.0,  color=("window_hi", 0.90)),
    "button":        dict(size=12.5, weight="medium",  track=0.0,    lh=1.0,  color=("window_hi", 1.0)),
    # Pull results
    "result_date":   dict(size=11.5, weight="medium",  track=0.0,    lh=1.0,  color=("gold", 1.0), mono=True),
    "result_title":  dict(size=13.0, weight="bold",    track=0.0,    lh=1.3,  color=("window_hi", 0.90)),
    "result_quote":  dict(size=12.5, weight="regular", track=0.0,    lh=1.5,  color=("window_hi", 0.66)),
    # Footer / menu / mono
    "footer_counter":dict(size=11.5, weight="regular", track=0.0,    lh=1.0,  color=("window_hi", 0.40), mono=True),
    "menu_item":     dict(size=13.0, weight="regular", track=0.0,    lh=1.0,  color=("window_hi", 0.90)),
    "menu_shortcut": dict(size=11.5, weight="regular", track=0.0,    lh=1.0,  color=("window_hi", 0.40), mono=True),
    # Ask-bar / overlays
    "ask_field":     dict(size=15.0, weight="regular", track=0.0,    lh=1.2,  color=("window_hi", 1.0)),
    "ask_placeholder":dict(size=15.0, weight="regular",track=0.0,    lh=1.2,  color=("window_hi", 0.45)),
    "toast":         dict(size=12.5, weight="medium",  track=0.0,    lh=1.0,  color=("window_hi", 0.90)),
    "trace":         dict(size=12.0, weight="regular", track=0.0,    lh=1.0,  color=("jade_text", 1.0), mono=True),
    "direction":     dict(size=13.0, weight="regular", track=0.0,    lh=1.4,  color=("window_hi", 0.90)),
}


def kern_pt(style: str) -> float:
    """Letter-spacing in points (CSS em × size) — 0 when negligible."""
    s = SPEC[style]
    return round(s["size"] * s["track"], 3)


def is_upper(style: str) -> bool:
    return bool(SPEC[style].get("upper"))


def font(style: str):
    """NSFont for a style (SF Pro / SF Mono), or ``None`` off-Mac."""
    if not _APPKIT:
        return None
    s = SPEC[style]
    w = _ns_weight(s["weight"])
    if s.get("mono"):
        return NSFont.monospacedSystemFontOfSize_weight_(s["size"], w)
    return NSFont.systemFontOfSize_weight_(s["size"], w)


def _color(token: str, alpha: float):
    r, g, b = theme._hex_to_rgb(theme.HEX[token])
    return NSColor.colorWithRed_green_blue_alpha_(r, g, b, alpha)


def attributes(style: str, *, color_alpha: Optional[float] = None) -> Optional[dict]:
    """NSAttributedString attribute dict for a style, or ``None`` off-Mac.

    ``color_alpha`` overrides the ramp's default alpha (e.g. a dimmed row).
    """
    if not _APPKIT:
        return None
    s = SPEC[style]
    para = NSMutableParagraphStyle.alloc().init()
    para.setLineHeightMultiple_(s["lh"])
    token, alpha = s["color"]
    attrs = {
        NSFontAttributeName: font(style),
        NSForegroundColorAttributeName: _color(token, color_alpha if color_alpha is not None else alpha),
        NSParagraphStyleAttributeName: para,
    }
    k = kern_pt(style)
    if abs(k) > 0.01:
        attrs[NSKernAttributeName] = k
    return attrs
