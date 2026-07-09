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
from typing import Callable, Optional, Tuple

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
            self.accessory_action = None
            return self

        def primaryClicked_(self, sender):
            self._finish(1)

        def secondaryClicked_(self, sender):
            self._finish(0)

        def tertiaryClicked_(self, sender):
            self._finish(-1)

        def accessoryClicked_(self, sender):
            """Run the caller's accessory handler without dismissing the modal."""
            action = getattr(self, "accessory_action", None)
            if action is not None:
                try:
                    action()
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("Onboarding accessory action failed: %s", exc)

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
    accessory: Optional[Callable[[float, object], Tuple[object, float]]] = None,
    accessory_action: Optional[Callable[[], None]] = None,
) -> Optional[int]:
    """Show one onboarding screen modally. Returns 1/0/-1, or None without AppKit.

    ``accessory`` lets a step embed its own controls (folder picker, popups, a
    text field) between the body and the progress dots. It is called as
    ``accessory(content_width, delegate)`` and must return ``(view, height)``;
    the window grows to fit. Buttons inside the accessory can target the
    delegate's ``accessoryClicked:`` selector (the run-modal stays up) and the
    caller is notified through ``accessory_action``. The caller reads control
    values back from references it closed over once this returns.
    """
    if not _APPKIT_AVAILABLE:
        return None

    has_dots = bool(step_count and step_count > 1)
    content_width = _WIDTH - 2 * _PAD

    # The delegate exists before the accessory so embedded buttons can target
    # it; the window is wired in once its height is known.
    delegate = _OnboardingDelegate.alloc().initWithWindow_(None)
    delegate.accessory_action = accessory_action

    acc_view = None
    acc_h = 0.0
    if accessory is not None:
        acc_view, acc_h = accessory(content_width, delegate)

    # Top-down (flipped) layout. Compute every slot up front so the window can
    # be sized exactly before any subview is placed.
    body_h = 44.0 if acc_view is not None else 86.0
    cy = _PAD
    icon_y = cy
    cy += 84
    title_y = cy
    cy += 36
    body_y = cy
    cy += body_h + 10
    acc_y = None
    if acc_view is not None:
        acc_y = cy
        cy += acc_h + 16
    dots_y = None
    if has_dots:
        dots_y = cy
        cy += 24
    buttons_y = cy + 16
    height = buttons_y + 32 + _PAD

    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, _WIDTH, height),
        NSWindowStyleMaskTitled,
        NSBackingStoreBuffered,
        False,
    )
    win.setTitle_("Timshel Setup")
    win.center()
    win.setReleasedWhenClosed_(False)
    delegate.window = win

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

    icon = _app_icon()
    if icon is not None:
        iv = NSImageView.alloc().initWithFrame_(
            NSMakeRect((_WIDTH - 72) / 2, icon_y, 72, 72)
        )
        iv.setImage_(icon)
        content.addSubview_(iv)

    title_label = _label(title, "headline")
    title_label.setFrame_(NSMakeRect(_PAD, title_y, content_width, 28))
    content.addSubview_(title_label)

    body_label = _label(body, "body", secondary=True)
    body_label.setFrame_(NSMakeRect(_PAD, body_y, content_width, body_h))
    content.addSubview_(body_label)

    if acc_view is not None:
        acc_view.setFrame_(  # type: ignore[attr-defined]
            NSMakeRect(_PAD, acc_y, content_width, acc_h)
        )
        content.addSubview_(acc_view)

    if has_dots:
        dots, total_w = _progress_dots(step_index or 0, step_count)
        dots.setFrame_(NSMakeRect((_WIDTH - total_w) / 2, dots_y, total_w, 8))
        content.addSubview_(dots)

    def _button(label, action, x, width, accent=False):
        btn = NSButton.alloc().initWithFrame_(NSMakeRect(x, buttons_y, width, 32))
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
    _RETAINED.append((win, delegate, acc_view))

    win.makeKeyAndOrderFront_(None)
    NSApp.activateIgnoringOtherApps_(True)
    try:
        NSApp.runModalForWindow_(win)
    except Exception as exc:  # pragma: no cover
        logger.warning("Onboarding modal failed: %s", exc)
        return None
    return int(delegate.result)
