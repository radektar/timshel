"""The Insights window (Direction B) — native AppKit, action-engine redesign.

A standalone, resizable ``NSWindow`` that is the *home* for the connections
Timshel finds: a left rail listing the queue, and a scrolling reader that lays
out one connection as **spark → ground → act** (ADR-004 / the dashboard
redesign):

* **spark** — the high-level rationale, with the constellation demoted to a small
  static *sigil* (shape = connection type) in the reader header and rail markers;
* **ground** — the dated, quoted evidence per note, revealed inline on demand so
  the insight survives without fresh memory;
* **act** — the directions become **multi-select**; one shared, pinned handoff bar
  hands the whole selection to the connected LLM (primary CTA) or to a task /
  calendar / clipboard. Odrzuć / Zachowaj live in a pinned footer that is never
  cropped.

Renders from the pure :class:`~src.ui.insight_model.InsightDeck`. Dark surface on
purpose. On resize the window re-renders (a delegate), so layout is absolute and
needs no autoresizing gymnastics. AppKit-optional: :func:`build_dashboard_window`
returns ``None`` without AppKit.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from src.config import config
from src.connections import handoff as ho
from src.connections import validation_signal as vsig
from src.logger import logger
from src.ui import insight_model as im

try:
    import objc
    from AppKit import (
        NSBackingStoreBuffered,
        NSBezierPath,
        NSButton,
        NSColor,
        NSColorSpace,
        NSCursor,
        NSFont,
        NSFontAttributeName,
        NSGradient,
        NSImage,
        NSImageLeft,
        NSImageOnly,
        NSImageView,
        NSMakePoint,
        NSMakeRect,
        NSMakeSize,
        NSScrollView,
        NSTextField,
        NSTrackingActiveAlways,
        NSTrackingArea,
        NSTrackingInVisibleRect,
        NSTrackingMouseEnteredAndExited,
        NSView,
        NSWindow,
        NSWindowStyleMaskClosable,
        NSWindowStyleMaskFullSizeContentView,
        NSWindowStyleMaskMiniaturizable,
        NSWindowStyleMaskResizable,
        NSWindowStyleMaskTitled,
    )
    from Foundation import NSObject

    _APPKIT_AVAILABLE = True
except ImportError:  # pragma: no cover - non-mac
    _APPKIT_AVAILABLE = False


# Dimensions (points).
_WIN_W = 860.0  # fallback only — see _initial_window_size()
_WIN_H = 560.0
_WIN_MIN_W = 740.0
_WIN_MIN_H = 460.0
# The window opens proportional to the screen so it isn't a tiny dialog on a big
# display; clamped so it stays sane on both a 13" laptop and a 27" external.
_WIN_FRAC = 0.62
_WIN_MAX_W = 1800.0
_WIN_MAX_H = 1100.0
_HEADER_H = 40.0
_RAIL_W = 236.0
_PAD = 16.0
_READER_PAD_X = 24.0
# Thesis reading measure — handoff ".thesis max 30em" (em = the 24pt font-size).
# Tunable pending the Claude Design redline; caps the line length on wide windows.
_THESIS_MEASURE = 30.0 * 24.0
_ROW_H = 78.0  # rail row step: 72pt row (9+16+2 + snippet 2 lines + 9) + 6 gap
_FOOTER_H = 46.0
_BAR_H = 48.0
_ASKBAR_H = 56.0  # pull entry strip under the header (recall — Faza 3)
# Radius family (design: one decision, held everywhere — native macOS feel).
_R_CONTROL = 6.0  # buttons, segment track, CTA, icons
_R_CHECK = 5.0    # checkbox
_R_ROW = 12.0     # rows, cards
_R_CARD = 14.0    # rail card / panels


def _initial_window_size():
    """Opening size: ~62% of the visible screen, clamped to a sane range."""
    try:
        from AppKit import NSScreen

        screen = NSScreen.mainScreen()
        if screen is not None:
            vis = screen.visibleFrame()
            w = min(_WIN_MAX_W, max(_WIN_MIN_W, vis.size.width * _WIN_FRAC))
            h = min(_WIN_MAX_H, max(_WIN_MIN_H, vis.size.height * _WIN_FRAC))
            return float(w), float(h)
    except Exception:  # pragma: no cover - headless / non-mac
        pass
    return _WIN_W, _WIN_H


def _c(r: float, g: float, b: float, a: float = 1.0):
    """NSColor from 0–255 channels (the dark-surface literals from the spec)."""
    return NSColor.colorWithRed_green_blue_alpha_(r / 255.0, g / 255.0, b / 255.0, a)


def _cream():
    return _c(250, 243, 226)


def _cream_soft():
    return _c(216, 203, 180)


def _muted():
    return _c(140, 130, 115)


def _gold():
    return _c(244, 221, 142)


def _terracotta():
    # terra on dark (design token --terra #D9542A) — connections / CTA / active.
    return _c(217, 84, 42)


def _terra_deep():
    # --terra-deep #C24010 — CTA fill, checkbox fill (deeper than the accent).
    return _c(194, 64, 16)


def _jade():
    # Keep ("Zachowaj") reads as the local/private affirmative (design token).
    return _c(70, 177, 126)


def _shift(color, toward, amt):
    """Blend ``color`` toward white (``toward=1``) or black (``toward=0``).

    Used to derive hover (brighter) / pressed (darker) variants from a base fill
    so every interactive button reacts without per-call-site colours.
    """
    if color is None:
        return None
    try:
        r = color.redComponent()
        g = color.greenComponent()
        b = color.blueComponent()
        a = color.alphaComponent()
    except Exception:  # pragma: no cover - non-RGB colourspace
        return color
    r += (toward - r) * amt
    g += (toward - g) * amt
    b += (toward - b) * amt
    return NSColor.colorWithRed_green_blue_alpha_(r, g, b, a)


def _hex(hexstr: str):
    """NSColor from a '#RRGGBB' string (falls back to terracotta)."""
    h = (hexstr or "").lstrip("#")
    if len(h) == 6:
        try:
            return _c(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        except ValueError:
            pass
    return _c(217, 84, 42)


if _APPKIT_AVAILABLE:

    class _DashFlippedView(NSView):
        def isFlipped(self):
            return True

    class _DarkBackground(NSView):
        """Window background: a soft dark radial, like the mock."""

        def isFlipped(self):
            return True

        def drawRect_(self, _rect):
            b = self.bounds()
            _c(16, 14, 21).setFill()
            NSBezierPath.bezierPathWithRect_(b).fill()
            grad = NSGradient.alloc().initWithColors_atLocations_colorSpace_(
                [_c(40, 38, 55, 0.6), _c(28, 27, 36, 0.22), _c(16, 14, 21, 0.0)],
                [0.0, 0.5, 1.0],
                NSColorSpace.sRGBColorSpace(),
            )
            if grad is not None:
                center = NSMakePoint(b.size.width * 0.64, 0.0)
                grad.drawFromCenter_radius_toCenter_radius_options_(
                    center, 0.0, center, b.size.height * 1.25, 0
                )

    class _FilterItemView(NSView):
        """View-based NSMenuItem for the rail filter (redesign A3).

        Native NSMenu highlight is the system accent (blue); the redesign wants
        terracotta (§02 gotcha). A view-based item paints its own terracotta bg
        when its enclosing item is highlighted, plus a checkmark on the current
        view and a right-aligned count (gold for 'Nowe').
        """

        def isFlipped(self):
            return True

        def drawRect_(self, _rect):
            from AppKit import (
                NSAttributedString,
                NSFontAttributeName,
                NSForegroundColorAttributeName,
            )

            b = self.bounds()
            spec = getattr(self, "_spec", {})
            item = self.enclosingMenuItem()
            hot = item is not None and item.isHighlighted()

            if hot:
                _c(194, 64, 16).setFill()  # terracotta #C24010
                NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    NSMakeRect(4, 3, b.size.width - 8, b.size.height - 6), 5.0, 5.0
                ).fill()

            def _draw(s, x, color, font, right=None):
                a = NSAttributedString.alloc().initWithString_attributes_(
                    s, {NSFontAttributeName: font, NSForegroundColorAttributeName: color}
                )
                px = x if right is None else right - a.size().width
                a.drawAtPoint_(NSMakePoint(px, (b.size.height - a.size().height) / 2.0))

            body = _c(255, 255, 255) if hot else _c(201, 187, 166)
            if spec.get("checked"):
                _draw("✓", 12.0, body, NSFont.systemFontOfSize_weight_(11.0, 0.0))
            _draw(spec.get("label", ""), 28.0, body,
                  NSFont.systemFontOfSize_weight_(12.5, 0.0))
            n = spec.get("count", 0)
            cnt_color = _c(255, 255, 255) if hot else (
                _gold() if spec.get("is_new") else _c(140, 130, 115)
            )
            _draw(str(n), 0.0, cnt_color,
                  NSFont.monospacedDigitSystemFontOfSize_weight_(11.0, 0.0),
                  right=b.size.width - 14.0)

    class _SigilView(NSView):
        """The demoted constellation: a small static mark whose *shape* encodes
        the connection type (axis = contradiction, convergence = shared thread,
        branching = emergent idea). Drawn in Core Graphics; no animation."""

        def isFlipped(self):
            return True

        def drawRect_(self, _rect):
            b = self.bounds()
            w, h = b.size.width, b.size.height

            def pt(x, y):
                return NSMakePoint(x / 32.0 * w, y / 32.0 * h)

            stroke = _hex(getattr(self, "stroke_hex", "#D9542A"))
            node = _c(194, 64, 16)
            bloom = _gold()
            sw = max(1.0, 1.5 * w / 32.0)
            layout = getattr(self, "layout_key", "thread")

            def line(a, z):
                p = NSBezierPath.bezierPath()
                p.moveToPoint_(a)
                p.lineToPoint_(z)
                p.setLineWidth_(sw)
                stroke.setStroke()
                p.stroke()

            def arc(a, z, ctrl):
                p = NSBezierPath.bezierPath()
                p.moveToPoint_(a)
                p.curveToPoint_controlPoint1_controlPoint2_(z, ctrl, ctrl)
                p.setLineWidth_(sw)
                stroke.setStroke()
                p.stroke()

            def disc(center, r, color):
                color.setFill()
                NSBezierPath.bezierPathWithOvalInRect_(
                    NSMakeRect(center.x - r, center.y - r, 2 * r, 2 * r)
                ).fill()

            nr = max(1.6, 2.5 * w / 32.0)
            br = max(2.0, 3.0 * w / 32.0)

            if layout == "contradiction":
                arc(pt(8, 16), pt(24, 16), pt(16, 6))
                arc(pt(8, 16), pt(24, 16), pt(16, 26))
                disc(pt(16, 16), br, bloom)
                disc(pt(8, 16), nr, node)
                disc(pt(24, 16), nr, node)
            elif layout == "triad":
                for x, y in ((8, 9), (25, 12), (15, 26)):
                    line(pt(16, 16), pt(x, y))
                for x, y in ((8, 9), (25, 12), (15, 26)):
                    disc(pt(x, y), nr, node)
                disc(pt(16, 16), br, bloom)
            else:  # thread (shared) — convergence to an apex bloom
                line(pt(9, 24), pt(16, 9))
                line(pt(23, 24), pt(16, 9))
                disc(pt(9, 24), nr, node)
                disc(pt(23, 24), nr, node)
                disc(pt(16, 9), br, bloom)

    class _FlashOverlay(NSView):
        """Micro-bloom + wash, shown briefly on keep/dismiss."""

        def isFlipped(self):
            return True

        def drawRect_(self, _rect):
            b = self.bounds()
            r, g, bl, a = getattr(self, "bloom", (244, 221, 142, 0.26))
            grad = NSGradient.alloc().initWithColors_atLocations_colorSpace_(
                [_c(r, g, bl, a), _c(16, 14, 21, 0.90)],
                [0.0, 0.64],
                NSColorSpace.sRGBColorSpace(),
            )
            if grad is not None:
                center = NSMakePoint(b.size.width * 0.5, b.size.height * 0.4)
                grad.drawFromCenter_radius_toCenter_radius_options_(
                    center, 0.0, center, b.size.width * 0.6, 0
                )

    def _skeleton_bar(frame, radius=7.0):
        v = NSView.alloc().initWithFrame_(frame)
        v.setWantsLayer_(True)
        if v.layer() is not None:
            v.layer().setBackgroundColor_(_c(255, 255, 255, 0.06).CGColor())
            v.layer().setCornerRadius_(radius)
        return v

    def _label(text, size, color, bold=False):
        field = NSTextField.labelWithString_(text)
        f = NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size)
        field.setFont_(f)
        field.setTextColor_(color)
        return field

    def _wrapping_label(text, size, color, frame, weight_bold=False):
        field = NSTextField.wrappingLabelWithString_(text)
        f = (
            NSFont.boldSystemFontOfSize_(size)
            if weight_bold
            else NSFont.systemFontOfSize_(size)
        )
        field.setFont_(f)
        field.setTextColor_(color)
        field.setSelectable_(False)
        field.setFrame_(frame)
        return field

    def _measure_height(text, size, width):
        """Height a wrapping label needs for ``text`` at ``width`` (avoid clip)."""
        f = NSTextField.wrappingLabelWithString_(text)
        f.setFont_(NSFont.systemFontOfSize_(size))
        sz = f.cell().cellSizeForBounds_(NSMakeRect(0, 0, width, 100000.0))
        return float(sz.height)

    def _eyebrow(text, color):
        return _label((text or "").upper(), 10.5, color)

    def _typo_label(text, style, frame, wrapping=True):
        """Wrapping/label NSTextField styled from the typography ramp (attrs)."""
        from AppKit import NSAttributedString
        from src.ui import typography as _T

        s = (text or "")
        if _T.is_upper(style):
            s = s.upper()
        field = (
            NSTextField.wrappingLabelWithString_(s)
            if wrapping
            else NSTextField.labelWithString_(s)
        )
        attrs = _T.attributes(style)
        if attrs is not None:
            field.setAttributedStringValue_(
                NSAttributedString.alloc().initWithString_attributes_(s, attrs)
            )
        field.setSelectable_(False)
        field.setFrame_(frame)
        return field

    def _typo_width(text, style):
        """Rendered width of ``text`` in ``style`` (kern-aware)."""
        from AppKit import NSAttributedString
        from src.ui import typography as _T

        s = (text or "")
        if _T.is_upper(style):
            s = s.upper()
        attrs = _T.attributes(style)
        if attrs is None:
            return 7.0 * len(s)
        a = NSAttributedString.alloc().initWithString_attributes_(s, attrs)
        return float(a.size().width)

    def _typo_measure(text, style, width):
        """Wrap height for ``text`` in ``style`` at ``width`` (kern+leading aware)."""
        from AppKit import NSAttributedString
        from src.ui import typography as _T

        s = (text or "")
        if _T.is_upper(style):
            s = s.upper()
        f = NSTextField.wrappingLabelWithString_(s)
        attrs = _T.attributes(style)
        if attrs is not None:
            f.setAttributedStringValue_(
                NSAttributedString.alloc().initWithString_attributes_(s, attrs)
            )
        sz = f.cell().cellSizeForBounds_(NSMakeRect(0, 0, width, 100000.0))
        return float(sz.height)

    def _sigil(frame, layout, hexcol):
        v = _SigilView.alloc().initWithFrame_(frame)
        v.layout_key = layout
        v.stroke_hex = hexcol
        return v

    _HOVER_OPTS = (
        NSTrackingMouseEnteredAndExited
        | NSTrackingActiveAlways
        | NSTrackingInVisibleRect
    )

    class _PillButton(NSButton):
        """A borderless pill/icon button with real interactive states.

        The Claude Design system specs hover (brighten + lift), a pressed state
        and ``cursor: pointer`` for every action; a plain borderless ``NSButton``
        gives none of these, so the bar read as inert. This adds: a pointing-hand
        cursor, a hover fill (derived by brightening the base), a darker pressed
        fill, an optional foreground-colour shift (ghost buttons), and a soft
        shadow on hover for the lift. Pure colour swaps on a tracking area — no
        layout churn, so no enter/exit flicker.
        """

        def initWithFrame_(self, frame):
            self = objc.super(_PillButton, self).initWithFrame_(frame)
            if self is None:
                return None
            self.setBordered_(False)
            self.setWantsLayer_(True)
            self._bg = self._bg_hover = self._bg_press = None
            self._fg = self._fg_hover = None
            self._tint = self._tint_hover = None
            self._border = self._border_hover = None
            self._title = ""
            self._hovering = False
            self._pressed = False
            return self

        @objc.python_method
        def configure(self, **kw):
            for k, v in kw.items():
                setattr(self, "_" + k, v)
            self._apply()

        @objc.python_method
        def _apply(self):
            from AppKit import NSAttributedString, NSForegroundColorAttributeName

            layer = self.layer()
            if layer is None:
                return
            if self._pressed and self._bg_press is not None:
                bg = self._bg_press
            elif self._hovering and self._bg_hover is not None:
                bg = self._bg_hover
            else:
                bg = self._bg
            layer.setBackgroundColor_(bg.CGColor() if bg is not None else None)

            border = (
                self._border_hover
                if (self._hovering and self._border_hover is not None)
                else self._border
            )
            if border is not None:
                layer.setBorderWidth_(1.0)
                layer.setBorderColor_(border.CGColor())
            else:
                layer.setBorderWidth_(0.0)

            fg = (
                self._fg_hover
                if (self._hovering and self._fg_hover is not None)
                else self._fg
            )
            if fg is not None and self._title:
                self.setAttributedTitle_(
                    NSAttributedString.alloc().initWithString_attributes_(
                        self._title, {NSForegroundColorAttributeName: fg}
                    )
                )
            tint = (
                self._tint_hover
                if (self._hovering and self._tint_hover is not None)
                else self._tint
            )
            if tint is not None:
                try:
                    self.setContentTintColor_(tint)
                except Exception:  # pragma: no cover - older AppKit
                    pass

            # Soft shadow on hover = the design's 1px "lift", without a frame
            # nudge (which would re-fire the tracking area and flicker).
            if self._hovering:
                layer.setShadowColor_(_c(0, 0, 0).CGColor())
                layer.setShadowOpacity_(0.30)
                layer.setShadowRadius_(5.0)
                layer.setShadowOffset_(NSMakeSize(0, -2))
            else:
                layer.setShadowOpacity_(0.0)

        def updateTrackingAreas(self):
            objc.super(_PillButton, self).updateTrackingAreas()
            for area in list(self.trackingAreas()):
                self.removeTrackingArea_(area)
            self.addTrackingArea_(
                NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
                    self.bounds(), _HOVER_OPTS, self, None
                )
            )

        def resetCursorRects(self):
            self.addCursorRect_cursor_(
                self.bounds(), NSCursor.pointingHandCursor()
            )

        def mouseEntered_(self, event):
            self._hovering = True
            self._apply()

        def mouseExited_(self, event):
            self._hovering = False
            self._pressed = False
            self._apply()

        def mouseDown_(self, event):
            self._pressed = True
            self._apply()
            objc.super(_PillButton, self).mouseDown_(event)
            self._pressed = False
            self._apply()

        def hitTest_(self, point):
            # The whole pill is one target; decorative count/label children (the
            # rail segments) must not swallow the click.
            if objc.super(_PillButton, self).hitTest_(point) is not None:
                return self
            return None

    def _pill_button(title, frame, fg, bg, border, target, action, size=13.0):
        """A text pill button with hover/pressed/cursor states (see _PillButton).

        ``bg``/``border`` may be ``None`` for a ghost button — hover then shifts
        the *text* brighter (the design's Dismiss treatment) instead of the fill.
        """
        btn = _PillButton.alloc().initWithFrame_(frame)
        btn.setFont_(NSFont.systemFontOfSize_(size))
        btn.setTarget_(target)
        btn.setAction_(action)
        if btn.layer() is not None:
            btn.layer().setCornerRadius_(_R_CONTROL)  # design radius family
        if bg is not None:
            bg_hover = _shift(bg, 1.0, 0.12)  # brighten the fill
            bg_press = _shift(bg, 0.0, 0.14)  # darken on press
            fg_hover = None
        else:
            bg_hover = _c(255, 255, 255, 0.06)  # faint wash for ghost buttons
            bg_press = _c(255, 255, 255, 0.10)
            fg_hover = _shift(fg, 1.0, 0.55)  # brighten the label instead
        btn.configure(
            title=title,
            fg=fg,
            fg_hover=fg_hover,
            bg=bg,
            bg_hover=bg_hover,
            bg_press=bg_press,
            border=border,
            border_hover=_shift(border, 1.0, 0.25) if border is not None else None,
        )
        return btn

    def _text_width(text, size):
        """Rendered width of ``text`` at ``size`` — for measured layout."""
        from AppKit import NSAttributedString

        attr = NSAttributedString.alloc().initWithString_attributes_(
            text, {NSFontAttributeName: NSFont.systemFontOfSize_(size)}
        )
        return float(attr.size().width)

    # Maps a handoff tool id to its vendored brand mark (assets/brands/*.svg).
    # The OpenAI mark stands in for ChatGPT. Used as a referral/handoff glyph.
    _BRAND_FILE = {
        "claude": "claude.svg",
        "chatgpt": "openai.svg",
    }

    def _asset_path(rel):
        """Resolve an asset relative path, bundle (.app) first, then dev tree."""
        try:
            from Foundation import NSBundle

            rp = NSBundle.mainBundle().resourcePath()
            if rp:
                p = Path(str(rp)) / rel
                if p.exists():
                    return p
        except Exception:  # pragma: no cover - defensive
            pass
        p = Path(__file__).resolve().parent.parent.parent / "assets" / rel
        return p if p.exists() else None

    def _brand_image(tool, point=15.0):
        """A vendored provider mark as a tintable template ``NSImage``.

        Loaded from ``assets/brands/`` (offline; never fetched at runtime) and
        flagged template so it adopts the surrounding tint on the CTA. Returns
        ``None`` if the asset or SVG support is missing — caller stays text-only.
        """
        fname = _BRAND_FILE.get(tool)
        if not fname:
            return None
        p = _asset_path("brands/" + fname)
        if p is None:
            return None
        img = NSImage.alloc().initWithContentsOfFile_(str(p))
        if img is None:
            return None
        img.setTemplate_(True)
        img.setSize_(NSMakeSize(point, point))
        return img

    def _icon_button(image, tooltip, frame, tint, bg, border, target, action):
        """A compact icon-only pill button with hover/pressed/cursor states.

        Icon-only secondaries read as decoration unless they react — so the
        resting fill is a touch stronger than before and hover brightens both the
        fill and the glyph tint (the design's affordance via colour shift).
        """
        btn = _PillButton.alloc().initWithFrame_(frame)
        btn.setTitle_("")
        if image is not None:
            btn.setImage_(image)
            btn.setImagePosition_(NSImageOnly)
        btn.setTarget_(target)
        btn.setAction_(action)
        if tooltip:
            btn.setToolTip_(tooltip)
        if btn.layer() is not None:
            btn.layer().setCornerRadius_(_R_CONTROL)  # design radius family
        bg_hover = _shift(bg, 1.0, 0.10) if bg is not None else _c(255, 255, 255, 0.12)
        btn.configure(
            tint=tint,
            tint_hover=_shift(tint, 1.0, 0.4),
            bg=bg,
            bg_hover=bg_hover,
            bg_press=_c(255, 255, 255, 0.16),
            border=border,
            border_hover=_shift(border, 1.0, 0.35) if border is not None else None,
        )
        return btn

    class _DashboardController(NSObject):
        """Owns the window and renders the deck; rebuilds on every change."""

        def initWithDeck_callbacks_(self, deck, callbacks):
            self = objc.super(_DashboardController, self).init()
            if self is None:
                return None
            self._deck = deck if deck is not None else im.InsightDeck()
            self._callbacks: Dict[str, Callable] = callbacks or {}
            self._window = None
            self._keep_timer = None
            self._dismiss_timer = None
            self._toast_timer = None
            self._toast = None
            self._transcribing = False
            self._selected: Set[int] = set()
            self._grounded = False
            self._scroll = None
            self._scroll_y = 0.0
            # pull (recall) surface — Faza 3
            self._mode = "insight"          # "insight" (push) | "recall" (pull)
            self._recall = None             # RecallResults view-model when in recall mode
            self._recall_note_ids: List[str] = []  # tag -> note_id for ↗ open
            self._query = ""                # last query text (persists across rebuilds)
            self._recall_loading = False    # search in flight (off the main thread)
            self._recall_status = "ok"      # "ok" | "empty" | "unavailable" (honest states)
            self._pending_recall = None     # worker→main-thread handoff payload
            self._recall_raw: List = []     # raw hits kept for the synthesis escalation
            self._answer = None             # RecallAnswer once synthesized (the LLM door)
            self._answer_loading = False    # synthesis in flight
            self._pending_answer = None     # synth worker→main-thread handoff
            self._synth_note_ids: List[str] = []  # tag -> note_id for answer-card ↗ open
            self._answer_failed = False     # last synthesis attempt returned nothing
            # Monotonic generation token: every new search/navigation bumps it, and
            # an off-thread search OR synthesis result is applied only if its captured
            # epoch still matches — text equality alone can't tell a stale answer
            # (built from old passages) from a fresh one for the same query text.
            self._epoch = 0
            return self

        # -- window lifecycle ------------------------------------------------ #

        @objc.python_method
        def _ensure_window(self):
            if self._window is not None:
                return
            mask = (
                NSWindowStyleMaskTitled
                | NSWindowStyleMaskClosable
                | NSWindowStyleMaskMiniaturizable
                | NSWindowStyleMaskResizable
                | NSWindowStyleMaskFullSizeContentView
            )
            win_w, win_h = _initial_window_size()
            win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, win_w, win_h), mask, NSBackingStoreBuffered, False
            )
            win.setTitle_("Timshel — Konstelacja")
            win.setReleasedWhenClosed_(False)
            win.setTitlebarAppearsTransparent_(True)
            win.setMovableByWindowBackground_(True)
            win.setMinSize_(NSMakeSize(_WIN_MIN_W, _WIN_MIN_H))
            win.setDelegate_(self)
            try:
                from AppKit import NSAppearance

                win.setAppearance_(
                    NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua")
                )
            except Exception:  # pragma: no cover - cosmetic
                pass
            win.center()
            self._window = win
            self._render()

        def showWindow(self):
            existed = self._window is not None
            self._ensure_window()
            win = self._window
            if win is None:  # pragma: no cover - defensive
                return
            # _ensure_window renders on first creation; only re-render on reopen.
            if existed:
                self._render()
            win.makeKeyAndOrderFront_(None)
            try:
                from AppKit import NSApp

                NSApp.activateIgnoringOtherApps_(True)
            except Exception:  # pragma: no cover
                pass

        def windowDidResize_(self, _note):
            # Absolute layout + rebuild beats autoresizing math for a
            # pinned-footer/scrolling reader — but coalesce the rebuild so a
            # live-resize drag doesn't re-measure the whole tree every tick.
            # performSelector:afterDelay: won't fire until the drag's
            # event-tracking run loop ends, so this effectively rebuilds once,
            # on resize-end.
            from Foundation import NSObject

            NSObject.cancelPreviousPerformRequestsWithTarget_selector_object_(
                self, "renderNow:", None
            )
            self.performSelector_withObject_afterDelay_("renderNow:", None, 0.05)

        def renderNow_(self, _arg):
            self._capture_scroll()
            self._render()

        # -- rendering ------------------------------------------------------- #

        @objc.python_method
        def _render(self):
            if self._window is None:
                return
            frame = (
                self._window.contentView().frame()
                if self._window.contentView()
                else NSMakeRect(0, 0, _WIN_W, _WIN_H)
            )
            w = frame.size.width or _WIN_W
            h = frame.size.height or _WIN_H

            bg = _DashFlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
            bg.setWantsLayer_(True)
            if bg.layer() is not None:
                bg.layer().setBackgroundColor_(_c(16, 14, 21).CGColor())
            backdrop = _DarkBackground.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
            bg.addSubview_(backdrop)

            # Position counter moved to the footer; the title-bar keeps only ⌕
            # (redesign). ⌕ accessory is the next increment (title-bar rebuild).
            rail_h = h - _HEADER_H
            rail = self._build_rail(NSMakeRect(0, 0, _RAIL_W, rail_h))
            rail.setFrameOrigin_(NSMakePoint(0, _HEADER_H))
            bg.addSubview_(rail)

            reader_w = w - _RAIL_W
            reader = self._build_reader(NSMakeRect(0, 0, reader_w, rail_h))
            reader.setFrameOrigin_(NSMakePoint(_RAIL_W, _HEADER_H))
            bg.addSubview_(reader)

            self._window.setContentView_(bg)

        @objc.python_method
        def _build_rail(self, frame):
            view = _DashFlippedView.alloc().initWithFrame_(frame)
            wash = NSView.alloc().initWithFrame_(
                NSMakeRect(0, 0, frame.size.width, frame.size.height)
            )
            wash.setWantsLayer_(True)
            if wash.layer() is not None:
                wash.layer().setBackgroundColor_(_c(0, 0, 0, 0.16).CGColor())
            view.addSubview_(wash)

            pad = 12.0
            cy = 13.0
            # Header row: "Podsunięte" (lit — active section) + "Nowe N ⌄" filter
            # trigger (redesign A3: the triage segment becomes a header filter).
            head = _typo_label(
                "Podsunięte", "rail_header", NSMakeRect(pad, cy, 120, 14), wrapping=False
            )
            view.addSubview_(head)
            self._build_rail_filter(view, frame, cy)
            cy += 30

            vis = self._deck.visible()
            if not vis:
                empty = _label("—", 11, _c(111, 102, 90))
                empty.setFrame_(NSMakeRect(pad + 2, cy + 2, frame.size.width - 2 * pad, 14))
                view.addSubview_(empty)
                cy += _ROW_H
            for i, conn in vis:
                self._add_rail_row(
                    view, conn, i, NSMakeRect(8, cy, frame.size.width - 16, _ROW_H - 6)
                )
                cy += _ROW_H

            # "Ostatnie transkrypty" cut per redesign (redesign-changelog):
            # the rail holds Podsunięte + collapsed Zapytałeś only; recents move
            # out of the window. Handler kept as a no-op via an empty path list.
            self._recent_paths = []
            return view

        _FILTER_LABELS = (("new", "Nowe"), ("kept", "Zachowane"), ("dismissed", "Odrzucone"))

        @objc.python_method
        def _build_rail_filter(self, view, frame, cy):
            """The 'Nowe N ⌄' trigger in the rail header → view-based NSMenu (A3)."""
            from src.ui.hover import make_hover_button

            cur = self._deck.view
            label = dict(self._FILTER_LABELS).get(cur, "Nowe")
            n = self._deck.counts().get(cur, 0)
            cnt_style = "rail_count" if cur == "new" else "menu_shortcut"
            # Kern-aware measured layout: [label] 6 [count] 5 [⌄], padded 6 each
            # side; trigger 22pt tall, radius 5 (redline).
            # NSTextField draws with ~2pt internal inset per side — measured
            # widths get +5 slack so the label never truncates ("NOWE"→"NOW").
            SLACK = 5.0
            lw = _typo_width(label, "collapsed_h") + SLACK
            cw = _typo_width(str(n), cnt_style) + SLACK
            PADS, GAP1, GAP2, CARW = 6.0, 5.0, 4.0, 12.0
            tw = PADS + lw + GAP1 + cw + GAP2 + CARW + PADS
            tx = frame.size.width - 12.0 - tw
            trig = make_hover_button(NSMakeRect(tx, cy - 4, tw, 22)) or (
                NSButton.alloc().initWithFrame_(NSMakeRect(tx, cy - 4, tw, 22))
            )
            trig.setTitle_("")
            trig.setBordered_(False)
            trig.setTarget_(self)
            trig.setAction_("railFilterClicked:")
            if trig.layer() is not None:
                trig.layer().setCornerRadius_(5.0)
            x = PADS
            lab = _typo_label(label, "collapsed_h", NSMakeRect(x, 4, lw, 14), wrapping=False)
            trig.addSubview_(lab)
            x += lw + GAP1
            cnt = _typo_label(str(n), cnt_style, NSMakeRect(x, 4, cw, 14), wrapping=False)
            trig.addSubview_(cnt)
            x += cw + GAP2
            car = _label("⌄", 10.0, _muted())
            car.setFrame_(NSMakeRect(x, 4, CARW, 14))
            trig.addSubview_(car)
            view.addSubview_(trig)

        def railFilterClicked_(self, sender):
            from AppKit import NSMenu, NSMenuItem

            counts = self._deck.counts()
            menu = NSMenu.alloc().init()
            menu.setAutoenablesItems_(False)
            for key, label in self._FILTER_LABELS:
                it = NSMenuItem.alloc().init()
                it.setTarget_(self)
                it.setAction_("railFilterPicked:")
                it.setRepresentedObject_(key)
                v = _FilterItemView.alloc().initWithFrame_(NSMakeRect(0, 0, 210, 28))
                v._spec = dict(
                    label=label, count=counts.get(key, 0),
                    checked=(key == self._deck.view), is_new=(key == "new"),
                )
                it.setView_(v)
                menu.addItem_(it)
            menu.popUpMenuPositioningItem_atLocation_inView_(
                None, NSMakePoint(0, sender.frame().size.height + 2), sender
            )

        def railFilterPicked_(self, sender):
            key = sender.representedObject()
            if key:
                self._deck.set_view(key)
                self._reset_card_state()
                self._render()

        def _add_rail_row(self, view, conn, index, frame):
            from src.ui.hover import make_hover_button

            from src.ui import style

            btn = make_hover_button(frame) or NSButton.alloc().initWithFrame_(frame)
            btn.setTitle_("")
            btn.setBordered_(False)
            btn.setTarget_(self)
            btn.setAction_("railRowClicked:")
            btn.setTag_(index)
            active = index == self._deck.active_index
            kept = self._deck.is_kept(index)
            if btn.layer() is not None:
                # radius 8 per the row redline (cards keep _R_ROW).
                btn.layer().setCornerRadius_(8.0)
                if active:
                    btn.layer().setBackgroundColor_(_c(255, 255, 255, 0.07).CGColor())

            if active:
                # Gold bar = the insight role; the TITLE stays full white.
                bar = NSView.alloc().initWithFrame_(
                    NSMakeRect(1, 11, 2.5, frame.size.height - 22)
                )
                bar.setWantsLayer_(True)
                if bar.layer() is not None:
                    bar.layer().setBackgroundColor_(_gold().CGColor())
                    bar.layer().setCornerRadius_(1.25)
                btn.addSubview_(bar)

            # Redline: padding 9×8, sigil 18, title 12.5/700 (1 line, truncated),
            # snippet 11.5 clamped to 2 lines with an ellipsis — never clipped.
            btn.addSubview_(_sigil(NSMakeRect(8, 9, 18, 18), conn.layout(), conn.resolved_tcolor()))

            text_x = 34.0
            text_w = frame.size.width - text_x - 8.0
            lab = _typo_label(
                conn.resolved_label(),
                "rail_title" if active else "rail_title_quiet",
                NSMakeRect(text_x, 9, text_w, 16),
                wrapping=False,
            )
            lab.setLineBreakMode_(4)  # truncate tail
            btn.addSubview_(lab)

            snip = _typo_label(
                conn.snippet, "rail_snippet",
                NSMakeRect(text_x, 27, text_w, frame.size.height - 27 - 8),
            )
            snip.setMaximumNumberOfLines_(2)
            try:
                snip.cell().setTruncatesLastVisibleLine_(True)
            except Exception:  # pragma: no cover - older AppKit
                pass
            btn.addSubview_(snip)

            if kept:
                mark = style.sf_symbol("bookmark.fill", point=11.0, weight="regular")
                if mark is not None:
                    miv = NSImageView.alloc().initWithFrame_(
                        NSMakeRect(frame.size.width - 22, 9, 12, 14)
                    )
                    miv.setImage_(mark)
                    try:
                        miv.setContentTintColor_(_c(139, 224, 181))  # jade-text
                    except Exception:  # pragma: no cover
                        pass
                    btn.addSubview_(miv)
                btn.setAlphaValue_(0.5)
            view.addSubview_(btn)

        # -- reader ---------------------------------------------------------- #

        @objc.python_method
        def _build_reader(self, frame):
            view = _DashFlippedView.alloc().initWithFrame_(frame)
            div = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 1, frame.size.height))
            div.setWantsLayer_(True)
            if div.layer() is not None:
                div.layer().setBackgroundColor_(_c(255, 255, 255, 0.07).CGColor())
            view.addSubview_(div)

            # Stały ask-bar cut per redesign (changelog): the pull entry moves to
            # the ⌥Space overlay (ekran C) + ⌕ in the title-bar; the reader
            # content now starts directly under the native titlebar. In Pytanie
            # the question becomes the reader title, not a field.
            top = 0.0
            if self._mode == "recall":
                self._build_recall_reader(view, frame, top)
            else:
                self._build_insight_reader(view, frame, top)
            return view

        @objc.python_method
        def _build_insight_reader(self, view, frame, top):
            conn = self._deck.active()
            if conn is None:
                if self._transcribing:
                    self._build_skeleton(view, frame)
                    return
                if not self._deck.is_empty:
                    # The deck has connections, just none in the current view.
                    title, subtitle = self._EMPTY_VIEW_COPY.get(
                        self._deck.view, (None, None)
                    )
                    self._build_empty(view, frame, title, subtitle)
                    return
                self._build_empty(view, frame)
                return

            has_sel = bool(self._selected)
            bar_h = _BAR_H if has_sel else 0.0
            scroll_h = frame.size.height - _FOOTER_H - bar_h - top

            # scrolling document (spark + ground + directions)
            scroll = NSScrollView.alloc().initWithFrame_(
                NSMakeRect(0, top, frame.size.width, scroll_h)
            )
            scroll.setHasVerticalScroller_(True)
            scroll.setAutohidesScrollers_(True)
            scroll.setDrawsBackground_(False)
            scroll.setBorderType_(0)
            doc, content_h = self._build_reader_content(frame.size.width, conn)
            doc.setFrame_(
                NSMakeRect(0, 0, frame.size.width, max(content_h, scroll_h))
            )
            scroll.setDocumentView_(doc)
            self._scroll = scroll
            # Preserve scroll position across the full rebuild — otherwise ticking
            # a direction (which lives below the fold) or expanding evidence would
            # jump the reader back to the top each time.
            if self._scroll_y > 0:
                clip = scroll.contentView()
                clip.scrollToPoint_(NSMakePoint(0, self._scroll_y))
                scroll.reflectScrolledClipView_(clip)
            view.addSubview_(scroll)

            # pinned handoff bar (only when ≥1 direction selected)
            if has_sel:
                self._build_handoff_bar(
                    view,
                    NSMakeRect(0, frame.size.height - _FOOTER_H - bar_h, frame.size.width, bar_h),
                    len(self._selected),
                )

            # pinned quiet footer — never cropped
            self._build_footer(
                view, NSMakeRect(0, frame.size.height - _FOOTER_H, frame.size.width, _FOOTER_H)
            )

        @objc.python_method
        def _build_recall_reader(self, view, frame, top):
            scroll_h = frame.size.height - _FOOTER_H - top
            scroll = NSScrollView.alloc().initWithFrame_(
                NSMakeRect(0, top, frame.size.width, scroll_h)
            )
            scroll.setHasVerticalScroller_(True)
            scroll.setAutohidesScrollers_(True)
            scroll.setDrawsBackground_(False)
            scroll.setBorderType_(0)
            doc, content_h = self._build_recall_content(frame.size.width, self._recall)
            doc.setFrame_(NSMakeRect(0, 0, frame.size.width, max(content_h, scroll_h)))
            scroll.setDocumentView_(doc)
            self._scroll = scroll
            view.addSubview_(scroll)
            self._build_footer(
                view, NSMakeRect(0, frame.size.height - _FOOTER_H, frame.size.width, _FOOTER_H)
            )

        # -- ask-bar (pull entry) + recall results (no LLM) ------------------ #

        @objc.python_method
        def _build_askbar(self, view, frame):
            strip = NSView.alloc().initWithFrame_(frame)
            strip.setWantsLayer_(True)
            if strip.layer() is not None:
                strip.layer().setBackgroundColor_(_c(0, 0, 0, 0.14).CGColor())
            view.addSubview_(strip)
            bd = NSView.alloc().initWithFrame_(
                NSMakeRect(0, frame.size.height - 1, frame.size.width, 1)
            )
            bd.setWantsLayer_(True)
            if bd.layer() is not None:
                bd.layer().setBackgroundColor_(_c(255, 255, 255, 0.06).CGColor())
            strip.addSubview_(bd)

            pad = 15.0
            field_h = 38.0
            fy = (frame.size.height - field_h) / 2.0
            left = pad
            if self._mode == "recall":
                back = _pill_button(
                    "‹ Podsunięte", NSMakeRect(pad, fy + 6, 118, 26),
                    _cream_soft(), _c(255, 255, 255, 0.05), _c(255, 255, 255, 0.16),
                    self, "backToInsightsClicked:", 12.0,
                )
                strip.addSubview_(back)
                left = pad + 130

            fld_w = max(160.0, frame.size.width - left - pad)
            cont = NSView.alloc().initWithFrame_(NSMakeRect(left, fy, fld_w, field_h))
            cont.setWantsLayer_(True)
            if cont.layer() is not None:
                cont.layer().setBackgroundColor_(_c(255, 255, 255, 0.05).CGColor())
                cont.layer().setCornerRadius_(6.0)
                cont.layer().setBorderWidth_(1.0)
                cont.layer().setBorderColor_(_c(255, 255, 255, 0.16).CGColor())
            strip.addSubview_(cont)

            glyph = _label("⌕", 15, _terracotta())
            glyph.setFrame_(NSMakeRect(11, (field_h - 20) / 2.0, 18, 20))
            cont.addSubview_(glyph)

            fld = NSTextField.alloc().initWithFrame_(
                NSMakeRect(34, (field_h - 22) / 2.0, fld_w - 44, 22)
            )
            fld.setEditable_(True)
            fld.setBezeled_(False)
            fld.setBordered_(False)
            fld.setDrawsBackground_(False)
            fld.setTextColor_(_cream())
            fld.setFont_(NSFont.systemFontOfSize_(14))
            try:
                fld.setPlaceholderString_("Zapytaj swój korpus…  (lokalnie, bez AI)")
                fld.setFocusRingType_(1)  # NSFocusRingTypeNone
            except Exception:  # pragma: no cover - cosmetic
                pass
            if self._query:
                fld.setStringValue_(self._query)
            fld.setTarget_(self)
            fld.setAction_("askSubmitted:")
            cont.addSubview_(fld)
            self._ask_field = fld

        @objc.python_method
        def _index_snapshot(self):
            cb = self._callbacks.get("recall_index_status")
            if cb is None:
                return None
            try:
                return cb()
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("recall_index_status callback failed: %s", exc)
                return None

        @objc.python_method
        def _build_index_banner(self, doc, cy, inner_w):
            """Honest 'still indexing' strip: you can ask now, results are partial."""
            snap = self._index_snapshot()
            if not snap or snap.get("state") != "indexing":
                return cy
            done, total = snap.get("done", 0), snap.get("total", 0)
            count = f"  ({done}/{total})" if total else ""
            band = NSView.alloc().initWithFrame_(NSMakeRect(_READER_PAD_X, cy, inner_w, 30))
            band.setWantsLayer_(True)
            if band.layer() is not None:
                band.layer().setBackgroundColor_(_c(214, 176, 51, 0.08).CGColor())
                band.layer().setCornerRadius_(6.0)
            doc.addSubview_(band)
            lbl = _label(f"Indeksuję Twoje notatki{count} — możesz pytać już teraz "
                         f"(wyniki częściowe).", 12, _gold())
            lbl.setFrame_(NSMakeRect(_READER_PAD_X + 10, cy + 7, inner_w - 20, 16))
            doc.addSubview_(lbl)
            return cy + 40

        @objc.python_method
        def _build_recall_content(self, reader_w, vm):
            doc = _DashFlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, reader_w, 10))
            inner_w = reader_w - 2 * _READER_PAD_X
            cy = _PAD
            self._recall_note_ids = []
            self._synth_note_ids = []  # reset in lockstep — never carry stale answer tags

            # honest partial-index banner while the background backfill is still running
            cy = self._build_index_banner(doc, cy, inner_w)

            # query header — the question IS the reader title (redesign B), not a
            # field: small "Zapytałeś" eyebrow + the query as a 21pt display title.
            if self._query:
                eye = _typo_label(
                    "Zapytałeś", "collapsed_h", NSMakeRect(_READER_PAD_X, cy, inner_w, 13),
                    wrapping=False,
                )
                doc.addSubview_(eye)
                cy += 20
                measure = min(inner_w, _THESIS_MEASURE)
                qh = max(24.0, _typo_measure(self._query, "question_title", measure))
                doc.addSubview_(_typo_label(
                    self._query, "question_title",
                    NSMakeRect(_READER_PAD_X, cy, measure, qh)))
                cy += qh + 12

            if self._recall_loading:
                lbl = _label("Szukam w Twoich notatkach…  (lokalnie, bez AI)", 13.5, _muted())
                lbl.setFrame_(NSMakeRect(_READER_PAD_X, cy, inner_w, 18))
                doc.addSubview_(lbl)
                cy += 30
                doc.setFrameSize_(NSMakeSize(reader_w, cy + _PAD))
                return doc, cy + _PAD

            if vm is None:
                lbl = _wrapping_label(
                    "Zadaj pytanie powyżej — przeszukam Twoje notatki lokalnie.",
                    15, _muted(), NSMakeRect(_READER_PAD_X, cy, inner_w, 26))
                doc.addSubview_(lbl)
                cy += 34
                # Privacy disclosure — the trust backbone: local search, cloud only on
                # the explicit synthesis, and only matched excerpts.
                privacy = (
                    "Wyszukiwanie jest w 100% lokalne — nic nie opuszcza Twojego Maca. "
                    "Do chmury idą tylko dopasowane fragmenty i tylko gdy klikniesz "
                    "„Zsyntetyzuj”."
                )
                ph = _measure_height(privacy, 12, inner_w)
                doc.addSubview_(_wrapping_label(
                    privacy, 12, _c(111, 102, 90),
                    NSMakeRect(_READER_PAD_X, cy, inner_w, ph)))
                doc.setFrameSize_(NSMakeSize(reader_w, cy + ph + 20))
                return doc, cy + ph + 20

            if not vm.is_empty:
                meta = _label(f"{vm.count} fragmentów · lokalnie, bez AI", 12, _muted())
                meta.setFrame_(NSMakeRect(_READER_PAD_X, cy, inner_w, 16))
                doc.addSubview_(meta)
                cy += 22

            rule = NSView.alloc().initWithFrame_(NSMakeRect(_READER_PAD_X, cy, inner_w, 1))
            rule.setWantsLayer_(True)
            if rule.layer() is not None:
                rule.layer().setBackgroundColor_(_c(255, 255, 255, 0.08).CGColor())
            doc.addSubview_(rule)
            cy += 16

            if vm.is_empty and self._recall_status != "ok":
                cy = self._build_recall_notready(doc, cy, inner_w)
            elif vm.is_empty:
                cy = self._build_recall_abstinence(doc, vm, cy, inner_w, reader_w)
            elif self._answer is not None:
                # synthesized card (thesis) sits above its grounding (the same passages)
                cy = self._build_answer_card(doc, cy, inner_w, reader_w)
                shdr = _eyebrow("Źródła", _muted())
                shdr.setFrame_(NSMakeRect(_READER_PAD_X, cy, inner_w, 13))
                doc.addSubview_(shdr)
                cy += 20
                for row in vm.rows:
                    cy = self._build_recall_row(doc, row, cy, inner_w, reader_w)
            else:
                for row in vm.rows:
                    cy = self._build_recall_row(doc, row, cy, inner_w, reader_w)
                cy = self._build_escalation(doc, cy, inner_w, reader_w)

            cy += _PAD
            doc.setFrameSize_(NSMakeSize(reader_w, cy))
            return doc, cy

        @objc.python_method
        def _build_recall_notready(self, doc, cy, inner_w):
            # Honest states distinct from a genuine no-match: never claim "nothing in
            # your notes about X" when the search couldn't actually run.
            if self._recall_status == "empty":
                head = "Twoje notatki nie są jeszcze zaindeksowane."
                sub = ("Recall potrzebuje jednorazowego zindeksowania vaulta, zanim "
                       "przeszuka — to nie znaczy, że nic nie ma. (Auto-backfill: wkrótce.)")
            else:  # "unavailable"
                head = "Nie udało się przeszukać notatek."
                sub = ("Indeks lub lokalny model nie są jeszcze gotowe — spróbuj "
                       "ponownie za chwilę. To nie znaczy, że nic nie ma.")
            hh = max(24.0, _measure_height(head, 20, inner_w))
            doc.addSubview_(_wrapping_label(
                head, 20, _cream(), NSMakeRect(_READER_PAD_X, cy, inner_w, hh)))
            cy += hh + 8
            sh = max(18.0, _measure_height(sub, 13.5, inner_w))
            doc.addSubview_(_wrapping_label(
                sub, 13.5, _muted(), NSMakeRect(_READER_PAD_X, cy, inner_w, sh)))
            cy += sh + 12
            return cy

        @objc.python_method
        def _build_escalation(self, doc, cy, inner_w, reader_w):
            # The one LLM door: explicit, gold, and honest that excerpts leave the Mac.
            cy += 8
            rule = NSView.alloc().initWithFrame_(NSMakeRect(_READER_PAD_X, cy, inner_w, 1))
            rule.setWantsLayer_(True)
            if rule.layer() is not None:
                rule.layer().setBackgroundColor_(_c(214, 176, 51, 0.22).CGColor())
            doc.addSubview_(rule)
            cy += 14
            if self._answer_loading:
                lbl = _label(
                    "Syntetyzuję…  (jedyny moment, gdy dopasowane fragmenty idą do chmury)",
                    12.5, _gold())
                lbl.setFrame_(NSMakeRect(_READER_PAD_X, cy, inner_w, 18))
                doc.addSubview_(lbl)
                cy += 28
                return cy
            btn = _pill_button(
                "✦ Zsyntetyzuj te wyniki", NSMakeRect(_READER_PAD_X, cy, 214, 30),
                _gold(), _c(214, 176, 51, 0.14), _c(214, 176, 51, 0.55),
                self, "synthesizeClicked:", 13.0)
            doc.addSubview_(btn)
            note = _label("Tylko teraz fragmenty świadomie opuszczają Maca.", 11.5, _c(140, 130, 115))
            note.setFrame_(NSMakeRect(_READER_PAD_X + 226, cy + 7, inner_w - 226, 16))
            doc.addSubview_(note)
            cy += 40
            return cy

        @objc.python_method
        def _build_answer_card(self, doc, cy, inner_w, reader_w):
            self._synth_note_ids = []
            ans = self._answer
            answered = getattr(ans, "answered", True)
            eye = _eyebrow(
                "✦ Synteza" if answered else "✦ Synteza — brak pokrycia w notatkach",
                _gold() if answered else _muted())
            eye.setFrame_(NSMakeRect(_READER_PAD_X, cy, inner_w - 130, 13))
            doc.addSubview_(eye)
            back = _pill_button(
                "‹ tylko wyniki", NSMakeRect(reader_w - _READER_PAD_X - 118, cy - 4, 118, 24),
                _cream_soft(), _c(255, 255, 255, 0.05), _c(255, 255, 255, 0.16),
                self, "clearAnswerClicked:", 11.5)
            doc.addSubview_(back)
            cy += 24

            # When the model says the notes don't cover the question, the thesis is an
            # honest "not covered" note — render it muted, not as a confident answer.
            thesis = "„" + (getattr(ans, "thesis", "") or "") + "”"
            tcolor = _cream() if answered else _c(176, 162, 141)
            th = max(28.0, _measure_height(thesis, 22, inner_w))
            doc.addSubview_(_wrapping_label(
                thesis, 22, tcolor, NSMakeRect(_READER_PAD_X, cy, inner_w, th)))
            cy += th + 14

            for ev in getattr(ans, "evidence", None) or []:
                cy = self._build_answer_evidence(doc, ev, cy, inner_w, reader_w)

            dirs = getattr(ans, "directions", None) or []
            if dirs:
                dh = _eyebrow("Kierunki", _muted())
                dh.setFrame_(NSMakeRect(_READER_PAD_X, cy, inner_w, 13))
                doc.addSubview_(dh)
                cy += 20
                for d in dirs:
                    line = "→  " + (d or "").strip()
                    lh = max(18.0, _measure_height(line, 13.5, inner_w))
                    doc.addSubview_(_wrapping_label(
                        line, 13.5, _cream_soft(), NSMakeRect(_READER_PAD_X, cy, inner_w, lh)))
                    cy += lh + 6

            save = _pill_button(
                "⤓ Zapisz do notatek", NSMakeRect(_READER_PAD_X, cy + 6, 170, 28),
                _cream(), _terra_deep(), _terra_deep(), self, "saveAnswerClicked:", 12.5)
            doc.addSubview_(save)
            cy += 46
            return cy

        @objc.python_method
        def _build_answer_evidence(self, doc, ev, cy, inner_w, reader_w):
            from src.ui.recall_presenter import split_stem

            date, title = split_stem(getattr(ev, "note", "") or "")
            top = f"{date}   ·   {title}" if date else (title or getattr(ev, "note", ""))
            tl = _label(top, 12.0, _muted())
            tl.setFrame_(NSMakeRect(_READER_PAD_X, cy, inner_w - 40, 16))
            doc.addSubview_(tl)
            idx = len(self._synth_note_ids)
            self._synth_note_ids.append(getattr(ev, "note", "") or "")
            ob = _pill_button(
                "↗", NSMakeRect(reader_w - _READER_PAD_X - 30, cy - 2, 30, 22),
                _terracotta(), _c(255, 255, 255, 0.0), _c(255, 255, 255, 0.0),
                self, "synthOpenClicked:", 12.0)
            ob.setTag_(idx)
            doc.addSubview_(ob)
            cy += 19
            quote = "„" + (getattr(ev, "quote", "") or "") + "”"
            qh = max(16.0, _measure_height(quote, 13.5, inner_w - 12))
            lbl = _wrapping_label(quote, 13.5, _cream_soft(),
                                  NSMakeRect(_READER_PAD_X + 12, cy, inner_w - 12, qh))
            doc.addSubview_(lbl)
            cy += qh + 12
            return cy

        @objc.python_method
        def _build_recall_row(self, doc, row, cy, inner_w, reader_w):
            x = _READER_PAD_X
            faint = _c(111, 102, 90)
            rank = _label(f"{row.rank:02d}", 12, faint)
            rank.setFrame_(NSMakeRect(x, cy + 1, 24, 15))
            doc.addSubview_(rank)
            text_x = x + 32
            text_w = inner_w - 32

            # Top line: date (mono, gold) + title (bold) — the redline split.
            tx = text_x
            if row.date:
                dlab = _typo_label(row.date, "result_date",
                                   NSMakeRect(tx, cy, 60, 16), wrapping=False)
                doc.addSubview_(dlab)
                tx += _text_width(row.date, 11.5) + 16
            if row.title:
                tlab = _typo_label(row.title, "result_title",
                                   NSMakeRect(tx, cy, text_w - (tx - text_x) - 96, 16),
                                   wrapping=False)
                tlab.setLineBreakMode_(4)
                doc.addSubview_(tlab)

            idx = len(self._recall_note_ids)
            self._recall_note_ids.append(row.note_id)
            ob = _pill_button(
                "↗ otwórz", NSMakeRect(reader_w - _READER_PAD_X - 84, cy - 3, 84, 22),
                _c(224, 213, 191, 0.45), _c(255, 255, 255, 0.0), _c(255, 255, 255, 0.0),
                self, "recallOpenClicked:", 11.5,
            )
            ob.setTag_(idx)
            doc.addSubview_(ob)
            cy += 20

            quote = "„" + row.quote + "”"
            qh = max(18.0, _typo_measure(quote, "result_quote", text_w))
            ql = _typo_label(quote, "result_quote", NSMakeRect(text_x, cy, text_w, qh))
            if row.dimmed:
                from AppKit import (
                    NSAttributedString, NSFontAttributeName,
                    NSForegroundColorAttributeName, NSParagraphStyleAttributeName,
                )
                from src.ui import typography as _T
                at = _T.attributes("result_quote", color_alpha=0.45)
                ql.setAttributedStringValue_(
                    NSAttributedString.alloc().initWithString_attributes_(quote, at))
            doc.addSubview_(ql)
            cy += qh + 12

            sep = NSView.alloc().initWithFrame_(NSMakeRect(text_x, cy, text_w, 1))
            sep.setWantsLayer_(True)
            if sep.layer() is not None:
                sep.layer().setBackgroundColor_(_c(255, 255, 255, 0.055).CGColor())
            doc.addSubview_(sep)
            cy += 12
            return cy

        @objc.python_method
        def _build_recall_abstinence(self, doc, vm, cy, inner_w, reader_w):
            head_txt = "Nic w Twoich notatkach na to pytanie."
            hh = max(24.0, _measure_height(head_txt, 20, inner_w))
            doc.addSubview_(_wrapping_label(
                head_txt, 20, _cream(), NSMakeRect(_READER_PAD_X, cy, inner_w, hh)))
            cy += hh + 8
            sub = ("Search jest w 100% lokalny i niczego nie zmyśla — "
                   "nic nie opuszcza Twojego Maca.")
            sh = max(18.0, _measure_height(sub, 13.5, inner_w))
            doc.addSubview_(_wrapping_label(
                sub, 13.5, _muted(), NSMakeRect(_READER_PAD_X, cy, inner_w, sh)))
            cy += sh + 20

            if vm.nearest is not None:
                nh = _eyebrow("Najbliższe (słabe) trafienie", _c(111, 102, 90))
                nh.setFrame_(NSMakeRect(_READER_PAD_X, cy, inner_w, 13))
                doc.addSubview_(nh)
                cy += 20
                cy = self._build_recall_row(doc, vm.nearest, cy, inner_w, reader_w)
            return cy

        # -- ask-bar / recall actions --------------------------------------- #

        def askSubmitted_(self, sender):
            try:
                text = str(sender.stringValue()).strip()
            except Exception:  # pragma: no cover - defensive
                text = ""
            self._run_recall(text)

        def recallOpenClicked_(self, sender):
            ids = getattr(self, "_recall_note_ids", [])
            i = int(sender.tag())
            if 0 <= i < len(ids):
                self._invoke_callback("open_note", ids[i])

        def backToInsightsClicked_(self, sender):
            self._epoch += 1          # invalidate any in-flight search/synthesis
            self._mode = "insight"
            self._recall = None
            self._recall_loading = False
            self._answer = None
            self._answer_loading = False
            self._query = ""
            self._render()

        @objc.python_method
        def _reset_recall_flight(self):
            """Clear per-query state and bump the epoch so in-flight workers drop."""
            self._epoch += 1
            self._recall = None
            self._recall_status = "ok"
            self._answer = None
            self._answer_loading = False
            self._answer_failed = False

        @objc.python_method
        def _run_recall(self, text):
            self._query = (text or "").strip()
            if not self._query:
                self._reset_recall_flight()
                self._mode = "insight"
                self._recall_loading = False
                self._render()
                return
            # Show the query in a "searching" state immediately, then do the work off
            # the main thread — the embed + full-corpus BM25 (and a first-run model
            # download) must never block the AppKit UI, mirroring the digest/retranscribe
            # daemon threads.
            self._reset_recall_flight()
            self._mode = "recall"
            self._recall_loading = True
            self._scroll_y = 0.0
            epoch = self._epoch
            self._render()
            import threading

            threading.Thread(
                target=self._recall_worker_, args=(self._query, epoch),
                name="RecallSearch", daemon=True,
            ).start()

        @objc.python_method
        def _recall_worker_(self, query, epoch):
            """Runs on a daemon thread: search + build the view-model, then marshal
            the result back onto the main thread for rendering."""
            results, confidence, status = [], 0.0, "unavailable"
            cb = self._callbacks.get("recall_search")
            if cb is None:
                status = "unavailable"
            else:
                try:
                    out = cb(query)
                    if isinstance(out, tuple) and len(out) == 3:
                        results, confidence, status = out
                    elif isinstance(out, tuple) and len(out) == 2:
                        results, confidence = out
                        status = "ok"
                    else:  # wrong-shape contract → treat as failure, not "no match"
                        status = "unavailable"
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug("recall_search callback failed: %s", exc)
                    status = "unavailable"
            from src.ui import recall_presenter as rp

            self._pending_recall = {
                "epoch": epoch,
                "query": query,
                "vm": rp.present(query, results, confidence),
                "status": status,
                "results": results,  # raw hits kept for the optional synthesis escalation
            }
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "applyRecall:", None, False
            )

        def applyRecall_(self, _ignored):
            payload = self._pending_recall
            # Drop stale results — a newer search/navigation bumped the epoch meanwhile.
            if not payload or payload.get("epoch") != self._epoch:
                return
            self._recall = payload["vm"]
            self._recall_status = payload.get("status", "ok")
            self._recall_raw = payload.get("results", [])
            self._recall_loading = False
            self._render()

        # -- synthesis escalation (the one LLM door in the pull path) -------- #

        @objc.python_method
        def _run_synthesis(self):
            if not self._recall_raw or self._answer_loading:
                return
            self._answer_failed = False
            self._answer_loading = True
            epoch = self._epoch
            self._render()
            import threading

            threading.Thread(
                target=self._synth_worker_, args=(self._query, list(self._recall_raw), epoch),
                name="RecallSynthesis", daemon=True,
            ).start()

        @objc.python_method
        def _synth_worker_(self, query, results, epoch):
            answer = None
            cb = self._callbacks.get("recall_synthesize")
            if cb is not None:
                try:
                    answer = cb(query, results)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug("recall_synthesize callback failed: %s", exc)
            self._pending_answer = {"epoch": epoch, "answer": answer}
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "applyAnswer:", None, False
            )

        def applyAnswer_(self, _ignored):
            payload = self._pending_answer
            # Epoch guard: a stale answer (built from now-replaced passages) must never
            # land on a newer result set — that would cite passages the user can't see.
            if not payload or payload.get("epoch") != self._epoch:
                return
            self._answer = payload.get("answer")
            self._answer_loading = False
            if self._answer is None:
                # Synthesis attempted but produced nothing (no key, disabled, or error) —
                # tell the user instead of silently snapping back to the same results.
                self._answer_failed = True
                self._show_toast("Synteza niedostępna — sprawdź klucz API lub spróbuj ponownie")
            self._render()

        def synthesizeClicked_(self, sender):
            self._run_synthesis()

        def clearAnswerClicked_(self, sender):
            self._answer = None
            self._answer_loading = False
            self._answer_failed = False
            self._render()

        def saveAnswerClicked_(self, sender):
            if self._answer is None:
                return
            path = None
            cb = self._callbacks.get("recall_save_answer")
            if cb is not None:
                try:
                    path = cb(self._query, self._answer)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug("recall_save_answer callback failed: %s", exc)
            self._show_toast("Zapisano do notatek" if path else "Nie udało się zapisać")

        def synthOpenClicked_(self, sender):
            ids = getattr(self, "_synth_note_ids", [])
            i = int(sender.tag())
            if 0 <= i < len(ids):
                self._invoke_callback("open_note", ids[i])

        def askAboutInsightClicked_(self, sender):
            # push→pull: seed the ask-bar with the active insight and search the corpus.
            conn = self._deck.active()
            if conn is not None and getattr(conn, "rationale", ""):
                self._run_recall(conn.rationale)

        @objc.python_method
        def focusRecall(self, prefill=None):
            """Recall entry (⌃⌥Space / ⌕): show the ask-bar overlay (screen C).

            The persistent in-window strip was cut in the redesign; the pull entry
            is now a floating NSPanel overlay. A prefill runs the query straight
            away (the 'Zapytaj o to' path) instead of opening the field.
            """
            if prefill:
                self._ensure_window()
                self._run_recall(prefill)
                self.showWindow()
                return
            self.showAskOverlay()

        @objc.python_method
        def showAskOverlay(self):
            """Present the ask-bar overlay (redesign C): a borderless floating
            NSPanel with a dark rounded field + terracotta focus ring."""
            from AppKit import (
                NSPanel, NSColor, NSTextField, NSFloatingWindowLevel,
                NSBackingStoreBuffered, NSAttributedString,
                NSForegroundColorAttributeName, NSFontAttributeName,
            )

            self._ensure_window()  # results land in the window; keep it realised
            W, FLD_H = 560.0, 52.0
            panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, W, FLD_H + 24), 1 << 7, NSBackingStoreBuffered, False
            )
            panel.setLevel_(NSFloatingWindowLevel)
            panel.setOpaque_(False)
            panel.setBackgroundColor_(NSColor.clearColor())
            panel.setHasShadow_(True)
            panel.setHidesOnDeactivate_(True)

            container = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, W, FLD_H + 24))
            container.setWantsLayer_(True)
            if container.layer() is not None:
                container.layer().setCornerRadius_(10.0)
                container.layer().setBackgroundColor_(_c(32, 30, 40, 0.98).CGColor())
                container.layer().setBorderWidth_(3.0)
                container.layer().setBorderColor_(_c(217, 84, 42, 0.18).CGColor())
            panel.setContentView_(container)

            fld = NSTextField.alloc().initWithFrame_(
                NSMakeRect(18, 12, W - 36, FLD_H)
            )
            fld.setBordered_(False)
            fld.setBezeled_(False)
            fld.setDrawsBackground_(False)
            fld.setFocusRingType_(1)  # NSFocusRingTypeNone — the ring is on the container
            fld.setTextColor_(_c(250, 243, 226))
            ph = NSAttributedString.alloc().initWithString_attributes_(
                "Zapytaj swój korpus…",
                {
                    NSForegroundColorAttributeName: _c(250, 243, 226, 0.4),
                    NSFontAttributeName: NSFont.systemFontOfSize_weight_(15.0, 0.0),
                },
            )
            fld.setPlaceholderAttributedString_(ph)
            fld.setFont_(NSFont.systemFontOfSize_weight_(15.0, 0.0))
            fld.setTarget_(self)
            fld.setAction_("askOverlaySubmitted:")
            container.addSubview_(fld)
            self._ask_overlay = panel
            self._ask_overlay_field = fld

            panel.center()
            panel.makeKeyAndOrderFront_(None)
            panel.makeFirstResponder_(fld)

        def askOverlaySubmitted_(self, sender):
            try:
                text = str(sender.stringValue()).strip()
            except Exception:  # pragma: no cover - defensive
                text = ""
            panel = getattr(self, "_ask_overlay", None)
            if panel is not None:
                panel.orderOut_(None)
                self._ask_overlay = None
            if text:
                self._ensure_window()
                self._run_recall(text)
                self.showWindow()

        @objc.python_method
        def _build_reader_content(self, reader_w, conn):
            doc = _DashFlippedView.alloc().initWithFrame_(
                NSMakeRect(0, 0, reader_w, 10)
            )
            inner_w = reader_w - 2 * _READER_PAD_X
            cy = _PAD

            # header: sigil + type + "✦ Nowy insight"
            doc.addSubview_(
                _sigil(NSMakeRect(_READER_PAD_X, cy, 34, 34), conn.layout(), conn.resolved_tcolor())
            )
            # type eyebrow — gold, uppercase, tracked (typography ramp)
            tlabel = _typo_label(
                conn.resolved_label(), "eyebrow",
                NSMakeRect(_READER_PAD_X + 44, cy + 12, inner_w - 160, 14),
                wrapping=False,
            )
            doc.addSubview_(tlabel)
            eye = _typo_label(
                "✦ Nowy insight", "eyebrow",
                NSMakeRect(reader_w - 190, cy + 12, 166, 14), wrapping=False,
            )
            eye.setAlignment_(2)
            doc.addSubview_(eye)
            cy += 46

            # thesis (the spark) — display 24pt, capped to a readable measure (30em)
            thesis = "„" + conn.rationale + "”"
            measure = min(inner_w, _THESIS_MEASURE)
            th = max(30.0, _typo_measure(thesis, "thesis", measure))
            doc.addSubview_(
                _typo_label(thesis, "thesis", NSMakeRect(_READER_PAD_X, cy, measure, th))
            )
            cy += th + 16

            # note chips
            self._note_basenames = list(conn.notes)
            cx = _READER_PAD_X
            for i, note in enumerate(conn.notes):
                chip = self._chip(note, NSMakePoint(cx, cy), i)
                doc.addSubview_(chip)
                cx += chip.frame().size.width + 6
                if cx > reader_w - 130:
                    cx = _READER_PAD_X
                    cy += 30
            cy += 34

            # push→pull bridge: ask the corpus about this insight ("Zapytaj o to")
            ask_btn = _pill_button(
                "✦ Zapytaj o to", NSMakeRect(_READER_PAD_X, cy, 148, 26),
                _terracotta(), _c(217, 84, 42, 0.10), _c(217, 84, 42, 0.5),
                self, "askAboutInsightClicked:", 12.0)
            doc.addSubview_(ask_btn)
            cy += 36

            # ground — evidence toggle + (when expanded) rows
            if conn.evidence:
                chev = "⌃" if self._grounded else "⌄"
                tog = NSButton.alloc().initWithFrame_(
                    NSMakeRect(_READER_PAD_X - 4, cy, inner_w, 20)
                )
                tog.setBordered_(False)
                tog.setTransparent_(True)
                tog.setTitle_("")
                tog.setTarget_(self)
                tog.setAction_("toggleEvidenceClicked:")
                from AppKit import NSAttributedString, NSForegroundColorAttributeName

                tog.setAttributedTitle_(
                    NSAttributedString.alloc().initWithString_attributes_(
                        f"{chev}  Dowód · {len(conn.evidence)} zacytowane fragmenty",
                        {NSForegroundColorAttributeName: _c(154, 140, 123)},
                    )
                )
                tog.setFont_(NSFont.systemFontOfSize_(12.5))
                tog.setAlignment_(0)
                doc.addSubview_(tog)
                cy += 24
                if self._grounded:
                    cy = self._build_evidence(doc, conn, cy, inner_w)

            # divider
            rule = NSView.alloc().initWithFrame_(
                NSMakeRect(_READER_PAD_X, cy, inner_w, 1)
            )
            rule.setWantsLayer_(True)
            if rule.layer() is not None:
                rule.layer().setBackgroundColor_(_c(255, 255, 255, 0.10).CGColor())
            doc.addSubview_(rule)
            cy += 16

            # act — directions header + multi-select rows
            dcap = _eyebrow("Kierunki", _muted())
            dcap.setFrame_(NSMakeRect(_READER_PAD_X, cy, 120, 13))
            doc.addSubview_(dcap)
            hint = _label("— zaznacz, by przekazać", 11.5, _c(111, 102, 90))
            hint.setFrame_(NSMakeRect(_READER_PAD_X + 78, cy, inner_w - 78, 13))
            doc.addSubview_(hint)
            cy += 22
            for i, d in enumerate(conn.directions):
                cy = self._build_direction_row(doc, i, d, cy, inner_w)
            cy += _PAD

            doc.setFrameSize_(NSMakeSize(reader_w, cy))
            return doc, cy

        @objc.python_method
        def _build_evidence(self, doc, conn, cy, inner_w):
            for ev in conn.evidence:
                x = _READER_PAD_X + 13
                bar = NSView.alloc().initWithFrame_(
                    NSMakeRect(_READER_PAD_X + 2, cy, 2, 0)
                )
                bar.setWantsLayer_(True)
                top = cy
                date = _label(ev.date or "·", 12, _terracotta())
                date.setFrame_(NSMakeRect(x, cy, 56, 15))
                doc.addSubview_(date)
                quote = "„" + ev.quote + "”"
                qh = max(16.0, _measure_height(quote, 14, inner_w - 70))
                doc.addSubview_(
                    _wrapping_label(quote, 14, _cream_soft(), NSMakeRect(x + 60, cy, inner_w - 70, qh))
                )
                cy += qh + 2
                src = _label("◇ " + ev.note + " ↗", 11.5, _muted())
                src.setFrame_(NSMakeRect(x + 60, cy, inner_w - 70, 14))
                doc.addSubview_(src)
                cy += 20
                if bar.layer() is not None:
                    bar.setFrame_(NSMakeRect(_READER_PAD_X + 2, top, 2, cy - top - 6))
                    bar.layer().setBackgroundColor_(_c(224, 99, 58, 0.4).CGColor())
                    doc.addSubview_(bar)
                cy += 8
            return cy + 4

        @objc.python_method
        def _build_direction_row(self, doc, index, text, cy, inner_w):
            from src.ui.hover import make_hover_button

            selected = index in self._selected
            # Design C3: padding 12/14, cols [18px chk] 11 [text], radius 12.
            PADX = 12.0
            PADTOP = 11.0
            BOX = 16.0
            COLGAP = 11.0
            text_x = PADX + BOX + COLGAP  # 39
            text_w = inner_w - text_x - PADX
            th = _typo_measure(text, "direction", text_w)
            row_h = max(46.0, PADTOP * 2 + th)
            frame = NSMakeRect(_READER_PAD_X, cy, inner_w, row_h)
            btn = make_hover_button(frame) or NSButton.alloc().initWithFrame_(frame)
            btn.setTitle_("")
            btn.setBordered_(False)
            btn.setTarget_(self)
            btn.setAction_("directionClicked:")
            btn.setTag_(index)
            btn.setWantsLayer_(True)
            if btn.layer() is not None:
                btn.layer().setCornerRadius_(_R_ROW)
                if selected:
                    btn.layer().setBackgroundColor_(_c(217, 84, 42, 0.09).CGColor())
                    btn.layer().setBorderWidth_(1.0)
                    btn.layer().setBorderColor_(_c(217, 84, 42, 0.55).CGColor())
                else:
                    btn.layer().setBackgroundColor_(_c(255, 255, 255, 0.018).CGColor())

            # Checkbox centred on the FIRST text line (redesign E). The ramp now
            # uses lineSpacing (between lines only), so the first line's glyph
            # box starts exactly at PADTOP: centre = PADTOP + lineHeight/2
            # (≈15.5/2 for 13pt) → box_y for a 16pt box ≈ PADTOP + 1.
            box_y = PADTOP + 1.0
            box = NSView.alloc().initWithFrame_(NSMakeRect(PADX, box_y, BOX, BOX))
            box.setWantsLayer_(True)
            if box.layer() is not None:
                box.layer().setCornerRadius_(_R_CHECK)
                if selected:
                    box.layer().setBackgroundColor_(_terra_deep().CGColor())
                    box.layer().setBorderWidth_(1.0)
                    box.layer().setBorderColor_(_terra_deep().CGColor())
                else:
                    box.layer().setBorderWidth_(1.5)
                    box.layer().setBorderColor_(_c(255, 255, 255, 0.24).CGColor())
            btn.addSubview_(box)
            if selected:
                chk = _label("✓", 11, _c(255, 255, 255), bold=True)
                chk.setFrame_(NSMakeRect(PADX, box_y - 1, BOX, 15))
                chk.setAlignment_(1)
                btn.addSubview_(chk)

            line = _typo_label(
                text, "direction",
                NSMakeRect(text_x, PADTOP, text_w, row_h - PADTOP * 2 + 4),
            )
            if selected:  # 'on' → lit to full white
                from AppKit import (
                    NSAttributedString,
                    NSFontAttributeName,
                    NSForegroundColorAttributeName,
                    NSParagraphStyleAttributeName,
                )
                from src.ui import typography as _T
                at = _T.attributes("direction", color_alpha=1.0)
                line.setAttributedStringValue_(
                    NSAttributedString.alloc().initWithString_attributes_(text, at)
                )
            btn.addSubview_(line)
            doc.addSubview_(btn)
            return cy + row_h + 9

        @objc.python_method
        def _build_handoff_bar(self, view, frame, n):
            bar = _DashFlippedView.alloc().initWithFrame_(frame)
            bar.setWantsLayer_(True)
            if bar.layer() is not None:
                bar.layer().setBackgroundColor_(_c(40, 22, 16, 0.62).CGColor())
            tdiv = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, frame.size.width, 1))
            tdiv.setWantsLayer_(True)
            if tdiv.layer() is not None:
                tdiv.layer().setBackgroundColor_(_c(224, 99, 58, 0.24).CGColor())
            bar.addSubview_(tdiv)

            from src.ui import style

            CTA_H = 34.0
            BTN_Y = (frame.size.height - CTA_H) / 2.0
            pad = _READER_PAD_X
            white = _c(255, 255, 255)

            tool = getattr(config, "LLM_HANDOFF_TOOL", "claude")
            if tool not in ho.LLM_TOOLS:  # stale config (e.g. retired Gemini)
                tool = "claude"
            name = ho.tool_name(tool)

            # Secondary actions: compact, icon-only with tooltips (a quiet cluster
            # set apart from the one strong CTA by silence, not size).
            secondary = (
                ("checklist", "Utwórz zadanie", "taskClicked:"),
                ("calendar", "Dodaj do kalendarza", "calendarClicked:"),
                ("doc.on.doc", "Kopiuj do schowka", "copyClicked:"),
            )
            ICON_W = 34.0
            ICON_GAP = 6.0
            CARET_W = 28.0
            GAP_CLUSTER = 16.0
            sec_w = len(secondary) * ICON_W + (len(secondary) - 1) * ICON_GAP

            def _cta_width(label):
                # lead pad + white brand chip + gap + measured text + trail pad
                return 10.0 + 18.0 + 8.0 + _text_width(label, 13.0) + 12.0

            def _cluster_width(cw):
                return cw + CARET_W + GAP_CLUSTER + sec_w

            # Measured, right-anchored layout; degrade so the actions never clip:
            # drop the provider name from the CTA, then drop the status label.
            avail = frame.size.width - 2 * pad
            cnt = "1 kierunek wybrany" if n == 1 else f"{n} kierunki wybrane"
            label_w = _text_width(cnt, 12.5)
            cta_label = "Kontynuuj w " + name
            cta_w = _cta_width(cta_label)
            show_label = True
            if label_w + GAP_CLUSTER + _cluster_width(cta_w) > avail:
                cta_label = "Kontynuuj"
                cta_w = _cta_width(cta_label)
            if label_w + GAP_CLUSTER + _cluster_width(cta_w) > avail:
                show_label = False

            if show_label:
                lab = _label(cnt, 12.5, _c(240, 224, 200))
                lab.setFrame_(
                    NSMakeRect(pad, frame.size.height / 2 - 8, label_w + 4, 16)
                )
                bar.addSubview_(lab)

            x = max(pad, frame.size.width - pad - _cluster_width(cta_w))

            # --- primary CTA = split pill: [chip + label] | caret ---
            LEFT_CORNERS = 1 | 4   # MinXMinY | MinXMaxY
            RIGHT_CORNERS = 2 | 8  # MaxXMinY | MaxXMaxY
            go = _pill_button(
                "", NSMakeRect(x, BTN_Y, cta_w, CTA_H),
                white, _terra_deep(), _terra_deep(),
                self, "continueLLMClicked:",
            )
            if go.layer() is not None:
                go.layer().setMaskedCorners_(LEFT_CORNERS)
                go.layer().setShadowColor_(_terra_deep().CGColor())
                go.layer().setShadowOpacity_(0.45)
                go.layer().setShadowRadius_(9.0)
                go.layer().setShadowOffset_(NSMakeSize(0, -3))
            go.setToolTip_("Przekaż wybrane kierunki do " + name)
            # white brand chip with the provider glyph tinted terracotta
            chip = NSView.alloc().initWithFrame_(NSMakeRect(10, (CTA_H - 18) / 2.0, 18, 18))
            chip.setWantsLayer_(True)
            if chip.layer() is not None:
                chip.layer().setCornerRadius_(5.0)
                chip.layer().setBackgroundColor_(white.CGColor())
            brand = _brand_image(tool, 12.0)
            if brand is not None:
                biv = NSImageView.alloc().initWithFrame_(NSMakeRect(3, 3, 12, 12))
                biv.setImage_(brand)
                try:
                    biv.setContentTintColor_(_terra_deep())
                except Exception:  # pragma: no cover
                    pass
                chip.addSubview_(biv)
            go.addSubview_(chip)
            golab = _label(cta_label, 13, white)
            golab.setFrame_(NSMakeRect(36, (CTA_H - 16) / 2.0, cta_w - 44, 16))
            go.addSubview_(golab)
            bar.addSubview_(go)

            caret = _pill_button(
                "⌄",
                NSMakeRect(x + cta_w, BTN_Y, CARET_W, CTA_H),
                white, _terra_deep(), None,
                self, "switchLLMClicked:",
            )
            if caret.layer() is not None:
                caret.layer().setMaskedCorners_(RIGHT_CORNERS)
            # seam divider between go and caret
            seam = NSView.alloc().initWithFrame_(
                NSMakeRect(x + cta_w, BTN_Y + 6, 1, CTA_H - 12)
            )
            seam.setWantsLayer_(True)
            if seam.layer() is not None:
                seam.layer().setBackgroundColor_(_c(255, 255, 255, 0.32).CGColor())
            caret.setToolTip_("Zmień narzędzie (Claude / ChatGPT)")
            bar.addSubview_(caret)
            bar.addSubview_(seam)

            sx = x + cta_w + CARET_W + GAP_CLUSTER
            for symbol, tip, sel in secondary:
                b = _icon_button(
                    style.sf_symbol(symbol, point=15.0, weight="regular"),
                    tip,
                    NSMakeRect(sx, BTN_Y, ICON_W, CTA_H),
                    _c(201, 187, 166), _c(255, 255, 255, 0.05), _c(255, 255, 255, 0.16),
                    self, sel,
                )
                bar.addSubview_(b)
                sx += ICON_W + ICON_GAP
            view.addSubview_(bar)

        @objc.python_method
        def _build_footer(self, view, frame):
            foot = _DashFlippedView.alloc().initWithFrame_(frame)
            foot.setWantsLayer_(True)
            if foot.layer() is not None:
                foot.layer().setBackgroundColor_(_c(16, 14, 21, 0.86).CGColor())
            tdiv = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, frame.size.width, 1))
            tdiv.setWantsLayer_(True)
            if tdiv.layer() is not None:
                tdiv.layer().setBackgroundColor_(_c(255, 255, 255, 0.08).CGColor())
            foot.addSubview_(tdiv)

            from src.ui import style

            # Center position counter "N z M" (redesign: lives in the footer, not
            # the title-bar, which keeps only ⌕).
            vis = self._deck.visible()
            if vis:
                pos = next(
                    (k for k, (i, _cn) in enumerate(vis) if i == self._deck.active_index),
                    -1,
                )
                if pos >= 0:
                    ctr = _typo_label(
                        f"{pos + 1} z {len(vis)}", "footer_counter",
                        NSMakeRect(frame.size.width / 2 - 50, 15, 100, 16), wrapping=False,
                    )
                    ctr.setAlignment_(1)
                    foot.addSubview_(ctr)

            # Redline A4: buttons 31pt / radius 6. Odrzuć = ghost WITH a border
            # (rgba .16, text .7); Zachowaj = jade (bg .16, border .45, text
            # #8BE0B5 bold) — text-only: an NSImage on the button forces a white
            # bezel draw, which is what washed the old Zachowaj out.
            dismiss = _pill_button(
                "Odrzuć", NSMakeRect(frame.size.width - 226, 8, 86, 31),
                _c(255, 255, 255, 0.7), None, _c(255, 255, 255, 0.16),
                self, "dismissClicked:", 12.5,
            )
            foot.addSubview_(dismiss)
            keep = _pill_button(
                "Zachowaj", NSMakeRect(frame.size.width - 128, 8, 112, 31),
                _c(139, 224, 181), _c(70, 177, 126, 0.16), _c(70, 177, 126, 0.45),
                self, "keepClicked:", 12.5,
            )
            keep.setFont_(NSFont.boldSystemFontOfSize_(12.5))
            foot.addSubview_(keep)
            view.addSubview_(foot)

        @objc.python_method
        def _build_empty(self, view, frame, title=None, subtitle=None):
            title = title or "Cisza w korpusie"
            subtitle = subtitle or (
                "Wszystkie połączenia przejrzane. Timshel czyta dalej — gdy coś "
                "się zapali, wróci tu rozbłysk."
            )
            view.addSubview_(
                _sigil(
                    NSMakeRect(frame.size.width / 2 - 27, frame.size.height / 2 - 96, 54, 54),
                    "triad", "#E3C16B",
                )
            )
            h = _typo_label(
                title, "empty_title",
                NSMakeRect(0, frame.size.height / 2, frame.size.width, 24), wrapping=False,
            )
            h.setAlignment_(1)
            view.addSubview_(h)
            p = _typo_label(
                subtitle, "empty_desc",
                NSMakeRect(frame.size.width / 2 - 170, frame.size.height / 2 + 28, 340, 50),
            )
            p.setAlignment_(1)
            view.addSubview_(p)
            return view

        # Per-view empty copy when the deck has items but the active view is empty.
        _EMPTY_VIEW_COPY = {
            "new": (
                "Wszystko przejrzane",
                "Nowych połączeń nie ma. Wrócą, gdy korpus urośnie o kolejne notatki.",
            ),
            "kept": (
                "Nic zachowanego",
                "To, co zachowasz, czeka tutaj — żeby wrócić, kiedy będzie czas to rozwinąć.",
            ),
            "dismissed": (
                "Nic odrzuconego",
                "Odrzucone trafiają tu i zostają odwracalne — odzyskasz je stąd jednym ruchem.",
            ),
        }

        @objc.python_method
        def _build_skeleton(self, view, frame):
            inner_w = frame.size.width - 2 * _READER_PAD_X
            cy = _PAD
            badge = _label("●  Transkrybuję…", 11, _c(224, 162, 123))
            badge.setFrame_(NSMakeRect(_READER_PAD_X, cy, inner_w, 16))
            view.addSubview_(badge)
            cy += 30
            for frac, hgt in ((0.5, 30), (0.92, 22), (0.78, 22), (0.4, 18)):
                view.addSubview_(
                    _skeleton_bar(NSMakeRect(_READER_PAD_X, cy, inner_w * frac, hgt))
                )
                cy += hgt + 10
            return view

        @objc.python_method
        def _chip(self, text, origin, index):
            from AppKit import NSAttributedString, NSForegroundColorAttributeName

            w = min(240.0, 22.0 + 7.0 * len(text))
            btn = NSButton.alloc().initWithFrame_(
                NSMakeRect(origin.x, origin.y, w, 26)
            )
            btn.setBordered_(False)
            btn.setTarget_(self)
            btn.setAction_("noteClicked:")
            btn.setTag_(int(index))
            btn.setWantsLayer_(True)
            if btn.layer() is not None:
                # radius 6 (native macOS feel — NOT a pill) per the redline.
                btn.layer().setCornerRadius_(_R_CONTROL)
                btn.layer().setBackgroundColor_(_c(255, 255, 255, 0.05).CGColor())
                btn.layer().setBorderWidth_(1.0)
                btn.layer().setBorderColor_(_c(255, 255, 255, 0.14).CGColor())
            btn.setAttributedTitle_(
                NSAttributedString.alloc().initWithString_attributes_(
                    "◇ " + text + "  ↗", {NSForegroundColorAttributeName: _c(224, 213, 191)}
                )
            )
            btn.setFont_(NSFont.systemFontOfSize_(11.5))
            btn.setToolTip_("Otwórz w Obsidian: " + text)
            return btn

        # -- actions --------------------------------------------------------- #

        def railRowClicked_(self, sender):
            self._deck.select(int(sender.tag()))
            self._reset_card_state()
            self._render()

        def directionClicked_(self, sender):
            i = int(sender.tag())
            if i in self._selected:
                self._selected.discard(i)
            else:
                self._selected.add(i)
            self._capture_scroll()
            self._render()

        def toggleEvidenceClicked_(self, sender):
            self._grounded = not self._grounded
            self._capture_scroll()
            self._render()

        def noteClicked_(self, sender):
            names = getattr(self, "_note_basenames", [])
            i = int(sender.tag())
            if 0 <= i < len(names):
                self._invoke_callback("open_note", names[i])

        def transcriptClicked_(self, sender):
            paths = getattr(self, "_recent_paths", [])
            i = int(sender.tag())
            if 0 <= i < len(paths) and paths[i] is not None:
                self._invoke_callback("open_transcript", paths[i])

        def continueLLMClicked_(self, sender):
            self._do_handoff(ho.LLM)

        def taskClicked_(self, sender):
            self._do_handoff(ho.TASK)

        def calendarClicked_(self, sender):
            self._do_handoff(ho.CALENDAR)

        def copyClicked_(self, sender):
            self._do_handoff(ho.CLIPBOARD)

        def switchLLMClicked_(self, sender):
            order = list(ho.LLM_TOOLS.keys())  # only prefill-capable tools
            cur = getattr(config, "LLM_HANDOFF_TOOL", "claude")
            nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else "claude"
            config.LLM_HANDOFF_TOOL = nxt
            try:
                from src.config.settings import UserSettings

                s = UserSettings.load()
                s.ai_handoff_tool = nxt
                s.save()
            except Exception as exc:  # pragma: no cover - best effort
                logger.debug("could not persist handoff tool: %s", exc)
            self._capture_scroll()
            self._render()

        @objc.python_method
        def _do_handoff(self, target):
            """Gather view state on the main thread, dispatch OFF it.

            ho.dispatch runs subprocess (osascript/open/pbcopy); osascript can
            block on the TCC consent prompt or a Reminders cold launch — on
            the main thread that froze the whole app ('Not Responding').
            Mirrors the _recall_worker_/applyRecall_ pattern.
            """
            conn = self._deck.active()
            if conn is None or not self._selected:
                return
            idxs = sorted(i for i in self._selected if 0 <= i < len(conn.directions))
            dirs = [conn.directions[i] for i in idxs]
            tool = getattr(config, "LLM_HANDOFF_TOOL", "claude")
            evidence = [(e.date, e.note, e.quote) for e in conn.evidence]
            payload = {
                "target": target,
                "label": conn.resolved_label(),
                "rationale": conn.rationale,
                "evidence": evidence,
                "directions": dirs,
                "direction_idxs": idxs,
                "tool": tool,
                "sig": conn.sig or "",
                "conn_type": conn.synthesis_type,  # raw type only — never the display constant (keeps the canonical sig joinable)
                "notes": conn.notes,
            }
            import threading

            # Kept on self so tests (and a curious debugger) can join it.
            self._handoff_thread = threading.Thread(
                target=self._handoff_worker_, args=(payload,),
                name="HandoffDispatch", daemon=True,
            )
            self._handoff_thread.start()

        @objc.python_method
        def _handoff_worker_(self, payload):
            """Daemon thread: subprocess dispatch + signal append, then toast
            back on the main thread. A late toast is harmless — no epoch."""
            target = payload["target"]
            res = ho.dispatch(
                target,
                label=payload["label"],
                rationale=payload["rationale"],
                evidence=payload["evidence"],
                directions=payload["directions"],
                tool=payload["tool"],
            )
            try:
                vsig.record_action(
                    target,
                    sig=payload["sig"],
                    conn_type=payload["conn_type"],
                    notes=payload["notes"],
                    directions=payload["direction_idxs"],
                    tool=(payload["tool"] if target == ho.LLM else ""),
                )
            except Exception as exc:  # pragma: no cover - signal is best-effort
                logger.debug("record_action failed: %s", exc)
            self._pending_handoff = {"toast": res.toast}
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "applyHandoff:", None, False
            )

        def applyHandoff_(self, _ignored):
            payload = getattr(self, "_pending_handoff", None)
            if not payload:
                return
            self._pending_handoff = None
            self._show_toast(payload["toast"])

        @objc.python_method
        def _reset_card_state(self):
            self._selected = set()
            self._grounded = False
            self._scroll_y = 0.0  # a new connection starts at the top

        @objc.python_method
        def _capture_scroll(self):
            """Remember the reader's scroll offset before a full rebuild."""
            s = getattr(self, "_scroll", None)
            if s is not None:
                try:
                    self._scroll_y = float(s.contentView().bounds().origin.y)
                except Exception:  # pragma: no cover - defensive
                    pass

        @objc.python_method
        def _invoke_callback(self, name, *args):
            cb = self._callbacks.get(name)
            if cb is None:
                logger.debug("dashboard callback %r not wired", name)
                return
            try:
                cb(*args)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("dashboard callback %r failed: %s", name, exc)

        @objc.python_method
        def _recent_transcripts(self):
            cb = self._callbacks.get("recent_transcripts")
            if cb is None:
                return []
            try:
                return list(cb() or [])
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("recent_transcripts callback failed: %s", exc)
                return []

        @objc.python_method
        def _emit_action(self, target):
            """Record the user's footer triage on the active connection.

            Zachowaj → ``save`` (quiet archive), Odrzuć → ``none`` (a signal, not a
            suppressor). Captured at click, before any deck mutation. Best-effort.
            """
            conn = self._deck.active()
            if conn is None:
                return
            vsig.record_action(
                target,
                sig=conn.sig or "",
                conn_type=conn.synthesis_type,  # raw type only — never the display constant (keeps the canonical sig joinable)
                notes=conn.notes,
            )

        def keepClicked_(self, sender):
            self._emit_action(vsig.TARGET_SAVE)
            if not self._show_keep_flash():
                self._deck.keep()
                self._reset_card_state()
                self._render()
                return
            from Foundation import NSTimer

            self._keep_timer = (
                NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    0.8, self, "afterKeepFlash:", None, False
                )
            )

        def afterKeepFlash_(self, timer):
            self._deck.keep()
            self._reset_card_state()
            self._render()

        def dismissClicked_(self, sender):
            self._emit_action(vsig.TARGET_NONE)
            if not self._show_dismiss_flash():
                self._deck.dismiss()
                self._reset_card_state()
                self._render()
                return
            from Foundation import NSTimer

            self._dismiss_timer = (
                NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    0.7, self, "afterDismissFlash:", None, False
                )
            )

        def afterDismissFlash_(self, timer):
            self._deck.dismiss()
            self._reset_card_state()
            self._render()

        @objc.python_method
        def _show_flash(self, symbol, title, subtitle, color, bloom):
            win = self._window
            if win is None or win.contentView() is None:
                return False
            content = win.contentView()
            b = content.bounds()
            frame = NSMakeRect(
                _RAIL_W, _HEADER_H, b.size.width - _RAIL_W, b.size.height - _HEADER_H
            )
            overlay = _FlashOverlay.alloc().initWithFrame_(frame)
            overlay.bloom = bloom
            spark = _label(symbol, 34, color, bold=False)
            spark.setAlignment_(1)
            spark.setFrame_(NSMakeRect(0, frame.size.height * 0.4 - 40, frame.size.width, 44))
            overlay.addSubview_(spark)
            lab = _label(title, 19, _cream(), bold=True)
            lab.setAlignment_(1)
            lab.setFrame_(NSMakeRect(0, frame.size.height * 0.4 + 6, frame.size.width, 26))
            overlay.addSubview_(lab)
            sub = _label(subtitle, 12.5, _muted())
            sub.setAlignment_(1)
            sub.setFrame_(NSMakeRect(0, frame.size.height * 0.4 + 34, frame.size.width, 18))
            overlay.addSubview_(sub)
            content.addSubview_(overlay)
            return True

        @objc.python_method
        def _show_keep_flash(self):
            return self._show_flash(
                "✦", "Zachowane", "cichy schowek · następne połączenie",
                _gold(), (244, 221, 142, 0.26),
            )

        @objc.python_method
        def _show_dismiss_flash(self):
            return self._show_flash(
                "✕", "Odrzucone", "następne połączenie",
                _c(176, 162, 141), (176, 162, 141, 0.12),
            )

        @objc.python_method
        def _show_toast(self, text):
            win = self._window
            if win is None or win.contentView() is None:
                return
            content = win.contentView()
            b = content.bounds()
            tw = min(420.0, 80.0 + 7.0 * len(text))
            toast = _DashFlippedView.alloc().initWithFrame_(
                NSMakeRect(
                    _RAIL_W + (b.size.width - _RAIL_W - tw) / 2,
                    b.size.height - _FOOTER_H - 44,
                    tw, 32,
                )
            )
            toast.setWantsLayer_(True)
            if toast.layer() is not None:
                toast.layer().setCornerRadius_(9.0)
                toast.layer().setBackgroundColor_(_gold().CGColor())
            lab = _label(text, 12.5, _c(14, 13, 18), bold=True)
            lab.setAlignment_(1)
            lab.setFrame_(NSMakeRect(8, 8, tw - 16, 16))
            toast.addSubview_(lab)
            content.addSubview_(toast)
            if self._toast is not None:
                self._toast.removeFromSuperview()
            self._toast = toast
            from Foundation import NSTimer

            self._toast_timer = (
                NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    1.7, self, "removeToast:", None, False
                )
            )

        def removeToast_(self, timer):
            t = getattr(self, "_toast", None)
            if t is not None:
                t.removeFromSuperview()
                self._toast = None

        # -- public API ------------------------------------------------------ #

        def updateDeck_(self, deck):
            self._deck = deck if deck is not None else im.InsightDeck()
            self._reset_card_state()
            if self._window is not None and self._window.isVisible():
                self._render()

        def setTranscribing_(self, flag):
            new = bool(flag)
            if new == self._transcribing:
                return
            self._transcribing = new
            if self._window is not None and self._window.isVisible():
                self._render()


def build_dashboard_window(
    deck: Optional["im.InsightDeck"] = None,
    callbacks: Optional[Dict[str, Callable]] = None,
):
    """Create the dashboard controller, or ``None`` without AppKit.

    ``deck`` defaults to the latest digest (or :func:`insight_model.sample_deck`
    until the pipeline lands). The returned object exposes ``showWindow`` and
    ``updateDeck_``.
    """
    if not _APPKIT_AVAILABLE:
        return None
    try:
        if deck is None:
            from src.ui.insight_pipeline import latest_deck

            deck = latest_deck() or im.sample_deck()
        return _DashboardController.alloc().initWithDeck_callbacks_(
            deck, callbacks or {}
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Could not build dashboard window: %s", exc)
        return None
