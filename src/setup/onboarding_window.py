"""A styled, vibrant onboarding screen — replaces the wizard's plain alerts.

``show_onboarding_screen`` renders one step of the first-run flow as a modal
NSWindow with the app icon, a headline, body text, optional accessory controls,
progress dots and up to three buttons (primary tinted with the brand accent).
It returns which button was pressed (``1`` primary / ``0`` secondary /
``-1`` tertiary), matching ``rumps.alert``'s convention so callers can swap it
in directly.

AppKit-optional: returns ``None`` when AppKit is unavailable, so the wizard
falls back to its ``rumps.alert`` path. The modal uses the same crash-safe
teardown as the Settings window (``setReleasedWhenClosed_(False)`` + ``orderOut_``
+ a retain slot).

See ``Docs/UI-REDESIGN-L4-PLAN.md`` (phase 4).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.logger import logger

try:
    import objc
    from AppKit import (
        NSApp,
        NSBackingStoreBuffered,
        NSButton,
        NSColor,
        NSImage,
        NSImageView,
        NSMakeRect,
        NSObject,
        NSTextField,
        NSWindow,
        NSWindowStyleMaskTitled,
    )

    from src.ui import style

    _APPKIT_AVAILABLE = True
except Exception:  # pragma: no cover - non-mac
    _APPKIT_AVAILABLE = False


_WIDTH = 500.0
_PAD = 28.0
_RETAINED: list = []


if _APPKIT_AVAILABLE:

    from AppKit import NSView

    class _OnboardingContent(NSView):
        def isFlipped(self):
            return True

    class _OnboardingDelegate(NSObject):
        def initWithWindow_(self, window):
            self = objc.super(_OnboardingDelegate, self).init()
            if self is None:
                return None
            self.window = window
            self.result = 0
            return self

        def primaryClicked_(self, sender):
            self._finish(1)

        def secondaryClicked_(self, sender):
            self._finish(0)

        def tertiaryClicked_(self, sender):
            self._finish(-1)

        @objc.python_method
        def _finish(self, value):
            self.result = value
            try:
                NSApp.stopModal()
            except Exception:
                pass
            self.window.orderOut_(None)

    def _app_icon():
        """The app icon as an NSImage, or None."""
        for base in (
            Path(__file__).resolve().parent.parent.parent / "assets" / "icon.icns",
        ):
            if base.exists():
                img = NSImage.alloc().initWithContentsOfFile_(str(base))
                if img is not None:
                    return img
        return None

    def _label(text, font_style, secondary=False, center=True):
        field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        field.setStringValue_(text)
        field.setBezeled_(False)
        field.setDrawsBackground_(False)
        field.setEditable_(False)
        field.setSelectable_(False)
        field.cell().setWraps_(True)
        if center:
            field.setAlignment_(1)  # centre
        field.setTextColor_(
            NSColor.secondaryLabelColor() if secondary else NSColor.labelColor()
        )
        font = style.system_font(font_style)
        if font is not None:
            field.setFont_(font)
        return field

    def _progress_dots(step_index, step_count):
        """A centred row of dots; the current step is the accent colour."""
        dot = 7.0
        gap = 8.0
        total_w = step_count * dot + (step_count - 1) * gap
        container = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, total_w, dot))
        x = 0.0
        for i in range(step_count):
            d = NSView.alloc().initWithFrame_(NSMakeRect(x, 0, dot, dot))
            d.setWantsLayer_(True)
            layer = d.layer()
            layer.setCornerRadius_(dot / 2.0)
            on = i == step_index
            colour = style.accent_color() if on else NSColor.tertiaryLabelColor()
            if colour is not None:
                layer.setBackgroundColor_(colour.CGColor())
            container.addSubview_(d)
            x += dot + gap
        return container, total_w


def show_onboarding_screen(
    *,
    title: str,
    body: str,
    primary: str,
    secondary: Optional[str] = None,
    tertiary: Optional[str] = None,
    step_index: Optional[int] = None,
    step_count: Optional[int] = None,
) -> Optional[int]:
    """Show one onboarding screen modally. Returns 1/0/-1, or None without AppKit."""
    if not _APPKIT_AVAILABLE:
        return None

    # Measure a tall-enough window; content is laid out top-down (flipped).
    has_dots = bool(step_count and step_count > 1)
    height = _PAD + 84 + 16 + 30 + 12 + 90 + (24 if has_dots else 0) + 56 + _PAD
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, _WIDTH, height),
        NSWindowStyleMaskTitled,
        NSBackingStoreBuffered,
        False,
    )
    win.setTitle_("Malinche Setup")
    win.center()
    win.setReleasedWhenClosed_(False)

    root = style.vibrant_view(NSMakeRect(0, 0, _WIDTH, height), material="window")
    if root is None:
        root = _OnboardingContent.alloc().initWithFrame_(
            NSMakeRect(0, 0, _WIDTH, height)
        )
    win.setContentView_(root)

    content = _OnboardingContent.alloc().initWithFrame_(
        NSMakeRect(0, 0, _WIDTH, height)
    )
    content.setAutoresizingMask_(18)
    root.addSubview_(content)

    cy = _PAD
    icon = _app_icon()
    if icon is not None:
        iv = NSImageView.alloc().initWithFrame_(
            NSMakeRect((_WIDTH - 72) / 2, cy, 72, 72)
        )
        iv.setImage_(icon)
        content.addSubview_(iv)
    cy += 84

    title_label = _label(title, "headline")
    title_label.setFrame_(NSMakeRect(_PAD, cy, _WIDTH - 2 * _PAD, 28))
    content.addSubview_(title_label)
    cy += 36

    body_label = _label(body, "body", secondary=True)
    body_label.setFrame_(NSMakeRect(_PAD, cy, _WIDTH - 2 * _PAD, 86))
    content.addSubview_(body_label)
    cy += 96

    if has_dots:
        dots, total_w = _progress_dots(step_index or 0, step_count)
        dots.setFrame_(NSMakeRect((_WIDTH - total_w) / 2, cy, total_w, 8))
        content.addSubview_(dots)
        cy += 24

    delegate = _OnboardingDelegate.alloc().initWithWindow_(win)

    def _button(label, action, x, width, accent=False):
        btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(x, height - _PAD - 32, width, 32)
        )
        btn.setTitle_(label)
        btn.setBezelStyle_(1)
        if accent:
            btn.setKeyEquivalent_("\r")
            try:
                import AppKit

                btn.setControlSize_(AppKit.NSControlSizeLarge)
                btn.setBezelColor_(style.accent_color())
            except Exception:
                pass
        btn.setTarget_(delegate)
        btn.setAction_(action)
        content.addSubview_(btn)
        return btn

    right = _WIDTH - _PAD - 120
    _button(primary, "primaryClicked:", right, 120, accent=True)
    if secondary is not None:
        _button(secondary, "secondaryClicked:", right - 12 - 110, 110)
    if tertiary is not None:
        _button(tertiary, "tertiaryClicked:", _PAD, 110)

    _RETAINED.clear()
    _RETAINED.append((win, delegate))

    win.makeKeyAndOrderFront_(None)
    NSApp.activateIgnoringOtherApps_(True)
    try:
        NSApp.runModalForWindow_(win)
    except Exception as exc:  # pragma: no cover
        logger.warning("Onboarding modal failed: %s", exc)
        return None
    return int(delegate.result)
