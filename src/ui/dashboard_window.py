"""The Insights window (Direction B) — native AppKit, action-engine redesign.

A standalone, resizable ``NSWindow`` that is the *home* for the connections
Malinche finds: a left rail listing the queue, and a scrolling reader that lays
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
from typing import Callable, Dict, Optional, Set

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
        NSFont,
        NSFontAttributeName,
        NSGradient,
        NSImage,
        NSImageLeft,
        NSImageOnly,
        NSMakePoint,
        NSMakeRect,
        NSMakeSize,
        NSScrollView,
        NSTextField,
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
_WIN_W = 860.0
_WIN_H = 560.0
_WIN_MIN_W = 740.0
_WIN_MIN_H = 460.0
_HEADER_H = 40.0
_RAIL_W = 236.0
_PAD = 16.0
_READER_PAD_X = 24.0
_ROW_H = 58.0
_FOOTER_H = 46.0
_BAR_H = 48.0


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
    return _c(224, 99, 58)


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

    def _sigil(frame, layout, hexcol):
        v = _SigilView.alloc().initWithFrame_(frame)
        v.layout_key = layout
        v.stroke_hex = hexcol
        return v

    def _pill_button(title, frame, fg, bg, border, target, action, size=13.0):
        from AppKit import NSAttributedString, NSForegroundColorAttributeName

        btn = NSButton.alloc().initWithFrame_(frame)
        btn.setBordered_(False)
        btn.setWantsLayer_(True)
        btn.setFont_(NSFont.systemFontOfSize_(size))
        btn.setTarget_(target)
        btn.setAction_(action)
        layer = btn.layer()
        if layer is not None:
            layer.setCornerRadius_(min(frame.size.height / 2.0, 9.0))
            layer.setBackgroundColor_(bg.CGColor() if bg is not None else None)
            if border is not None:
                layer.setBorderWidth_(1.0)
                layer.setBorderColor_(border.CGColor())
        btn.setAttributedTitle_(
            NSAttributedString.alloc().initWithString_attributes_(
                title, {NSForegroundColorAttributeName: fg}
            )
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
        "gemini": "gemini.svg",
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
        """A compact icon-only pill button (secondary handoff actions)."""
        btn = NSButton.alloc().initWithFrame_(frame)
        btn.setBordered_(False)
        btn.setWantsLayer_(True)
        btn.setTitle_("")
        if image is not None:
            btn.setImage_(image)
            btn.setImagePosition_(NSImageOnly)
            try:
                btn.setContentTintColor_(tint)
            except Exception:  # pragma: no cover - older AppKit
                pass
        btn.setTarget_(target)
        btn.setAction_(action)
        if tooltip:
            btn.setToolTip_(tooltip)
        layer = btn.layer()
        if layer is not None:
            layer.setCornerRadius_(min(frame.size.height / 2.0, 9.0))
            layer.setBackgroundColor_(bg.CGColor() if bg is not None else None)
            if border is not None:
                layer.setBorderWidth_(1.0)
                layer.setBorderColor_(border.CGColor())
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
            win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, _WIN_W, _WIN_H), mask, NSBackingStoreBuffered, False
            )
            win.setTitle_("Malinche — Konstelacja")
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

            total = len(self._deck)
            idx = self._deck.active_index
            nav = (
                "0 połączeń"
                if self._deck.is_empty
                else f"połączenie {idx + 1} z {total}"
            )
            nav_label = _label(nav, 11.5, _muted())
            nav_label.setFrame_(NSMakeRect(w - 200, 11, 180, 18))
            nav_label.setAlignment_(2)
            bg.addSubview_(nav_label)

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
            head = _eyebrow("Połączenia", _muted())
            head.setFrame_(NSMakeRect(pad, cy, 120, 14))
            view.addSubview_(head)
            count = _label(
                f"{self._deck.unseen_count} niezobaczonych", 10.5, _c(111, 102, 90)
            )
            count.setFrame_(NSMakeRect(frame.size.width - 130, cy, 118, 14))
            count.setAlignment_(2)
            view.addSubview_(count)
            cy += 24

            for i, conn in enumerate(self._deck.items):
                self._add_rail_row(
                    view, conn, i, NSMakeRect(8, cy, frame.size.width - 16, _ROW_H - 6)
                )
                cy += _ROW_H

            foot_y = frame.size.height - 96
            fdiv = NSView.alloc().initWithFrame_(
                NSMakeRect(pad, foot_y - 10, frame.size.width - 2 * pad, 1)
            )
            fdiv.setWantsLayer_(True)
            if fdiv.layer() is not None:
                fdiv.layer().setBackgroundColor_(_c(255, 255, 255, 0.07).CGColor())
            view.addSubview_(fdiv)
            fhead = _eyebrow("Ostatnie transkrypty", _c(126, 117, 101))
            fhead.setFrame_(NSMakeRect(pad, foot_y, 200, 13))
            view.addSubview_(fhead)
            ry = foot_y + 20
            recents = self._recent_transcripts()
            self._recent_paths = [r.get("path") for r in recents]
            if not recents:
                empty = _label("—", 11, _c(111, 102, 90))
                empty.setFrame_(NSMakeRect(pad, ry, frame.size.width - 2 * pad, 14))
                view.addSubview_(empty)
            for i, r in enumerate(recents):
                btn = NSButton.alloc().initWithFrame_(
                    NSMakeRect(pad - 4, ry - 3, frame.size.width - 2 * pad + 8, 18)
                )
                btn.setBordered_(False)
                btn.setTransparent_(True)
                btn.setTitle_("")
                btn.setTarget_(self)
                btn.setAction_("transcriptClicked:")
                btn.setTag_(i)
                btn.setToolTip_("Otwórz w Obsidian")
                lab = _label(r.get("label", "Transkrypt"), 11, _muted())
                lab.setFrame_(NSMakeRect(4, 2, frame.size.width - 2 * pad, 14))
                lab.setLineBreakMode_(4)
                btn.addSubview_(lab)
                when = r.get("when")
                if when:
                    t = _label(when, 11, _c(111, 102, 90))
                    t.setFrame_(NSMakeRect(frame.size.width - pad - 34, ry, 34, 14))
                    t.setAlignment_(2)
                    view.addSubview_(t)
                view.addSubview_(btn)
                ry += 19
            return view

        @objc.python_method
        def _add_rail_row(self, view, conn, index, frame):
            from src.ui.hover import make_hover_button

            btn = make_hover_button(frame) or NSButton.alloc().initWithFrame_(frame)
            btn.setTitle_("")
            btn.setBordered_(False)
            btn.setTarget_(self)
            btn.setAction_("railRowClicked:")
            btn.setTag_(index)
            active = index == self._deck.active_index
            kept = self._deck.is_kept(index)

            if active:
                bar = NSView.alloc().initWithFrame_(
                    NSMakeRect(0, 9, 2.5, frame.size.height - 18)
                )
                bar.setWantsLayer_(True)
                if bar.layer() is not None:
                    bar.layer().setBackgroundColor_(_gold().CGColor())
                    bar.layer().setCornerRadius_(1.25)
                btn.addSubview_(bar)

            btn.addSubview_(_sigil(NSMakeRect(8, 5, 22, 22), conn.layout(), conn.resolved_tcolor()))

            lab = _label(
                conn.resolved_label() + ("   ✓ zachowane" if kept else ""),
                11,
                _gold() if active else _cream_soft(),
                bold=True,
            )
            lab.setFrame_(NSMakeRect(36, 5, frame.size.width - 42, 14))
            lab.setLineBreakMode_(4)
            btn.addSubview_(lab)

            snip = _wrapping_label(
                conn.snippet,
                11.5,
                _muted() if not active else _c(169, 156, 136),
                NSMakeRect(36, 21, frame.size.width - 44, 30),
            )
            btn.addSubview_(snip)
            if kept:
                btn.setAlphaValue_(0.46)
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

            conn = self._deck.active()
            if conn is None:
                if self._transcribing:
                    return self._build_skeleton(view, frame)
                return self._build_empty(view, frame)

            has_sel = bool(self._selected)
            bar_h = _BAR_H if has_sel else 0.0
            scroll_h = frame.size.height - _FOOTER_H - bar_h

            # scrolling document (spark + ground + directions)
            scroll = NSScrollView.alloc().initWithFrame_(
                NSMakeRect(0, 0, frame.size.width, scroll_h)
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
            return view

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
            tlabel = _eyebrow(conn.resolved_label(), _hex(conn.resolved_tcolor()))
            tlabel.setFrame_(NSMakeRect(_READER_PAD_X + 44, cy + 10, inner_w - 160, 14))
            doc.addSubview_(tlabel)
            eye = _label("✦ NOWY INSIGHT", 10.5, _c(154, 140, 123))
            eye.setFrame_(NSMakeRect(reader_w - 160, cy + 10, 136, 14))
            eye.setAlignment_(2)
            doc.addSubview_(eye)
            cy += 46

            # thesis (the spark)
            thesis = "„" + conn.rationale + "”"
            th = max(30.0, _measure_height(thesis, 21, inner_w))
            doc.addSubview_(
                _wrapping_label(thesis, 21, _cream(), NSMakeRect(_READER_PAD_X, cy, inner_w, th))
            )
            cy += th + 14

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
            text_w = inner_w - 36
            row_h = max(34.0, _measure_height(text, 13.5, text_w) + 18)
            frame = NSMakeRect(_READER_PAD_X, cy, inner_w, row_h)
            btn = make_hover_button(frame) or NSButton.alloc().initWithFrame_(frame)
            btn.setTitle_("")
            btn.setBordered_(False)
            btn.setTarget_(self)
            btn.setAction_("directionClicked:")
            btn.setTag_(index)
            btn.setWantsLayer_(True)
            if btn.layer() is not None:
                btn.layer().setCornerRadius_(12.0)
                if selected:
                    btn.layer().setBackgroundColor_(_c(224, 99, 58, 0.10).CGColor())
                    btn.layer().setBorderWidth_(1.0)
                    btn.layer().setBorderColor_(_c(224, 99, 58, 0.34).CGColor())
                else:
                    btn.layer().setBackgroundColor_(_c(255, 255, 255, 0.018).CGColor())

            # Vertically center the checkbox on the *first text line*, not on the
            # whole (possibly multi-line) row — multi-line directions wrap, and a
            # fixed offset left the box visibly low. Derive the line centre from
            # the measured single-line height.
            TEXT_TOP = 9.0
            BOX = 18.0
            line_h = _measure_height("Ag", 13.5, 10000.0)
            box_y = TEXT_TOP + line_h / 2.0 - BOX / 2.0
            box = NSView.alloc().initWithFrame_(NSMakeRect(12, box_y, BOX, BOX))
            box.setWantsLayer_(True)
            if box.layer() is not None:
                box.layer().setCornerRadius_(5.0)
                if selected:
                    box.layer().setBackgroundColor_(_terracotta().CGColor())
                else:
                    box.layer().setBorderWidth_(1.5)
                    box.layer().setBorderColor_(_c(255, 255, 255, 0.26).CGColor())
            btn.addSubview_(box)
            if selected:
                chk = _label("✓", 12, _c(255, 255, 255), bold=True)
                chk.setFrame_(NSMakeRect(12, box_y - 1, BOX, 16))
                chk.setAlignment_(1)
                btn.addSubview_(chk)

            line = _wrapping_label(
                text,
                13.5,
                _cream() if selected else _cream_soft(),
                NSMakeRect(40, TEXT_TOP, text_w, row_h - 16),
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

            BTN_H = 32.0
            BTN_Y = (frame.size.height - BTN_H) / 2.0
            pad = _READER_PAD_X
            white = _c(255, 255, 255)

            tool = getattr(config, "LLM_HANDOFF_TOOL", "claude")
            name = ho.tool_name(tool)

            # Secondary actions: compact, icon-only with tooltips. Keeping them
            # square means the action row stays narrow and can never push the
            # last button (the old "Kopiuj") off the right edge.
            secondary = (
                ("checklist", "Utwórz zadanie", "taskClicked:"),
                ("calendar", "Dodaj do kalendarza", "calendarClicked:"),
                ("doc.on.doc", "Kopiuj do schowka", "copyClicked:"),
            )
            ICON_W = 34.0
            ICON_GAP = 6.0
            CARET_W = 26.0
            GAP_CTA_CARET = 3.0
            GAP_CLUSTER = 16.0
            sec_w = len(secondary) * ICON_W + (len(secondary) - 1) * ICON_GAP

            def _cta_width(label):
                # leading pad + brand glyph + gap + measured text + trailing pad
                return 14.0 + 16.0 + 8.0 + _text_width(label, 13.0) + 16.0

            def _cluster_width(cw):
                return cw + GAP_CTA_CARET + CARET_W + GAP_CLUSTER + sec_w

            # One measured, right-anchored layout — no hardcoded width guesses.
            # Degrade gracefully under width pressure so the *actions* never clip:
            # 1) drop the provider name from the CTA, 2) drop the status label.
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

            primary = _pill_button(
                cta_label,
                NSMakeRect(x, BTN_Y, cta_w, BTN_H),
                white, _terracotta(), _terracotta(),
                self, "continueLLMClicked:",
            )
            brand = _brand_image(tool, 15.0)
            if brand is not None:
                primary.setImage_(brand)
                primary.setImagePosition_(NSImageLeft)
                try:
                    primary.setImageHugsTitle_(True)
                    primary.setContentTintColor_(white)
                except Exception:  # pragma: no cover - older AppKit
                    pass
            primary.setToolTip_("Przekaż wybrane kierunki do " + name)
            bar.addSubview_(primary)

            caret = _pill_button(
                "⌄",
                NSMakeRect(x + cta_w + GAP_CTA_CARET, BTN_Y, CARET_W, BTN_H),
                white, _c(224, 99, 58, 0.85), _terracotta(),
                self, "switchLLMClicked:",
            )
            caret.setToolTip_("Zmień narzędzie (Claude / ChatGPT / Gemini)")
            bar.addSubview_(caret)

            sx = x + cta_w + GAP_CTA_CARET + CARET_W + GAP_CLUSTER
            for symbol, tip, sel in secondary:
                b = _icon_button(
                    style.sf_symbol(symbol, point=14.0, weight="regular"),
                    tip,
                    NSMakeRect(sx, BTN_Y, ICON_W, BTN_H),
                    _cream_soft(), _c(255, 255, 255, 0.05), _c(255, 255, 255, 0.15),
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

            dismiss = _pill_button(
                "Odrzuć", NSMakeRect(frame.size.width - 220, 8, 90, 30),
                _muted(), None, None, self, "dismissClicked:",
            )
            foot.addSubview_(dismiss)
            dot = _label("·", 13, _c(70, 68, 61))
            dot.setFrame_(NSMakeRect(frame.size.width - 128, 12, 8, 16))
            foot.addSubview_(dot)
            keep = _pill_button(
                "Zachowaj", NSMakeRect(frame.size.width - 116, 8, 100, 30),
                _c(126, 117, 101), None, None, self, "keepClicked:",
            )
            foot.addSubview_(keep)
            view.addSubview_(foot)

        @objc.python_method
        def _build_empty(self, view, frame):
            view.addSubview_(
                _sigil(
                    NSMakeRect(frame.size.width / 2 - 27, frame.size.height / 2 - 96, 54, 54),
                    "triad", "#E3C16B",
                )
            )
            h = _label("Cisza w korpusie", 20, _cream(), bold=True)
            h.setFrame_(NSMakeRect(0, frame.size.height / 2, frame.size.width, 26))
            h.setAlignment_(1)
            view.addSubview_(h)
            p = _wrapping_label(
                "Wszystkie połączenia przejrzane. Malinche czyta dalej — gdy coś "
                "się zapali, wróci tu rozbłysk.",
                13.5, _muted(),
                NSMakeRect(frame.size.width / 2 - 150, frame.size.height / 2 + 30, 300, 50),
            )
            p.setAlignment_(1)
            view.addSubview_(p)
            return view

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
                btn.layer().setCornerRadius_(13)
                btn.layer().setBackgroundColor_(_c(255, 255, 255, 0.05).CGColor())
                btn.layer().setBorderWidth_(1.0)
                btn.layer().setBorderColor_(_c(255, 255, 255, 0.12).CGColor())
            btn.setAttributedTitle_(
                NSAttributedString.alloc().initWithString_attributes_(
                    "◇ " + text + "  ↗", {NSForegroundColorAttributeName: _c(216, 203, 180)}
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
            order = ["claude", "chatgpt", "gemini"]
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
            conn = self._deck.active()
            if conn is None or not self._selected:
                return
            idxs = sorted(i for i in self._selected if 0 <= i < len(conn.directions))
            dirs = [conn.directions[i] for i in idxs]
            tool = getattr(config, "LLM_HANDOFF_TOOL", "claude")
            evidence = [(e.date, e.note, e.quote) for e in conn.evidence]
            res = ho.dispatch(
                target,
                label=conn.resolved_label(),
                rationale=conn.rationale,
                evidence=evidence,
                directions=dirs,
                tool=tool,
            )
            vsig.record_action(
                target,
                sig=conn.sig or "",
                conn_type=conn.synthesis_type,  # raw type only — never the display constant (keeps the canonical sig joinable)
                notes=conn.notes,
                directions=idxs,
                tool=(tool if target == ho.LLM else ""),
            )
            self._show_toast(res.toast)

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
