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
_WINDOW_SIZE = (640, 440)
_TAB_FRAME = (16, 56, 608, 360)  # x, y, w, h within content view
_BUTTON_W, _BUTTON_H = 96, 28


#: Keeps the most recent settings window + delegate alive past the runloop turn
#: that tears them down, so the autorelease-pool drain never touches objects
#: Python has already freed. Bounded to one entry (the prior window's close
#: animation is long finished by the next open).
_RETAINED_SETTINGS_WINDOWS: list = []


def _truncate_path(path: str, max_length: int = 60) -> str:
    if len(path) <= max_length:
        return path
    return "..." + path[-(max_length - 3):]


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
    from Foundation import NSMakeRect

    class _SettingsDelegate(NSObject):
        def init(self):
            self = objc.super(_SettingsDelegate, self).init()
            if self is None:
                return None
            self.window = None
            self.state = None
            self.callbacks = None
            return self

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

def _build_general_tab(view, state, delegate) -> None:
    from AppKit import NSButton, NSTextField
    from Foundation import NSMakeRect

    label = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 256, 160, 20))
    label.setStringValue_("Output folder:")
    label.setBezeled_(False)
    label.setDrawsBackground_(False)
    label.setEditable_(False)
    label.setSelectable_(False)
    view.addSubview_(label)

    value = NSTextField.alloc().initWithFrame_(NSMakeRect(180, 256, 400, 20))
    value.setStringValue_(_truncate_path(state["selected_folder"]))
    value.setBezeled_(False)
    value.setDrawsBackground_(False)
    value.setEditable_(False)
    value.setSelectable_(True)
    view.addSubview_(value)
    state["folder_value_field"] = value

    pick_btn = NSButton.alloc().initWithFrame_(NSMakeRect(180, 216, 200, 28))
    pick_btn.setTitle_("Choose folder…")
    pick_btn.setBezelStyle_(1)
    pick_btn.setTarget_(delegate)
    pick_btn.setAction_("folderPickClicked:")
    view.addSubview_(pick_btn)

    login_checkbox = NSButton.alloc().initWithFrame_(NSMakeRect(20, 170, 560, 22))
    login_checkbox.setButtonType_(3)  # NSSwitchButton
    login_checkbox.setTitle_("Launch Malinche automatically at login")
    login_checkbox.setState_(1 if state.get("start_at_login") else 0)
    view.addSubview_(login_checkbox)
    state["start_at_login_checkbox"] = login_checkbox

    note = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 60, 560, 60))
    note.setStringValue_(
        "UI language: English. Output transcripts and AI summaries are produced "
        "in the language configured under the Transcription tab."
    )
    note.setBezeled_(False)
    note.setDrawsBackground_(False)
    note.setEditable_(False)
    note.setSelectable_(False)
    view.addSubview_(note)


def _build_transcription_tab(view, state) -> None:
    from AppKit import NSPopUpButton, NSSecureTextField, NSTextField
    from Foundation import NSMakeRect

    language_codes = state["language_codes"]
    model_codes = state["model_codes"]

    lang_label = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 260, 160, 20))
    lang_label.setStringValue_("Audio language:")
    lang_label.setBezeled_(False)
    lang_label.setDrawsBackground_(False)
    lang_label.setEditable_(False)
    lang_label.setSelectable_(False)
    view.addSubview_(lang_label)

    lang_popup = NSPopUpButton.alloc().initWithFrame_(NSMakeRect(180, 256, 400, 26))
    for code, name in SUPPORTED_LANGUAGES.items():
        lang_popup.addItemWithTitle_(f"{name} ({code})")
    lang_popup.selectItemAtIndex_(language_codes.index(state["selected_language"]))
    view.addSubview_(lang_popup)
    state["language_popup"] = lang_popup

    model_label = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 216, 160, 20))
    model_label.setStringValue_("Whisper model:")
    model_label.setBezeled_(False)
    model_label.setDrawsBackground_(False)
    model_label.setEditable_(False)
    model_label.setSelectable_(False)
    view.addSubview_(model_label)

    model_popup = NSPopUpButton.alloc().initWithFrame_(NSMakeRect(180, 212, 400, 26))
    for code, name in SUPPORTED_MODELS.items():
        model_popup.addItemWithTitle_(f"{code.upper()}: {name}")
    model_popup.selectItemAtIndex_(model_codes.index(state["selected_model"]))
    view.addSubview_(model_popup)
    state["model_popup"] = model_popup

    key_label = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 170, 160, 20))
    key_label.setStringValue_("Claude API key:")
    key_label.setBezeled_(False)
    key_label.setDrawsBackground_(False)
    key_label.setEditable_(False)
    key_label.setSelectable_(False)
    view.addSubview_(key_label)

    key_field = NSSecureTextField.alloc().initWithFrame_(NSMakeRect(180, 166, 400, 26))
    key_field.setStringValue_(_mask_api_key(state["original_api_key"]))
    key_field.setPlaceholderString_(
        "sk-ant-… (leave unchanged to keep current; clear to remove)"
    )
    view.addSubview_(key_field)
    state["api_key_field"] = key_field

    hint = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 100, 560, 56))
    hint.setStringValue_(
        "Get a key at console.anthropic.com → Settings → API keys.\n"
        "Without a key, Malinche falls back to filename-based titles and skips "
        "AI summaries."
    )
    hint.setBezeled_(False)
    hint.setDrawsBackground_(False)
    hint.setEditable_(False)
    hint.setSelectable_(False)
    view.addSubview_(hint)


