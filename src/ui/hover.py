"""A reusable hover-highlighting button (macOS menu-row feel).

Borderless ``NSButton`` doesn't highlight on hover, which is what makes a custom
popover/sidebar feel inert next to a real ``NSMenu``. ``_HoverButton`` adds a
tracking area and paints a subtle rounded highlight on mouse-enter — used by the
status panel and the Settings sidebar.

Single ObjC class defined once here (class names are global in the ObjC runtime),
so both call sites share it without clashing. AppKit-optional: with no AppKit,
:func:`make_hover_button` returns ``None``.
"""

from __future__ import annotations

try:
    import objc
    from AppKit import (
        NSButton,
        NSColor,
        NSCursor,
        NSTrackingActiveAlways,
        NSTrackingArea,
        NSTrackingInVisibleRect,
        NSTrackingMouseEnteredAndExited,
        NSView,
        NSWindowBelow,
    )

    _APPKIT_AVAILABLE = True
except ImportError:  # pragma: no cover - non-mac
    _APPKIT_AVAILABLE = False


if _APPKIT_AVAILABLE:

    _HOVER_OPTS = (
        NSTrackingMouseEnteredAndExited
        | NSTrackingActiveAlways
        | NSTrackingInVisibleRect
    )

    class _HoverButton(NSButton):
        """A borderless row button that highlights on hover.

        Hover is painted as a non-destructive **wash overlay** inserted behind the
        row's content, so call sites that set their own resting background (the
        rail rows, the direction rows — terracotta tints) keep it; the old code
        stamped the layer background directly and clobbered those tints on exit.
        The wash is a brand-neutral white (the design's ``rgba(255,255,255,.04)``
        conn-item hover), not the system selection blue. Plus a pointing-hand
        cursor, so the row reads as clickable.
        """

        def initWithFrame_(self, frame):
            self = objc.super(_HoverButton, self).initWithFrame_(frame)
            if self is None:
                return None
            self.setWantsLayer_(True)
            self.layer().setCornerRadius_(6.0)
            self._selected = False
            self._wash = None
            return self

        def updateTrackingAreas(self):
            objc.super(_HoverButton, self).updateTrackingAreas()
            for area in list(self.trackingAreas()):
                self.removeTrackingArea_(area)
            area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
                self.bounds(), _HOVER_OPTS, self, None
            )
            self.addTrackingArea_(area)

        def resetCursorRects(self):
            self.addCursorRect_cursor_(self.bounds(), NSCursor.pointingHandCursor())

        # Persistent selection (e.g. the active sidebar item) — still painted on
        # the layer background; the wash composites on top of it on hover.
        def setSelected_(self, flag):
            self._selected = bool(flag)
            self._applyRestingBackground()

        @objc.python_method
        def _applyRestingBackground(self):
            colour = (
                NSColor.selectedContentBackgroundColor().CGColor()
                if self._selected
                else NSColor.clearColor().CGColor()
            )
            self.layer().setBackgroundColor_(colour)

        @objc.python_method
        def _ensure_wash(self):
            if self._wash is None:
                wash = NSView.alloc().initWithFrame_(self.bounds())
                wash.setWantsLayer_(True)
                wash.setAutoresizingMask_(2 | 16)  # width + height sizable
                if wash.layer() is not None and self.layer() is not None:
                    wash.layer().setCornerRadius_(self.layer().cornerRadius())
                self.addSubview_positioned_relativeTo_(wash, NSWindowBelow, None)
                self._wash = wash
            return self._wash

        def mouseEntered_(self, event):
            wash = self._ensure_wash()
            if wash.layer() is not None:
                alpha = 0.08 if self._selected else 0.05
                wash.layer().setBackgroundColor_(
                    NSColor.whiteColor().colorWithAlphaComponent_(alpha).CGColor()
                )

        def mouseExited_(self, event):
            if self._wash is not None and self._wash.layer() is not None:
                self._wash.layer().setBackgroundColor_(NSColor.clearColor().CGColor())

        def hitTest_(self, point):
            # The whole row is one click target; decorative icon/label children
            # (and the wash overlay) must not swallow the click.
            if objc.super(_HoverButton, self).hitTest_(point) is not None:
                return self
            return None


def make_hover_button(frame):
    """A borderless button that highlights on hover, or ``None`` without AppKit.

    The caller configures title/image/target/action as on any ``NSButton``.
    """
    if not _APPKIT_AVAILABLE:
        return None
    return _HoverButton.alloc().initWithFrame_(frame)
