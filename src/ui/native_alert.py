"""A crash-safe replacement for ``rumps.alert`` (macOS 26 fix).

rumps 0.4.0 builds alerts through
``NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_…`` —
a factory deprecated since macOS 10.10 that returns an *autoreleased* alert —
and force-sets the retired ``NSAppearanceNameVibrantDark`` appearance. On
macOS 26 (Tahoe) that combination over-releases: both tester crash reports
(2026-07-16) show ``SIGSEGV`` in ``objc_release`` during the main run loop's
autorelease-pool drain, seconds after a rumps alert was dismissed.

:func:`alert` is signature-compatible with ``rumps.alert`` (same kwargs, same
1 / 0 / -1 return convention) but uses the modern ``NSAlert.alloc().init()`` +
``addButtonWithTitle_`` API and lets the system pick the appearance. It also
activates the app first, so the default button renders with the accent colour
instead of the inactive grey the tester reported.

:func:`install` swaps it into ``rumps.alert`` at one choke point — every one
of the ~70 existing call sites (menu_app, wizard, settings, dialogs) is fixed
without touching them, and tests that monkeypatch ``rumps.alert`` keep
working exactly as before.
"""

from __future__ import annotations

from src.logger import logger

#: NSModalResponse for the Nth ``addButtonWithTitle_`` button (AppKit).
_FIRST_BUTTON = 1000

#: rumps.alert return convention, by button position (ok, cancel, other).
_POSITION_CODES = (1, 0, -1)


def map_response(modal_response: int) -> int:
    """Map an ``NSAlert.runModal()`` code to the rumps 1 / 0 / -1 convention.

    Buttons are added in (ok, cancel, other) order, so 1000 → 1 (ok),
    1001 → 0 (cancel), 1002 → -1 (other). Unknown codes pass through so a
    caller comparing ``response == 1`` still fails safe.
    """
    index = int(modal_response) - _FIRST_BUTTON
    if 0 <= index < len(_POSITION_CODES):
        return _POSITION_CODES[index]
    return int(modal_response)


def alert(title=None, message="", ok=None, cancel=None, other=None, icon_path=None):
    """Drop-in ``rumps.alert`` on the modern NSAlert API. Returns 1 / 0 / -1."""
    from AppKit import NSAlert, NSAlertStyleInformational, NSApp, NSImage

    panel = NSAlert.alloc().init()
    panel.setMessageText_(str(title) if title is not None else "")
    panel.setInformativeText_(str(message))
    panel.setAlertStyle_(NSAlertStyleInformational)
    panel.addButtonWithTitle_(str(ok) if ok is not None else "OK")
    if cancel:
        panel.addButtonWithTitle_(cancel if isinstance(cancel, str) else "Cancel")
    if other:
        panel.addButtonWithTitle_(str(other))
    if icon_path:
        try:
            icon = NSImage.alloc().initByReferencingFile_(str(icon_path))
            if icon is not None:
                panel.setIcon_(icon)
        except Exception:  # pragma: no cover - cosmetic
            pass
    # Without key-window status the default button loses its accent and the
    # whole row renders inactive-grey — activate before running the modal.
    try:
        NSApp.activateIgnoringOtherApps_(True)
    except Exception:  # pragma: no cover - cosmetic
        pass
    return map_response(panel.runModal())


def install() -> bool:
    """Replace ``rumps.alert`` with :func:`alert`. True when installed."""
    try:
        import AppKit  # noqa: F401 — only patch where the fix can actually run
        import rumps
    except Exception as exc:  # pragma: no cover - non-mac / headless
        logger.debug("native_alert not installed: %s", exc)
        return False
    rumps.alert = alert
    logger.debug("native_alert installed over rumps.alert")
    return True