def _build_disks_tab(view, settings, state, callbacks, delegate) -> None:
    from AppKit import NSButton, NSScrollView, NSTextField, NSTextView
    from Foundation import NSMakeRect

    header = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 268, 560, 20))
    header.setStringValue_("Trusted disks (from previous prompts):")
    header.setBezeled_(False)
    header.setDrawsBackground_(False)
    header.setEditable_(False)
    header.setSelectable_(False)
    view.addSubview_(header)

    volumes = list(settings.trusted_volumes or [])
    body_lines = (
        "\n".join(_format_volume_row(v) for v in volumes)
        if volumes
        else "  (no remembered disks yet — connect a recorder to be prompted)"
    )

    scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(20, 96, 560, 164))
    scroll.setHasVerticalScroller_(True)
    scroll.setBorderType_(2)

    body = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 544, 164))
    body.setEditable_(False)
    body.setRichText_(False)
    body.setString_(body_lines)
    scroll.setDocumentView_(body)
    view.addSubview_(scroll)
    state["disks_textview"] = body

    review_btn = NSButton.alloc().initWithFrame_(NSMakeRect(20, 52, 200, _BUTTON_H))
    review_btn.setTitle_("Review mounted disks…")
    review_btn.setBezelStyle_(1)
    if "review_volumes" in callbacks:
        review_btn.setTarget_(delegate)
        review_btn.setAction_("reviewVolumesClicked:")
    else:
        review_btn.setEnabled_(False)
    view.addSubview_(review_btn)

    forget_btn = NSButton.alloc().initWithFrame_(NSMakeRect(232, 52, 160, _BUTTON_H))
    forget_btn.setTitle_("Forget all")
    forget_btn.setBezelStyle_(1)
    if "forget_all_volumes" in callbacks:
        forget_btn.setTarget_(delegate)
        forget_btn.setAction_("forgetAllVolumesClicked:")
    else:
        forget_btn.setEnabled_(False)
    view.addSubview_(forget_btn)

    note = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 14, 560, 32))
    note.setStringValue_(
        "Forgetting a disk will prompt you again the next time it is connected."
    )
    note.setBezeled_(False)
    note.setDrawsBackground_(False)
    note.setEditable_(False)
    note.setSelectable_(False)
    view.addSubview_(note)


