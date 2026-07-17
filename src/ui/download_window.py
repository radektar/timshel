"""Native download progress window for dependency downloads."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class DownloadWindowState:
    """Simple state container used by wizard/menu."""

    title: str
    detail: str
    progress: float = 0.0
    closed: bool = False


class DownloadWindow:
    """Best-effort native progress window.

    All AppKit mutations are dispatched to the main thread because download
    callbacks arrive from a background worker. Falls back to a no-op
    (state-only) window when AppKit is unavailable (e.g. in unit tests).
    """

    def __init__(self, title: str, detail: str):
        self.state = DownloadWindowState(title=title, detail=detail)
        self._appkit = None
        self._window = None
        self._label = None
        self._progress = None
        try:
            from AppKit import (
                NSWindow,
                NSWindowStyleMaskTitled,
                NSWindowStyleMaskClosable,
                NSTextField,
                NSProgressIndicator,
                NSBackingStoreBuffered,
                NSOperationQueue,
            )
            from Foundation import NSMakeRect

            self._appkit = {
                "NSWindow": NSWindow,
                "NSWindowStyleMaskTitled": NSWindowStyleMaskTitled,
                "NSWindowStyleMaskClosable": NSWindowStyleMaskClosable,
                "NSMakeRect": NSMakeRect,
                "NSTextField": NSTextField,
                "NSProgressIndicator": NSProgressIndicator,
                "NSBackingStoreBuffered": NSBackingStoreBuffered,
                "NSOperationQueue": NSOperationQueue,
            }
        except ImportError:
            self._appkit = None

    def _run_on_main(self, block: Callable[[], None]) -> None:
        """Schedule UI work on the main thread.

        NSWindow / NSTextField / NSProgressIndicator are not thread-safe;
        calling them from a worker thread can crash the app.
        """
        if not self._appkit:
            block()
            return
        try:
            self._appkit["NSOperationQueue"].mainQueue().addOperationWithBlock_(block)
        except Exception:
            block()

    def show(self) -> None:
        if not self._appkit:
            return

        def _build():
            NSWindow = self._appkit["NSWindow"]
            NSMakeRect = self._appkit["NSMakeRect"]
            NSTextField = self._appkit["NSTextField"]
            NSProgressIndicator = self._appkit["NSProgressIndicator"]
            style = (
                self._appkit["NSWindowStyleMaskTitled"]
                | self._appkit["NSWindowStyleMaskClosable"]
            )

            self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, 460, 140),
                style,
                self._appkit["NSBackingStoreBuffered"],
                False,
            )
            # Crash-safe teardown (same pattern as the Settings/onboarding
            # windows): titled NSWindows default to releasedWhenClosed=YES, so
            # close() deallocates the window while the PyObjC proxy still owns
            # a retain it sends on GC — release-to-deallocated-instance, the
            # SIGSEGV every tester hit seconds after the download finished.
            self._window.setReleasedWhenClosed_(False)
            self._window.setTitle_(self.state.title)

            content = self._window.contentView()
            self._label = NSTextField.alloc().initWithFrame_(
                NSMakeRect(20, 80, 420, 40)
            )
            self._label.setStringValue_(self.state.detail)
            self._label.setBezeled_(False)
            self._label.setDrawsBackground_(False)
            self._label.setEditable_(False)
            self._label.setSelectable_(False)
            content.addSubview_(self._label)

            self._progress = NSProgressIndicator.alloc().initWithFrame_(
                NSMakeRect(20, 40, 420, 20)
            )
            self._progress.setIndeterminate_(False)
            self._progress.setMinValue_(0.0)
            self._progress.setMaxValue_(100.0)
            self._progress.setDoubleValue_(self.state.progress * 100.0)
            content.addSubview_(self._progress)
            self._window.makeKeyAndOrderFront_(None)

        self._run_on_main(_build)

    def update(
        self, detail: Optional[str] = None, progress: Optional[float] = None
    ) -> None:
        if detail is not None:
            self.state.detail = detail
        if progress is not None:
            self.state.progress = max(0.0, min(1.0, progress))

        def _apply():
            if self._label is not None:
                self._label.setStringValue_(self.state.detail)
            if self._progress is not None:
                self._progress.setDoubleValue_(self.state.progress * 100.0)

        self._run_on_main(_apply)

    def close(self) -> None:
        if self.state.closed:
            return
        self.state.closed = True
        window = self._window
        self._window = None

        def _close():
            if window is not None:
                try:
                    window.orderOut_(None)
                except Exception:
                    pass

        self._run_on_main(_close)

    def close_after(self, delay_seconds: float) -> None:
        """Keep the current state visible for `delay_seconds`, then close.

        Intended to be called from a worker thread after a successful
        download so the user briefly sees the final "done" state before the
        window disappears.
        """
        if self.state.closed:
            return

        def _delayed():
            try:
                time.sleep(max(0.0, delay_seconds))
            finally:
                self.close()

        threading.Thread(target=_delayed, daemon=True).start()
