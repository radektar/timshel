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
        NSTrackingActiveAlways,
        NSTrackingArea,
        NSTrackingInVisibleRect,
        NSTrackingMouseEnteredAndExited,
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
        def initWithFrame_(self, frame):
            self = objc.super(_HoverButton, self).initWithFrame_(frame)
            if self is None:
                return None
            self.setWantsLayer_(True)
            self.layer().setCornerRadius_(6.0)
            self._selected = False
            return self

        def updateTrackingAreas(self):
            objc.super(_HoverButton, self).updateTrackingAreas()
            for area in list(self.trackingAreas()):
                self.removeTrackingArea_(area)
            area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
                self.bounds(), _HOVER_OPTS, self, None
            )
            self.addTrackingArea_(area)

        # Persistent selection (e.g. the active sidebar item). Hover paints over
        # it; leaving restores the selected fill instead of clearing it.
        def setSelected_(self, flag):
            self._selected = bool(flag)
            self._applyRestingBackground()

        @objc.python_method
        def _applyRestingBackground(self):
            if self._selected:
                colour = NSColor.selectedContentBackgroundColor().CGColor()
            else:
                colour = NSColor.clearColor().CGColor()
            self.layer().setBackgroundColor_(colour)

        def mouseEntered_(self, event):
            self.layer().setBackgroundColor_(
                NSColor.selectedContentBackgroundColor()
                .colorWithAlphaComponent_(0.5 if not self._selected else 1.0)
                .CGColor()
            )

        def mouseExited_(self, event):
            self._applyRestingBackground()

        def hitTest_(self, point):
            # The whole row is one click target; decorative icon/label children
            # must not swallow the click.
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
