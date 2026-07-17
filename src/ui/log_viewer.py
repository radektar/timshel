"""Native log viewer window: newest-first list with level filter, search, live tail.

The viewer reads the chronological log file but displays entries in reverse
order so the most recent activity is on top. A 1-second NSTimer polls the file
mtime to pick up newly appended lines without reloading the whole file.

The parsing layer (`LogEntry`, `parse_lines`, `read_recent`) is pure Python and
testable without AppKit. The window class falls back to a no-op when AppKit is
unavailable (e.g. headless test environments).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from src.logger import logger


# Matches the format produced by `src/logger.py`:
#   2026-05-05 08:29:12 - timshel - INFO - message
# Multi-line tracebacks: subsequent lines do NOT match and are appended to the
# previous entry's message (handled by parse_lines).
LOG_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - "
    r"(?P<name>\S+) - "
    r"(?P<level>\w+) - "
    r"(?P<msg>.*)$"
)

LEVEL_RANK = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


@dataclass
class LogEntry:
    timestamp: str
    name: str
    level: str
    message: str

    def matches_level(self, min_level: str) -> bool:
        return LEVEL_RANK.get(self.level, 0) >= LEVEL_RANK.get(min_level, 0)

    def matches_search(self, needle: str) -> bool:
        if not needle:
            return True
        n = needle.lower()
        return n in self.message.lower() or n in self.timestamp.lower()


def parse_lines(lines: Iterable[str]) -> List[LogEntry]:
    """Convert raw log lines into LogEntry list. Continuations append to last."""
    entries: List[LogEntry] = []
    for raw in lines:
        line = raw.rstrip("\n")
        m = LOG_LINE_RE.match(line)
        if m:
            entries.append(
                LogEntry(
                    timestamp=m.group("ts"),
                    name=m.group("name"),
                    level=m.group("level").upper(),
                    message=m.group("msg"),
                )
            )
        elif entries:
            # Multi-line continuation (traceback, embedded newlines)
            entries[-1].message = entries[-1].message + "\n" + line
        # Lines before any timestamped entry are dropped silently.
    return entries


# Bytes read from the tail of the log per refresh. The viewer's 1 s timer
# re-reads whenever the file grew (whisper -pp heartbeats touch it every few
# seconds during a long transcription), so an unbounded readlines() re-read the
# whole file — up to the 5 MB rotation cap — every second. A fixed tail window
# bounds each read regardless of file size and still holds far more than the
# ~5000 displayed entries.
_TAIL_BYTES = 1_048_576  # 1 MiB


def read_recent(path: Path, max_entries: int = 5000) -> List[LogEntry]:
    """Read up to ``max_entries`` newest entries from the log file's tail."""
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        with path.open("rb") as fb:
            if size > _TAIL_BYTES:
                fb.seek(size - _TAIL_BYTES)
                raw = fb.read()
                # Drop the first (probably partial) line after the seek.
                nl = raw.find(b"\n")
                if nl != -1:
                    raw = raw[nl + 1:]
            else:
                raw = fb.read()
        text = raw.decode("utf-8", errors="replace")
    except OSError as exc:
        logger.warning("log_viewer: cannot read %s: %s", path, exc)
        return []

    lines = text.splitlines(keepends=True)
    # Tail: keep last ~max_entries*2 raw lines (multi-line entries collapse).
    tail_lines = lines[-(max_entries * 2):] if len(lines) > max_entries * 2 else lines
    entries = parse_lines(tail_lines)
    if len(entries) > max_entries:
        entries = entries[-max_entries:]
    return entries


# --------------------------------------------------------------------------
# Native window (best-effort; no-op without AppKit)
# --------------------------------------------------------------------------

try:
    import objc  # type: ignore
    from AppKit import (
        NSApp,
        NSWindow,
        NSWindowStyleMaskTitled,
        NSWindowStyleMaskClosable,
        NSWindowStyleMaskResizable,
        NSWindowStyleMaskMiniaturizable,
        NSBackingStoreBuffered,
        NSScrollView,
        NSTextView,
        NSPopUpButton,
        NSSearchField,
        NSButton,
        NSTextField,
        NSFont,
        NSColor,
        NSAttributedString,
        NSMutableAttributedString,
        NSForegroundColorAttributeName,
        NSFontAttributeName,
        NSTimer,
        NSObject,
    )
    from Foundation import NSMakeRange, NSMakeRect
    _APPKIT_AVAILABLE = True
