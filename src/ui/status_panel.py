"""AppKit renderer for the menu-bar status panel (L4 phase 2b — render).

A left-click on the status item opens this NSPopover — a vibrant card showing the
current status, the file being transcribed, recent transcripts, and the primary
actions — instead of the flat native menu. Right-click still shows the full
native menu, so nothing is lost.

The card is rendered from the pure
:class:`~src.ui.status_panel_model.PanelModel` (tested separately); this module
is the thin AppKit layer that draws it, fresh on each open so the recent list and
active row stay current. AppKit-optional: with no AppKit
:func:`build_status_panel` returns ``None`` and the caller keeps the native menu.

See ``Docs/UI-REDESIGN-L4-PLAN.md`` (phase 2).
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from src.logger import logger
from src.ui import style

try:
    import objc
    from AppKit import (
        NSApp,
        NSBox,
        NSBoxSeparator,
        NSButton,
        NSEventMaskLeftMouseDown,
        NSEventMaskRightMouseDown,
        NSEventModifierFlagControl,
        NSEventTypeRightMouseDown,
        NSMakeRect,
        NSMakeSize,
        NSPopover,
        NSPopoverBehaviorTransient,
        NSProgressIndicator,
        NSProgressIndicatorStyleSpinning,
        NSView,
        NSViewController,
    )
    from Foundation import NSObject

    _APPKIT_AVAILABLE = True
except ImportError:  # pragma: no cover - non-mac
    _APPKIT_AVAILABLE = False


_PANEL_WIDTH = 320.0
_PAD = 16.0
_ROW_GAP = float(style.SPACE_TIGHT)
_BTN_H = 30.0
_BTN_GAP = 2.0


if _APPKIT_AVAILABLE:

    class _FlippedView(NSView):
        """Top-left origin so we can lay rows out top-to-bottom."""

        def isFlipped(self):
            return True

    class _StatusPanelController(NSObject):
        """Owns the NSPopover and renders the PanelModel on each open."""

        def initWithCallbacks_(self, callbacks):
            self = objc.super(_StatusPanelController, self).init()
            if self is None:
                return None
            self._callbacks: Dict[str, Callable] = callbacks or {}
            self._model = None
            self._status_item = None
            self._menu = None
            self._popover = NSPopover.alloc().init()
            self._popover.setBehavior_(NSPopoverBehaviorTransient)
            self._popover.setContentViewController_(NSViewController.alloc().init())
            return self

        # -- rendering ----------------------------------------------------- #

        @objc.python_method
        def _footer_spec(self, model):
            pro_label = (
                "Malinche PRO" if (model and model.pro_active) else "Activate PRO…"
            )
            return [
                ("Open logs", "doc.plaintext", "logsClicked:"),
                ("Settings", "gearshape", "settingsClicked:"),
                (pro_label, "sparkles", "proClicked:"),
                ("Quit", "power", "quitClicked:"),
            ]

        @objc.python_method
        def _render(self, model):
            """Build the content view for *model*; return (view, height)."""
            width = _PANEL_WIDTH
            inner = width - 2 * _PAD
            elements = []  # (subview,) added after we know total height
            cy = _PAD

            # Header: status symbol + title.
            sym_name = model.status_symbol if model else "waveform"
            header_symbol = self._icon_button(
                sym_name, NSMakeRect(_PAD, cy, 20, 20), point=16.0
            )
            elements.append(header_symbol)
            title = style.make_label("Malinche", style="title")
            if title is not None:
                title.setFrame_(NSMakeRect(_PAD + 28, cy - 1, inner - 28, 20))
                elements.append(title)
            cy += 22

            status_text = model.status_text if model else "…"
            status_label = style.make_label(
                status_text, style="caption", secondary=True
            )
            if status_label is not None:
                status_label.setFrame_(NSMakeRect(_PAD, cy, inner, 16))
                elements.append(status_label)
            cy += 16

            # Active row: file + indeterminate spinner.
            if model and model.active_row is not None:
                cy += 4
                elements.append(self._divider(cy, inner))
                cy += _ROW_GAP
                elements.append(
                    self._icon_button(
                        model.active_row.symbol,
                        NSMakeRect(_PAD, cy, 16, 16),
                        point=14.0,
                    )
                )
                file_label = style.make_label(model.active_row.title, style="caption")
                if file_label is not None:
                    file_label.setFrame_(NSMakeRect(_PAD + 22, cy, inner - 22 - 22, 16))
                    elements.append(file_label)
                spinner = NSProgressIndicator.alloc().initWithFrame_(
                    NSMakeRect(width - _PAD - 16, cy, 16, 16)
                )
                spinner.setStyle_(NSProgressIndicatorStyleSpinning)
                spinner.setIndeterminate_(True)
                spinner.startAnimation_(None)
                elements.append(spinner)
                cy += 22

            # Recent transcripts.
            recent = list(model.recent_rows) if model else []
            if recent:
                cy += 4
                elements.append(self._divider(cy, inner))
                cy += _ROW_GAP
                cap = style.make_label("Recent", style="caption", secondary=True)
                if cap is not None:
                    cap.setFrame_(NSMakeRect(_PAD, cy, inner, 14))
                    elements.append(cap)
                cy += 18
                for row in recent:
                    elements.append(
                        self._icon_button(
                            row.symbol or "doc.text",
                            NSMakeRect(_PAD, cy, 16, 16),
                            point=14.0,
                        )
                    )
                    lbl = style.make_label(row.title, style="caption")
                    if lbl is not None:
                        lbl.setFrame_(NSMakeRect(_PAD + 24, cy, inner - 24, 15))
                        elements.append(lbl)
                    cy += 20

            # Footer actions (full-width vertical rows).
            cy += 4
            elements.append(self._divider(cy, inner))
            cy += _ROW_GAP
            for label, symbol_name, action in self._footer_spec(model):
                btn = self._make_action_button(
                    label,
                    symbol_name,
                    NSMakeRect(_PAD, cy, inner, _BTN_H),
                    action,
                )
                elements.append(btn)
                cy += _BTN_H + _BTN_GAP
            cy = cy - _BTN_GAP + _PAD  # trim trailing gap, add bottom padding

            total_h = cy
            root = _FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, width, total_h))
            bg = style.vibrant_view(
                NSMakeRect(0, 0, width, total_h), material="popover"
            )
            if bg is not None:
                bg.setAutoresizingMask_(18)  # width + height sizable
                root.addSubview_(bg)
            for view in elements:
                root.addSubview_(view)
            return root, total_h

        @objc.python_method
        def _icon_button(self, symbol_name, frame, point=14.0):
            btn = NSButton.alloc().initWithFrame_(frame)
            btn.setBordered_(False)
            btn.setImagePosition_(2)  # image only
            btn.setEnabled_(False)
            img = style.sf_symbol(symbol_name, point=point)
            if img is not None:
                btn.setImage_(img)
            return btn

        @objc.python_method
        def _divider(self, y, width):
            box = NSBox.alloc().initWithFrame_(NSMakeRect(_PAD, y, width, 1))
            box.setBoxType_(NSBoxSeparator)
            return box

        @objc.python_method
        def _make_action_button(self, label, symbol_name, frame, action):
            # Borderless menu-style row with hover highlight: leading SF Symbol,
            # label tight beside it.
            from src.ui.hover import make_hover_button

            button = make_hover_button(frame) or NSButton.alloc().initWithFrame_(frame)
            button.setTitle_("  " + label)
            button.setBordered_(False)
            button.setAlignment_(0)  # left-aligned content
            font = style.system_font("body")
            if font is not None:
                button.setFont_(font)
            img = style.sf_symbol(symbol_name, point=14.0)
            if img is not None:
                button.setImage_(img)
                button.setImagePosition_(2)  # NSImageLeft — icon on the leading edge
            button.setTarget_(self)
            button.setAction_(action)
            return button

        # -- actions ------------------------------------------------------- #

        @objc.python_method
        def _invoke(self, key):
            self.close()
            cb = self._callbacks.get(key)
            if cb is not None:
                try:
                    cb(None)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.error("Panel action %s failed: %s", key, exc)

        def settingsClicked_(self, sender):
            self._invoke("settings")

        def quitClicked_(self, sender):
            self._invoke("quit")

        def logsClicked_(self, sender):
            self._invoke("logs")

        def proClicked_(self, sender):
            self._invoke("pro")

        # -- status-item wiring -------------------------------------------- #

        def installOnStatusItem_button_menu_(self, status_item, button, ns_menu):
            """Left-click → popover, right-click → the native menu (re-attached
            only for the duration of the right-click). Caller-guarded."""
            self._status_item = status_item
            self._menu = ns_menu
            status_item.setMenu_(None)
            button.setTarget_(self)
            button.setAction_("statusButtonClicked:")
            button.sendActionOn_(NSEventMaskLeftMouseDown | NSEventMaskRightMouseDown)

        def statusButtonClicked_(self, sender):
            event = NSApp.currentEvent()
            is_right = event is not None and (
                event.type() == NSEventTypeRightMouseDown
                or bool(event.modifierFlags() & NSEventModifierFlagControl)
            )
            if is_right and self._status_item is not None and self._menu is not None:
                self._status_item.setMenu_(self._menu)
                sender.performClick_(None)
                self._status_item.setMenu_(None)
            else:
                self.toggleRelativeTo_(sender)

        # -- public API ---------------------------------------------------- #

        def toggleRelativeTo_(self, button):
            if self._popover is None or button is None:
                return
            if self._popover.isShown():
                self._popover.close()
                return
            view, height = self._render(self._model)
            self._popover.contentViewController().setView_(view)
            self._popover.setContentSize_(NSMakeSize(_PANEL_WIDTH, height))
            self._popover.showRelativeToRect_ofView_preferredEdge_(
                button.bounds(), button, 1  # below
            )

        def close(self):
            if self._popover is not None and self._popover.isShown():
                self._popover.close()

        def update_(self, model):
            # Stored and rendered on next open (keeps the card fresh, no flicker).
            self._model = model


def build_status_panel(callbacks: Optional[Dict[str, Callable]] = None):
    """Create the panel controller, or ``None`` without AppKit.

    ``callbacks`` maps action keys (``settings``, ``logs``, ``pro``, ``quit``)
    to the menu-app handlers. Returned object exposes
    ``installOnStatusItem_button_menu_``, ``toggleRelativeTo_``, ``update_`` and
    ``close``.
    """
    if not _APPKIT_AVAILABLE:
        return None
    try:
        return _StatusPanelController.alloc().initWithCallbacks_(callbacks or {})
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Could not build status panel: %s", exc)
        return None