def _build_maintenance_tab(view, state, callbacks, delegate) -> None:
    from AppKit import NSButton, NSTextField
    from Foundation import NSMakeRect

    rows = [
        ("Reset memory…",       "reset_memory",   "Re-process recordings from a chosen date."),
        ("Repair whisper-cli…", "repair_whisper", "Re-download and verify the whisper.cpp binary."),
        ("Open logs",           "open_logs",      "Open the in-app log viewer (newest entries first)."),
        ("About Malinche",      "show_about",     "Version, credits, links."),
    ]
    actions = {
        "reset_memory":   "resetMemoryClicked:",
        "repair_whisper": "repairWhisperClicked:",
        "open_logs":      "openLogsClicked:",
        "show_about":     "showAboutClicked:",
    }

    # NSTabView reserves ~30px at the top for the tab strip. Start the first
    # button safely below that, then space rows by 44px so all 4 rows + the
    # warning footer fit comfortably inside the tab content area.
    y = 256
    for title, key, hint_text in rows:
        btn = NSButton.alloc().initWithFrame_(NSMakeRect(20, y, 220, _BUTTON_H))
        btn.setTitle_(title)
        btn.setBezelStyle_(1)
        if key in callbacks:
            btn.setTarget_(delegate)
            btn.setAction_(actions[key])
        else:
            btn.setEnabled_(False)
        view.addSubview_(btn)

        hint = NSTextField.alloc().initWithFrame_(NSMakeRect(250, y + 4, 340, 20))
        hint.setStringValue_(hint_text)
        hint.setBezeled_(False)
        hint.setDrawsBackground_(False)
        hint.setEditable_(False)
        hint.setSelectable_(False)
        view.addSubview_(hint)

        y -= 44

    try:
        from src.ui import theme
        warning_color = theme.terracotta()
    except Exception:
        warning_color = None

    warning = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 24, 560, 36))
    warning.setStringValue_(
        "Reset memory is destructive: previously processed recordings will be "
        "transcribed again."
    )
    warning.setBezeled_(False)
    warning.setDrawsBackground_(False)
    warning.setEditable_(False)
    warning.setSelectable_(False)
    if warning_color is not None:
        try:
            warning.setTextColor_(warning_color)
        except Exception:
            pass
    view.addSubview_(warning)


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
        NSTabView,
        NSTabViewItem,
        NSView,
        NSWindow,
        NSWindowStyleMaskClosable,
        NSWindowStyleMaskTitled,
    )
    from Foundation import NSMakeRect

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

    cancel_btn = NSButton.alloc().initWithFrame_(NSMakeRect(420, 16, 96, 32))
    cancel_btn.setTitle_("Cancel")
    cancel_btn.setBezelStyle_(1)
    cancel_btn.setKeyEquivalent_("\x1b")  # Escape
    content.addSubview_(cancel_btn)

    save_btn = NSButton.alloc().initWithFrame_(NSMakeRect(524, 16, 96, 32))
    save_btn.setTitle_("Save")
    save_btn.setBezelStyle_(1)
    save_btn.setKeyEquivalent_("\r")
    content.addSubview_(save_btn)

    tab_view = NSTabView.alloc().initWithFrame_(
        NSMakeRect(_TAB_FRAME[0], _TAB_FRAME[1], _TAB_FRAME[2], _TAB_FRAME[3])
    )
    content.addSubview_(tab_view)

    delegate = _SettingsDelegate.alloc().init()
    delegate.window = window
    delegate.state = state
    delegate.callbacks = callbacks

    save_btn.setTarget_(delegate)
    save_btn.setAction_("saveClicked:")
    cancel_btn.setTarget_(delegate)
    cancel_btn.setAction_("cancelClicked:")

    # Retain window + delegate beyond this function's scope (drop the previous
    # one, whose teardown has long since completed). See _RETAINED note above.
    _RETAINED_SETTINGS_WINDOWS.clear()
    _RETAINED_SETTINGS_WINDOWS.append((window, delegate))

    def _new_tab(label: str):
        item = NSTabViewItem.alloc().initWithIdentifier_(label)
        item.setLabel_(label)
        tv = NSView.alloc().initWithFrame_(
            NSMakeRect(0, 0, _TAB_FRAME[2], _TAB_FRAME[3] - 30)
        )
        item.setView_(tv)
        tab_view.addTabViewItem_(item)
        return tv

    general_view = _new_tab("General")
    transcription_view = _new_tab("Transcription")
    disks_view = _new_tab("Disks")
    maintenance_view = _new_tab("Maintenance")

    _build_general_tab(general_view, state, delegate)
    _build_transcription_tab(transcription_view, state)
    _build_disks_tab(disks_view, settings, state, callbacks, delegate)
    _build_maintenance_tab(maintenance_view, state, callbacks, delegate)

    window.makeKeyAndOrderFront_(None)
    try:
        NSApp.runModalForWindow_(window)
    except Exception as exc:
        logger.warning("Settings modal loop failed: %s", exc)

    if not state["result_save"]:
        return False

    selected_language = state["language_codes"][state["language_popup"].indexOfSelectedItem()]
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