except ImportError:
    _APPKIT_AVAILABLE = False


_active_viewers: List["LogViewerWindow"] = []


class LogViewerWindow:
    """Native NSWindow showing recent log entries newest-first."""

    LEVEL_OPTIONS = ("All", "INFO+", "WARNING+", "ERROR")
    LEVEL_TO_MIN = {"All": "DEBUG", "INFO+": "INFO", "WARNING+": "WARNING", "ERROR": "ERROR"}

    def __init__(self, log_path: Path):
        self.log_path = Path(log_path)
        self.entries: List[LogEntry] = []
        self._mtime: float = 0.0
        self._min_level = "DEBUG"
        self._search = ""
        # AppKit handles
        self._window = None
        self._text_view = None
        self._popup = None
        self._search_field = None
        self._timer = None
        self._delegate = None  # NSObject subclass instance, retained

    # -- Public API ---------------------------------------------------------

    def show(self) -> None:
        if not _APPKIT_AVAILABLE:
            logger.info("log_viewer: AppKit unavailable, skipping window")
            return
        self._build_window()
        self._reload_from_file()
        self._render()
        self._start_timer()
        self._window.makeKeyAndOrderFront_(None)
        try:
            NSApp.activateIgnoringOtherApps_(True)
        except Exception:
            pass
        _active_viewers.append(self)

    def close(self) -> None:
        if self._timer is not None:
            try:
                self._timer.invalidate()
            except Exception:
                pass
            self._timer = None
        if self._window is not None:
            try:
                self._window.close()
            except Exception:
                pass
        if self in _active_viewers:
            _active_viewers.remove(self)

    # -- Build --------------------------------------------------------------

    def _build_window(self) -> None:
        style = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskResizable
            | NSWindowStyleMaskMiniaturizable
        )
        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 760, 520),
            style,
            NSBackingStoreBuffered,
            False,
        )
        # Crash-safe teardown: without this, close() deallocates the window
        # while the PyObjC proxy still owns a retain (release-on-deallocated
        # SIGSEGV — the DownloadWindow bug, same mechanism).
        self._window.setReleasedWhenClosed_(False)
        self._window.setTitle_("Timshel logs")
        self._window.center()

        content = self._window.contentView()

        # Toolbar row at top: level popup + search field + clear button
        toolbar_y = 480
        self._popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(16, toolbar_y, 130, 26),
            False,
        )
        for opt in self.LEVEL_OPTIONS:
            self._popup.addItemWithTitle_(opt)
        self._popup.selectItemAtIndex_(0)
        content.addSubview_(self._popup)

        self._search_field = NSSearchField.alloc().initWithFrame_(
            NSMakeRect(156, toolbar_y, 480, 26)
        )
        self._search_field.setPlaceholderString_("Filter messages…")
        content.addSubview_(self._search_field)

        clear_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(648, toolbar_y, 96, 26)
        )
        clear_btn.setTitle_("Clear filter")
        clear_btn.setBezelStyle_(1)  # NSBezelStyleRounded
        content.addSubview_(clear_btn)

        # Status label below toolbar (entry count + path)
        self._status_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(16, 452, 728, 18)
        )
        self._status_label.setBezeled_(False)
        self._status_label.setDrawsBackground_(False)
        self._status_label.setEditable_(False)
        self._status_label.setSelectable_(True)
        self._status_label.setStringValue_("Loading…")
        content.addSubview_(self._status_label)

        # Scrollable text view (newest-first content)
        scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(16, 16, 728, 428)
        )
        scroll.setHasVerticalScroller_(True)
        scroll.setHasHorizontalScroller_(False)
        scroll.setAutohidesScrollers_(False)
        scroll.setBorderType_(2)  # NSBezelBorder

        self._text_view = NSTextView.alloc().initWithFrame_(
            NSMakeRect(0, 0, 712, 428)
        )
        self._text_view.setEditable_(False)
        self._text_view.setRichText_(True)
        self._text_view.setFont_(NSFont.userFixedPitchFontOfSize_(11.0))
        self._text_view.setVerticallyResizable_(True)
        self._text_view.setHorizontallyResizable_(False)
        scroll.setDocumentView_(self._text_view)
        content.addSubview_(scroll)

        # Wire control actions via dynamic NSObject subclass
        self._delegate = _LogViewerDelegate.alloc().init()
        self._delegate.viewer = self  # weakref-ish; we keep delegate alive too
        self._popup.setTarget_(self._delegate)
        self._popup.setAction_("popupChanged:")
        self._search_field.setTarget_(self._delegate)
        self._search_field.setAction_("searchChanged:")
        clear_btn.setTarget_(self._delegate)
        clear_btn.setAction_("clearClicked:")

    # -- Data flow ----------------------------------------------------------

    def _reload_from_file(self) -> None:
        try:
            self._mtime = self.log_path.stat().st_mtime if self.log_path.exists() else 0.0
        except OSError:
            self._mtime = 0.0
        self.entries = read_recent(self.log_path, max_entries=5000)

    def _render(self) -> None:
        if self._text_view is None:
            return
        filtered = [
            e for e in self.entries
            if e.matches_level(self._min_level) and e.matches_search(self._search)
        ]
        # newest first
        filtered = list(reversed(filtered))

        attr = NSMutableAttributedString.alloc().init()
        mono = NSFont.userFixedPitchFontOfSize_(11.0)
        for entry in filtered:
            color = self._color_for_level(entry.level)
            line = f"{entry.timestamp}  {entry.level:<8}  {entry.message}\n"
            piece = NSAttributedString.alloc().initWithString_attributes_(
                line,
                {NSForegroundColorAttributeName: color, NSFontAttributeName: mono},
            )
            attr.appendAttributedString_(piece)

        self._text_view.textStorage().setAttributedString_(attr)
        self._status_label.setStringValue_(
            f"{len(filtered)} of {len(self.entries)} entries  •  {self.log_path}"
        )
        # Scroll to top so newest stays in view
        self._text_view.scrollRangeToVisible_(NSMakeRange(0, 0))

    def _color_for_level(self, level: str):
        # Deferred import: theme uses NSColor too, but we keep direct refs here
        # so the module remains importable on platforms without theme niceties.
        try:
            from src.ui import theme
            if level == "ERROR" or level == "CRITICAL":
                return NSColor.systemRedColor()
            if level == "WARNING":
                return theme.terracotta() or NSColor.systemOrangeColor()
            if level == "DEBUG":
                return NSColor.secondaryLabelColor()
            return NSColor.labelColor()
        except Exception:
            return NSColor.labelColor()

    # -- Live tail ----------------------------------------------------------

    def _start_timer(self) -> None:
        if self._delegate is None:
            return
        self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0, self._delegate, "tick:", None, True
        )

    def _on_tick(self) -> None:
        if not self.log_path.exists():
            return
        try:
            mtime = self.log_path.stat().st_mtime
        except OSError:
            return
        if mtime == self._mtime:
            return
        # File grew — reload tail and re-render.
        self._reload_from_file()
        self._render()

    # -- Filter changes -----------------------------------------------------

    def _on_popup_changed(self, title: str) -> None:
        self._min_level = self.LEVEL_TO_MIN.get(title, "DEBUG")
        self._render()

    def _on_search_changed(self, value: str) -> None:
        self._search = value
        self._render()

    def _on_clear(self) -> None:
        self._min_level = "DEBUG"
        self._search = ""
        if self._popup is not None:
            self._popup.selectItemAtIndex_(0)
        if self._search_field is not None:
            self._search_field.setStringValue_("")
        self._render()


# AppKit forwarding delegate. Defined at module load only if AppKit is present
# so import works on test/CI machines.
if _APPKIT_AVAILABLE:

    class _LogViewerDelegate(NSObject):
        def init(self):
            self = objc.super(_LogViewerDelegate, self).init()
            if self is None:
                return None
            self.viewer = None
            return self

        def popupChanged_(self, sender):
            if self.viewer is None:
                return
            title = sender.titleOfSelectedItem()
            self.viewer._on_popup_changed(str(title) if title else "All")

        def searchChanged_(self, sender):
            if self.viewer is None:
                return
            value = sender.stringValue()
            self.viewer._on_search_changed(str(value) if value else "")

        def clearClicked_(self, sender):
            if self.viewer is None:
                return
            self.viewer._on_clear()

        def tick_(self, _timer):
            if self.viewer is None:
                return
            self.viewer._on_tick()


def show_log_viewer(log_path: Path) -> Optional[LogViewerWindow]:
    """Open the log viewer window. Returns the controller (or None on fallback)."""
    if not _APPKIT_AVAILABLE:
        logger.info("log_viewer: AppKit unavailable; cannot show viewer")
        return None
    viewer = LogViewerWindow(log_path)
    viewer.show()
    return viewer
