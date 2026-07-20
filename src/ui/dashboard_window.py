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
from src.config.defaults import APP_SUPPORT_DIR
from src.connections import handoff as ho
from src.connections import validation_signal as vsig
from src.logger import logger
from src.ui import insight_model as im
from src.ui import note_renderer as nrend
from src.ui import obsidian_link

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
        NSPanel,
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
    from Foundation import NSObject, NSURL

    _APPKIT_AVAILABLE = True
except ImportError:  # pragma: no cover - non-mac
    _APPKIT_AVAILABLE = False

try:  # WKWebView hosts the in-app note reader; optional like AppKit.
    from WebKit import (
        WKWebpagePreferences,
        WKWebView,
        WKWebViewConfiguration,
    )

    try:
        from WebKit import WKNavigationActionPolicyAllow as _WK_ALLOW
        from WebKit import WKNavigationActionPolicyCancel as _WK_CANCEL
    except ImportError:  # pragma: no cover - constants absent in old wrappers
        _WK_ALLOW, _WK_CANCEL = 1, 0

    _WEBKIT_AVAILABLE = True
except ImportError:  # pragma: no cover - non-mac / stripped env
    _WEBKIT_AVAILABLE = False
    _WK_ALLOW, _WK_CANCEL = 1, 0


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
_ROW_H = 64.0  # rail row step: ~58pt row (10/11/11 pad + 2-line snippet) + 6 gap
_FOOTER_H = 46.0
_BAR_H = 48.0  # inline directions bar (C4) — lives UNDER the list, in the scroll
_ASKBAR_H = 56.0  # pull entry strip under the header (recall — Faza 3)
_TOOLBAR_H = 36.0  # ask toolbar over the reader column (U6 rev. 3)
_SEC_H = 30.0  # rail accordion section header (C8)
_SEG_H = 30.0  # triage segment track (3px pad + 24px items)
_SHEET_W = 560.0  # ask history sheet (U8)
# Radius family (design: one decision, held everywhere — native macOS feel).
_R_CONTROL = 6.0  # buttons, segment track, CTA, icons
_R_CHECK = 5.0  # checkbox
_R_ROW = 12.0  # rows, cards
_R_CARD = 14.0  # rail card / panels

# Neutral scale (visual-identity review 2026-07-20): ONE hairline + three fills,
# on white-over-dark. Replaces six ad-hoc alphas (0.04/0.055/0.06/0.07/0.08/
# 0.018) that made every divider and surface a slightly different grey. Every
# thin separator uses _HAIRLINE_A — no exceptions — so lines never mismatch.
_HAIRLINE_A = 0.07  # every thin divider / rule / separator / border
_FILL_SUBTLE_A = 0.04  # recessed strips: segment track, quiet fills
_FILL_RAISED_A = 0.055  # cards, panels, active rows
_FILL_GHOST_A = 0.02  # ghost-button rest state

