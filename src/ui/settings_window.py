"""Settings window with 4 tabs: General / Transcription / Disks / Maintenance.

External API kept stable: ``show_settings_window(callbacks=None) -> bool``.
The optional ``callbacks`` dict allows the Disks and Maintenance tabs to
trigger actions that live on ``MalincheMenuApp`` (reset memory, repair
whisper-cli, open log viewer, review mounted volumes, etc.). When called
without callbacks, those buttons are disabled.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional

import rumps

from src.config import UserSettings, SUPPORTED_LANGUAGES, SUPPORTED_MODELS
from src.config.settings import TrustedVolume
from src.logger import logger
from src.setup.dependency_manager import DependencyManager
from src.ui.constants import TEXTS
from src.ui.dialogs import choose_folder_dialog
from src.vault_index import is_icloud_synced

# UI constants
_API_KEY_PLACEHOLDER = "—"
_WINDOW_SIZE = (760, 520)
_SIDEBAR_W = 190
_PANE_PAD = 20
_CARD_INSET = 14
_ROW_H = 44
_BUTTON_W, _BUTTON_H = 96, 28


def _content_width() -> int:
    """Usable width of the content pane (right of the sidebar)."""
    return _WINDOW_SIZE[0] - _SIDEBAR_W - 2 * _PANE_PAD


try:
    from AppKit import NSView as _NSViewBase

    class _SettingsFlippedView(_NSViewBase):
        """Top-left origin so cards/rows lay out top-to-bottom."""

        def isFlipped(self):
            return True

    _FLIPPED_AVAILABLE = True
except Exception:  # pragma: no cover - non-mac
    _SettingsFlippedView = None  # type: ignore[assignment]
    _FLIPPED_AVAILABLE = False


def _rounded_card(width, height):
    """A layer-backed rounded 'card' container (flipped), macOS-settings style."""
    from AppKit import NSColor
    from Foundation import NSMakeRect

    card = _SettingsFlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
    card.setWantsLayer_(True)
    layer = card.layer()
    layer.setCornerRadius_(10.0)
    layer.setBackgroundColor_(
        NSColor.controlBackgroundColor().colorWithAlphaComponent_(0.6).CGColor()
    )
    layer.setBorderWidth_(1.0)
    layer.setBorderColor_(NSColor.separatorColor().CGColor())
    return card


def _field_label(text):
    """A right-aligned secondary field label (leading column of a card row)."""
    from src.ui import style

    label = style.make_label(text, style="body", secondary=True)
    if label is not None:
        label.setAlignment_(2)  # NSTextAlignmentRight
    return label


def _card_separator(width, y):
    from AppKit import NSColor
    from Foundation import NSMakeRect

    line = _SettingsFlippedView.alloc().initWithFrame_(NSMakeRect(0, y, width, 1))
    line.setWantsLayer_(True)
    line.layer().setBackgroundColor_(NSColor.separatorColor().CGColor())
    return line


def _build_card(rows):
    """Assemble a card from *rows* and return ``(card_view, height)``.

    Each row is a dict with ``height`` and a ``place(card, width, y)`` callback
    that adds the row's subviews at vertical offset *y*. Rows are separated by a
    hairline. The card is sized to fit.
    """
    width = _content_width()
    total = sum(r["height"] for r in rows) + (len(rows) - 1)
    card = _rounded_card(width, total)
    y = 0.0
    for index, row in enumerate(rows):
        row["place"](card, width, y)
        y += row["height"]
        if index < len(rows) - 1:
            card.addSubview_(_card_separator(width, y))
            y += 1
    return card, total


#: Keeps the most recent settings window + delegate alive past the runloop turn
#: that tears them down, so the autorelease-pool drain never touches objects
#: Python has already freed. Bounded to one entry (the prior window's close
#: animation is long finished by the next open).
_RETAINED_SETTINGS_WINDOWS: list = []


def _truncate_path(path: str, max_length: int = 60) -> str:
    if len(path) <= max_length:
        return path
    return "..." + path[-(max_length - 3) :]


def _mask_api_key(key: Optional[str]) -> str:
    if not key:
        return ""
    return _API_KEY_PLACEHOLDER


def _format_volume_row(v: TrustedVolume) -> str:
    decision = (v.decision or "trusted").upper()
    name = v.name or "(unnamed volume)"
    uuid_short = (v.uuid or "")[:18]
    return f"  • {decision:<8} {name}  [{uuid_short}]"


# ---------------------------------------------------------------------------
# AppKit delegate (defined once at module load when AppKit is available)
# ---------------------------------------------------------------------------

try:
    import objc
    from AppKit import NSApp, NSObject

    class _SettingsDelegate(NSObject):
        def init(self):
            self = objc.super(_SettingsDelegate, self).init()
            if self is None:
                return None
            self.window = None
            self.state = None
            self.callbacks = None
            self.sections = None
            self.sidebar_buttons = None
            return self

        # Sidebar section switching
        def selectSection_(self, sender):
            self.highlightSection_(sender.tag())

        def highlightSection_(self, index):
            from AppKit import NSColor

            if self.sections:
                for i, view in enumerate(self.sections):
                    view.setHidden_(i != index)
            if self.sidebar_buttons:
                selected = NSColor.selectedContentBackgroundColor()
                clear = NSColor.clearColor()
                for i, button in enumerate(self.sidebar_buttons):
                    button.layer().setBackgroundColor_(
                        (selected if i == index else clear).CGColor()
                    )

        # Save / Cancel
        def saveClicked_(self, sender):
            self.state["result_save"] = True
            try:
                NSApp.stopModal()
            except Exception:
                pass
            # orderOut_ (not close) dismisses the window WITHOUT the transform
            # close animation, whose deferred dealloc segfaulted under PyObjC.
            self.window.orderOut_(None)

        def cancelClicked_(self, sender):
            self.state["result_save"] = False
            try:
                NSApp.stopModal()
            except Exception:
                pass
            self.window.orderOut_(None)

        # Folder picker (custom; opens NSOpenPanel via dialogs.choose_folder_dialog)
        def folderPickClicked_(self, sender):
            from src.ui.folder_picker import select_folder_with_warning

            picked = select_folder_with_warning(
                choose_folder_dialog,
                warn_non_icloud=lambda _p: rumps.alert(
                    title="Folder outside iCloud",
                    message=(
                        "Selected folder is not inside iCloud. Multi-device "
                        "deduplication will only work locally."
                    ),
                    ok="OK",
                ),
                is_icloud_check=lambda p: is_icloud_synced(Path(p)),
                title="Choose output folder",
                message="Pick a folder where Malinche should save transcripts.",
            )
            if picked:
                self.state["selected_folder"] = picked
                field = self.state.get("folder_value_field")
                if field is not None:
                    field.setStringValue_(_truncate_path(picked))

        # Maintenance
        def resetMemoryClicked_(self, sender):
            cb = self.callbacks.get("reset_memory")
            if cb is not None:
                cb(None)

        def repairWhisperClicked_(self, sender):
            cb = self.callbacks.get("repair_whisper")
            if cb is not None:
                cb(None)

        def openLogsClicked_(self, sender):
            cb = self.callbacks.get("open_logs")
            if cb is not None:
                cb(None)

        def showAboutClicked_(self, sender):
            cb = self.callbacks.get("show_about")
            if cb is not None:
                cb(None)

        # Disks
        def reviewVolumesClicked_(self, sender):
            cb = self.callbacks.get("review_volumes")
            if cb is not None:
                cb(None)

        def forgetAllVolumesClicked_(self, sender):
            cb = self.callbacks.get("forget_all_volumes")
            if cb is not None:
                cb(None)

    _APPKIT_DELEGATE_AVAILABLE = True
except ImportError:
    _APPKIT_DELEGATE_AVAILABLE = False
    _SettingsDelegate = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Tab content builders
# ---------------------------------------------------------------------------


def _note(text, height=44):
    """A wrapping, secondary-coloured note label spanning the content width."""
    from AppKit import NSColor, NSTextField
    from Foundation import NSMakeRect

    from src.ui import style

    label = NSTextField.alloc().initWithFrame_(
        NSMakeRect(0, 0, _content_width(), height)
    )
    label.setStringValue_(text)
    label.setBezeled_(False)
    label.setDrawsBackground_(False)
    label.setEditable_(False)
    label.setSelectable_(False)
    label.setTextColor_(NSColor.secondaryLabelColor())
    label.cell().setWraps_(True)
    font = style.system_font("caption")
    if font is not None:
        label.setFont_(font)
    return label, height


def _field_row(label_text, control, control_w, control_h, height=_ROW_H):
    """Card row: leading right-aligned label + a trailing control."""
    from Foundation import NSMakeRect

    def place(card, width, y):
        lbl = _field_label(label_text)
        if lbl is not None:
            lbl.setFrame_(NSMakeRect(_CARD_INSET, y + (height - 20) / 2, 150, 20))
            card.addSubview_(lbl)
        if control is not None:
            cx = width - _CARD_INSET - control_w
            control.setFrame_(
                NSMakeRect(cx, y + (height - control_h) / 2, control_w, control_h)
            )
            card.addSubview_(control)

    return {"height": height, "place": place}


def _action_row(button, button_w, button_h, hint_label, height=_ROW_H):
    """Card row: a leading action button + a trailing secondary hint."""
    from Foundation import NSMakeRect

    def place(card, width, y):
        button.setFrame_(
            NSMakeRect(_CARD_INSET, y + (height - button_h) / 2, button_w, button_h)
        )
        card.addSubview_(button)
        if hint_label is not None:
            hx = _CARD_INSET + button_w + 12
            hint_label.setFrame_(
                NSMakeRect(hx, y + (height - 18) / 2, width - hx - _CARD_INSET, 18)
            )
            card.addSubview_(hint_label)

    return {"height": height, "place": place}


def _full_row(view, view_h, height=None):
    """Card row holding a single full-width control (scroll list, etc.)."""
    from Foundation import NSMakeRect

    h = height if height is not None else view_h + 2 * 10

    def place(card, width, y):
        view.setFrame_(
            NSMakeRect(
                _CARD_INSET, y + (h - view_h) / 2, width - 2 * _CARD_INSET, view_h
            )
        )
        card.addSubview_(view)

    return {"height": h, "place": place}


def _section(blocks):
    """Stack cards/notes (each ``(view, height)``) top-down with a gap."""
    from Foundation import NSMakePoint, NSMakeRect

    width = _content_width()
    gap = 16
    total = sum(h for _, h in blocks) + gap * max(len(blocks) - 1, 0)
    section = _SettingsFlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, width, total))
    y = 0.0
    for view, height in blocks:
        view.setFrameOrigin_(NSMakePoint(0, y))
        section.addSubview_(view)
        y += height + gap
    return section, total


def _secondary_hint(text):
    from src.ui import style

    return style.make_label(text, style="caption", secondary=True)


def _build_general_section(state, delegate):
    from AppKit import NSButton, NSTextField
    from Foundation import NSMakeRect

    value = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 280, 20))
    value.setStringValue_(_truncate_path(state["selected_folder"]))
    value.setBezeled_(False)
    value.setDrawsBackground_(False)
    value.setEditable_(False)
    value.setSelectable_(True)
    value.setAlignment_(2)  # right
    state["folder_value_field"] = value

    pick_btn = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 160, 28))
    pick_btn.setTitle_("Choose folder…")
    pick_btn.setBezelStyle_(1)
    pick_btn.setTarget_(delegate)
    pick_btn.setAction_("folderPickClicked:")

    login_switch = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 40, 22))
    login_switch.setButtonType_(3)  # switch
    login_switch.setTitle_("")
    login_switch.setState_(1 if state.get("start_at_login") else 0)
    state["start_at_login_checkbox"] = login_switch

    location_card, lh = _build_card(
        [
            _field_row("Output folder", value, 300, 20),
            _action_row(pick_btn, 160, 28, None),
        ]
    )
    startup_card, sh = _build_card(
        [
            _field_row("Launch at login", login_switch, 40, 22),
        ]
    )
    note = _note(
        "UI language: English. Transcripts and AI summaries are produced in the "
        "language set under Transcription."
    )
    return _section([(location_card, lh), (startup_card, sh), note])


def _build_transcription_section(state):
    from AppKit import NSPopUpButton, NSSecureTextField
    from Foundation import NSMakeRect

    language_codes = state["language_codes"]
    model_codes = state["model_codes"]

    lang_popup = NSPopUpButton.alloc().initWithFrame_(NSMakeRect(0, 0, 300, 26))
    for code, name in SUPPORTED_LANGUAGES.items():
        lang_popup.addItemWithTitle_(f"{name} ({code})")
    lang_popup.selectItemAtIndex_(language_codes.index(state["selected_language"]))
    state["language_popup"] = lang_popup

    model_popup = NSPopUpButton.alloc().initWithFrame_(NSMakeRect(0, 0, 300, 26))
    for code, name in SUPPORTED_MODELS.items():
        model_popup.addItemWithTitle_(f"{code.upper()}: {name}")
    model_popup.selectItemAtIndex_(model_codes.index(state["selected_model"]))
    state["model_popup"] = model_popup

    key_field = NSSecureTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 300, 24))
    key_field.setStringValue_(_mask_api_key(state["original_api_key"]))
    key_field.setPlaceholderString_("sk-ant-… (leave to keep; clear to remove)")
    state["api_key_field"] = key_field

    card, ch = _build_card(
        [
            _field_row("Audio language", lang_popup, 300, 26),
            _field_row("Whisper model", model_popup, 300, 26),
            _field_row("Claude API key", key_field, 300, 24),
        ]
    )
    note = _note(
        "Get a key at console.anthropic.com → Settings → API keys. Without a "
        "key, Malinche uses filename-based titles and skips AI summaries.",
        height=44,
    )
    return _section([(card, ch), note])


def _build_disks_section(settings, state, callbacks, delegate):
    from AppKit import NSButton, NSScrollView, NSTextView
    from Foundation import NSMakeRect

    volumes = list(settings.trusted_volumes or [])
    body_lines = (
        "\n".join(_format_volume_row(v) for v in volumes)
        if volumes
        else "  (no remembered disks yet — connect a recorder to be prompted)"
    )

    scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 150))
    scroll.setHasVerticalScroller_(True)
    scroll.setBorderType_(0)
    body = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 150))
    body.setEditable_(False)
    body.setRichText_(False)
    body.setString_(body_lines)
    scroll.setDocumentView_(body)
    state["disks_textview"] = body

    review_btn = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 200, _BUTTON_H))
    review_btn.setTitle_("Review mounted disks…")
    review_btn.setBezelStyle_(1)
    if "review_volumes" in callbacks:
        review_btn.setTarget_(delegate)
        review_btn.setAction_("reviewVolumesClicked:")
    else:
        review_btn.setEnabled_(False)

    list_card, lh = _build_card([_full_row(scroll, 150)])
    action_card, ah = _build_card([_action_row(review_btn, 200, _BUTTON_H, None)])
    note = _note(
        "Forgetting a disk will prompt you again the next time it is connected."
    )
    return _section([(list_card, lh), (action_card, ah), note])


def _build_maintenance_section(state, callbacks, delegate):
    from AppKit import NSButton
    from Foundation import NSMakeRect

    rows_spec = [
        (
            "Reset memory…",
            "reset_memory",
            "resetMemoryClicked:",
            "Re-process recordings from a chosen date.",
        ),
        (
            "Repair whisper-cli…",
            "repair_whisper",
            "repairWhisperClicked:",
            "Re-download and verify the whisper.cpp binary.",
        ),
        ("Open logs", "open_logs", "openLogsClicked:", "Open the in-app log viewer."),
        (
            "About Malinche",
            "show_about",
            "showAboutClicked:",
            "Version, credits, links.",
        ),
    ]
    rows = []
    for title, key, action, hint_text in rows_spec:
        btn = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 190, _BUTTON_H))
        btn.setTitle_(title)
        btn.setBezelStyle_(1)
        if key in callbacks:
            btn.setTarget_(delegate)
            btn.setAction_(action)
        else:
            btn.setEnabled_(False)
        rows.append(_action_row(btn, 190, _BUTTON_H, _secondary_hint(hint_text)))

    card, ch = _build_card(rows)

    warning, wh = _note(
        "Reset memory is destructive: previously processed recordings will be "
        "transcribed again.",
        height=36,
    )
    try:
        from src.ui import theme

        warning.setTextColor_(theme.terracotta())
    except Exception:
        pass
    return _section([(card, ch), (warning, wh)])


# ---------------------------------------------------------------------------
# Modal window
# ---------------------------------------------------------------------------


def _show_native_settings_window(
    settings: UserSettings,
    callbacks: Dict[str, Callable],
) -> bool:
    """Build and run the modal Settings window. Returns True if anything saved."""
    from AppKit import (
        NSApp,
        NSBackingStoreBuffered,
        NSButton,
        NSView,
        NSWindow,
        NSWindowStyleMaskClosable,
        NSWindowStyleMaskTitled,
    )
    from Foundation import NSMakePoint, NSMakeRect

    from src.ui import style as ui_style
    from src.ui.folder_picker import apply_basic_settings

    state: dict = {
        "selected_folder": str(settings.output_dir),
        "language_codes": list(SUPPORTED_LANGUAGES.keys()),
        "model_codes": list(SUPPORTED_MODELS.keys()),
        "selected_language": (
            settings.language
            if settings.language in SUPPORTED_LANGUAGES
            else next(iter(SUPPORTED_LANGUAGES))
        ),
        "selected_model": (
            settings.whisper_model
            if settings.whisper_model in SUPPORTED_MODELS
            else next(iter(SUPPORTED_MODELS))
        ),
        "original_api_key": settings.ai_api_key or "",
        "start_at_login": bool(settings.start_at_login),
        "result_save": False,
    }

    style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, _WINDOW_SIZE[0], _WINDOW_SIZE[1]),
        style,
        NSBackingStoreBuffered,
        False,
    )
    window.setTitle_("Malinche Settings")
    window.center()
    # Python owns the window's lifetime; without this AppKit also releases it on
    # close, and the double-release segfaults in the autorelease-pool drain
    # (-[_NSWindowTransformAnimation dealloc], EXC_BAD_ACCESS).
    window.setReleasedWhenClosed_(False)

    content = window.contentView()
    win_w, win_h = _WINDOW_SIZE

    # Bottom button bar (right-aligned).
    save_btn = NSButton.alloc().initWithFrame_(NSMakeRect(win_w - 20 - 96, 16, 96, 32))
    save_btn.setTitle_("Save")
    save_btn.setBezelStyle_(1)
    save_btn.setKeyEquivalent_("\r")
    content.addSubview_(save_btn)

    cancel_btn = NSButton.alloc().initWithFrame_(
        NSMakeRect(win_w - 20 - 96 - 12 - 96, 16, 96, 32)
    )
    cancel_btn.setTitle_("Cancel")
    cancel_btn.setBezelStyle_(1)
    cancel_btn.setKeyEquivalent_("\x1b")  # Escape
    content.addSubview_(cancel_btn)

    delegate = _SettingsDelegate.alloc().init()
    delegate.window = window
    delegate.state = state
    delegate.callbacks = callbacks
    save_btn.setTarget_(delegate)
    save_btn.setAction_("saveClicked:")
    cancel_btn.setTarget_(delegate)
    cancel_btn.setAction_("cancelClicked:")

    _RETAINED_SETTINGS_WINDOWS.clear()
    _RETAINED_SETTINGS_WINDOWS.append((window, delegate))

    # Sidebar (left, vibrant) with selectable section rows + content pane.
    sidebar = ui_style.vibrant_view(
        NSMakeRect(0, 0, _SIDEBAR_W, win_h), material="sidebar"
    ) or NSView.alloc().initWithFrame_(NSMakeRect(0, 0, _SIDEBAR_W, win_h))
    content.addSubview_(sidebar)

    sections_def = [
        ("General", "gearshape", lambda: _build_general_section(state, delegate)),
        ("Transcription", "waveform", lambda: _build_transcription_section(state)),
        (
            "Disks",
            "externaldrive",
            lambda: _build_disks_section(settings, state, callbacks, delegate),
        ),
        (
            "Maintenance",
            "wrench.and.screwdriver",
            lambda: _build_maintenance_section(state, callbacks, delegate),
        ),
    ]

    pane_x = _SIDEBAR_W + _PANE_PAD
    pane_top = win_h - _PANE_PAD
    section_views = []
    sidebar_buttons = []
    row_y = win_h - 52
    for index, (label, symbol, builder) in enumerate(sections_def):
        section, sec_h = builder()
        section.setFrameOrigin_(NSMakePoint(pane_x, pane_top - sec_h))
        section.setHidden_(index != 0)
        content.addSubview_(section)
        section_views.append(section)

        row = NSButton.alloc().initWithFrame_(
            NSMakeRect(10, row_y, _SIDEBAR_W - 20, 34)
        )
        row.setTitle_("  " + label)
        row.setBordered_(False)
        row.setAlignment_(0)
        font = ui_style.system_font("body")
        if font is not None:
            row.setFont_(font)
        img = ui_style.sf_symbol(symbol, point=14.0)
        if img is not None:
            row.setImage_(img)
            row.setImagePosition_(2)  # leading
        row.setWantsLayer_(True)
        row.layer().setCornerRadius_(6.0)
        row.setTag_(index)
        row.setTarget_(delegate)
        row.setAction_("selectSection:")
        sidebar.addSubview_(row)
        sidebar_buttons.append(row)
        row_y -= 38

    delegate.sections = section_views
    delegate.sidebar_buttons = sidebar_buttons
    delegate.highlightSection_(0)

    window.makeKeyAndOrderFront_(None)
    try:
        NSApp.runModalForWindow_(window)
    except Exception as exc:
        logger.warning("Settings modal loop failed: %s", exc)

    if not state["result_save"]:
        return False

    selected_language = state["language_codes"][
        state["language_popup"].indexOfSelectedItem()
    ]
    selected_model = state["model_codes"][state["model_popup"].indexOfSelectedItem()]

    api_key_input = str(state["api_key_field"].stringValue() or "").strip()
    if api_key_input == _API_KEY_PLACEHOLDER:
        new_api_key: Optional[str] = state["original_api_key"] or None
    elif api_key_input == "":
        new_api_key = None
    else:
        new_api_key = api_key_input

    basic_changed = apply_basic_settings(
        settings,
        selected_folder=state["selected_folder"],
        selected_language=selected_language,
        selected_model=selected_model,
        supported_languages=SUPPORTED_LANGUAGES,
        supported_models=SUPPORTED_MODELS,
    )
    api_key_changed = (settings.ai_api_key or None) != new_api_key
    if api_key_changed:
        settings.ai_api_key = new_api_key

    new_start_at_login = bool(state["start_at_login_checkbox"].state())
    start_at_login_changed = settings.start_at_login != new_start_at_login
    if start_at_login_changed:
        settings.start_at_login = new_start_at_login
        from src import startup_manager

        if new_start_at_login:
            if not startup_manager.enable_launch_at_login():
                settings.start_at_login = False
                rumps.alert(
                    title="Launch at login unavailable",
                    message=(
                        "Autostart requires Malinche to be installed as an "
                        "app bundle (drag Malinche.app to /Applications)."
                    ),
                    ok="OK",
                )
        else:
            startup_manager.disable_launch_at_login()

    return basic_changed or api_key_changed or start_at_login_changed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def show_settings_window(callbacks: Optional[Dict[str, Callable]] = None) -> bool:
    """Show settings window. Returns True if any setting was saved."""
    settings = UserSettings.load()
    old_model = settings.whisper_model
    callbacks = callbacks or {}

    try:
        changed = _show_native_settings_window(settings, callbacks)
    except ImportError:
        logger.warning("AppKit not available, using text fallback")
        window = rumps.Window(
            title=TEXTS["settings_title"],
            message=(
                "Native settings panel is unavailable.\n"
                "Enter the output folder manually:"
            ),
            default_text=settings.output_dir,
            ok="Save",
            cancel="Cancel",
            dimensions=(350, 24),
        )
        result = window.run()
        if result.clicked == 0:
            return False
        new_folder = result.text.strip()
        changed = bool(new_folder and new_folder != settings.output_dir)
        if changed:
            settings.output_dir = new_folder

    if not changed:
        return False

    settings.save()
    logger.info("Settings updated and saved")

    if settings.whisper_model != old_model:
        manager = DependencyManager()
        missing = manager.needed()
        if missing:
            total_mb = sum(size for _, size in missing) / 1_000_000
            rumps.alert(
                title="Downloading model",
                message=(
                    f"New model: {settings.whisper_model}\n"
                    f"Missing data: ~{total_mb:.0f} MB.\n\n"
                    "Download will start in the background."
                ),
                ok="OK",
            )
            manager.download_async()

    rumps.alert(
        title=TEXTS["saved_title"],
        message=TEXTS["saved_message"],
        ok="OK",
    )
    return True
