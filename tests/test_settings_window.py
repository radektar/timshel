"""Smoke tests for the Settings window's card/sidebar section builders.

The modal window itself needs a run loop to judge, but these verify each section
constructs without raising and — critically — still populates the ``state`` keys
the Save logic depends on. A regression there would only surface at runtime.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.config import SUPPORTED_LANGUAGES, SUPPORTED_MODELS, UserSettings
import src.ui.settings_window as sw

requires_appkit = pytest.mark.skipif(
    not getattr(sw, "_FLIPPED_AVAILABLE", False), reason="requires AppKit (PyObjC)"
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Clean paste — the normal case.
        ("sk-ant-api03-NEW", "sk-ant-api03-NEW"),
        # A pre-filled value left unchanged passes straight through.
        ("sk-ant-old", "sk-ant-old"),
        # Stray em-dash from a legacy seeded placeholder MUST be stripped, else
        # "—sk-ant-…" is saved and every API call 401s with no visible cause.
        ("—sk-ant-api03-NEW", "sk-ant-api03-NEW"),
        # Surrounding whitespace from a copy is trimmed.
        ("  sk-ant-api03-NEW  ", "sk-ant-api03-NEW"),
        # Field cleared → no key (the user deliberately emptied a visible field).
        ("", None),
        # Only the legacy placeholder char → treated as empty.
        ("—", None),
    ],
)
def test_resolve_api_key_input(raw, expected):
    assert sw._resolve_api_key_input(raw) == expected


def _state():
    settings = UserSettings.load()
    return settings, {
        "selected_folder": str(settings.output_dir or "/tmp/out"),
        "language_codes": list(SUPPORTED_LANGUAGES.keys()),
        "model_codes": list(SUPPORTED_MODELS.keys()),
        "selected_language": next(iter(SUPPORTED_LANGUAGES)),
        "selected_model": next(iter(SUPPORTED_MODELS)),
        "original_api_key": "",
        "start_at_login": False,
        "voice_memos_enabled": False,
        "voice_memos_connector": None,
        "result_save": False,
    }


@requires_appkit
def test_all_sections_build_and_populate_state():
    settings, state = _state()
    delegate = sw._SettingsDelegate.alloc().init()
    delegate.state = state
    delegate.callbacks = {}

    builders = [
        lambda: sw._build_general_section(state, delegate),
        lambda: sw._build_transcription_section(state),
        lambda: sw._build_disks_section(settings, state, {}, delegate),
        lambda: sw._build_voice_memos_section(state, {}, delegate),
        lambda: sw._build_maintenance_section(state, {}, delegate),
    ]
    for build in builders:
        view, height = build()
        assert view is not None
        assert height > 0

    # The keys the Save logic reads must all be present after building.
    for key in (
        "folder_value_field",
        "start_at_login_checkbox",
        "language_popup",
        "model_popup",
        "api_key_field",
        "disks_textview",
        "voice_memos_checkbox",
    ):
        assert key in state, f"missing state key: {key}"


@requires_appkit
def test_sections_fit_the_content_pane():
    """Each section should fit above the button bar (no clipping)."""
    settings, state = _state()
    delegate = sw._SettingsDelegate.alloc().init()
    delegate.state = state
    delegate.callbacks = {}
    available = sw._WINDOW_SIZE[1] - 56 - sw._PANE_PAD  # below title, above buttons
    sections = [
        sw._build_general_section(state, delegate),
        sw._build_transcription_section(state),
        sw._build_disks_section(settings, state, {}, delegate),
        sw._build_voice_memos_section(state, {}, delegate),
        sw._build_maintenance_section(state, {}, delegate),
    ]
    for _view, height in sections:
        assert height <= available, f"section height {height} exceeds {available}"


class _FakeSwitch:
    def __init__(self, on):
        self._on = on

    def state(self):
        return 1 if self._on else 0


class TestApplyVoiceMemosSettings:
    """The consent rule, isolated from the modal so it can be verified."""

    def _apply(self, *, was_enabled, now_on, connector=None):
        settings = UserSettings(voice_memos_enabled=was_enabled)
        state = {
            "voice_memos_checkbox": _FakeSwitch(now_on),
            "voice_memos_connector": connector,
        }
        changed = sw.apply_voice_memos_settings(settings, state)
        return settings, changed

    def test_turning_it_on_saves_and_stamps_consent(self):
        connector = MagicMock()

        settings, changed = self._apply(
            was_enabled=False, now_on=True, connector=connector
        )

        assert (changed, settings.voice_memos_enabled) == (True, True)
        # consented=True moves the marker to now, so an off period stays back
        # catalogue instead of being swept in as new.
        assert connector.enable.call_args.kwargs == {"consented": True}
        assert settings.voice_memos_proposal_shown is True

    def test_turning_it_off_leaves_the_marker_alone(self):
        connector = MagicMock()

        settings, changed = self._apply(
            was_enabled=True, now_on=False, connector=connector
        )

        assert (changed, settings.voice_memos_enabled) == (True, False)
        connector.enable.assert_not_called()

    def test_no_change_is_not_reported_as_a_save(self):
        _settings, changed = self._apply(was_enabled=True, now_on=True)

        assert changed is False

    def test_a_missing_connector_still_saves_the_toggle(self):
        # Settings can be opened before the daemon built the connector; the
        # per-tick self-repair stamps the marker instead.
        settings, changed = self._apply(was_enabled=False, now_on=True, connector=None)

        assert (changed, settings.voice_memos_enabled) == (True, True)

    def test_an_unbuilt_section_is_a_no_op(self):
        settings = UserSettings(voice_memos_enabled=False)

        assert sw.apply_voice_memos_settings(settings, {}) is False


@requires_appkit
def test_delegate_exposes_section_selectors():
    delegate = sw._SettingsDelegate.alloc().init()
    assert delegate.respondsToSelector_(b"selectSection:")
    assert delegate.respondsToSelector_(b"highlightSection:")


@requires_appkit
def test_api_key_field_prefilled_with_stored_key():
    """The plaintext key field shows the stored key so the user can verify it.

    Regression for the 401 saga: the masked field hid whatever was stored, so a
    mis-pasted value (a shell command) sat there invisibly. The field must now
    surface the real saved key on open.
    """
    _settings, state = _state()
    state["original_api_key"] = "sk-ant-STORED-KEY"
    sw._build_transcription_section(state)
    assert state["api_key_field"].stringValue() == "sk-ant-STORED-KEY"


@requires_appkit
def test_settings_window_overrides_key_equivalent_for_paste():
    """The window subclass defines its own performKeyEquivalent: (⌘V/C/X/A).

    Without it, the menu-bar app has no Edit menu and keyboard paste is dead in
    the API-key field.
    """
    assert sw._SettingsWindow is not None
    # The override must be defined on our subclass, not merely inherited.
    assert "performKeyEquivalent_" in sw._SettingsWindow.__dict__
