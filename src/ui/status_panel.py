"""AppKit renderer for the menu-bar status panel (L4 phase 2b — render).

A left-click on the status item opens this NSPopover — a small vibrant card with
the current status and quick actions — instead of the flat native menu. The
right-click menu is kept for the full action list, so nothing is lost.

The card's *content* is derived from the pure :class:`~src.ui.status_panel_model.PanelModel`
(tested separately); this module is the thin AppKit layer that draws it. It is
AppKit-optional: with no AppKit, :func:`build_status_panel` returns ``None`` and
the caller keeps the native menu.

v1 deliberately renders the header + Settings/Quit footer to prove the popover
plumbing; the recent-list and live progress row (already in the view-model) are
layered on once the mechanism is confirmed. See ``Docs/UI-REDESIGN-L4-PLAN.md``.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from src.logger import logger
from src.ui import style

try:
    import objc
    from AppKit import (
        NSApp,
        NSButton,
        NSEventMaskLeftMouseDown,
        NSEventMaskRightMouseDown,
        NSEventModifierFlagControl,
        NSEventTypeRightMouseDown,
        NSMakeRect,
        NSMakeSize,
        NSPopover,
        NSPopoverBehaviorTransient,
        NSView,
        NSViewController,
    )
    from Foundation import NSObject

    _APPKIT_AVAILABLE = True
except ImportError:  # pragma: no cover - non-mac
    _APPKIT_AVAILABLE = False


_PANEL_WIDTH = 300.0
_PAD = float(style.SPACE_PADDING)
_GAP = float(style.SPACE_CONTROL)


if _APPKIT_AVAILABLE:

    class _StatusPanelController(NSObject):
        """Owns the NSPopover and routes button clicks to Python callbacks."""

        def initWithCallbacks_(self, callbacks):
            self = objc.super(_StatusPanelController, self).init()
            if self is None:
                return None
            self._callbacks: Dict[str, Callable] = callbacks or {}
            self._popover = None
            self._status_label = None
            self._symbol_view = None
            self._status_item = None
            self._menu = None
            self._build_popover()
            return self

        # -- construction -------------------------------------------------- #

        @objc.python_method
        def _build_popover(self):
            # Vertical, full-width action rows under the header.
            header_h = 44.0
            btn_h = 30.0
            btn_gap = float(style.SPACE_TIGHT)
            footer_h = 2 * btn_h + btn_gap
            total_h = _PAD + header_h + _GAP + footer_h + _PAD

            root = style.vibrant_view(
                NSMakeRect(0, 0, _PANEL_WIDTH, total_h), material="popover"
            ) or NSView.alloc().initWithFrame_(NSMakeRect(0, 0, _PANEL_WIDTH, total_h))

            # Header: SF status symbol + title, with the status line below.
            symbol = NSButton.alloc().initWithFrame_(
                NSMakeRect(_PAD, total_h - _PAD - 24, 24, 24)
            )
            symbol.setBordered_(False)
            symbol.setImagePosition_(2)  # NSImageOnly
            symbol.setEnabled_(False)
            self._symbol_view = symbol
            root.addSubview_(symbol)

            title = style.make_label("Malinche", style="title")
            if title is not None:
                title.setFrame_(NSMakeRect(_PAD + 32, total_h - _PAD - 24, 200, 22))
                root.addSubview_(title)

            status = style.make_label("Status: …", style="caption", secondary=True)
            if status is not None:
                status.setFrame_(
                    NSMakeRect(_PAD, total_h - _PAD - 44, _PANEL_WIDTH - 2 * _PAD, 18)
                )
                self._status_label = status
                root.addSubview_(status)

            # Footer: full-width rows, stacked vertically (Settings on top).
            btn_w = _PANEL_WIDTH - 2 * _PAD
            settings_btn = self._make_action_button(
                "Settings",
                "gearshape",
                NSMakeRect(_PAD, _PAD + btn_h + btn_gap, btn_w, btn_h),
                "settingsClicked:",
            )
            root.addSubview_(settings_btn)
            quit_btn = self._make_action_button(
                "Quit",
                "power",
                NSMakeRect(_PAD, _PAD, btn_w, btn_h),
                "quitClicked:",
            )
            root.addSubview_(quit_btn)

            controller = NSViewController.alloc().init()
            controller.setView_(root)

            popover = NSPopover.alloc().init()
            popover.setContentViewController_(controller)
            popover.setContentSize_(NSMakeSize(_PANEL_WIDTH, total_h))
            popover.setBehavior_(NSPopoverBehaviorTransient)
            self._popover = popover

        @objc.python_method
        def _make_action_button(self, label, symbol_name, frame, action):
            button = NSButton.alloc().initWithFrame_(frame)
            button.setTitle_(label)
            button.setBezelStyle_(1)  # rounded
            button.setAlignment_(0)  # NSTextAlignmentLeft — left-aligned content
            img = style.sf_symbol(symbol_name, point=12.0)
            if img is not None:
                button.setImage_(img)
                button.setImagePosition_(3)  # NSImageLeft
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

        # -- public API ---------------------------------------------------- #

        def installOnStatusItem_button_menu_(self, status_item, button, ns_menu):
            """Wire the status-item button: left-click → popover, right → menu.

            The native menu is detached so the button's action fires on click;
            it is re-attached only for the duration of a right-click so the full
            menu still works. All guarded by the caller — on any failure the menu
            stays attached and behaviour is unchanged.
            """
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
                # Temporarily re-attach the menu so a right-click pops it.
                self._status_item.setMenu_(self._menu)
                sender.performClick_(None)
                self._status_item.setMenu_(None)
            else:
                self.toggleRelativeTo_(sender)

        def toggleRelativeTo_(self, button):
            if self._popover is None or button is None:
                return
            if self._popover.isShown():
                self._popover.close()
            else:
                self._popover.showRelativeToRect_ofView_preferredEdge_(
                    button.bounds(), button, 1  # NSRectEdgeMinY (below)
                )

        def close(self):
            if self._popover is not None and self._popover.isShown():
                self._popover.close()

        def update_(self, model):
            if model is None:
                return
            if self._status_label is not None:
                self._status_label.setStringValue_(model.status_text)
            if self._symbol_view is not None:
                img = style.sf_symbol(model.status_symbol, point=16.0)
                if img is not None:
                    self._symbol_view.setImage_(img)


def build_status_panel(callbacks: Optional[Dict[str, Callable]] = None):
    """Create the panel controller, or ``None`` without AppKit.

    ``callbacks`` maps action keys (``settings``, ``quit``) to the menu-app
    handlers. The returned object exposes ``toggleRelativeTo_(button)``,
    ``update_(model)`` and ``close()``.
    """
    if not _APPKIT_AVAILABLE:
        return None
    try:
        return _StatusPanelController.alloc().initWithCallbacks_(callbacks or {})
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Could not build status panel: %s", exc)
        return None
