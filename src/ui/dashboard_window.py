"""The Insights "Konstelacja" window (Direction B) — native AppKit.

A standalone, resizable ``NSWindow`` that is the *home* for the connections
Malinche finds: a left rail listing the queue, and a reader that shows the live
constellation, the rationale, the source notes and the directions, with
Zachowaj / Odrzuć. The user enters it from the menu or a notification (not by
clicking the menu-bar icon — that opens the native menu).

Spec: ``design-system/pages/dashboard-screens.html``. Renders from the pure
:class:`~src.ui.insight_model.InsightDeck`; the constellation is drawn by
:mod:`~src.ui.constellation_view`. Dark surface on purpose — the constellation
glows only on dark. v1 uses the native dark titlebar (cheaper, consistent) with
a transparent, full-size content view so the dark surface runs edge to edge.

AppKit-optional: :func:`build_dashboard_window` returns ``None`` without AppKit.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from src.logger import logger
from src.ui import insight_model as im
from src.ui.constellation_view import build_constellation_view

try:
    import objc
    from AppKit import (
        NSBackingStoreBuffered,
        NSBezierPath,
        NSButton,
        NSColor,
        NSColorSpace,
        NSFont,
        NSGradient,
        NSMakePoint,
        NSMakeRect,
        NSMakeSize,
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


# Dimensions (points), from the redline in dashboard-screens.html.
_WIN_W = 860.0
_WIN_H = 560.0
_WIN_MIN_W = 620.0
_WIN_MIN_H = 420.0
_HEADER_H = 40.0
_RAIL_W = 236.0
_PAD = 16.0
_READER_PAD_X = 22.0
_ROW_H = 58.0  # one connection row (dot + label + 2-line snippet)
_STAGE_H = 200.0


def _c(r: float, g: float, b: float, a: float = 1.0):
    """NSColor from 0–255 channels (the dark-surface literals from the spec)."""
    return NSColor.colorWithRed_green_blue_alpha_(r / 255.0, g / 255.0, b / 255.0, a)


# Dark-surface palette (intentionally local — the dashboard is its own world).
def _cream():
    return _c(250, 243, 226)


def _cream_soft():
    return _c(201, 187, 166)


def _muted():
    return _c(140, 130, 115)


def _gold():
    return _c(244, 221, 142)


if _APPKIT_AVAILABLE:

    class _FlippedView(NSView):
        def isFlipped(self):
            return True

    class _DarkBackground(NSView):
        """Window background: a soft dark radial, like the mock."""

        def isFlipped(self):
            return True

        def drawRect_(self, _rect):
            b = self.bounds()
            # Solid deep-obsidian base first — guarantees the dark surface even if
            # the gradient is subtle or the offscreen capture skips it.
            _c(16, 14, 21).setFill()
            NSBezierPath.bezierPathWithRect_(b).fill()
            # A soft, low-alpha lighter halo from the top (mock: "at 64% 0%").
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

    class _FlashOverlay(NSView):
        """Gold micro-bloom + 'Zachowane' wash, shown briefly on keep."""

        def isFlipped(self):
            return True

        def drawRect_(self, _rect):
            b = self.bounds()
            grad = NSGradient.alloc().initWithColors_atLocations_colorSpace_(
                [_c(244, 221, 142, 0.26), _c(16, 14, 21, 0.90)],
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

    def _label(text, size, color, weight="regular", bold=False):
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

    def _eyebrow(text, color):
        field = _label(text.upper(), 10.5, color)
        return field

    def _pill_button(title, frame, fg, bg, border, target, action):
        btn = NSButton.alloc().initWithFrame_(frame)
        btn.setTitle_(title)
        btn.setBordered_(False)
        btn.setWantsLayer_(True)
        btn.setFont_(NSFont.systemFontOfSize_(13))
        btn.setContentTintColor_(fg)
        btn.setTarget_(target)
        btn.setAction_(action)
        layer = btn.layer()
        if layer is not None:
            layer.setCornerRadius_(frame.size.height / 2.0)
            layer.setBackgroundColor_(bg.CGColor() if bg is not None else None)
            if border is not None:
                layer.setBorderWidth_(1.0)
                layer.setBorderColor_(border.CGColor())
        # tint the title colour via an attributed string
        from AppKit import NSAttributedString, NSForegroundColorAttributeName

        btn.setAttributedTitle_(
            NSAttributedString.alloc().initWithString_attributes_(
                title, {NSForegroundColorAttributeName: fg}
            )
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
            self._row_buttons: List[object] = []
            self._keep_timer = None
            self._transcribing = False
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
            win.setTitlebarAppearsTransparent_(True)
            win.setMovableByWindowBackground_(True)
            win.setMinSize_(NSMakeSize(_WIN_MIN_W, _WIN_MIN_H))
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
            self._ensure_window()
            win = self._window
            if win is None:  # pragma: no cover - defensive
                return
            self._render()
            win.makeKeyAndOrderFront_(None)
            try:
                from AppKit import NSApp

                NSApp.activateIgnoringOtherApps_(True)
            except Exception:  # pragma: no cover
                pass

        # -- rendering ------------------------------------------------------- #

        @objc.python_method
        def _render(self):
            if self._window is None:
                return
            frame = self._window.contentView().frame() if self._window.contentView() else NSMakeRect(0, 0, _WIN_W, _WIN_H)
            w = frame.size.width or _WIN_W
            h = frame.size.height or _WIN_H

            bg = _FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
            bg.setWantsLayer_(True)
            if bg.layer() is not None:
                bg.layer().setBackgroundColor_(_c(16, 14, 21).CGColor())
            # Deep-obsidian backdrop as a drawRect subview (a contentView's own
            # drawRect is not reliably invoked; a subview's is). Fills solid +
            # a soft top halo.
            backdrop = _DarkBackground.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
            backdrop.setAutoresizingMask_(18)
            bg.addSubview_(backdrop)

            # nav label top-right ("połączenie X z N")
            total = len(self._deck)
            idx = self._deck.active_index
            nav = "0 połączeń" if self._deck.is_empty else f"połączenie {idx + 1} z {total}"
            nav_label = _label(nav, 11.5, _muted())
            nav_label.setFrame_(NSMakeRect(w - 200, 11, 180, 18))
            nav_label.setAlignment_(2)  # right
            nav_label.setAutoresizingMask_(1)  # min-x flexible (stick right)
            bg.addSubview_(nav_label)

            rail_h = h - _HEADER_H
            rail = self._build_rail(NSMakeRect(0, 0, _RAIL_W, rail_h))
            rail.setFrameOrigin_(NSMakePoint(0, _HEADER_H))
            rail.setAutoresizingMask_(16)  # height flexible
            bg.addSubview_(rail)

            reader_w = w - _RAIL_W
            reader = self._build_reader(NSMakeRect(0, 0, reader_w, rail_h))
            reader.setFrameOrigin_(NSMakePoint(_RAIL_W, _HEADER_H))
            reader.setAutoresizingMask_(18)  # width + height flexible
            bg.addSubview_(reader)

            self._window.setContentView_(bg)

        @objc.python_method
        def _build_rail(self, frame):
            view = _FlippedView.alloc().initWithFrame_(frame)
            # left divider drawn by reader bg; rail gets a darker wash
            wash = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, frame.size.width, frame.size.height))
            wash.setWantsLayer_(True)
            if wash.layer() is not None:
                wash.layer().setBackgroundColor_(_c(0, 0, 0, 0.16).CGColor())
            wash.setAutoresizingMask_(16)
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

            self._row_buttons = []
            for i, conn in enumerate(self._deck.items):
                self._add_rail_row(view, conn, i, NSMakeRect(8, cy, frame.size.width - 16, _ROW_H - 6))
                cy += _ROW_H

            # foot: recent transcripts
            foot_y = frame.size.height - 96
            fdiv = NSView.alloc().initWithFrame_(NSMakeRect(pad, foot_y - 10, frame.size.width - 2 * pad, 1))
            fdiv.setWantsLayer_(True)
            if fdiv.layer() is not None:
                fdiv.layer().setBackgroundColor_(_c(255, 255, 255, 0.07).CGColor())
            view.addSubview_(fdiv)
            fhead = _eyebrow("Ostatnie transkrypty", _c(126, 117, 101))
            fhead.setFrame_(NSMakeRect(pad, foot_y, 200, 13))
            view.addSubview_(fhead)
            ry = foot_y + 20
            for name, when in (
                ("Haetta — rozmowa z konstruktorem", "17.06"),
                ("8Moons — filmiki 2", "18.06"),
                ("Harmonogram 2-tyg. projektu", "03.06"),
            ):
                row = _label(name, 11, _muted())
                row.setFrame_(NSMakeRect(pad, ry, frame.size.width - 2 * pad - 36, 14))
                row.setLineBreakMode_(4)  # truncate tail
                view.addSubview_(row)
                t = _label(when, 11, _c(111, 102, 90))
                t.setFrame_(NSMakeRect(frame.size.width - pad - 34, ry, 34, 14))
                t.setAlignment_(2)
                view.addSubview_(t)
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

            # active gold rail
            if active:
                bar = NSView.alloc().initWithFrame_(NSMakeRect(0, 9, 2.5, frame.size.height - 18))
                bar.setWantsLayer_(True)
                if bar.layer() is not None:
                    bar.layer().setBackgroundColor_(_gold().CGColor())
                    bar.layer().setCornerRadius_(1.25)
                btn.addSubview_(bar)

            dot = NSView.alloc().initWithFrame_(NSMakeRect(10, 8, 7, 7))
            dot.setWantsLayer_(True)
            if dot.layer() is not None:
                hexcol = conn.resolved_tcolor()
                dot.layer().setBackgroundColor_(_hex(hexcol).CGColor())
                dot.layer().setCornerRadius_(3.5)
            btn.addSubview_(dot)

            lab = _label(conn.resolved_label() + ("   ✓ zachowane" if kept else ""), 11, _gold() if active else _cream_soft(), bold=True)
            lab.setFrame_(NSMakeRect(26, 5, frame.size.width - 32, 14))
            lab.setLineBreakMode_(4)
            btn.addSubview_(lab)

            snip = _wrapping_label(
                conn.snippet, 11.5, _muted() if not active else _c(169, 156, 136),
                NSMakeRect(26, 21, frame.size.width - 34, 30),
            )
            btn.addSubview_(snip)
            if kept:
                btn.setAlphaValue_(0.46)
            view.addSubview_(btn)
            self._row_buttons.append(btn)

        @objc.python_method
        def _build_reader(self, frame):
            view = _FlippedView.alloc().initWithFrame_(frame)
            # left divider
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

            inner_w = frame.size.width - 2 * _READER_PAD_X
            cy = _PAD

            # constellation stage
            stage = build_constellation_view(
                NSMakeRect(_READER_PAD_X, cy, inner_w, _STAGE_H), conn.layout(), False
            )
            if stage is not None:
                stage.setAutoresizingMask_(2)  # width flexible
                view.addSubview_(stage)
            cy += _STAGE_H + 8

            # type row
            tdot = NSView.alloc().initWithFrame_(NSMakeRect(_READER_PAD_X, cy + 2, 7, 7))
            tdot.setWantsLayer_(True)
            if tdot.layer() is not None:
                tdot.layer().setBackgroundColor_(_hex(conn.resolved_tcolor()).CGColor())
                tdot.layer().setCornerRadius_(3.5)
            view.addSubview_(tdot)
            tlabel = _eyebrow(conn.resolved_label(), _c(235, 213, 140))
            tlabel.setFrame_(NSMakeRect(_READER_PAD_X + 14, cy, inner_w - 14, 14))
            view.addSubview_(tlabel)
            cy += 24

            # rationale (display)
            rat = _wrapping_label(
                "„" + conn.rationale + "”", 21, _cream(),
                NSMakeRect(_READER_PAD_X, cy, inner_w, 84), weight_bold=False,
            )
            view.addSubview_(rat)
            cy += 92

            # notes chips
            ncap = _eyebrow("Notatki", _muted())
            ncap.setFrame_(NSMakeRect(_READER_PAD_X, cy, inner_w, 13))
            view.addSubview_(ncap)
            cy += 18
            cx = _READER_PAD_X
            for note in conn.notes:
                chip = self._chip(note, NSMakePoint(cx, cy))
                view.addSubview_(chip)
                cx += chip.frame().size.width + 6
                if cx > frame.size.width - 120:
                    cx = _READER_PAD_X
                    cy += 28
            cy += 34

            # directions
            dcap = _eyebrow("Kierunki", _muted())
            dcap.setFrame_(NSMakeRect(_READER_PAD_X, cy, inner_w, 13))
            view.addSubview_(dcap)
            cy += 18
            for d in conn.directions:
                row = _wrapping_label(
                    "·  " + d, 13.5, _cream_soft(),
                    NSMakeRect(_READER_PAD_X, cy, inner_w, 20),
                )
                view.addSubview_(row)
                cy += 24
            cy += 8

            # actions
            keep = _pill_button(
                "Zachowaj", NSMakeRect(_READER_PAD_X, cy, 110, 30),
                _c(139, 224, 181), _c(70, 177, 126, 0.16), _c(91, 196, 149, 0.42),
                self, "keepClicked:",
            )
            view.addSubview_(keep)
            dismiss = _pill_button(
                "Odrzuć", NSMakeRect(_READER_PAD_X + 120, cy, 96, 30),
                _c(176, 162, 141), None, None, self, "dismissClicked:",
            )
            view.addSubview_(dismiss)
            return view

        @objc.python_method
        def _build_empty(self, view, frame):
            cv = build_constellation_view(
                NSMakeRect((frame.size.width - 200) / 2, frame.size.height / 2 - 120, 200, 110),
                "triad", True,
            )
            if cv is not None:
                view.addSubview_(cv)
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
            """Loading state: a 'Transkrybuję…' badge + shimmer-grey placeholders,
            shown when the window is open while the model works and no insight
            has landed yet — no fake content."""
            inner_w = frame.size.width - 2 * _READER_PAD_X
            cy = _PAD
            badge = _label("●  Transkrybuję…", 11, _c(224, 162, 123))
            badge.setFrame_(NSMakeRect(_READER_PAD_X, cy, inner_w, 16))
            view.addSubview_(badge)
            cy += 26
            view.addSubview_(
                _skeleton_bar(NSMakeRect(_READER_PAD_X, cy, inner_w, _STAGE_H), 11)
            )
            cy += _STAGE_H + 16
            for frac, h in ((0.3, 13), (0.92, 18), (0.78, 18)):
                view.addSubview_(
                    _skeleton_bar(NSMakeRect(_READER_PAD_X, cy, inner_w * frac, h))
                )
                cy += h + 9
            cy += 10
            cx = _READER_PAD_X
            for w in (120.0, 150.0):
                view.addSubview_(
                    _skeleton_bar(NSMakeRect(cx, cy, w, 22), 11)
                )
                cx += w + 8
            return view

        @objc.python_method
        def _chip(self, text, origin):
            w = min(220.0, 18.0 + 7.0 * len(text))
            btn = NSButton.alloc().initWithFrame_(NSMakeRect(origin.x, origin.y, w, 24))
            btn.setBordered_(False)
            btn.setWantsLayer_(True)
            if btn.layer() is not None:
                btn.layer().setCornerRadius_(12)
                btn.layer().setBackgroundColor_(_c(255, 255, 255, 0.05).CGColor())
                btn.layer().setBorderWidth_(1.0)
                btn.layer().setBorderColor_(_c(255, 255, 255, 0.12).CGColor())
            from AppKit import NSAttributedString, NSForegroundColorAttributeName

            btn.setAttributedTitle_(
                NSAttributedString.alloc().initWithString_attributes_(
                    "◇ " + text, {NSForegroundColorAttributeName: _c(216, 203, 180)}
                )
            )
            btn.setFont_(NSFont.systemFontOfSize_(11.5))
            btn.setToolTip_("Otwórz w Obsidian: " + text)
            return btn

        # -- actions --------------------------------------------------------- #

        def railRowClicked_(self, sender):
            self._deck.select(int(sender.tag()))
            self._render()

        def keepClicked_(self, sender):
            # The quiet punchline: a gold micro-bloom + "Zachowane", then advance.
            if not self._show_keep_flash():
                self._deck.keep()
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
            self._render()

        @objc.python_method
        def _show_keep_flash(self):
            """Overlay the gold bloom on the reader region; False if no window."""
            win = self._window
            if win is None or win.contentView() is None:
                return False
            content = win.contentView()
            b = content.bounds()
            frame = NSMakeRect(
                _RAIL_W, _HEADER_H, b.size.width - _RAIL_W, b.size.height - _HEADER_H
            )
            overlay = _FlashOverlay.alloc().initWithFrame_(frame)
            overlay.setAutoresizingMask_(18)
            spark = _label("✦", 34, _gold(), bold=False)
            spark.setAlignment_(1)
            spark.setFrame_(
                NSMakeRect(0, frame.size.height * 0.4 - 40, frame.size.width, 44)
            )
            overlay.addSubview_(spark)
            lab = _label("Zachowane", 19, _cream(), bold=True)
            lab.setAlignment_(1)
            lab.setFrame_(
                NSMakeRect(0, frame.size.height * 0.4 + 6, frame.size.width, 26)
            )
            overlay.addSubview_(lab)
            sub = _label(
                "trafia do digestu · następne połączenie", 12.5, _muted()
            )
            sub.setAlignment_(1)
            sub.setFrame_(
                NSMakeRect(0, frame.size.height * 0.4 + 34, frame.size.width, 18)
            )
            overlay.addSubview_(sub)
            content.addSubview_(overlay)
            return True

        def dismissClicked_(self, sender):
            self._deck.dismiss()
            self._render()

        # -- public API ------------------------------------------------------ #

        def updateDeck_(self, deck):
            self._deck = deck if deck is not None else im.InsightDeck()
            if self._window is not None:
                self._render()

        def setTranscribing_(self, flag):
            """Tell the window the model is working (skeleton when empty)."""
            new = bool(flag)
            if new == self._transcribing:
                return
            self._transcribing = new
            if self._window is not None and self._window.isVisible():
                self._render()


def _hex(hexstr: str):
    """NSColor from a '#RRGGBB' string."""
    h = hexstr.lstrip("#")
    if len(h) == 6:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return _c(r, g, b)
    return _c(217, 84, 42)


def build_dashboard_window(
    deck: Optional["im.InsightDeck"] = None,
    callbacks: Optional[Dict[str, Callable]] = None,
):
    """Create the dashboard controller, or ``None`` without AppKit.

    ``deck`` defaults to :func:`insight_model.sample_deck` (placeholder data
    until the pipeline lands). The returned object exposes ``showWindow`` and
    ``updateDeck_``.
    """
    if not _APPKIT_AVAILABLE:
        return None
    try:
        if deck is None:
            from src.ui.insight_pipeline import latest_deck

            deck = latest_deck() or im.sample_deck()
        return _DashboardController.alloc().initWithDeck_callbacks_(deck, callbacks or {})
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Could not build dashboard window: %s", exc)
        return None
