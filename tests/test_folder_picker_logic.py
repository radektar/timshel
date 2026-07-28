"""Tests for folder picker helpers used by wizard and settings window."""

import pytest

from src.config import UserSettings, SUPPORTED_LANGUAGES, SUPPORTED_MODELS
from src.setup.wizard import SetupWizard, WizardStep
from src.ui import folder_picker
from src.ui.folder_picker import (
    PICK_FOLDER_RESPONSE,
    apply_basic_settings,
    select_folder_with_warning,
)


def test_basic_config_step_is_part_of_wizard_order():
    """Wizard must include output folder configuration step."""
    assert WizardStep.BASIC_CONFIG in SetupWizard.STEPS_ORDER


def test_pick_folder_response_code_is_distinct():
    """Response code used by our folder picker must not collide with NSAlert button codes."""
    assert PICK_FOLDER_RESPONSE not in {1000, 1001, 1002, 1003}


def test_apply_basic_settings_persists_all_fields(tmp_path):
    settings = UserSettings(output_dir=tmp_path / "old")
    new_folder = str(tmp_path / "new_vault")

    changed = apply_basic_settings(
        settings,
        selected_folder=new_folder,
        selected_language="pl",
        selected_model="small",
        supported_languages=SUPPORTED_LANGUAGES,
        supported_models=SUPPORTED_MODELS,
    )

    assert changed is True
    assert str(settings.output_dir) == new_folder
    assert settings.language == "pl"
    assert settings.whisper_model == "small"


def test_apply_basic_settings_rejects_empty_folder(tmp_path):
    settings = UserSettings(output_dir=tmp_path)
    with pytest.raises(ValueError):
        apply_basic_settings(
            settings,
            selected_folder="",
            selected_language="pl",
            selected_model="small",
            supported_languages=SUPPORTED_LANGUAGES,
            supported_models=SUPPORTED_MODELS,
        )


def test_apply_basic_settings_rejects_unknown_language(tmp_path):
    settings = UserSettings(output_dir=tmp_path)
    with pytest.raises(ValueError):
        apply_basic_settings(
            settings,
            selected_folder=str(tmp_path),
            selected_language="xx",
            selected_model="small",
            supported_languages=SUPPORTED_LANGUAGES,
            supported_models=SUPPORTED_MODELS,
        )


def test_select_folder_with_warning_returns_selected_path_and_triggers_icloud_warning(
    tmp_path,
):
    warnings = []

    def fake_choose(**_kwargs):
        return str(tmp_path / "picked")

    def fake_warn(path):
        warnings.append(path)

    result = select_folder_with_warning(
        fake_choose,
        warn_non_icloud=fake_warn,
        is_icloud_check=lambda _p: False,
        title="t",
        message="m",
    )

    assert result == str(tmp_path / "picked")
    assert warnings == [str(tmp_path / "picked")]


def test_select_folder_with_warning_skips_warning_for_icloud_path(tmp_path):
    warnings = []

    result = select_folder_with_warning(
        lambda **_kw: str(tmp_path / "icloud"),
        warn_non_icloud=lambda p: warnings.append(p),
        is_icloud_check=lambda _p: True,
        title="t",
        message="m",
    )

    assert result == str(tmp_path / "icloud")
    assert warnings == []


def test_select_folder_with_warning_returns_none_when_cancelled(tmp_path):
    result = select_folder_with_warning(
        lambda **_kw: None,
        warn_non_icloud=lambda _p: pytest.fail("should not warn"),
        is_icloud_check=lambda _p: False,
        title="t",
        message="m",
    )
    assert result is None


def test_make_folder_picker_button_returns_none_without_appkit(monkeypatch):
    """Helper must degrade gracefully when AppKit is unavailable."""
    monkeypatch.setattr(folder_picker, "APPKIT_AVAILABLE", False)
    monkeypatch.setattr(folder_picker, "NSButton", None)
    result = folder_picker.make_folder_picker_button(
        frame=object(),
        target=folder_picker.FolderPickerTarget(),
        title="x",
    )
    assert result is None
