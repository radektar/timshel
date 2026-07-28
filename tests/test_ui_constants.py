"""Unit tests for UI constants module."""

import pytest
from src.ui.constants import (
    APP_VERSION,
    APP_NAME,
    APP_AUTHOR,
    APP_WEBSITE,
    APP_GITHUB,
    TEXTS,
)


class TestUIConstants:
    """Test UI constants."""

    def test_app_version_format(self):
        """APP_VERSION follows SemVer 2.0.0, incl. optional prerelease/build metadata."""
        import re

        semver = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
        assert semver.match(APP_VERSION), (
            f"APP_VERSION '{APP_VERSION}' must match SemVer 2.0.0 "
            "(MAJOR.MINOR.PATCH with optional -prerelease/+build)"
        )

    def test_app_name_not_empty(self):
        """APP_NAME is not empty."""
        assert APP_NAME, "APP_NAME should not be empty"
        assert isinstance(APP_NAME, str), "APP_NAME should be a string"

    def test_app_author_not_empty(self):
        """APP_AUTHOR is not empty."""
        assert APP_AUTHOR, "APP_AUTHOR should not be empty"
        assert isinstance(APP_AUTHOR, str), "APP_AUTHOR should be a string"

    def test_app_website_valid(self):
        """APP_WEBSITE is a valid URL."""
        assert APP_WEBSITE.startswith("http"), "APP_WEBSITE should start with http"
        assert isinstance(APP_WEBSITE, str), "APP_WEBSITE should be a string"

    def test_app_github_valid(self):
        """APP_GITHUB is a valid GitHub URL."""
        assert "github.com" in APP_GITHUB, "APP_GITHUB should contain github.com"
        assert isinstance(APP_GITHUB, str), "APP_GITHUB should be a string"

    def test_texts_dict_has_required_keys(self):
        """TEXTS contains all required keys."""
        required_keys = [
            "about_title",
            "about_message",
            "reset_memory_title",
            "reset_memory_message",
            "reset_memory_7days",
            "reset_memory_30days",
            "reset_memory_custom",
            "reset_memory_custom_input",
            "reset_memory_invalid_date",
            "reset_memory_success",
            "reset_memory_error",
            "folder_picker_title",
            "folder_picker_message",
            "folder_picker_select",
            "folder_picker_default",
            "folder_picker_back",
        ]

        for key in required_keys:
            assert key in TEXTS, f"TEXTS should contain key '{key}'"
            assert TEXTS[key], f"TEXTS['{key}'] should not be empty"

    def test_texts_are_strings(self):
        """All TEXTS values are strings."""
        for key, value in TEXTS.items():
            assert isinstance(value, str), f"TEXTS['{key}'] should be a string"

    def test_about_message_contains_version(self):
        """About message contains APP_VERSION."""
        assert (
            APP_VERSION in TEXTS["about_message"]
        ), "About message should contain version"

    def test_about_message_contains_app_name(self):
        """About message contains APP_NAME."""
        assert (
            APP_NAME in TEXTS["about_message"]
        ), "About message should contain app name"