# The reader is loaded via loadFileURL (not loadHTMLString with a nil
# baseURL): a page with no real document URL makes in-page "#anchor" jumps
# ("Przejdź do transkrypcji") unreliable on some WebKit builds. A real
# file:// URL fixes that outright and also makes the navigation policy exact
# — content can never spoof "this is our own page" (see the policy delegate).
_READER_HTML_PATH = APP_SUPPORT_DIR / "runtime" / "reader" / "note.html"


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

    class _DashWindow(NSWindow):
        """Konstelacja window: routes ⌘K to the ask field (U6 rev. 3).

        A menu-bar (LSUIElement) app has no main menu, so key equivalents are
        never translated — without this, ⌘K would be a dead shortcut.
        """

        def performKeyEquivalent_(self, event):
            try:
                from AppKit import NSEventModifierFlagCommand

                if event.modifierFlags() & NSEventModifierFlagCommand and (
                    (event.charactersIgnoringModifiers() or "").lower() == "k"
                ):
                    delegate = self.delegate()
                    if delegate is not None and delegate.respondsToSelector_(
                        "focusAskField"
                    ):
                        delegate.focusAskField()
                        return True
            except Exception:  # pragma: no cover - defensive
                pass
            return objc.super(_DashWindow, self).performKeyEquivalent_(event)

    class _AskPanel(NSPanel):
        """Borderless ask-bar panel that can actually take keyboard input.

        A borderless NSPanel refuses key status by default, so the field
        looked focused but never received a keystroke — and with no Esc or
        click-away path the overlay could only be escaped by quitting the
        app. Key here, Esc and losing key both dismiss.
        """

        def canBecomeKeyWindow(self):
            return True

        def cancelOperation_(self, _sender):  # Esc
            self.orderOut_(None)

        def resignKeyWindow(self):  # click-away / app switch
            objc.super(_AskPanel, self).resignKeyWindow()
            self.orderOut_(None)

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
                    s,
                    {NSFontAttributeName: font, NSForegroundColorAttributeName: color},
                )
                px = x if right is None else right - a.size().width
                a.drawAtPoint_(NSMakePoint(px, (b.size.height - a.size().height) / 2.0))

            body = _c(255, 255, 255) if hot else _c(201, 187, 166)
            if spec.get("checked"):
                _draw("✓", 12.0, body, NSFont.systemFontOfSize_weight_(11.0, 0.0))
            _draw(
                spec.get("label", ""),
                28.0,
                body,
                NSFont.systemFontOfSize_weight_(12.5, 0.0),
            )
            n = spec.get("count", 0)
            cnt_color = (
                _c(255, 255, 255)
                if hot
                else (_gold() if spec.get("is_new") else _c(140, 130, 115))
            )
            _draw(
                str(n),
                0.0,
                cnt_color,
                NSFont.monospacedDigitSystemFontOfSize_weight_(11.0, 0.0),
                right=b.size.width - 14.0,
            )

    class _SigilView(NSView):
        """The demoted constellation: a small static mark whose *shape* encodes
        the connection type (axis = contradiction, convergence = shared thread,
        branching = emergent idea). Drawn in Core Graphics; no animation."""

        def isFlipped(self):
            return True

        def drawRect_(self, _rect):
            # Ported 1:1 from the geometry spec (port-appkit/06): viewBox 32×32.
            # A node = radial glow (TYPE colour) + fixed #C24010 core r2.5 +
            # #FAF3E2 centre r1; the bloom = gold radial r0×2.6 → #F4DD8E disc
            # r0 → #FFFBF0 spark r0×0.4. Only strokes + node glow take the type
            # colour; core and bloom are constant across types.
            b = self.bounds()
            s = b.size.width / 32.0

            def pt(x, y):
                return NSMakePoint(x * s, y * s)

            stroke = _hex(getattr(self, "stroke_hex", "#D9542A"))
            layout = getattr(self, "layout_key", "thread")

            def _alpha(color, a):
                return color.colorWithAlphaComponent_(a)

            def line(a, z, alpha, w, dash=None):
                p = NSBezierPath.bezierPath()
                p.moveToPoint_(a)
                p.lineToPoint_(z)
                p.setLineWidth_(w * s)
                p.setLineCapStyle_(1)  # round
                if dash:
                    p.setLineDash_count_phase_([d * s for d in dash], len(dash), 0.0)
                _alpha(stroke, alpha).setStroke()
                p.stroke()

            def quad(a, q, z, alpha, w):
                # Quadratic → cubic: c1 = a + 2/3(q−a), c2 = z + 2/3(q−z).
                c1 = NSMakePoint(
                    a.x + 2.0 / 3.0 * (q.x - a.x), a.y + 2.0 / 3.0 * (q.y - a.y)
                )
                c2 = NSMakePoint(
                    z.x + 2.0 / 3.0 * (q.x - z.x), z.y + 2.0 / 3.0 * (q.y - z.y)
                )
                p = NSBezierPath.bezierPath()
                p.moveToPoint_(a)
                p.curveToPoint_controlPoint1_controlPoint2_(z, c1, c2)
                p.setLineWidth_(w * s)
                p.setLineCapStyle_(1)
                _alpha(stroke, alpha).setStroke()
                p.stroke()

            def disc(center, r, color):
                color.setFill()
                NSBezierPath.bezierPathWithOvalInRect_(
                    NSMakeRect(center.x - r, center.y - r, 2 * r, 2 * r)
                ).fill()

            def radial(center, radius, colors, locs):
                grad = NSGradient.alloc().initWithColors_atLocations_colorSpace_(
                    colors, locs, NSColorSpace.sRGBColorSpace()
                )
                if grad is not None:
                    grad.drawFromCenter_radius_toCenter_radius_options_(
                        center, 0.0, center, radius, 0
                    )

            def node(x, y):
                c = pt(x, y)
                radial(
                    c,
                    7.0 * s,
                    [_alpha(stroke, 0.50), _alpha(stroke, 0.08), _alpha(stroke, 0.0)],
                    [0.0, 0.6, 1.0],
                )
                disc(c, 2.5 * s, _c(194, 64, 16))  # core #C24010 (fixed)
                disc(c, 1.0 * s, _c(250, 243, 226))  # centre #FAF3E2 (fixed)

            def bloom(x, y, r0):
                c = pt(x, y)
                radial(
                    c,
                    r0 * 2.6 * s,
                    [
                        _c(244, 221, 142, 0.90),
                        _c(214, 176, 51, 0.30),
                        _c(214, 176, 51, 0.0),
                    ],
                    [0.0, 0.55, 1.0],
                )
                disc(c, r0 * s, _c(244, 221, 142))  # #F4DD8E
                disc(c, r0 * 0.4 * s, _c(255, 251, 240))  # spark #FFFBF0

            if layout == "contradiction":
                # z-order: dashed baseline → arcs → bloom → nodes on top
                line(pt(5, 16), pt(27, 16), 0.28, 1.0, dash=(2.0, 4.0))
                quad(pt(8, 16), pt(16, 7), pt(24, 16), 0.85, 1.5)
                quad(pt(8, 16), pt(16, 25), pt(24, 16), 0.85, 1.5)
                bloom(16, 16, 2.4)
                node(8, 16)
                node(24, 16)
            elif layout == "triad":
                # z-order: lines → nodes → bloom on top (centre)
                for x, y in ((8, 9), (25, 12), (15, 26)):
                    line(pt(16, 16), pt(x, y), 0.55, 1.3)
                for x, y in ((8, 9), (25, 12), (15, 26)):
                    node(x, y)
                bloom(16, 16, 3.0)
            else:  # thread (shared) — z-order: lines → nodes → bloom (apex)
                line(pt(9, 24), pt(16, 9), 0.7, 1.4)
                line(pt(23, 24), pt(16, 9), 0.7, 1.4)
                node(9, 24)
                node(23, 24)
                bloom(16, 9, 3.0)

    class _DirBarBG(NSView):
        """C4 directions-bar background: warm dark gradient, terracotta
        border, radius 12 — drawn natively (no web-only effects)."""

        def isFlipped(self):
            return True

        def drawRect_(self, _rect):
            b = self.bounds()
            path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                b, _R_ROW, _R_ROW
            )
            grad = NSGradient.alloc().initWithColors_atLocations_colorSpace_(
                [_c(44, 24, 17, 0.5), _c(28, 16, 12, 0.75)],
                [0.0, 1.0],
                NSColorSpace.sRGBColorSpace(),
            )
            if grad is not None:
                grad.drawInBezierPath_angle_(path, 90.0)
            _c(217, 84, 42, 0.28).setStroke()
            path.setLineWidth_(1.0)
            path.stroke()

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
            v.layer().setBackgroundColor_(_c(255, 255, 255, _FILL_RAISED_A).CGColor())
            v.layer().setCornerRadius_(radius)
        return v

    def _label(text, size, color, bold=False):
        field = NSTextField.labelWithString_(text)
        f = (
            NSFont.boldSystemFontOfSize_(size)
            if bold
            else NSFont.systemFontOfSize_(size)
        )
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

        s = text or ""
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

    def _hairline():
        """1 physical device pixel (spec §05): 0.5pt on Retina, 1pt @1x."""
        try:
            from AppKit import NSScreen

            scr = NSScreen.mainScreen()
            return 1.0 / (scr.backingScaleFactor() if scr else 2.0)
        except Exception:  # pragma: no cover - defensive
            return 0.5

    def _reduce_motion():
        """prefers-reduced-motion (spec §04): cuts instead of slides."""
        try:
            from AppKit import NSWorkspace

            return bool(
                NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion()
            )
        except Exception:  # pragma: no cover - defensive
            return False

    def _slide_in(view, dy, dur, ease_pts=(0.4, 0.0, 0.2, 1.0)):
        """opacity 0→1 + translation.y dy→0 (spec §04). Reduce-motion → cut."""
        layer = view.layer() if view.wantsLayer() else None
        if layer is None or _reduce_motion():
            return  # state is already final — the cut
        try:
            from Quartz import (
                CAAnimationGroup,
                CABasicAnimation,
                CAMediaTimingFunction,
            )

            o = CABasicAnimation.animationWithKeyPath_("opacity")
            o.setFromValue_(0.0)
            o.setToValue_(1.0)
            t = CABasicAnimation.animationWithKeyPath_("transform.translation.y")
            t.setFromValue_(dy)
            t.setToValue_(0.0)
            g = CAAnimationGroup.animation()
            g.setAnimations_([o, t])
            g.setDuration_(dur)
            g.setTimingFunction_(
                CAMediaTimingFunction.functionWithControlPoints____(*ease_pts)
            )
            layer.addAnimation_forKey_(g, "slideIn")
        except Exception:  # pragma: no cover - animation is decoration
            pass

    def _typo_width(text, style):
        """Rendered width of ``text`` in ``style`` (kern-aware)."""
        from AppKit import NSAttributedString
        from src.ui import typography as _T

        s = text or ""
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

        s = text or ""
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
            # Kill the factory cell title ("Button") — pills composed of
            # subview labels (keep, split-CTA, caret) otherwise draw BOTH.
            self.setTitle_("")
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
            # ALWAYS with an explicit shadowPath: a CALayer shadow without one
            # is rendered from the layer's content INCLUDING sublayers, which
            # duplicates any label subview as a blurred ghost.
            if self._hovering:
                self._set_pill_shadow_path(layer)
                layer.setShadowColor_(_c(0, 0, 0).CGColor())
                layer.setShadowOpacity_(0.30)
                layer.setShadowRadius_(5.0)
                layer.setShadowOffset_(NSMakeSize(0, -2))
            else:
                layer.setShadowOpacity_(0.0)

        @objc.python_method
        def _set_pill_shadow_path(self, layer):
            try:
                from Quartz import CGPathCreateWithRoundedRect

                b = self.bounds()
                r = min(layer.cornerRadius(), b.size.height / 2.0)
                layer.setShadowPath_(CGPathCreateWithRoundedRect(b, r, r, None))
            except Exception:  # pragma: no cover - shadow stays content-based
                pass

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
            self.addCursorRect_cursor_(self.bounds(), NSCursor.pointingHandCursor())

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
            # U9: the window lands on the first non-empty triage view; the
            # user's in-session choice wins from then on.
            self._deck.focus_first_nonempty()
            self._callbacks: Dict[str, Callable] = callbacks or {}
            # C8 accordion: exactly one rail section open at a time.
            self._section = "serendypacje"  # serendypacje | zapytales | notatki
            self._ask_sheet = None  # history sheet (U8) when open
            self._ask_scrim = None  # reader-only scrim behind the sheet
            self._toolbar_field = None  # the ask field in the toolbar
            self._hist_idx = -1  # ↑↓ position in the history sheet
            self._notes_rows: List = []  # (title, path) rows of the Notatki section
            self._recent_paths: List = []  # legacy hook (transcriptClicked_)
            self._asked_rows: List = []  # ask-history entries behind rail rows
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
            self._mode = "insight"  # "insight" | "recall" | "note"
            # in-app note reader (markdown-reader plan)
            self._note_path = None  # Path of the note shown in "note" mode
            self._note_html = ""  # rendered page for _note_path
            self._note_stack: List = []  # wikilink breadcrumb (previous paths)
            self._note_return_mode = "insight"  # mode „← Wróć" exits to
            self._webview = None  # persistent WKWebView (note mode)
            self._webview_path = None  # note whose HTML the webview holds
            self._reader_page_url = None  # the loaded file:// URL, for policy
            self._recall = None  # RecallResults view-model when in recall mode
            self._recall_note_ids: List[str] = []  # tag -> note_id for ↗ open
            self._query = ""  # last query text (persists across rebuilds)
            self._recall_loading = False  # search in flight (off the main thread)
            self._recall_status = "ok"  # "ok" | "empty" | "unavailable" (honest states)
            self._pending_recall = None  # worker→main-thread handoff payload
            self._recall_raw: List = []  # raw hits kept for the synthesis escalation
            self._answer = None  # RecallAnswer once synthesized (the LLM door)
            self._answer_loading = False  # synthesis in flight
            self._pending_answer = None  # synth worker→main-thread handoff
            self._synth_note_ids: List[str] = (
                []
            )  # tag -> note_id for answer-card ↗ open
            self._answer_failed = False  # last synthesis attempt returned nothing
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
            win = _DashWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, win_w, win_h), mask, NSBackingStoreBuffered, False
            )
            win.setTitle_("Timshel")
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
            # U6 rev. 3: the title-bar ⌕ accessory is RETIRED — the pull entry
            # is the toolbar field over the reader column. Title-bar stays
            # clean (traffic lights + title).

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

        def windowWillClose_(self, _note):
            # Closing while reading must release the WKWebView (and its
            # out-of-process WebContent) — the window object itself survives
            # (setReleasedWhenClosed False) and would pin it for the session.
            if self._mode == "note":
                mode = self._note_return_mode
                self._exit_note_mode()
                self._mode = mode

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

            # Layout (U6 rev. 3): the rail owns its full column up to the
            # title-bar; the ask toolbar spans ONLY the reader column, starting
            # exactly at the rail's right edge — it never overlaps the rail.
            rail_h = h - _HEADER_H
            rail = self._build_rail(NSMakeRect(0, 0, _RAIL_W, rail_h))
            rail.setFrameOrigin_(NSMakePoint(0, _HEADER_H))
            bg.addSubview_(rail)

            reader_w = w - _RAIL_W
            toolbar = self._build_toolbar(NSMakeRect(0, 0, reader_w, _TOOLBAR_H))
            toolbar.setFrameOrigin_(NSMakePoint(_RAIL_W, _HEADER_H))
            bg.addSubview_(toolbar)

            reader_h = rail_h - _TOOLBAR_H
            reader = self._build_reader(NSMakeRect(0, 0, reader_w, reader_h))
            reader.setFrameOrigin_(NSMakePoint(_RAIL_W, _HEADER_H + _TOOLBAR_H))
            bg.addSubview_(reader)

            self._window.setContentView_(bg)
            # A rebuild drops the transient ask sheet (its views lived in the
            # old content view) — clear the refs so state stays honest.
            self._ask_sheet = None
            self._ask_scrim = None

        # C8 accordion — one grammar of section headers carries all three
        # peer sections. NOT a dropdown: disclosure in place, one open at a
        # time, collapsed headers keep their counters (anti-error 1 & 10).
        _SECTIONS = ("serendypacje", "zapytales", "notatki")
        _SECTION_LABELS = {
            "serendypacje": "Serendypacje",
            "zapytales": "Zapytałeś",
            "notatki": "Notatki",
        }

        @objc.python_method
        def _build_rail(self, frame):
            # The rail sits on the SAME continuous window field as the reader —
            # no darkening wash. The radial glow is centered on the reader
            # column (0.64·W), so the rail is naturally a touch dimmer (it's in
            # the gradient's tail): recessed, but the same material. A single
            # hairline (in _build_reader) is the only rail↔reader boundary.
            view = _DashFlippedView.alloc().initWithFrame_(frame)

            from src.connections import ask_history

            counts = self._deck.counts()
            new_n = counts.get(im.NEW, 0)
            self._asked_rows = list(ask_history.recent(50))
            self._notes_rows = self._recent_transcripts()
            notes_n = self._notes_count(len(self._notes_rows))

            # Section counters (always visible, anti-error 10): Serendypacje
            # shows "N nowe" in gold only when new > 0, else the total.
            ser_cnt = f"{new_n} nowe" if new_n > 0 else str(len(self._deck))
            spec = (
                ("serendypacje", ser_cnt, new_n > 0),
                ("zapytales", str(len(self._asked_rows)), False),
                ("notatki", str(notes_n), False),
            )

            # Open section takes the remaining height (flex 1 + inner scroll);
            # the other headers stay visible — the rail never pushes a section
            # out of the window.
            body_h = max(frame.size.height - 3 * _SEC_H - 18.0, 60.0)
            cy = 6.0
            for idx, (key, cnt, gold) in enumerate(spec):
                self._add_section_header(
                    view, frame, cy, idx, key, cnt, gold, open_=(key == self._section)
                )
                cy += _SEC_H
                if key == self._section:
                    body = self._build_section_body(
                        key, NSMakeRect(6, cy, frame.size.width - 12, body_h)
                    )
                    view.addSubview_(body)
                    cy += body_h
            return view

        @objc.python_method
        def _add_section_header(self, view, frame, y, idx, key, count, gold, open_):
            """One 30px accordion header: label · counter · chevron (C8)."""
            from src.ui.hover import make_hover_button

            btn = make_hover_button(
                NSMakeRect(6, y, frame.size.width - 12, _SEC_H - 2)
            ) or (
                NSButton.alloc().initWithFrame_(
                    NSMakeRect(6, y, frame.size.width - 12, _SEC_H - 2)
                )
            )
            btn.setTitle_("")
            btn.setBordered_(False)
            btn.setTarget_(self)
            btn.setAction_("sectionHeaderClicked:")
            btn.setTag_(idx)
            if btn.layer() is not None:
                btn.layer().setCornerRadius_(8.0)
            w = frame.size.width - 12
            label = self._SECTION_LABELS[key]
            lab = _typo_label(
                label, "collapsed_h", NSMakeRect(8, 7, w - 90, 14), wrapping=False
            )
            if open_:  # otwarta: label lights up to rgba(250,243,226,.82)
                try:
                    lab.setTextColor_(_c(250, 243, 226, 0.82))
                except Exception:  # pragma: no cover
                    pass
            btn.addSubview_(lab)
            cnt_style = "rail_count" if gold else "menu_shortcut"
            cw = _typo_width(str(count), cnt_style) + 6
            cnt = _typo_label(
                str(count),
                cnt_style,
                NSMakeRect(w - 22 - cw, 7, cw, 14),
                wrapping=False,
            )
            btn.addSubview_(cnt)
            car = _label("›", 11.0, _muted())
            car.setFrame_(NSMakeRect(w - 18, 6, 12, 15))
            if open_:
                try:  # chevron rotates 90° when the section is open
                    car.setFrameCenterRotation_(-90.0)
                except Exception:  # pragma: no cover
                    pass
            btn.addSubview_(car)
            view.addSubview_(btn)

        def sectionHeaderClicked_(self, sender):
            key = self._SECTIONS[int(sender.tag()) % len(self._SECTIONS)]
            if key == self._section:
                return  # exactly one section open — no closed-all state
            self._section = key
            # The reader follows the section (BEHAVIOR §2.2): Serendypacje →
            # insight mode; Zapytałeś → last query (or the ask empty state).
            # Notatki is pure navigation — the reader keeps its content.
            if key == "serendypacje":
                if self._mode == "note":
                    self._exit_note_mode()
                self._mode = "insight"
            elif key == "zapytales":
                if self._mode == "note":
                    self._exit_note_mode()
                self._mode = "recall"
            self._render()

        @objc.python_method
        def _build_section_body(self, key, frame):
            """The open section's content area (internal scroll)."""
            holder = _DashFlippedView.alloc().initWithFrame_(frame)
            if key == "serendypacje":
                self._build_serendypacje_body(holder, frame)
            elif key == "zapytales":
                self._build_asked_body(holder, frame)
            else:
                self._build_notes_body(holder, frame)
            return holder

        @objc.python_method
        def _wrap_in_scroll(self, doc, content_h, frame_y, frame):
            scroll = NSScrollView.alloc().initWithFrame_(
                NSMakeRect(0, frame_y, frame.size.width, frame.size.height - frame_y)
            )
            scroll.setHasVerticalScroller_(True)
            scroll.setAutohidesScrollers_(True)
            scroll.setDrawsBackground_(False)
            scroll.setBorderType_(0)
            doc.setFrame_(
                NSMakeRect(
                    0,
                    0,
                    frame.size.width,
                    max(content_h, frame.size.height - frame_y),
                )
            )
            scroll.setDocumentView_(doc)
            return scroll

        @objc.python_method
        def _build_serendypacje_body(self, holder, frame):
            # U9/C1: the triage segment pins to the top of the list (it never
            # scrolls away); the rows scroll under it.
            self._build_triage_segment(holder, frame.size.width)
            top = _SEG_H + 6.0
            vis = self._deck.visible()
            if not vis:
                self._build_rail_empty_view(holder, frame, top)
                return
            doc = _DashFlippedView.alloc().initWithFrame_(
                NSMakeRect(0, 0, frame.size.width, 10)
            )
            cy = 2.0
            for i, conn in vis:
                self._add_rail_row(
                    doc, conn, i, NSMakeRect(2, cy, frame.size.width - 4, _ROW_H - 6)
                )
                cy += _ROW_H
            holder.addSubview_(self._wrap_in_scroll(doc, cy, top, frame))

        @objc.python_method
        def _build_triage_segment(self, holder, width):
            """C1 hybrid segment: active = icon+label+count (tinted), inactive
            = icon+count (ghost). Counters always visible; 0 stays clickable."""
            from src.ui import style

            track = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, _SEG_H))
            track.setWantsLayer_(True)
            if track.layer() is not None:
                track.layer().setCornerRadius_(_R_CONTROL)
                track.layer().setBackgroundColor_(
                    _c(255, 255, 255, _FILL_SUBTLE_A).CGColor()
                )
                track.layer().setBorderWidth_(1.0)
                track.layer().setBorderColor_(_c(255, 255, 255, 0.10).CGColor())

            counts = self._deck.counts()
            segs = (
                (im.NEW, "Nowe", "sparkle"),
                (im.KEPT, "Zachowane", "bookmark"),
                (im.DISMISSED, "Odrzucone", "archivebox"),
            )
            PAD, GAP = 3.0, 2.0
            item_h = _SEG_H - 2 * PAD
            # Natural widths for the inactive items (icon 14 + count), active
            # flexes into the remaining track width.
            widths = []
            for key, label, _ in segs:
                n = counts.get(key, 0)
                if key == self._deck.view:
                    widths.append(None)  # flex
                else:
                    widths.append(8 + 14 + 5 + _typo_width(str(n), "menu_shortcut") + 8)
            fixed = sum(w for w in widths if w is not None) + 2 * PAD + GAP * 2
            flex_w = max(width - fixed, 60.0)
            x = PAD
            for tag, ((key, label, symbol), w) in enumerate(zip(segs, widths)):
                n = counts.get(key, 0)
                iw = flex_w if w is None else w
                active = key == self._deck.view
                seg = NSButton.alloc().initWithFrame_(NSMakeRect(x, PAD, iw, item_h))
                seg.setTitle_("")
                seg.setBordered_(False)
                seg.setTarget_(self)
                seg.setAction_("triageSegClicked:")
                seg.setTag_(tag)
                seg.setToolTip_(f"{label} — {n}")
                seg.setWantsLayer_(True)
                if seg.layer() is not None:
                    seg.layer().setCornerRadius_(4.0)
                    if active:
                        seg.layer().setBackgroundColor_(_c(217, 84, 42, 0.16).CGColor())
                        seg.layer().setBorderWidth_(1.0)
                        seg.layer().setBorderColor_(_c(217, 84, 42, 0.55).CGColor())
                # icon (template SF symbol, tinted like the segment text)
                empty = n == 0 and not active
                tint = (
                    _c(250, 243, 226)
                    if active
                    else (_c(140, 130, 115) if empty else _c(176, 162, 141))
                )
                img = style.sf_symbol(symbol, point=10.5, weight="medium")
                ix = 8.0
                if img is not None:
                    iv = NSImageView.alloc().initWithFrame_(
                        NSMakeRect(ix, (item_h - 14) / 2.0, 14, 14)
                    )

                    iv.setImage_(img)
                    try:
                        iv.setContentTintColor_(tint)
                    except Exception:  # pragma: no cover
                        pass
                    seg.addSubview_(iv)
                tx = ix + 14 + 5
                if active:  # label rides only on the active segment
                    lw = _typo_width(label, "seg_label") + 4
                    lab = _typo_label(
                        label,
                        "seg_label",
                        NSMakeRect(tx, (item_h - 13) / 2.0, lw, 13),
                        wrapping=False,
                    )
                    seg.addSubview_(lab)
                    tx += lw + 5
                cnt_col = (
                    _c(217, 84, 42)
                    if active
                    else (_c(90, 82, 73) if empty else _c(111, 102, 90))
                )
                cnt = _label(str(n), 10.0, cnt_col)
                try:
                    cnt.setFont_(
                        NSFont.monospacedDigitSystemFontOfSize_weight_(10.0, 0.0)
                    )
                except Exception:  # pragma: no cover
                    pass
                cnt.setFrame_(NSMakeRect(tx, (item_h - 13) / 2.0, 30, 13))
                seg.addSubview_(cnt)
                track.addSubview_(seg)
                x += iw + GAP
            holder.addSubview_(track)

        def triageSegClicked_(self, sender):
            key = (im.NEW, im.KEPT, im.DISMISSED)[int(sender.tag()) % 3]
            if self._mode == "note" and key == self._deck.view:
                # Same-view segment while reading = "back to insights" gesture:
                # behave like „← Wróć" — keep ticked directions and scroll.
                self._leave_note_for_insights()
                self._render()
                return
            if key != self._deck.view:
                self._leave_note_for_insights()
                self._deck.set_view(key)
                self._reset_card_state()
                self._render()

        @objc.python_method
        def _build_rail_empty_view(self, holder, frame, top):
            """U9: an empty triage view is a sentence + a bridge, never blank."""
            copy = {
                im.NEW: "Nic nowego. Digest wróci, gdy korpus urośnie.",
                im.KEPT: "Nic zachowanego. To, co zachowasz, czeka tutaj.",
                im.DISMISSED: "Nic odrzuconego.",
            }[self._deck.view]
            sent = _typo_label(
                copy,
                "rail_snippet",
                NSMakeRect(10, top + 10, frame.size.width - 20, 40),
            )
            sent.setMaximumNumberOfLines_(3)
            holder.addSubview_(sent)
            counts = self._deck.counts()
            bridge = None
            if self._deck.view != im.KEPT and counts.get(im.KEPT, 0) > 0:
                bridge = (
                    f"Zachowane czekają — {counts[im.KEPT]}",
                    "bridgeToKeptClicked:",
                )
            elif self._deck.view != im.NEW and counts.get(im.NEW, 0) > 0:
                bridge = (f"Nowe czekają — {counts[im.NEW]}", "bridgeToNewClicked:")
            if bridge is None:
                return
            from src.ui import style
            from src.ui.hover import make_hover_button

            text, action = bridge
            btn = make_hover_button(
                NSMakeRect(4, top + 58, frame.size.width - 8, 28)
            ) or NSButton.alloc().initWithFrame_(
                NSMakeRect(4, top + 58, frame.size.width - 8, 28)
            )
            btn.setTitle_("")
            btn.setBordered_(False)
            btn.setTarget_(self)
            btn.setAction_(action)
            if btn.layer() is not None:
                btn.layer().setCornerRadius_(8.0)
            mark = style.sf_symbol("bookmark", point=11.0, weight="regular")
            if mark is not None:
                iv = NSImageView.alloc().initWithFrame_(NSMakeRect(8, 7, 14, 14))
                iv.setImage_(mark)
                try:
                    iv.setContentTintColor_(_c(139, 224, 181))
                except Exception:  # pragma: no cover
                    pass
                btn.addSubview_(iv)
            lab = _label(text, 12.5, _c(139, 224, 181))
            lab.setFrame_(NSMakeRect(28, 6, frame.size.width - 60, 16))
            btn.addSubview_(lab)
            car = _label("›", 11.0, _c(139, 224, 181))
            car.setFrame_(NSMakeRect(frame.size.width - 24, 6, 12, 15))
            btn.addSubview_(car)
            holder.addSubview_(btn)

        def bridgeToKeptClicked_(self, _sender):
            self._leave_note_for_insights()
            self._deck.set_view(im.KEPT)
            self._reset_card_state()
            self._render()

        def bridgeToNewClicked_(self, _sender):
            self._leave_note_for_insights()
            self._deck.set_view(im.NEW)
            self._reset_card_state()
            self._render()

        @objc.python_method
        def _notes_count(self, fallback):
            cb = self._callbacks.get("notes_count")
            if cb is None:
                return fallback
            try:
                return int(cb())
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("notes_count callback failed: %s", exc)
                return fallback

        @objc.python_method
        def _add_icon_text_row(
            self, doc, y, width, symbol, text, tag, action, active=False
        ):
            """Shared row for Zapytałeś / Notatki: 18px icon column + 12.5px
            text clamped to 2 lines (C8), terracotta bar on the active query."""
            from src.ui import style
            from src.ui.hover import make_hover_button

            h = 40.0
            btn = make_hover_button(NSMakeRect(2, y, width - 4, h - 4)) or (
                NSButton.alloc().initWithFrame_(NSMakeRect(2, y, width - 4, h - 4))
            )
            btn.setTitle_("")
            btn.setBordered_(False)
            btn.setTarget_(self)
            btn.setAction_(action)
            btn.setTag_(tag)
            if btn.layer() is not None:
                btn.layer().setCornerRadius_(_R_ROW)
                if active:
                    btn.layer().setBackgroundColor_(
                        _c(255, 255, 255, _FILL_RAISED_A).CGColor()
                    )
            if active:
                bar = NSView.alloc().initWithFrame_(NSMakeRect(1, 7, 2.5, h - 18))
                bar.setWantsLayer_(True)
                if bar.layer() is not None:
                    bar.layer().setBackgroundColor_(_terracotta().CGColor())
                    bar.layer().setCornerRadius_(2.0)
                btn.addSubview_(bar)
            img = style.sf_symbol(symbol, point=12.0, weight="regular")
            if img is not None:
                iv = NSImageView.alloc().initWithFrame_(
                    NSMakeRect(9, (h - 4 - 18) / 2.0, 18, 18)
                )
                iv.setImage_(img)
                try:
                    iv.setContentTintColor_(_c(176, 162, 141))
                except Exception:  # pragma: no cover
                    pass
                btn.addSubview_(iv)
            text_w = width - 4 - 42
            th = min(_typo_measure(text, "rail_title_quiet", text_w), h - 8)
            lab = _typo_label(
                text,
                "rail_title_quiet",
                NSMakeRect(34, max((h - 4 - th) / 2.0, 2.0), text_w, th),
            )
            lab.setMaximumNumberOfLines_(2)
            try:
                lab.cell().setTruncatesLastVisibleLine_(True)
            except Exception:  # pragma: no cover
                pass
            btn.addSubview_(lab)
            doc.addSubview_(btn)
            return y + h

        @objc.python_method
        def _build_asked_body(self, holder, frame):
            doc = _DashFlippedView.alloc().initWithFrame_(
                NSMakeRect(0, 0, frame.size.width, 10)
            )
            cy = 2.0
            if not self._asked_rows:
                sent = _typo_label(
                    "Zapytaj swój korpus — historia pytań zostanie tutaj.",
                    "rail_snippet",
                    NSMakeRect(10, cy + 8, frame.size.width - 20, 40),
                )
                sent.setMaximumNumberOfLines_(3)
                doc.addSubview_(sent)
                cy += 60
            for i, entry in enumerate(self._asked_rows):
                cy = self._add_icon_text_row(
                    doc,
                    cy,
                    frame.size.width,
                    "magnifyingglass",
                    entry["query"],
                    i,
                    "askedRowClicked:",
                    active=(self._mode == "recall" and entry["query"] == self._query),
                )
            if self._asked_rows:
                from src.ui.hover import make_hover_button

                btn = make_hover_button(
                    NSMakeRect(2, cy + 4, frame.size.width - 4, 24)
                ) or NSButton.alloc().initWithFrame_(
                    NSMakeRect(2, cy + 4, frame.size.width - 4, 24)
                )
                btn.setTitle_("")
                btn.setBordered_(False)
                btn.setTarget_(self)
                btn.setAction_("clearAskHistoryClicked:")
                if btn.layer() is not None:
                    btn.layer().setCornerRadius_(6.0)
                lab = _label("Wyczyść historię", 11.0, _muted())
                lab.setFrame_(NSMakeRect(10, 4, frame.size.width - 24, 14))
                btn.addSubview_(lab)
                doc.addSubview_(btn)
                cy += 32
            holder.addSubview_(self._wrap_in_scroll(doc, cy, 0.0, frame))

        def askedRowClicked_(self, sender):
            i = int(sender.tag())
            if 0 <= i < len(self._asked_rows):
                query = self._asked_rows[i]["query"]
                self._hide_ask_sheet()
                self._run_recall(query)

        def clearAskHistoryClicked_(self, _sender):
            from src.connections import ask_history

            ask_history.clear()
            self._render()

        @objc.python_method
        def _build_notes_body(self, holder, frame):
            # §7: corpus navigation, not an editor — a click renders the note
            # in the in-app reader (read-only); editing stays in the opener.
            doc = _DashFlippedView.alloc().initWithFrame_(
                NSMakeRect(0, 0, frame.size.width, 10)
            )
            cy = 2.0
            if not self._notes_rows:
                sent = _typo_label(
                    "Brak notatek w korpusie — zaimportuj audio albo transkrypty.",
                    "rail_snippet",
                    NSMakeRect(10, cy + 8, frame.size.width - 20, 40),
                )
                sent.setMaximumNumberOfLines_(3)
                doc.addSubview_(sent)
                cy += 60
            for i, row in enumerate(self._notes_rows):
                cy = self._add_icon_text_row(
                    doc,
                    cy,
                    frame.size.width,
                    "doc.text",
                    str(row.get("label", "")),
                    i,
                    "notesRowClicked:",
                )
            holder.addSubview_(self._wrap_in_scroll(doc, cy, 0.0, frame))

        def notesRowClicked_(self, sender):
            i = int(sender.tag())
            if 0 <= i < len(self._notes_rows):
                path = self._notes_rows[i].get("path")
                if path is not None:
                    # A rail row is a fresh entry, not a wikilink hop — it must
                    # not grow the breadcrumb („← Wróć" exits in one press).
                    # The reset happens inside, only after a successful render.
                    self._open_note_in_reader(path, breadcrumb="reset")

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
                # C2 redline: row radius 12, active bg = raised fill + gold bar 2.5.
                btn.layer().setCornerRadius_(_R_ROW)
                if active:
                    btn.layer().setBackgroundColor_(
                        _c(255, 255, 255, _FILL_RAISED_A).CGColor()
                    )

            if active:
                # Gold bar = the insight role; the label lights gold-glow (C2).
                bar = NSView.alloc().initWithFrame_(
                    NSMakeRect(1, 8, 2.5, frame.size.height - 16)
                )
                bar.setWantsLayer_(True)
                if bar.layer() is not None:
                    bar.layer().setBackgroundColor_(_gold().CGColor())
                    bar.layer().setCornerRadius_(2.0)
                btn.addSubview_(bar)

            # C2: padding 10/11/11 · sigil 26 · cols 26px/1fr gap 10 ·
            # label 12.5/600 · snippet 12 clamped to 2 lines.
            btn.addSubview_(
                _sigil(
                    NSMakeRect(11, 10, 26, 26), conn.layout(), conn.resolved_tcolor()
                )
            )

            text_x = 47.0
            text_w = frame.size.width - text_x - 10.0
            lab = _typo_label(
                conn.resolved_label(),
                "rail_title" if active else "rail_title_quiet",
                NSMakeRect(text_x, 9, text_w, 16),
                wrapping=False,
            )
            lab.setLineBreakMode_(4)  # truncate tail
            if active:
                try:  # aktywny → gold-glow #F4DD8E (C2)
                    lab.setTextColor_(_hex("#F4DD8E"))
                except Exception:  # pragma: no cover
                    pass
            btn.addSubview_(lab)

            snip = _typo_label(
                conn.snippet,
                "rail_snippet",
                NSMakeRect(text_x, 27, text_w, frame.size.height - 27 - 6),
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

        # -- ask toolbar + history sheet (U6 rev. 3 + U8) --------------------- #

        @objc.python_method
        def _build_toolbar(self, frame):
            """36px toolbar over the reader column only — never over the rail.
            The field is the ONE text input of the window (none in the rail)."""
            bar = _DashFlippedView.alloc().initWithFrame_(frame)
            bd = NSView.alloc().initWithFrame_(
                NSMakeRect(0, frame.size.height - 1, frame.size.width, 1)
            )
            bd.setWantsLayer_(True)
            if bd.layer() is not None:
                bd.layer().setBackgroundColor_(_c(255, 255, 255, _HAIRLINE_A).CGColor())
            bar.addSubview_(bd)

            FLD_H = 28.0
            margin = 12.0
            fld_w = min(260.0, max(frame.size.width - 2 * margin, 120.0))
            fx = frame.size.width - margin - fld_w
            cont = NSView.alloc().initWithFrame_(
                NSMakeRect(fx, (frame.size.height - FLD_H) / 2.0, fld_w, FLD_H)
            )
            cont.setWantsLayer_(True)
            if cont.layer() is not None:
                cont.layer().setCornerRadius_(_R_CONTROL)
                cont.layer().setBackgroundColor_(
                    _c(255, 255, 255, _FILL_SUBTLE_A).CGColor()
                )
                cont.layer().setBorderWidth_(1.0)
                cont.layer().setBorderColor_(_c(255, 255, 255, 0.16).CGColor())
            bar.addSubview_(cont)

            glyph = _label("⌕", 13, _terracotta())
            glyph.setFrame_(NSMakeRect(9, (FLD_H - 17) / 2.0, 15, 17))
            cont.addSubview_(glyph)

            # ⌘K badge at the field's right edge (mono, quiet).
            KB_W = 26.0
            kbd = _label("⌘K", 10.5, _c(111, 102, 90))
            try:
                kbd.setFont_(NSFont.monospacedSystemFontOfSize_weight_(10.5, 0.0))
            except Exception:  # pragma: no cover
                pass
            kbd.setFrame_(NSMakeRect(fld_w - KB_W - 8, (FLD_H - 13) / 2.0, KB_W, 13))
            cont.addSubview_(kbd)

            fld = NSTextField.alloc().initWithFrame_(
                NSMakeRect(28, (FLD_H - 17) / 2.0, fld_w - 28 - KB_W - 12, 17)
            )
            fld.setEditable_(True)
            fld.setBezeled_(False)
            fld.setBordered_(False)
            fld.setDrawsBackground_(False)
            fld.setTextColor_(_cream())
            fld.setFont_(NSFont.systemFontOfSize_(12.5))
            fld.setUsesSingleLineMode_(True)
            try:
                fld.setPlaceholderString_("Zapytaj swój korpus…")
                fld.setFocusRingType_(1)  # NSFocusRingTypeNone
                fld.cell().setLineBreakMode_(4)  # truncate tail, no wrap
            except Exception:  # pragma: no cover - cosmetic
                pass
            fld.setDelegate_(self)  # focus → sheet; ↑↓ history; Esc closes
            fld.setTarget_(self)
            fld.setAction_("askToolbarSubmitted:")
            cont.addSubview_(fld)
            self._toolbar_field = fld
            return bar

        def focusAskField(self):
            """⌘K (window) — focus the toolbar field and open the sheet."""
            fld = getattr(self, "_toolbar_field", None)
            if fld is None or self._window is None:
                return
            self._window.makeFirstResponder_(fld)
            self._show_ask_sheet()

        def controlTextDidBeginEditing_(self, note):
            try:
                if note.object() is self._toolbar_field:
                    self._show_ask_sheet()
            except Exception:  # pragma: no cover - defensive
                pass

        @objc.python_method
        def _show_ask_sheet(self):
            """U8: the history sheet under the field — fixed position, scrim
            over the reader column ONLY (the rail stays active)."""
            if self._ask_sheet is not None or self._window is None:
                return
            content = self._window.contentView()
            if content is None:
                return
            from src.connections import ask_history
            from src.ui.hover import make_hover_button

            b = content.bounds()
            reader_x = _RAIL_W
            top_y = _HEADER_H + _TOOLBAR_H

            scrim = NSButton.alloc().initWithFrame_(
                NSMakeRect(
                    reader_x, top_y, b.size.width - reader_x, b.size.height - top_y
                )
            )
            scrim.setTitle_("")
            scrim.setBordered_(False)
            scrim.setTransparent_(False)
            scrim.setWantsLayer_(True)
            if scrim.layer() is not None:
                scrim.layer().setBackgroundColor_(_c(10, 9, 14, 0.45).CGColor())
            scrim.setTarget_(self)
            scrim.setAction_("hideAskSheetClicked:")
            content.addSubview_(scrim)
            self._ask_scrim = scrim

            entries = ask_history.recent(5)
            self._sheet_entries = entries
            self._hist_idx = -1
            ROW_H, HEAD_H, FOOT_H, PADV = 34.0, 26.0, 26.0, 8.0
            sheet_h = (
                PADV * 2 + FOOT_H + (HEAD_H + ROW_H * len(entries) if entries else 34.0)
            )
            sheet_w = min(_SHEET_W, b.size.width - reader_x - 24.0)
            sx = b.size.width - 12.0 - sheet_w  # aligned to the field's right edge
            sheet = _DashFlippedView.alloc().initWithFrame_(
                NSMakeRect(sx, top_y, sheet_w, sheet_h)
            )
            sheet.setWantsLayer_(True)
            if sheet.layer() is not None:
                sheet.layer().setCornerRadius_(_R_ROW)
                sheet.layer().setBackgroundColor_(_c(28, 27, 36, 0.98).CGColor())
                sheet.layer().setBorderWidth_(1.0)
                sheet.layer().setBorderColor_(_c(255, 255, 255, 0.16).CGColor())
                try:  # shape-based shadow — never rendered from sublayer text
                    from Quartz import CGPathCreateWithRoundedRect

                    sheet.layer().setShadowPath_(
                        CGPathCreateWithRoundedRect(
                            sheet.bounds(), _R_ROW, _R_ROW, None
                        )
                    )
                except Exception:  # pragma: no cover
                    pass
                sheet.layer().setShadowOpacity_(0.5)
                sheet.layer().setShadowRadius_(18.0)
                sheet.layer().setShadowOffset_(NSMakeSize(0, -8))
            cy = PADV
            if entries:
                head = _typo_label(
                    "Ostatnie pytania",
                    "collapsed_h",
                    NSMakeRect(14, cy + 4, sheet_w - 28, 14),
                    wrapping=False,
                )
                sheet.addSubview_(head)
                cy += HEAD_H
                for i, entry in enumerate(entries):
                    row = make_hover_button(
                        NSMakeRect(6, cy, sheet_w - 12, ROW_H - 2)
                    ) or NSButton.alloc().initWithFrame_(
                        NSMakeRect(6, cy, sheet_w - 12, ROW_H - 2)
                    )
                    row.setTitle_("")
                    row.setBordered_(False)
                    row.setTarget_(self)
                    row.setAction_("sheetRowClicked:")
                    row.setTag_(i)
                    if row.layer() is not None:
                        row.layer().setCornerRadius_(8.0)
                    glyph = _label("⌕", 12, _c(176, 162, 141))
                    glyph.setFrame_(NSMakeRect(10, 8, 14, 16))
                    row.addSubview_(glyph)
                    frag = f"{entry['fragmentCount']} fragm."
                    fw = 70.0
                    q = _label(entry["query"], 13, _cream_soft())
                    q.setFrame_(NSMakeRect(30, 8, sheet_w - 12 - 30 - fw - 14, 16))
                    try:
                        q.cell().setLineBreakMode_(4)
                    except Exception:  # pragma: no cover
                        pass
                    row.addSubview_(q)
                    fc = _label(frag, 10.5, _c(111, 102, 90))
                    try:
                        fc.setFont_(
                            NSFont.monospacedSystemFontOfSize_weight_(10.5, 0.0)
                        )
                    except Exception:  # pragma: no cover
                        pass
                    fc.setAlignment_(2)
                    fc.setFrame_(NSMakeRect(sheet_w - 12 - fw - 8, 9, fw, 14))
                    row.addSubview_(fc)
                    sheet.addSubview_(row)
                    cy += ROW_H
            else:
                hintl = _label(
                    "Zadaj pierwsze pytanie — historia zostanie tutaj.",
                    12.0,
                    _muted(),
                )
                hintl.setFrame_(NSMakeRect(14, cy + 6, sheet_w - 28, 16))
                sheet.addSubview_(hintl)
                cy += 34.0
            foot = _label(
                "↵ zapytaj · ↑↓ historia · esc zamknij", 11.0, _c(111, 102, 90)
            )
            foot.setFrame_(NSMakeRect(14, cy + 5, sheet_w - 28, 14))
            sheet.addSubview_(foot)
            content.addSubview_(sheet)
            self._ask_sheet = sheet
            _slide_in(sheet, 8.0, 0.18)

        @objc.python_method
        def _hide_ask_sheet(self):
            for attr in ("_ask_sheet", "_ask_scrim"):
                v = getattr(self, attr, None)
                if v is not None:
                    v.removeFromSuperview()
                    setattr(self, attr, None)
            self._hist_idx = -1

        def hideAskSheetClicked_(self, _sender):
            self._hide_ask_sheet()

        def sheetRowClicked_(self, sender):
            entries = getattr(self, "_sheet_entries", [])
            i = int(sender.tag())
            if 0 <= i < len(entries):
                query = entries[i]["query"]
                self._hide_ask_sheet()
                self._run_recall(query)

        def askToolbarSubmitted_(self, sender):
            text = str(sender.stringValue()).strip()
            self._hide_ask_sheet()
            if text:
                self._run_recall(text)

        # -- reader ---------------------------------------------------------- #

        @objc.python_method
        def _build_reader(self, frame):
            view = _DashFlippedView.alloc().initWithFrame_(frame)
            div = NSView.alloc().initWithFrame_(
                NSMakeRect(0, 0, _hairline(), frame.size.height)
            )
            div.setWantsLayer_(True)
            if div.layer() is not None:
                div.layer().setBackgroundColor_(
                    _c(255, 255, 255, _HAIRLINE_A).CGColor()
                )
            view.addSubview_(div)

            # Stały ask-bar cut per redesign (changelog): the pull entry moves to
            # the ⌥Space overlay (ekran C) + ⌕ in the title-bar; the reader
            # content now starts directly under the native titlebar. In Pytanie
            # the question becomes the reader title, not a field.
            top = 0.0
            if self._mode == "note":
                self._build_note_reader(view, frame, top)
            elif self._mode == "recall":
                self._build_recall_reader(view, frame, top)
            else:
                self._build_insight_reader(view, frame, top)
            return view

        @objc.python_method
        def _build_note_reader(self, view, frame, top):
            """In-app note view: native header (Wróć / Otwórz w Obsidianie)
            over a WKWebView with the rendered note. Read-only by design —
            Timshel never edits notes; editing stays in the user's opener."""
            head_h = 40.0
            back = _pill_button(
                "← Wróć",
                NSMakeRect(_READER_PAD_X, top + 7, 88, 26),
                _c(200, 188, 168),
                None,
                None,
                self,
                "noteBackClicked:",
                12.5,
            )
            view.addSubview_(back)
            # The escape hatch honors the configured opener — don't claim
            # Obsidian when the click will launch a different editor.
            opener = str(getattr(config, "NOTE_OPENER", "obsidian") or "obsidian")
            ext_label = (
                "Otwórz w Obsidianie ↗"
                if opener == "obsidian"
                else "Otwórz w edytorze ↗"
            )
            open_w = 176.0
            ext = _pill_button(
                ext_label,
                NSMakeRect(
                    frame.size.width - _READER_PAD_X - open_w, top + 7, open_w, 26
                ),
                _c(140, 130, 115),
                None,
                None,
                self,
                "noteOpenExternalClicked:",
                12.5,
            )
            view.addSubview_(ext)
            div = NSView.alloc().initWithFrame_(
                NSMakeRect(0, top + head_h, frame.size.width, _hairline())
            )
            div.setWantsLayer_(True)
            if div.layer() is not None:
                div.layer().setBackgroundColor_(
                    _c(255, 255, 255, _HAIRLINE_A).CGColor()
                )
            view.addSubview_(div)

            web_y = top + head_h + _hairline()
            web_rect = NSMakeRect(0, web_y, frame.size.width, frame.size.height - web_y)
            if not _WEBKIT_AVAILABLE:  # pragma: no cover - stripped env
                lbl = _wrapping_label(
                    "Podgląd niedostępny — otwórz notatkę w Obsidianie.",
                    13.0,
                    _muted(),
                    NSMakeRect(
                        _READER_PAD_X,
                        web_y + 16,
                        frame.size.width - 2 * _READER_PAD_X,
                        40,
                    ),
                )
                view.addSubview_(lbl)
                return
            # ONE persistent webview per window session: re-parented across
            # re-renders (resize, updateDeck_, setTranscribing_) so the user's
            # reading position survives them; the page reloads only when the
            # shown note actually changes.
            web = self._webview
            if web is None:
                cfg = WKWebViewConfiguration.alloc().init()
                prefs = WKWebpagePreferences.alloc().init()
                prefs.setAllowsContentJavaScript_(False)
                cfg.setDefaultWebpagePreferences_(prefs)
                web = WKWebView.alloc().initWithFrame_configuration_(web_rect, cfg)
                web.setNavigationDelegate_(self)
                try:
                    # No white flash before the dark page paints.
                    web.setValue_forKey_(False, "drawsBackground")
                except Exception:  # pragma: no cover - KVC gone in a future OS
                    pass
                self._webview = web
            else:
                web.setFrame_(web_rect)
            if self._webview_path != self._note_path:
                _READER_HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
                _READER_HTML_PATH.write_text(self._note_html, encoding="utf-8")
                file_url = NSURL.fileURLWithPath_(str(_READER_HTML_PATH))
                web.loadFileURL_allowingReadAccessToURL_(
                    file_url, _READER_HTML_PATH.parent
                )
                self._reader_page_url = str(file_url.absoluteString())
                self._webview_path = self._note_path
            view.addSubview_(web)

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

            if not self._selected:
                self._handoff_bar_shown = False  # next reveal animates again
            # U4 rev. 2: the directions bar lives INSIDE the scroll, under the
            # KIERUNKI list — the footer never morphs and never hosts the CTA.
            scroll_h = frame.size.height - _FOOTER_H - top

            # scrolling document (spark + ground + directions + dirbar)
            scroll = NSScrollView.alloc().initWithFrame_(
                NSMakeRect(0, top, frame.size.width, scroll_h)
            )
            scroll.setHasVerticalScroller_(True)
            scroll.setAutohidesScrollers_(True)
            scroll.setDrawsBackground_(False)
            scroll.setBorderType_(0)
            doc, content_h = self._build_reader_content(frame.size.width, conn)
            doc.setFrame_(NSMakeRect(0, 0, frame.size.width, max(content_h, scroll_h)))
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

            # pinned quiet footer — never cropped, never morphing (C5)
            self._build_footer(
                view,
                NSMakeRect(
                    0, frame.size.height - _FOOTER_H, frame.size.width, _FOOTER_H
                ),
                overflow=content_h > scroll_h,
            )

        @objc.python_method
        def _build_recall_reader(self, view, frame, top):
            # The triage footer DOES NOT EXIST in Pytanie mode (redesign B) —
            # the mistake disappears from the architecture, not behind an `if`
            # on the buttons: the reader owns the full height here.
            scroll_h = frame.size.height - top
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
                bd.layer().setBackgroundColor_(_c(255, 255, 255, _HAIRLINE_A).CGColor())
            strip.addSubview_(bd)

            pad = 15.0
            field_h = 38.0
            fy = (frame.size.height - field_h) / 2.0
            left = pad
            if self._mode == "recall":
                back = _pill_button(
                    "‹ Podsunięte",
                    NSMakeRect(pad, fy + 6, 118, 26),
                    _cream_soft(),
                    _c(255, 255, 255, _FILL_RAISED_A),
                    _c(255, 255, 255, 0.16),
                    self,
                    "backToInsightsClicked:",
                    12.0,
                )
                strip.addSubview_(back)
                left = pad + 130

            fld_w = max(160.0, frame.size.width - left - pad)
            cont = NSView.alloc().initWithFrame_(NSMakeRect(left, fy, fld_w, field_h))
            cont.setWantsLayer_(True)
            if cont.layer() is not None:
                cont.layer().setBackgroundColor_(
                    _c(255, 255, 255, _FILL_RAISED_A).CGColor()
                )
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
            band = NSView.alloc().initWithFrame_(
                NSMakeRect(_READER_PAD_X, cy, inner_w, 30)
            )
            band.setWantsLayer_(True)
            if band.layer() is not None:
                band.layer().setBackgroundColor_(_c(214, 176, 51, 0.08).CGColor())
                band.layer().setCornerRadius_(6.0)
            doc.addSubview_(band)
            lbl = _label(
                f"Indeksuję Twoje notatki{count} — możesz pytać już teraz "
                f"(wyniki częściowe).",
                12,
                _gold(),
            )
            lbl.setFrame_(NSMakeRect(_READER_PAD_X + 10, cy + 7, inner_w - 20, 16))
            doc.addSubview_(lbl)
            return cy + 40

        @objc.python_method
        def _build_recall_content(self, reader_w, vm):
            doc = _DashFlippedView.alloc().initWithFrame_(
                NSMakeRect(0, 0, reader_w, 10)
            )
            inner_w = reader_w - 2 * _READER_PAD_X
            cy = _PAD
            self._recall_note_ids = []
            self._synth_note_ids = (
                []
            )  # reset in lockstep — never carry stale answer tags

            # honest partial-index banner while the background backfill is still running
            cy = self._build_index_banner(doc, cy, inner_w)

            # query header — the question IS the reader title (redesign B), not a
            # field: small "Zapytałeś" eyebrow + the query as a 21pt display title.
            if self._query:
                eye = _typo_label(
                    "Zapytałeś",
                    "collapsed_h",
                    NSMakeRect(_READER_PAD_X, cy, inner_w, 13),
                    wrapping=False,
                )
                doc.addSubview_(eye)
                cy += 20
                measure = min(inner_w, _THESIS_MEASURE)
                qh = max(24.0, _typo_measure(self._query, "question_title", measure))
                doc.addSubview_(
                    _typo_label(
                        self._query,
                        "question_title",
                        NSMakeRect(_READER_PAD_X, cy, measure, qh),
                    )
                )
                cy += qh + 12

            if self._recall_loading:
                lbl = _label(
                    "Szukam w Twoich notatkach…  (lokalnie, bez AI)", 13.5, _muted()
                )
                lbl.setFrame_(NSMakeRect(_READER_PAD_X, cy, inner_w, 18))
                doc.addSubview_(lbl)
                cy += 30
                doc.setFrameSize_(NSMakeSize(reader_w, cy + _PAD))
                return doc, cy + _PAD

            if vm is None:
                lbl = _wrapping_label(
                    "Zapytaj swój korpus — ⌘K albo pole nad czytnikiem "
                    "(globalnie: ⌃⌥Space). Przeszukam Twoje notatki lokalnie.",
                    15,
                    _muted(),
                    NSMakeRect(_READER_PAD_X, cy, inner_w, 26),
                )
                doc.addSubview_(lbl)
                cy += 34
                # Privacy disclosure — the trust backbone: local search, cloud only on
                # the explicit synthesis, and only matched excerpts.
                privacy = (
                    "Wyszukiwanie jest w 100% lokalne — nic nie opuszcza Twojego Maca. "
                    "Do Claude idą tylko dopasowane fragmenty i tylko gdy klikniesz "
                    "„Zsyntetyzuj”."
                )
                ph = _measure_height(privacy, 12, inner_w)
                doc.addSubview_(
                    _wrapping_label(
                        privacy,
                        12,
                        _c(111, 102, 90),
                        NSMakeRect(_READER_PAD_X, cy, inner_w, ph),
                    )
                )
                doc.setFrameSize_(NSMakeSize(reader_w, cy + ph + 20))
                return doc, cy + ph + 20

            if not vm.is_empty:
                meta_txt = f"{vm.count} fragmentów · lokalnie, bez AI"
                if getattr(vm, "lexical_only", False):
                    meta_txt += " · tryb dosłowny"
                meta = _label(meta_txt, 12, _muted())
                meta.setFrame_(NSMakeRect(_READER_PAD_X, cy, inner_w, 16))
                doc.addSubview_(meta)
                cy += 22

            rule = NSView.alloc().initWithFrame_(
                NSMakeRect(_READER_PAD_X, cy, inner_w, _hairline())
            )
            rule.setWantsLayer_(True)
            if rule.layer() is not None:
                rule.layer().setBackgroundColor_(
                    _c(255, 255, 255, _HAIRLINE_A).CGColor()
                )
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
                sub = (
                    "Recall potrzebuje jednorazowego zindeksowania vaulta, zanim "
                    "przeszuka — to nie znaczy, że nic nie ma. (Auto-backfill: wkrótce.)"
                )
            else:  # "unavailable"
                head = "Nie udało się przeszukać notatek."
                sub = (
                    "Indeks lub lokalny model nie są jeszcze gotowe — spróbuj "
                    "ponownie za chwilę. To nie znaczy, że nic nie ma."
                )
            hh = max(24.0, _measure_height(head, 20, inner_w))
            doc.addSubview_(
                _wrapping_label(
                    head, 20, _cream(), NSMakeRect(_READER_PAD_X, cy, inner_w, hh)
                )
            )
            cy += hh + 8
            sh = max(18.0, _measure_height(sub, 13.5, inner_w))
            doc.addSubview_(
                _wrapping_label(
                    sub, 13.5, _muted(), NSMakeRect(_READER_PAD_X, cy, inner_w, sh)
                )
            )
            cy += sh + 12
            return cy

        @objc.python_method
        def _build_escalation(self, doc, cy, inner_w, reader_w):
            # The one LLM door: explicit, gold, and honest that excerpts leave the Mac.
            cy += 8
            rule = NSView.alloc().initWithFrame_(
                NSMakeRect(_READER_PAD_X, cy, inner_w, _hairline())
            )
            rule.setWantsLayer_(True)
            if rule.layer() is not None:
                rule.layer().setBackgroundColor_(_c(214, 176, 51, 0.22).CGColor())
            doc.addSubview_(rule)
            cy += 14
            if self._answer_loading:
                lbl = _label(
                    "Syntetyzuję…  (jedyny moment, gdy dopasowane fragmenty idą do Claude)",
                    12.5,
                    _gold(),
                )
                lbl.setFrame_(NSMakeRect(_READER_PAD_X, cy, inner_w, 18))
                doc.addSubview_(lbl)
                cy += 28
                return cy
            btn = _pill_button(
                "✦ Zsyntetyzuj te wyniki",
                NSMakeRect(_READER_PAD_X, cy, 214, 30),
                _c(244, 221, 142),
                _c(214, 176, 51, 0.08),
                _c(214, 176, 51, 0.5),
                self,
                "synthesizeClicked:",
                13.0,
            )
            doc.addSubview_(btn)
            note = _label(
                "Tylko teraz fragmenty świadomie opuszczają Maca.",
                11.5,
                _c(140, 130, 115),
            )
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
                _gold() if answered else _muted(),
            )
            eye.setFrame_(NSMakeRect(_READER_PAD_X, cy, inner_w - 130, 13))
            doc.addSubview_(eye)
            back = _pill_button(
                "‹ tylko wyniki",
                NSMakeRect(reader_w - _READER_PAD_X - 118, cy - 4, 118, 24),
                _cream_soft(),
                _c(255, 255, 255, _FILL_RAISED_A),
                _c(255, 255, 255, 0.16),
                self,
                "clearAnswerClicked:",
                11.5,
            )
            doc.addSubview_(back)
            cy += 24

            # When the model says the notes don't cover the question, the thesis is an
            # honest "not covered" note — render it muted, not as a confident answer.
            thesis = "„" + (getattr(ans, "thesis", "") or "") + "”"
            tcolor = _cream() if answered else _c(176, 162, 141)
            th = max(28.0, _measure_height(thesis, 22, inner_w))
            doc.addSubview_(
                _wrapping_label(
                    thesis, 22, tcolor, NSMakeRect(_READER_PAD_X, cy, inner_w, th)
                )
            )
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
                    doc.addSubview_(
                        _wrapping_label(
                            line,
                            13.5,
                            _cream_soft(),
                            NSMakeRect(_READER_PAD_X, cy, inner_w, lh),
                        )
                    )
                    cy += lh + 6

            save = _pill_button(
                "⤓ Zapisz do notatek",
                NSMakeRect(_READER_PAD_X, cy + 6, 170, 28),
                _c(255, 255, 255),
                _terra_deep(),
                _terra_deep(),
                self,
                "saveAnswerClicked:",
                12.5,
            )
            doc.addSubview_(save)
            cy += 46
            return cy

        @objc.python_method
        def _build_answer_evidence(self, doc, ev, cy, inner_w, reader_w):
            from src.ui.recall_presenter import split_stem

            date, title = split_stem(getattr(ev, "note", "") or "")
            top = (
                f"{date}   ·   {title}" if date else (title or getattr(ev, "note", ""))
            )
            tl = _label(top, 12.0, _muted())
            tl.setFrame_(NSMakeRect(_READER_PAD_X, cy, inner_w - 40, 16))
            doc.addSubview_(tl)
            idx = len(self._synth_note_ids)
            self._synth_note_ids.append(getattr(ev, "note", "") or "")
            ob = _pill_button(
                "↗",
                NSMakeRect(reader_w - _READER_PAD_X - 30, cy - 2, 30, 22),
                _terracotta(),
                _c(255, 255, 255, 0.0),
                _c(255, 255, 255, 0.0),
                self,
                "synthOpenClicked:",
                12.0,
            )
            ob.setTag_(idx)
            doc.addSubview_(ob)
            cy += 19
            quote = "„" + (getattr(ev, "quote", "") or "") + "”"
            qh = max(16.0, _measure_height(quote, 13.5, inner_w - 12))
            lbl = _wrapping_label(
                quote,
                13.5,
                _cream_soft(),
                NSMakeRect(_READER_PAD_X + 12, cy, inner_w - 12, qh),
            )
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
                dlab = _typo_label(
                    row.date, "result_date", NSMakeRect(tx, cy, 60, 16), wrapping=False
                )
                doc.addSubview_(dlab)
                tx += _text_width(row.date, 11.5) + 16
            if row.title:
                tlab = _typo_label(
                    row.title,
                    "result_title",
                    NSMakeRect(tx, cy, text_w - (tx - text_x) - 96, 16),
                    wrapping=False,
                )
                tlab.setLineBreakMode_(4)
                doc.addSubview_(tlab)

            idx = len(self._recall_note_ids)
            self._recall_note_ids.append(row.note_id)
            ob = _pill_button(
                "↗ otwórz",
                NSMakeRect(reader_w - _READER_PAD_X - 84, cy - 3, 84, 22),
                _c(224, 213, 191, 0.45),
                _c(255, 255, 255, 0.0),
                _c(255, 255, 255, 0.0),
                self,
                "recallOpenClicked:",
                11.5,
            )
            ob.setTag_(idx)
            doc.addSubview_(ob)
            cy += 20

            quote = "„" + row.quote + "”"
            qh = max(18.0, _typo_measure(quote, "result_quote", text_w))
            ql = _typo_label(quote, "result_quote", NSMakeRect(text_x, cy, text_w, qh))
            if row.dimmed:
                from AppKit import (
                    NSAttributedString,
                    NSFontAttributeName,
                    NSForegroundColorAttributeName,
                    NSParagraphStyleAttributeName,
                )
                from src.ui import typography as _T

                at = _T.attributes("result_quote", color_alpha=0.45)
                ql.setAttributedStringValue_(
                    NSAttributedString.alloc().initWithString_attributes_(quote, at)
                )
            doc.addSubview_(ql)
            cy += qh + 12

            sep = NSView.alloc().initWithFrame_(
                NSMakeRect(text_x, cy, text_w, _hairline())
            )
            sep.setWantsLayer_(True)
            if sep.layer() is not None:
                sep.layer().setBackgroundColor_(
                    _c(255, 255, 255, _HAIRLINE_A).CGColor()
                )
            doc.addSubview_(sep)
            cy += 12
            return cy

        @objc.python_method
        def _build_recall_abstinence(self, doc, vm, cy, inner_w, reader_w):
            head_txt = "Nic w Twoich notatkach na to pytanie."
            hh = max(24.0, _measure_height(head_txt, 20, inner_w))
            doc.addSubview_(
                _wrapping_label(
                    head_txt, 20, _cream(), NSMakeRect(_READER_PAD_X, cy, inner_w, hh)
                )
            )
            cy += hh + 8
            if getattr(vm, "lexical_only", False):
                # Honest about the degraded mode: a paraphrase miss here may be
                # the missing semantic channel, not an absent topic.
                sub = (
                    "Wyszukiwanie działa w trybie dosłownym (bez warstwy "
                    "semantycznej) — spróbuj słów, które padły w notatce. "
                    "Nic nie opuszcza Twojego Maca."
                )
            else:
                sub = (
                    "Search jest w 100% lokalny i niczego nie zmyśla — "
                    "nic nie opuszcza Twojego Maca."
                )
            sh = max(18.0, _measure_height(sub, 13.5, inner_w))
            doc.addSubview_(
                _wrapping_label(
                    sub, 13.5, _muted(), NSMakeRect(_READER_PAD_X, cy, inner_w, sh)
                )
            )
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
            self._reset_recall_flight()  # bump epoch + clear ALL query state
            if self._mode == "note":
                self._exit_note_mode()
            self._mode = "insight"
            self._section = "serendypacje"
            self._recall_loading = False
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
                if self._mode == "note":
                    self._exit_note_mode()
                self._mode = "insight"
                self._recall_loading = False
                self._render()
                return
            # Show the query in a "searching" state immediately, then do the work off
            # the main thread — the embed + full-corpus BM25 (and a first-run model
            # download) must never block the AppKit UI, mirroring the digest/retranscribe
            # daemon threads.
            self._reset_recall_flight()
            if self._mode == "note":
                self._exit_note_mode()
            self._mode = "recall"
            self._section = "zapytales"  # the rail follows the executed pull
            self._recall_loading = True
            self._scroll_y = 0.0
            epoch = self._epoch
            self._render()
            import threading

            threading.Thread(
                target=self._recall_worker_,
                args=(self._query, epoch),
                name="RecallSearch",
                daemon=True,
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

            lexical = None
            lex_cb = self._callbacks.get("recall_lexical_only")
            if lex_cb is not None:
                try:
                    lexical = bool(lex_cb())
                except Exception:  # pragma: no cover - defensive
                    lexical = None
            self._pending_recall = {
                "epoch": epoch,
                "query": query,
                "vm": rp.present(query, results, confidence, lexical_only=lexical),
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
            # U8: an executed question tops the persistent, local askHistory —
            # it feeds the sheet and the rail's "Zapytałeś" section.
            try:
                from src.connections import ask_history

                if self._query:
                    ask_history.append(self._query, len(self._recall_raw))
            except Exception as exc:  # pragma: no cover - best effort
                logger.debug("ask history append failed: %s", exc)
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
                target=self._synth_worker_,
                args=(self._query, list(self._recall_raw), epoch),
                name="RecallSynthesis",
                daemon=True,
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
                self._show_toast(
                    "Synteza niedostępna — sprawdź klucz API lub spróbuj ponownie"
                )
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
                NSApp,
                NSColor,
                NSTextField,
                NSFloatingWindowLevel,
                NSBackingStoreBuffered,
                NSAttributedString,
                NSForegroundColorAttributeName,
                NSFontAttributeName,
            )

            self._ensure_window()  # results land in the window; keep it realised

            # Reuse the panel across invocations — rebuilding leaked the
            # previous one and its field each time the loupe was clicked.
            panel = getattr(self, "_ask_overlay", None)
            if panel is not None:
                fld = self._ask_overlay_field
                fld.setStringValue_("")
                NSApp.activateIgnoringOtherApps_(True)
                panel.center()
                panel.makeKeyAndOrderFront_(None)
                panel.makeFirstResponder_(fld)
                return

            W, FLD_H = 560.0, 52.0
            panel = _AskPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, W, FLD_H + 24), 1 << 7, NSBackingStoreBuffered, False
            )
            # We keep the only strong reference and never close() — dropping
            # AppKit's close-time autorelease avoids the over-release crash
            # class (see download_window.py).
            panel.setReleasedWhenClosed_(False)
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

            fld = NSTextField.alloc().initWithFrame_(NSMakeRect(18, 12, W - 36, FLD_H))
            fld.setBordered_(False)
            fld.setBezeled_(False)
            fld.setDrawsBackground_(False)
            fld.setFocusRingType_(
                1
            )  # NSFocusRingTypeNone — the ring is on the container
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
            fld.setDelegate_(self)  # Esc lands in control:textView:doCommandBySelector:
            container.addSubview_(fld)
            self._ask_overlay = panel
            self._ask_overlay_field = fld

            # LSUIElement app: without explicit activation the panel never
            # becomes key and typing goes nowhere.
            NSApp.activateIgnoringOtherApps_(True)
            panel.center()
            panel.makeKeyAndOrderFront_(None)
            panel.makeFirstResponder_(fld)

        def control_textView_doCommandBySelector_(self, control, _tv, selector):
            sel = str(selector)
            # Esc inside the overlay panel (⌥Space): dismiss it.
            if sel == "cancelOperation:" and control is getattr(
                self, "_ask_overlay_field", None
            ):
                panel = getattr(self, "_ask_overlay", None)
                if panel is not None:
                    panel.orderOut_(None)
                return True
            # Toolbar field (U8): Esc closes the sheet without a trace; ↑↓
            # walks the history (the entry jumps into the input).
            if control is getattr(self, "_toolbar_field", None):
                if sel == "cancelOperation:":
                    self._hide_ask_sheet()
                    control.setStringValue_("")
                    return True
                if sel in ("moveUp:", "moveDown:"):
                    entries = getattr(self, "_sheet_entries", None)
                    if not entries:
                        return False
                    step = 1 if sel == "moveDown:" else -1
                    self._hist_idx = (self._hist_idx + step) % len(entries)
                    control.setStringValue_(entries[self._hist_idx]["query"])
                    return True
            return False

        def titlebarAskClicked_(self, _sender):
            self.showAskOverlay()

        def askOverlaySubmitted_(self, sender):
            try:
                text = str(sender.stringValue()).strip()
            except Exception:  # pragma: no cover - defensive
                text = ""
            panel = getattr(self, "_ask_overlay", None)
            if panel is not None:
                panel.orderOut_(None)  # kept alive for reuse
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

            # header: sigil + type eyebrow + quiet provenance metadata (U5)
            doc.addSubview_(
                _sigil(
                    NSMakeRect(_READER_PAD_X, cy, 34, 34),
                    conn.layout(),
                    conn.resolved_tcolor(),
                )
            )
            # type eyebrow — gold, uppercase, tracked (typography ramp)
            tlabel = _typo_label(
                conn.resolved_label(),
                "eyebrow",
                NSMakeRect(_READER_PAD_X + 44, cy + 12, inner_w - 200, 14),
                wrapping=False,
            )
            doc.addSubview_(tlabel)
            # U5: provenance is quiet metadata at the header's right edge —
            # brand chip (template, soft tint) + "digest · dd.mm · Claude".
            # The word "chmura" does not exist in this window (anti-error 7).
            marker = getattr(self._deck, "digest_label", None) or "digest"
            meta_text = f"{marker} · Claude"
            mw = _text_width(meta_text, 12.0) + 8
            chip_img = _brand_image("claude", 15.0)
            mx = reader_w - _READER_PAD_X - mw
            if chip_img is not None:
                biv = NSImageView.alloc().initWithFrame_(
                    NSMakeRect(mx - 20, cy + 11, 15, 15)
                )
                biv.setImage_(chip_img)
                try:
                    biv.setContentTintColor_(_c(176, 162, 141))
                except Exception:  # pragma: no cover
                    pass
                biv.setToolTip_(
                    "Ten digest powstał z użyciem Claude — wybrane notatki "
                    "zostały wysłane do Anthropic."
                )
                doc.addSubview_(biv)
            meta = _label(meta_text, 12.0, _c(111, 102, 90))
            meta.setAlignment_(2)
            meta.setFrame_(NSMakeRect(mx, cy + 12, mw, 15))
            meta.setToolTip_(
                "Ten digest powstał z użyciem Claude — wybrane notatki "
                "zostały wysłane do Anthropic."
            )
            doc.addSubview_(meta)
            cy += 46

            # Kadr 2: a dismissed insight opens under a recall banner — Zachowaj
            # acts as "odzyskaj" (constant label, meaning from context).
            if self._deck.view == im.DISMISSED:
                ban = NSView.alloc().initWithFrame_(
                    NSMakeRect(_READER_PAD_X, cy, inner_w, 34)
                )
                ban.setWantsLayer_(True)
                if ban.layer() is not None:
                    ban.layer().setCornerRadius_(_R_ROW)
                    ban.layer().setBackgroundColor_(_c(70, 177, 126, 0.10).CGColor())
                    ban.layer().setBorderWidth_(1.0)
                    ban.layer().setBorderColor_(_c(91, 196, 149, 0.35).CGColor())
                from src.ui import style as _style

                ric = _style.sf_symbol(
                    "arrow.uturn.backward", point=11.0, weight="regular"
                )
                if ric is not None:
                    riv = NSImageView.alloc().initWithFrame_(NSMakeRect(12, 10, 14, 14))
                    riv.setImage_(ric)
                    try:
                        riv.setContentTintColor_(_c(139, 224, 181))
                    except Exception:  # pragma: no cover
                        pass
                    ban.addSubview_(riv)
                bl = _label(
                    "Odrzucone — możesz odzyskać. Zachowaj przeniesie to z "
                    "powrotem do Zachowanych.",
                    12.0,
                    _c(139, 224, 181),
                )
                bl.setFrame_(NSMakeRect(32, 9, inner_w - 44, 16))
                ban.addSubview_(bl)
                doc.addSubview_(ban)
                cy += 44

            # thesis (the spark) — display 24pt, capped to a readable measure (30em)
            thesis = "„" + conn.rationale + "”"
            measure = min(inner_w, _THESIS_MEASURE)
            th = max(30.0, _typo_measure(thesis, "thesis", measure))
            doc.addSubview_(
                _typo_label(
                    thesis, "thesis", NSMakeRect(_READER_PAD_X, cy, measure, th)
                )
            )
            cy += th + 16

            # note chips — measured widths; a chip that would cross the right
            # edge wraps to the next line BEFORE it is placed (never clipped).
            self._note_basenames = list(conn.notes)
            cx = _READER_PAD_X
            right_edge = reader_w - _READER_PAD_X
            for i, note in enumerate(conn.notes):
                chip = self._chip(
                    note, NSMakePoint(cx, cy), i, right_edge - _READER_PAD_X
                )
                w = chip.frame().size.width
                if cx + w > right_edge and cx > _READER_PAD_X:
                    cx = _READER_PAD_X
                    cy += 32
                    chip.setFrameOrigin_(NSMakePoint(cx, cy))
                doc.addSubview_(chip)
                cx += w + 6
            cy += 34

            # NOTE: the beta.17 "✦ Zapytaj o to" pill is CUT — in the redesign
            # the card carries no such button (A1: eyebrow → thesis → chips →
            # Dowód → Kierunki). The push→pull entry from a card is a gesture
            # into the ask-bar with a prefill (spec C); askAboutInsightClicked_
            # stays wired for that entry point.

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
                NSMakeRect(_READER_PAD_X, cy, inner_w, _hairline())
            )
            rule.setWantsLayer_(True)
            if rule.layer() is not None:
                rule.layer().setBackgroundColor_(
                    _c(255, 255, 255, _HAIRLINE_A).CGColor()
                )
            doc.addSubview_(rule)
            cy += 16

            # act — directions header (U2): label starts EXACTLY at the
            # checkboxes' left edge; no inline description — the "?" glyph
            # carries the explanation as a tooltip.
            DIR_PADX = 14.0  # row's inner padding = the checkbox left edge
            dcap = _eyebrow("Kierunki", _muted())
            dcap.setFrame_(NSMakeRect(_READER_PAD_X + DIR_PADX, cy, 90, 13))
            doc.addSubview_(dcap)
            qx = _READER_PAD_X + DIR_PADX + _typo_width("KIERUNKI", "eyebrow") + 10
            qm = NSView.alloc().initWithFrame_(NSMakeRect(qx, cy - 1, 14, 14))
            qm.setWantsLayer_(True)
            if qm.layer() is not None:
                qm.layer().setCornerRadius_(7.0)
                qm.layer().setBorderWidth_(1.0)
                qm.layer().setBorderColor_(_c(255, 255, 255, 0.16).CGColor())
            qlab = _label("?", 9.0, _muted())
            qlab.setAlignment_(1)
            qlab.setFrame_(NSMakeRect(0, 1, 14, 11))
            qm.addSubview_(qlab)
            qm.setToolTip_(
                "Zaznaczone kierunki trafią do handoffu — „Kontynuuj w Claude”."
            )
            doc.addSubview_(qm)
            cy += 22
            for i, d in enumerate(conn.directions):
                cy = self._build_direction_row(doc, i, d, cy, inner_w)

            # U4 rev. 2: the directions bar appears right UNDER the list (same
            # width and left edge) the moment ≥1 checkbox is ticked.
            if self._selected:
                cy = self._build_dirbar(doc, cy + 4, inner_w, len(self._selected))
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
                    _wrapping_label(
                        quote,
                        14,
                        _cream_soft(),
                        NSMakeRect(x + 60, cy, inner_w - 70, qh),
                    )
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

        # U3 — THE checkbox constant: 18×18, border 1.5, radius 5, margin-top 3.
        # One constant in code; if two checkboxes differ by a pixel, that's a
        # bug (anti-error 6).
        _CHK_BOX = 18.0
        _CHK_BORDER = 1.5
        _CHK_MT = 3.0

        @objc.python_method
        def _build_direction_row(self, doc, index, text, cy, inner_w):
            from src.ui.hover import make_hover_button

            selected = index in self._selected
            # C3 redline: padding 12/14, cols [18px chk] 11 [text 15/1.5],
            # radius 12; the row border stays TRANSPARENT in every state (U7).
            PADX = 14.0
            PADTOP = 12.0
            BOX = self._CHK_BOX
            COLGAP = 11.0
            text_x = PADX + BOX + COLGAP
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
                if selected:  # U7: one signal — checkbox + tint, NO frame
                    btn.layer().setBackgroundColor_(_c(217, 84, 42, 0.09).CGColor())
                else:
                    btn.layer().setBackgroundColor_(
                        _c(255, 255, 255, _FILL_GHOST_A).CGColor()
                    )

            # U3: margin-top 3px puts the box on the optical centre of the
            # FIRST text line (15px × 1.5 − 18) / 2 ≈ 2.6 → 3.
            box_y = PADTOP + self._CHK_MT
            box = NSView.alloc().initWithFrame_(NSMakeRect(PADX, box_y, BOX, BOX))
            box.setWantsLayer_(True)
            if box.layer() is not None:
                box.layer().setCornerRadius_(_R_CHECK)
                if selected:
                    box.layer().setBackgroundColor_(_terra_deep().CGColor())
                    box.layer().setBorderWidth_(self._CHK_BORDER)
                    box.layer().setBorderColor_(_terra_deep().CGColor())
                else:
                    box.layer().setBorderWidth_(self._CHK_BORDER)
                    box.layer().setBorderColor_(_c(255, 255, 255, 0.24).CGColor())
            btn.addSubview_(box)
            if selected:
                chk = _label("✓", 11, _c(255, 255, 255), bold=True)
                chk.setFrame_(NSMakeRect(PADX, box_y + 1, BOX, 15))
                chk.setAlignment_(1)
                btn.addSubview_(chk)

            line = _typo_label(
                text,
                "direction",
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
        def _build_dirbar(self, doc, cy, inner_w, n):
            """C4 / U4 rev. 2 — the directions bar, inline UNDER the KIERUNKI
            list (same width and left edge). Appears at >=1 selection; the
            window footer never hosts the handoff CTA (anti-error 4)."""
            from src.ui import style

            bar = _DirBarBG.alloc().initWithFrame_(
                NSMakeRect(_READER_PAD_X, cy, inner_w, _BAR_H)
            )

            CTA_H = 34.0
            BTN_Y = (_BAR_H - CTA_H) / 2.0
            pad = 13.0
            white = _c(255, 255, 255)

            tool = getattr(config, "LLM_HANDOFF_TOOL", "claude")
            if tool not in ho.LLM_TOOLS:  # stale config (e.g. retired Gemini)
                tool = "claude"
            name = ho.tool_name(tool)

            ICON_W = 34.0
            CARET_W = 24.0
            GAP = 8.0
            GAP_CLUSTER = 14.0

            def _cta_width(label):
                # lead pad + white brand chip + gap + measured text + trail pad
                return 10.0 + 18.0 + 9.0 + _text_width(label, 13.0) + 12.0

            # PL plurals per the redline: 1 kierunek · 2–4 kierunki · 5+ kierunków.
            if n == 1:
                cnt = "1 kierunek wybrany"
            elif 2 <= n <= 4:
                cnt = f"{n} kierunki wybrane"
            else:
                cnt = f"{n} kierunków wybranych"

            icons_w = 3 * ICON_W + 2 * GAP
            avail = inner_w - 2 * pad
            cta_label = "Kontynuuj w " + name
            cta_w = _cta_width(cta_label)
            label_w = _text_width(cnt, 12.5) + 8
            show_label = True
            if label_w + GAP_CLUSTER + icons_w + GAP_CLUSTER + cta_w + CARET_W > avail:
                cta_label = "Kontynuuj"
                cta_w = _cta_width(cta_label)
            if label_w + GAP_CLUSTER + icons_w + GAP_CLUSTER + cta_w + CARET_W > avail:
                show_label = False

            if show_label:
                lab = _typo_label(
                    cnt,
                    "dirbar_count",
                    NSMakeRect(pad, _BAR_H / 2 - 8, label_w, 16),
                    wrapping=False,
                )
                bar.addSubview_(lab)

            # right-anchored: [icons] gap [split CTA]
            x_cta = max(pad, inner_w - pad - cta_w - CARET_W)
            sx = x_cta - GAP_CLUSTER - icons_w
            for k, (symbol, tip, action) in enumerate(
                (
                    ("checkmark.square", "Utwórz zadanie", "taskClicked:"),
                    ("calendar", "Do kalendarza", "calendarClicked:"),
                    ("doc.on.doc", "Kopiuj", "copyClicked:"),
                )
            ):
                btn = _icon_button(
                    style.sf_symbol(symbol, point=13.0, weight="regular"),
                    tip,
                    NSMakeRect(sx + k * (ICON_W + GAP), BTN_Y, ICON_W, CTA_H),
                    _c(201, 187, 166),
                    _c(255, 255, 255, _FILL_RAISED_A),
                    _c(255, 255, 255, 0.16),
                    self,
                    action,
                )
                bar.addSubview_(btn)

            # --- primary CTA = split pill: [chip + label] | caret ---
            LEFT_CORNERS = 1 | 4  # MinXMinY | MinXMaxY
            RIGHT_CORNERS = 2 | 8  # MaxXMinY | MaxXMaxY
            go = _pill_button(
                "",
                NSMakeRect(x_cta, BTN_Y, cta_w, CTA_H),
                white,
                _terra_deep(),
                _terra_deep(),
                self,
                "continueLLMClicked:",
            )
            if go.layer() is not None:
                go.layer().setMaskedCorners_(LEFT_CORNERS)
                try:  # explicit path — otherwise the label ghosts in the shadow
                    from Quartz import CGPathCreateWithRoundedRect

                    go.layer().setShadowPath_(
                        CGPathCreateWithRoundedRect(
                            go.bounds(), _R_CONTROL, _R_CONTROL, None
                        )
                    )
                except Exception:  # pragma: no cover
                    pass
                go.layer().setShadowColor_(_terra_deep().CGColor())
                go.layer().setShadowOpacity_(0.45)
                go.layer().setShadowRadius_(9.0)
                go.layer().setShadowOffset_(NSMakeSize(0, -3))
            go.setToolTip_("Przekaż wybrane kierunki do " + name)
            # white brand chip with the provider glyph tinted terracotta
            chip = NSView.alloc().initWithFrame_(
                NSMakeRect(10, (CTA_H - 18) / 2.0, 18, 18)
            )
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
            golab.setFrame_(NSMakeRect(37, (CTA_H - 16) / 2.0, cta_w - 45, 16))
            go.addSubview_(golab)
            bar.addSubview_(go)

            caret = _pill_button(
                "",
                NSMakeRect(x_cta + cta_w, BTN_Y, CARET_W, CTA_H),
                white,
                _terra_deep(),
                None,
                self,
                "switchLLMClicked:",
            )
            cimg = style.sf_symbol("chevron.down", point=9.0, weight="semibold")
            if cimg is not None:
                civ = NSImageView.alloc().initWithFrame_(
                    NSMakeRect((CARET_W - 10) / 2.0, (CTA_H - 10) / 2.0, 10, 10)
                )
                civ.setImage_(cimg)
                try:
                    civ.setContentTintColor_(white)
                except Exception:  # pragma: no cover
                    pass
                caret.addSubview_(civ)
            else:  # pragma: no cover - symbol fallback
                caret.setTitle_("⌄")
            if caret.layer() is not None:
                caret.layer().setMaskedCorners_(RIGHT_CORNERS)
            # seam divider between go and caret
            seam = NSView.alloc().initWithFrame_(
                NSMakeRect(x_cta + cta_w, BTN_Y + 6, 1, CTA_H - 12)
            )
            seam.setWantsLayer_(True)
            if seam.layer() is not None:
                seam.layer().setBackgroundColor_(_c(255, 255, 255, 0.32).CGColor())
            caret.setToolTip_("Zmień narzędzie (Claude / ChatGPT)")
            bar.addSubview_(caret)
            bar.addSubview_(seam)

            doc.addSubview_(bar)
            # Reveal (spec §04): fade + 8px slide, ~180ms — only on the 0→>=1
            # transition, not on every rebuild; reduced-motion cuts instead.
            if not getattr(self, "_handoff_bar_shown", False):
                _slide_in(bar, 8.0, 0.18)
            self._handoff_bar_shown = True
            return cy + _BAR_H

        @objc.python_method
        def _build_footer(self, view, frame, overflow=False):
            """C5 — the FIXED footer: Odrzuć (ghost) · „1 z N" · Zachowaj
            (jade). Constant labels in every view; never morphs; never carries
            the handoff CTA (anti-error 4). Hidden in Pytanie and on empty."""
            foot = _DashFlippedView.alloc().initWithFrame_(frame)
            foot.setWantsLayer_(True)
            if foot.layer() is not None:
                foot.layer().setBackgroundColor_(_c(16, 14, 21, 0.86).CGColor())
            tdiv = NSView.alloc().initWithFrame_(
                NSMakeRect(0, 0, frame.size.width, _hairline())
            )
            tdiv.setWantsLayer_(True)
            if tdiv.layer() is not None:
                tdiv.layer().setBackgroundColor_(
                    _c(255, 255, 255, _HAIRLINE_A).CGColor()
                )
            foot.addSubview_(tdiv)

            from src.ui import style

            if overflow:  # quiet scroll hint (C5 .more) — only when it's true
                more = _label("↓ przewiń, by zobaczyć resztę", 11.0, _c(111, 102, 90))
                more.setFrame_(NSMakeRect(16, 16, 220, 14))
                foot.addSubview_(more)

            # Center position counter "N z M" — position in the current view.
            vis = self._deck.visible()
            if vis:
                pos = next(
                    (
                        k
                        for k, (i, _cn) in enumerate(vis)
                        if i == self._deck.active_index
                    ),
                    -1,
                )
                if pos >= 0:
                    ctr = _typo_label(
                        f"{pos + 1} z {len(vis)}",
                        "footer_counter",
                        NSMakeRect(frame.size.width / 2 - 50, 15, 100, 16),
                        wrapping=False,
                    )
                    ctr.setAlignment_(1)
                    foot.addSubview_(ctr)

            # Buttons — the one 34px/r6 control family (C5 redline).
            BTN_H = 34.0
            BTN_Y = (frame.size.height - BTN_H) / 2.0
            dismiss = _pill_button(
                "Odrzuć",
                NSMakeRect(frame.size.width - 232, BTN_Y, 86, BTN_H),
                _c(140, 130, 115),
                None,
                None,
                self,
                "dismissClicked:",
                12.5,
            )
            foot.addSubview_(dismiss)
            in_kept = self._deck.view == im.KEPT
            keep = _pill_button(
                "",
                NSMakeRect(frame.size.width - 134, BTN_Y, 118, BTN_H),
                _c(139, 224, 181),
                _c(70, 177, 126, 0.16),
                _c(91, 196, 149, 0.5),
                self,
                "keepClicked:",
                12.5,
            )
            keep_label = "Zachowano" if in_kept else "Zachowaj"
            keep_symbol = "bookmark.fill" if in_kept else "bookmark"
            if in_kept:
                # State, not verb: already-kept — no action, quieter face.
                keep.setEnabled_(False)
                keep.setAlphaValue_(0.55)
            mark = style.sf_symbol(keep_symbol, point=11.0, weight="regular")
            lx = 14.0
            if mark is not None:
                miv = NSImageView.alloc().initWithFrame_(
                    NSMakeRect(lx, (BTN_H - 14) / 2.0, 12, 14)
                )
                miv.setImage_(mark)
                try:
                    miv.setContentTintColor_(_c(139, 224, 181))
                except Exception:  # pragma: no cover
                    pass
                keep.addSubview_(miv)
                lx += 18.0
            klab = _label(keep_label, 12.5, _c(139, 224, 181), bold=True)
            klab.setFrame_(NSMakeRect(lx, (BTN_H - 16) / 2.0, 118 - lx - 8, 16))
            keep.addSubview_(klab)
            foot.addSubview_(keep)
            view.addSubview_(foot)

        # Sigil grammar per view for the empty block (C6): each state
        # inherits the view's sigil, muted to 85% opacity.
        _EMPTY_SIGIL = {
            "new": ("triad", "#E3C16B"),
            "kept": ("shared", "#D6B033"),
            "dismissed": ("contradiction", "#D9542A"),
        }

        @objc.python_method
        def _build_empty(self, view, frame, title=None, subtitle=None):
            """U10 — one centred column in the READER area (max 360px): sigil
            46px → 14 → title 18 display → 7 → one sentence. Under it, +20px,
            at most two quiet actions — never filled-primary. The triage
            footer does not render on an empty view (caller returns early)."""
            title = title or "Cisza w korpusie"
            subtitle = subtitle or (
                "Wszystkie połączenia przejrzane. Timshel czyta dalej — gdy coś "
                "się zapali, wróci tu rozbłysk."
            )
            block_w = min(360.0, frame.size.width - 40.0)
            bx = (frame.size.width - block_w) / 2.0
            sub_h = max(20.0, _typo_measure(subtitle, "empty_desc", block_w))
            block_h = 46.0 + 14.0 + 24.0 + 7.0 + sub_h
            by = max((frame.size.height - block_h - 50.0) / 2.0, 20.0)

            layout, hexcol = self._EMPTY_SIGIL.get(
                self._deck.view, ("triad", "#E3C16B")
            )
            sig = _sigil(
                NSMakeRect(frame.size.width / 2 - 23, by, 46, 46), layout, hexcol
            )
            try:
                sig.setAlphaValue_(0.85)
            except Exception:  # pragma: no cover
                pass
            view.addSubview_(sig)
            h = _typo_label(
                title,
                "empty_title",
                NSMakeRect(bx, by + 46 + 14, block_w, 24),
                wrapping=False,
            )
            h.setAlignment_(1)
            view.addSubview_(h)
            p = _typo_label(
                subtitle,
                "empty_desc",
                NSMakeRect(bx, by + 46 + 14 + 24 + 7, block_w, sub_h),
            )
            p.setAlignment_(1)
            view.addSubview_(p)

            # „co dalej" row (max 2 quiet actions, 30px, never filled):
            # a contextual bridge + „Zapytaj ⌘K".
            ay = by + block_h + 20.0
            counts = self._deck.counts()
            actions = []
            if self._deck.view == im.NEW and counts.get(im.KEPT, 0) > 0:
                actions.append(
                    (f"Zachowane · {counts[im.KEPT]}", "bridgeToKeptClicked:", True)
                )
            elif self._deck.view == im.KEPT and counts.get(im.NEW, 0) > 0:
                actions.append(
                    (f"Nowe · {counts[im.NEW]}", "bridgeToNewClicked:", True)
                )
            actions.append(("Zapytaj  ⌘K", "emptyAskClicked:", False))

            widths = [max(96.0, _text_width(t, 12.0) + 30.0) for t, _a, _j in actions]
            total = sum(widths) + 10.0 * (len(actions) - 1)
            ax = (frame.size.width - total) / 2.0
            for (text, action, jade), w in zip(actions, widths):
                if jade:  # jade tinted — the bridge to saved insights
                    btn = _pill_button(
                        text,
                        NSMakeRect(ax, ay, w, 30),
                        _c(139, 224, 181),
                        _c(70, 177, 126, 0.16),
                        _c(91, 196, 149, 0.5),
                        self,
                        action,
                        12.0,
                    )
                else:  # ghost with a border — the ask entry
                    btn = _pill_button(
                        text,
                        NSMakeRect(ax, ay, w, 30),
                        _c(201, 187, 166),
                        _c(255, 255, 255, _FILL_SUBTLE_A),
                        _c(255, 255, 255, 0.16),
                        self,
                        action,
                        12.0,
                    )
                view.addSubview_(btn)
                ax += w + 10.0
            return view

        def emptyAskClicked_(self, _sender):
            self.focusAskField()

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
        def _chip(self, text, origin, index, max_w=300.0):
            # Redline .nchip: 10px inset BOTH sides, 5pt terracotta dot, gap 8,
            # label body .8 (tail-truncated), trailing ↗. Width is measured —
            # the old glyph-count estimate gave lopsided padding.
            PAD = 10.0
            DOT = 5.0
            GAP = 8.0
            ARROW_W = 12.0
            # +6 slack: NSTextField draws with ~2–3px internal inset per side,
            # so a bare glyph measure truncates text that actually fits.
            text_w = _text_width(text, 11.5) + 6.0
            w = min(PAD + DOT + GAP + text_w + 6.0 + ARROW_W + PAD, max_w)
            btn = NSButton.alloc().initWithFrame_(NSMakeRect(origin.x, origin.y, w, 26))
            btn.setTitle_("")
            btn.setBordered_(False)
            btn.setTarget_(self)
            btn.setAction_("noteClicked:")
            btn.setTag_(int(index))
            btn.setWantsLayer_(True)
            if btn.layer() is not None:
                # radius 6 (native macOS feel — NOT a pill) per the redline.
                btn.layer().setCornerRadius_(_R_CONTROL)
                btn.layer().setBackgroundColor_(
                    _c(255, 255, 255, _FILL_RAISED_A).CGColor()
                )
                btn.layer().setBorderWidth_(1.0)
                btn.layer().setBorderColor_(_c(255, 255, 255, 0.14).CGColor())
            dot = NSView.alloc().initWithFrame_(NSMakeRect(PAD, 10.5, DOT, DOT))
            dot.setWantsLayer_(True)
            if dot.layer() is not None:
                dot.layer().setCornerRadius_(DOT / 2.0)
                dot.layer().setBackgroundColor_(_c(217, 84, 42).CGColor())
            btn.addSubview_(dot)
            tx = PAD + DOT + GAP
            lab = _label(text, 11.5, _c(224, 213, 191))
            lab.setFrame_(NSMakeRect(tx, 5, w - tx - PAD - ARROW_W - 4.0, 15))
            try:
                lab.cell().setLineBreakMode_(4)  # truncate tail inside max_w
            except Exception:  # pragma: no cover
                pass
            btn.addSubview_(lab)
            arr = _label("↗", 11.0, _muted())
            arr.setFrame_(NSMakeRect(w - PAD - ARROW_W + 2.0, 5, ARROW_W, 15))
            btn.addSubview_(arr)
            btn.setToolTip_("Otwórz w Obsidian: " + text)
            return btn

        # -- actions --------------------------------------------------------- #

        def railRowClicked_(self, sender):
            # Picking an insight while reading a note must SHOW that insight —
            # leave the reader first or the click looks like a no-op.
            idx = int(sender.tag())
            if self._mode == "note" and idx == self._deck.active_index:
                # The ACTIVE insight's row = "back to it" gesture — keep the
                # ticked directions and the captured scroll, like „← Wróć".
                self._leave_note_for_insights()
                self._render()
                return
            self._leave_note_for_insights()
            self._deck.select(idx)
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
            if not (0 <= i < len(names)):
                return
            # Source chip on a connection → read the note in-app (the digest
            # entry point of the markdown-reader plan); unresolvable basenames
            # degrade to the external opener as before.
            path = self._resolve_note_basename(names[i])
            if path is not None:
                self._open_note_in_reader(path)
            else:
                self._invoke_callback("open_note", names[i])

        def transcriptClicked_(self, sender):
            paths = getattr(self, "_recent_paths", [])
            i = int(sender.tag())
            if 0 <= i < len(paths) and paths[i] is not None:
                self._invoke_callback("open_transcript", paths[i])

        # -- in-app note reader (markdown-reader plan) ----------------------- #

        @objc.python_method
        def _resolve_note_basename(self, basename):
            try:
                return obsidian_link.resolve_note_path(
                    basename, Path(config.TRANSCRIBE_DIR)
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("note resolve failed for %r: %s", basename, exc)
                return None

        @objc.python_method
        def _open_note_in_reader(self, path, breadcrumb="push", fallback_external=True):
            """Render ``path`` in the in-app reader; returns True on success.

            ``breadcrumb``: "push" (wikilink hop), "reset" (fresh rail entry),
            "replace" (back-navigation — no stack mutation). State mutates
            only AFTER a successful render, so a failed open never corrupts
            the view or the trail. ``fallback_external=False`` suppresses the
            opener fallback (back-navigation must not steal focus for a note
            it is skipping)."""
            if breadcrumb not in ("push", "reset", "replace"):
                # A typo'd mode would silently behave like "replace" — fail
                # loud instead so tests catch it at the call site.
                raise ValueError(f"unknown breadcrumb mode: {breadcrumb!r}")
            try:
                html = nrend.note_page_html(Path(path))
            except Exception as exc:
                logger.warning("in-app render failed for %s: %s", path, exc)
                if fallback_external:
                    self._invoke_callback("open_transcript", path)
                return False
            if self._mode != "note":
                # Save where the user was — both the mode to return to and
                # the reader scroll offset restored on „← Wróć"; the epoch
                # bump drops in-flight recall/synthesis deliveries so they
                # can't re-render (and yank) the note view. The dropped
                # deliveries can't clear their own loading flags — clear them
                # here or the restored recall view spins forever.
                self._capture_scroll()
                self._epoch += 1
                self._recall_loading = False
                self._answer_loading = False
                self._note_return_mode = self._mode
                self._note_stack = []
            elif breadcrumb == "reset":
                self._note_stack = []
            elif (
                breadcrumb == "push"
                and self._note_path is not None
                and Path(path) != self._note_path
            ):
                self._note_stack.append(self._note_path)
            self._note_path = Path(path)
            self._note_html = html
            # Fresh HTML must reach the webview even when the SAME note is
            # re-opened (the file may have changed on disk) — invalidate the
            # loaded-page marker so _build_note_reader reloads.
            self._webview_path = None
            self._mode = "note"
            self._render()
            return True

        @objc.python_method
        def _leave_note_for_insights(self):
            """No-op outside note mode; otherwise exit the reader into the
            insight view (rail rows / triage segments / bridges)."""
            if self._mode == "note":
                self._exit_note_mode()
                self._mode = "insight"

        @objc.python_method
        def _exit_note_mode(self):
            """Drop all reader state (webview incl.) — every path that leaves
            "note" mode goes through here so nothing keeps retaining the
            out-of-process web content. The webview must also LEAVE the view
            hierarchy: on window close no re-render replaces the content
            view, so dropping the Python ref alone would let the closed
            window's tree keep the WebContent process pinned."""
            if self._webview is not None:
                try:
                    self._webview.removeFromSuperview()
                except Exception:  # pragma: no cover - defensive
                    pass
            self._note_path = None
            self._note_html = ""
            self._note_stack = []
            self._webview = None
            self._webview_path = None
            self._reader_page_url = None

        def noteBackClicked_(self, _sender):
            # Walk the breadcrumb until an entry actually renders — a note
            # deleted, renamed, or corrupted since the push is skipped instead
            # of desyncing the view or bouncing to the external opener.
            while self._note_stack:
                prev = self._note_stack.pop()
                if self._open_note_in_reader(
                    prev, breadcrumb="replace", fallback_external=False
                ):
                    return
                logger.info("breadcrumb note unreadable, skipping: %s", prev)
            mode = self._note_return_mode
            self._exit_note_mode()
            self._mode = mode
            self._render()

        def noteOpenExternalClicked_(self, _sender):
            if self._note_path is not None:
                self._invoke_callback("open_transcript", self._note_path)

        def openNoteFromLink_(self, path_str):
            """Deferred wikilink navigation (off the WKWebView delegate)."""
            self._open_note_in_reader(Path(str(path_str)))

        def webView_decidePolicyForNavigationAction_decisionHandler_(
            self, _web, action, handler
        ):
            """Reader navigation policy: our own page (+ in-page #anchor jumps)
            stays in the webview, wikilinks re-render in-app, http(s)/mailto/
            obsidian go to the system, and everything else is denied (the
            page is fully self-contained). The page is loaded via a real
            file:// URL (loadFileURL), so "is this our own page" is an exact
            string match — no navigationType heuristics needed, and no note
            content can spoof it."""
            try:
                url = action.request().URL()
                s = str(url.absoluteString()) if url is not None else ""
            except Exception:  # pragma: no cover - defensive
                handler(_WK_CANCEL)
                return
            page = getattr(self, "_reader_page_url", None)
            if page and (s == page or s.startswith(page + "#")):
                handler(_WK_ALLOW)
                return
            handler(_WK_CANCEL)
            target = nrend.wikilink_target(s)
            if target is not None:
                path = self._resolve_note_basename(target)
                if path is not None:
                    # Defer: re-rendering tears the webview down mid-callback.
                    self.performSelectorOnMainThread_withObject_waitUntilDone_(
                        "openNoteFromLink:", str(path), False
                    )
                else:
                    self._invoke_callback("open_note", target)
                return
            if s.startswith(("http://", "https://", "mailto:", "obsidian://")):
                obsidian_link.open_url(s)

        def webViewWebContentProcessDidTerminate_(self, _web):
            """macOS killed the reader's WebContent process (memory pressure,
            long sleep) — reload instead of leaving a permanently blank pane."""
            logger.warning("reader web content terminated — reloading")
            self._webview_path = None
            if self._mode == "note":
                self._render()

        def continueLLMClicked_(self, sender):
            self._do_handoff(ho.LLM)

        def taskClicked_(self, sender):
            self._do_handoff(ho.TASK)

        def calendarClicked_(self, sender):
            self._do_handoff(ho.CALENDAR)

        def copyClicked_(self, sender):
            self._do_handoff(ho.CLIPBOARD)

        def switchLLMClicked_(self, sender):
            """C4 caret: the connected-tools menu (Claude / ChatGPT)."""
            from AppKit import NSMenu, NSMenuItem

            cur = getattr(config, "LLM_HANDOFF_TOOL", "claude")
            menu = NSMenu.alloc().init()
            menu.setAutoenablesItems_(False)
            head = NSMenuItem.alloc().init()
            head.setTitle_("Podłączone narzędzie")
            head.setEnabled_(False)
            menu.addItem_(head)
            for key in ho.LLM_TOOLS:
                it = NSMenuItem.alloc().init()
                it.setTitle_(ho.tool_name(key))
                it.setTarget_(self)
                it.setAction_("pickLLMClicked:")
                it.setRepresentedObject_(key)
                it.setState_(1 if key == cur else 0)
                img = _brand_image(key, 13.0)
                if img is not None:
                    it.setImage_(img)
                menu.addItem_(it)
            menu.popUpMenuPositioningItem_atLocation_inView_(
                None, NSMakePoint(0, sender.frame().size.height + 2), sender
            )

        def pickLLMClicked_(self, sender):
            key = sender.representedObject()
            if not key or key not in ho.LLM_TOOLS:
                return
            config.LLM_HANDOFF_TOOL = key
            try:  # global, remembered — the same setting as in Ustawienia
                from src.config.settings import UserSettings

                s = UserSettings.load()
                s.ai_handoff_tool = key
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
                # U4 rev. 2: every directions exit auto-keeps THIS insight —
                # captured now, not whatever is active when the worker returns.
                "index": self._deck.active_index,
            }
            import threading

            # Kept on self so tests (and a curious debugger) can join it.
            self._handoff_thread = threading.Thread(
                target=self._handoff_worker_,
                args=(payload,),
                name="HandoffDispatch",
                daemon=True,
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
            payload = dict(payload)
            payload["toast"] = res.toast
            self._pending_handoff = payload
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "applyHandoff:", None, False
            )

        def applyHandoff_(self, _ignored):
            payload = getattr(self, "_pending_handoff", None)
            if not payload:
                return
            self._pending_handoff = None
            # U4 rev. 2 / anti-error 11: a handoff auto-keeps the insight — it
            # may NOT stay in Nowych. In-memory retag + an explicit ``save``
            # event so the decision survives restart (triage replay).
            idx = payload.get("index", -1)
            already_kept = self._deck.state_at(idx) == im.KEPT
            if not already_kept and idx >= 0:
                self._deck.retag_index(idx, im.KEPT)
                try:
                    vsig.record_action(
                        vsig.TARGET_SAVE,
                        sig=payload.get("sig", ""),
                        conn_type=payload.get("conn_type", ""),
                        notes=payload.get("notes"),
                    )
                except Exception as exc:  # pragma: no cover - best effort
                    logger.debug("auto-keep record_action failed: %s", exc)
            # Checkboxes clear, the directions bar disappears (BEHAVIOR §4.5).
            self._selected = set()
            self._handoff_bar_shown = False
            self._capture_scroll()
            self._render()
            target = payload.get("target")
            if target == ho.CLIPBOARD:
                toast = "Skopiowano"  # BEHAVIOR §9 — the copy channel's exact copy
            elif already_kept:
                toast = payload.get("toast") or "Przekazano"
            else:
                toast = "Przekazano · zachowano"
            self._show_toast(toast)

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
            """C5/BEHAVIOR §3: Zachowaj — also „odzyskaj" in the Odrzucone
            view (constant label, meaning from context). Toast with Cofnij."""
            conn = self._deck.active()
            if conn is None:
                return
            idx = self._deck.active_index
            prev_view = self._deck.view
            self._emit_action(vsig.TARGET_SAVE)
            self._deck.keep()
            self._reset_card_state()
            self._render()
            label = "Odzyskano" if prev_view == im.DISMISSED else "Zachowano"
            self._show_toast(
                label,
                undo=(idx, prev_view, conn.sig or "", conn.synthesis_type, conn.notes),
            )

        def dismissClicked_(self, sender):
            conn = self._deck.active()
            if conn is None:
                return
            # U4 rev. 2: dismissing an already-kept insight (which includes
            # every handed-off one — handoff auto-keeps) undoes a decision, so
            # it asks first. „Przekazać-a-potem-odrzucić" is a contradiction
            # the system does not silently offer.
            if self._deck.view == im.KEPT:
                try:
                    from AppKit import NSAlert

                    alert = NSAlert.alloc().init()
                    alert.setMessageText_("Odrzucić zachowany insight?")
                    alert.setInformativeText_(
                        "Ten insight jest w Zachowanych (mógł też zostać "
                        "przekazany dalej). Odrzucenie cofnie zachowanie."
                    )
                    alert.addButtonWithTitle_("Odrzuć")
                    alert.addButtonWithTitle_("Anuluj")
                    if alert.runModal() != 1000:  # first button = proceed
                        return
                except Exception:  # pragma: no cover - headless/tests
                    pass
            idx = self._deck.active_index
            prev_view = self._deck.view
            self._emit_action(vsig.TARGET_NONE)
            self._deck.dismiss()
            self._reset_card_state()
            self._render()
            self._show_toast(
                "Odrzucono",
                undo=(idx, prev_view, conn.sig or "", conn.synthesis_type, conn.notes),
            )

        def undoTriageClicked_(self, _sender):
            """Toast „Cofnij": restore the pre-click state, in memory AND in
            the signal log (a ``reset``/re-triage event — survives restart)."""
            payload = getattr(self, "_undo_payload", None)
            if not payload:
                return
            self._undo_payload = None
            idx, prev_view, sig, conn_type, notes = payload
            self._deck.retag_index(idx, prev_view)
            target = {
                im.NEW: vsig.TARGET_RESET,
                im.KEPT: vsig.TARGET_SAVE,
                im.DISMISSED: vsig.TARGET_NONE,
            }.get(prev_view, vsig.TARGET_RESET)
            try:
                vsig.record_action(target, sig=sig, conn_type=conn_type, notes=notes)
            except Exception as exc:  # pragma: no cover - best effort
                logger.debug("undo record_action failed: %s", exc)
            self.removeToast_(None)
            self._deck.set_view(prev_view)
            self._deck.select(idx)
            self._reset_card_state()
            self._render()

        def _show_toast(self, text, undo=None):
            """Gold toast, 2s. With ``undo`` (BEHAVIOR §9: Zachowaj/Odrzuć),
            a „Cofnij" button restores the pre-click state."""
            win = self._window
            if win is None or win.contentView() is None:
                return
            content = win.contentView()
            b = content.bounds()
            undo_w = 62.0 if undo is not None else 0.0
            tw = min(440.0, 80.0 + 7.0 * len(text) + undo_w)
            toast = _DashFlippedView.alloc().initWithFrame_(
                NSMakeRect(
                    _RAIL_W + (b.size.width - _RAIL_W - tw) / 2,
                    b.size.height - _FOOTER_H - 44,
                    tw,
                    32,
                )
            )
            toast.setWantsLayer_(True)
            if toast.layer() is not None:
                toast.layer().setCornerRadius_(9.0)
                toast.layer().setBackgroundColor_(_gold().CGColor())
            lab = _label(text, 12.5, _c(14, 13, 18), bold=True)
            lab.setAlignment_(1)
            lab.setFrame_(NSMakeRect(8, 8, tw - 16 - undo_w, 16))
            toast.addSubview_(lab)
            if undo is not None:
                self._undo_payload = undo
                ub = NSButton.alloc().initWithFrame_(
                    NSMakeRect(tw - undo_w - 4, 4, undo_w, 24)
                )
                ub.setTitle_("")
                ub.setBordered_(False)
                ub.setTarget_(self)
                ub.setAction_("undoTriageClicked:")
                ub.setWantsLayer_(True)
                if ub.layer() is not None:
                    ub.layer().setCornerRadius_(6.0)
                    ub.layer().setBackgroundColor_(_c(14, 13, 18, 0.14).CGColor())
                ul = _label("Cofnij", 11.5, _c(14, 13, 18), bold=True)
                ul.setAlignment_(1)
                ul.setFrame_(NSMakeRect(0, 4, undo_w, 15))
                ub.addSubview_(ul)
                toast.addSubview_(ub)
            content.addSubview_(toast)
            if self._toast is not None:
                self._toast.removeFromSuperview()
            self._toast = toast
            from Foundation import NSTimer

            self._toast_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                2.0, self, "removeToast:", None, False
            )

        def removeToast_(self, timer):
            t = getattr(self, "_toast", None)
            if t is not None:
                t.removeFromSuperview()
                self._toast = None

        # -- public API ------------------------------------------------------ #

        def updateDeck_(self, deck):
            prev_view = self._deck.view if self._deck is not None else None
            self._deck = deck if deck is not None else im.InsightDeck()
            if self._window is not None and prev_view:
                # An open window keeps the user's in-session view choice;
                # a fresh window applies the first-non-empty rule (U9).
                self._deck.set_view(prev_view)
            else:
                self._deck.focus_first_nonempty()
            # Reset the card state; under the reader keep the scroll offset
            # captured at note entry, or „← Wróć" lands at the top.
            keep = self._scroll_y if self._mode == "note" else 0.0
            self._reset_card_state()
            self._scroll_y = keep
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
