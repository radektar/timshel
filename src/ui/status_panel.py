"""AppKit renderer for the menu-bar status panel (L4 phase 2b — render).

A click (left or right) on the status item opens this NSPopover — a vibrant card
showing the current status, the file being transcribed, recent transcripts, and
every action (import, re-transcribe, digest, logs, settings, quit) — instead of
the flat native menu. Both clicks open the same card; the native menu remains
only as the AppKit-less fallback, so nothing is lost.

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
        NSBox,
        NSBoxSeparator,
        NSButton,
        NSEventMaskLeftMouseDown,
        NSEventMaskRightMouseDown,
        NSImageView,
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
_TEXT_DX = 28.0  # text column: icons at _PAD, labels at _PAD + _TEXT_DX
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
            self._retranscribe_expanded = False
            self._popover = NSPopover.alloc().init()
            self._popover.setBehavior_(NSPopoverBehaviorTransient)
            self._popover.setContentViewController_(NSViewController.alloc().init())
            return self

        # -- rendering ----------------------------------------------------- #

        #: Sentinel label marking where the expandable re-transcribe block goes.
        _RETRANSCRIBE = "__retranscribe__"

        @objc.python_method
        def _footer_spec(self, model):
            return [
                ("Import audio…", "square.and.arrow.down", "importClicked:"),
                (self._RETRANSCRIBE, "arrow.triangle.2.circlepath", None),
                ("Open latest digest", "doc.append", "digestClicked:"),
                ("Generate digest now", "sparkles", "genDigestClicked:"),
                ("Open logs", "doc.plaintext", "logsClicked:"),
                ("Settings", "gearshape", "settingsClicked:"),
                ("Quit", "power", "quitClicked:"),
            ]

        @objc.python_method
        def _render(self, model):
            """Build the content view for *model*; return (view, height)."""
            width = _PANEL_WIDTH
            inner = width - 2 * _PAD
            elements = []  # (subview,) added after we know total height
            cy = _PAD

            # Header: icon (vertically centred) + stacked title / status, so the
            # status line sits directly under the name on the text column.
            header_h = 40.0
            text_x = _PAD + _TEXT_DX
            text_w = inner - _TEXT_DX
            sym_name = model.status_symbol if model else "waveform"
            header_symbol = self._icon_button(
                sym_name,
                NSMakeRect(_PAD, cy + (header_h - 18) / 2, 18, 18),
                point=17.0,
            )
            elements.append(header_symbol)
            title = style.make_label("Malinche", style="title")
            if title is not None:
                title.setFrame_(NSMakeRect(text_x, cy, text_w, 20))
                elements.append(title)
            status_text = model.status_text if model else "…"
            status_label = style.make_label(
                status_text, style="caption", secondary=True
            )
            if status_label is not None:
                status_label.setFrame_(NSMakeRect(text_x, cy + 21, text_w, 16))
                elements.append(status_label)
            cy += header_h

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
                    file_label.setFrame_(
                        NSMakeRect(_PAD + _TEXT_DX, cy, inner - _TEXT_DX - 22, 16)
                    )
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
                        lbl.setFrame_(
                            NSMakeRect(_PAD + _TEXT_DX, cy, inner - _TEXT_DX, 15)
                        )
                        elements.append(lbl)
                    cy += 20

            # Footer actions (full-width vertical rows).
            cy += 4
            elements.append(self._divider(cy, inner))
            cy += _ROW_GAP
            for label, symbol_name, action in self._footer_spec(model):
                if label == self._RETRANSCRIBE:
                    cy = self._render_retranscribe(model, elements, symbol_name, cy, inner)
                    continue
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
        def _make_action_button(
            self, label, symbol_name, frame, action,
            trailing_symbol=None, tag=None, label_style="body",
        ):
            # Menu-style row: full-width hover-highlight button as the click
            # target, with a separate icon (icon column) + label (text column)
            # so everything lines up on the same two-column grid as the header.
            # Optional trailing_symbol draws a chevron at the right edge (used by
            # the expandable re-transcribe row); tag lets a shared action map a
            # click back to a list index (the staged-file rows).
            from src.ui.hover import make_hover_button

            button = make_hover_button(frame) or NSButton.alloc().initWithFrame_(frame)
            button.setTitle_("")
            button.setBordered_(False)
            button.setTarget_(self)
            button.setAction_(action)
            if tag is not None:
                button.setTag_(tag)
            h = frame.size.height
            w = frame.size.width

            img = style.sf_symbol(symbol_name, point=14.0)
            if img is not None:
                icon = NSImageView.alloc().initWithFrame_(
                    NSMakeRect(0, (h - 16) / 2, 16, 16)
                )
                icon.setImage_(img)
                button.addSubview_(icon)

            trailing_w = 18 if trailing_symbol else 0
            lbl = style.make_label(label, style=label_style)
            if lbl is not None:
                lbl.setFrame_(
                    NSMakeRect(
                        _TEXT_DX, (h - 18) / 2, w - _TEXT_DX - trailing_w, 18
                    )
                )
                button.addSubview_(lbl)

            if trailing_symbol:
                chev = style.sf_symbol(trailing_symbol, point=11.0)
                if chev is not None:
                    cv = NSImageView.alloc().initWithFrame_(
                        NSMakeRect(w - 16, (h - 12) / 2, 12, 12)
                    )
                    cv.setImage_(chev)
                    button.addSubview_(cv)
            return button

        @objc.python_method
        def _render_retranscribe(self, model, elements, symbol_name, cy, inner):
            """Render the expandable 'Re-transcribe' row + its staged files.

            Collapsed: a single row with a disclosure chevron. Expanded: the
            staged audio files as indented, clickable rows (each re-transcribes
            that recording). Returns the new vertical cursor.
            """
            files = list(model.retranscribe_files) if model else []
            expanded = self._retranscribe_expanded and bool(files)
            chevron = "chevron.down" if expanded else "chevron.right"
            toggle = self._make_action_button(
                "Re-transcribe",
                symbol_name,
                NSMakeRect(_PAD, cy, inner, _BTN_H),
                "retranscribeToggleClicked:",
                trailing_symbol=(chevron if files else None),
            )
            elements.append(toggle)
            cy += _BTN_H + _BTN_GAP

            if not self._retranscribe_expanded:
                return cy

            if not files:
                cap = style.make_label(
                    "    No recordings to re-transcribe", style="caption",
                    secondary=True,
                )
                if cap is not None:
                    cap.setFrame_(NSMakeRect(_PAD + _TEXT_DX, cy, inner - _TEXT_DX, 16))
                    elements.append(cap)
                    cy += 20
                return cy

            indent = 14.0
            for i, name in enumerate(files):
                row = self._make_action_button(
                    name,
                    "waveform",
                    NSMakeRect(_PAD + indent, cy, inner - indent, _BTN_H - 4),
                    "retranscribeFileClicked:",
                    tag=i,
                    label_style="caption",
                )
                elements.append(row)
                cy += (_BTN_H - 4) + _BTN_GAP
            return cy

        # -- actions ------------------------------------------------------- #

        @objc.python_method
        def _invoke(self, key, arg=None):
            self.close()
            cb = self._callbacks.get(key)
            if cb is not None:
                try:
                    cb(arg)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.error("Panel action %s failed: %s", key, exc)

        def settingsClicked_(self, sender):
            self._invoke("settings")

        def quitClicked_(self, sender):
            self._invoke("quit")

        def logsClicked_(self, sender):
            self._invoke("logs")

        def importClicked_(self, sender):
            self._invoke("import")

        def digestClicked_(self, sender):
            self._invoke("digest")

        def genDigestClicked_(self, sender):
            self._invoke("genDigest")

        def retranscribeToggleClicked_(self, sender):
            # Expand/collapse the staged-file list in place (no close).
            self._retranscribe_expanded = not self._retranscribe_expanded
            self._rerender_in_place()

        def retranscribeFileClicked_(self, sender):
            files = list(self._model.retranscribe_files) if self._model else []
            idx = int(sender.tag())
            if 0 <= idx < len(files):
                self._invoke("retranscribe", files[idx])

        @objc.python_method
        def _rerender_in_place(self):
            if self._popover is None or not self._popover.isShown():
                return
            view, height = self._render(self._model)
            self._popover.contentViewController().setView_(view)
            self._popover.setContentSize_(NSMakeSize(_PANEL_WIDTH, height))

        # -- status-item wiring -------------------------------------------- #

        def installOnStatusItem_button_menu_(self, status_item, button, ns_menu):
            """Both left- and right-click open the same popover — it carries
            every action, so the native menu is no longer a separate surface.
            ``ns_menu`` is kept only for AppKit-less fallback. Caller-guarded."""
            self._status_item = status_item
            self._menu = ns_menu
            status_item.setMenu_(None)
            button.setTarget_(self)
            button.setAction_("statusButtonClicked:")
            button.sendActionOn_(NSEventMaskLeftMouseDown | NSEventMaskRightMouseDown)

        def statusButtonClicked_(self, sender):
            # One surface: any click toggles the panel.
            self.toggleRelativeTo_(sender)

        # -- public API ---------------------------------------------------- #

        def toggleRelativeTo_(self, button):
            if self._popover is None or button is None:
                return
            if self._popover.isShown():
                self._popover.close()
                return
            # Each fresh open starts with the re-transcribe list collapsed.
            self._retranscribe_expanded = False
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

    ``callbacks`` maps action keys (``settings``, ``logs``, ``import``,
    ``digest``, ``genDigest``, ``retranscribe``, ``quit``) to the menu-app
    handlers — ``retranscribe`` receives the staged file name. Returned object
    exposes
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
