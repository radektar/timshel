"""Smoke tests for the Settings window's card/sidebar section builders.

The modal window itself needs a run loop to judge, but these verify each section
constructs without raising and — critically — still populates the ``state`` keys
the Save logic depends on. A regression there would only surface at runtime.
"""

from __future__ import annotations

import pytest

from src.config import SUPPORTED_LANGUAGES, SUPPORTED_MODELS, UserSettings
import src.ui.settings_window as sw

requires_appkit = pytest.mark.skipif(
    not getattr(sw, "_FLIPPED_AVAILABLE", False), reason="requires AppKit (PyObjC)"
)


@pytest.mark.parametrize(
    "raw, original, expected",
    [
        # Clean paste — the normal case.
        ("sk-ant-api03-NEW", "sk-ant-old", "sk-ant-api03-NEW"),
        # Paste that didn't replace the seeded placeholder: the em-dash MUST be
        # stripped, else "—sk-ant-…" is saved and every API call 401s. This is
        # the bug: a correct key pasted, still rejected, with no visible cause.
        ("—sk-ant-api03-NEW", "sk-ant-old", "sk-ant-api03-NEW"),
        # Surrounding whitespace from a copy is trimmed.
        ("  sk-ant-api03-NEW  ", None, "sk-ant-api03-NEW"),
        # Blank field → keep the existing key untouched.
        ("", "sk-ant-old", "sk-ant-old"),
        # Only the placeholder (field left untouched) → keep existing.
        ("—", "sk-ant-old", "sk-ant-old"),
        # Blank field with no prior key → stays unset.
        ("", "", None),
    ],
)
def test_resolve_api_key_input(raw, original, expected):
    assert sw._resolve_api_key_input(raw, original) == expected


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
        sw._build_maintenance_section(state, {}, delegate),
    ]
    for _view, height in sections:
        assert height <= available, f"section height {height} exceeds {available}"


@requires_appkit
def test_delegate_exposes_section_selectors():
    delegate = sw._SettingsDelegate.alloc().init()
    assert delegate.respondsToSelector_(b"selectSection:")
    assert delegate.respondsToSelector_(b"highlightSection:")
