"""Unit tests for UI dialogs module."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from src.ui.dialogs import choose_date_dialog, choose_folder_dialog, show_about_dialog
from src.ui.constants import TEXTS


class TestDateParsing:
    """Test date parsing in choose_date_dialog."""

    @patch("src.ui.dialogs.rumps.alert")
    def test_choose_date_7days(self, mock_alert):
        """7 days option returns correct date."""
        mock_alert.return_value = 1  # 7 days option
        
        result = choose_date_dialog(default_days=7)
        
        assert result is not None
        expected_date = datetime.now() - timedelta(days=7)
        # Allow 1 second tolerance
        assert abs((result - expected_date).total_seconds()) < 1

    @patch("src.ui.dialogs.rumps.alert")
    def test_choose_date_30days(self, mock_alert):
        """30 days option returns correct date."""
        mock_alert.return_value = -1  # 30 days option (other) - rumps returns -1 for "other"
        
        result = choose_date_dialog(default_days=7)
        
        assert result is not None
        expected_date = datetime.now() - timedelta(days=30)
        assert abs((result - expected_date).total_seconds()) < 1

    @patch("src.ui.dialogs.rumps.Window")
    @patch("src.ui.dialogs.rumps.alert")
    def test_choose_date_custom_valid(self, mock_alert, mock_window):
        """Custom date with valid format."""
        mock_alert.return_value = 0  # Custom date option
        mock_result = Mock()
        mock_result.clicked = 1  # OK
        mock_result.text = "2025-12-01"
        mock_window.return_value.run.return_value = mock_result
        
        result = choose_date_dialog(default_days=7)
        
        assert result is not None
        assert result == datetime(2025, 12, 1)

    @patch("src.ui.dialogs.rumps.Window")
    @patch("src.ui.dialogs.rumps.alert")
    def test_choose_date_custom_invalid_format(self, mock_alert, mock_window):
        """Custom date with invalid format shows error."""
        mock_alert.return_value = 0  # Custom date option
        mock_result = Mock()
        mock_result.clicked = 1  # OK
        mock_result.text = "invalid-date"
        mock_window.return_value.run.return_value = mock_result
        
        with patch("src.ui.dialogs.rumps.alert") as mock_error_alert:
            result = choose_date_dialog(default_days=7)
            
            assert result is None
            mock_error_alert.assert_called_once()

    @patch("src.ui.dialogs.rumps.Window")
    @patch("src.ui.dialogs.rumps.alert")
    def test_choose_date_custom_cancelled(self, mock_alert, mock_window):
        """Custom date cancelled returns None."""
        mock_alert.return_value = 0  # Custom date option
        mock_result = Mock()
        mock_result.clicked = 0  # Cancel
        mock_window.return_value.run.return_value = mock_result
        
        result = choose_date_dialog(default_days=7)
        
        assert result is None


class TestFolderDialog:
    """Test folder picker dialog."""

    @patch("builtins.__import__")
    def test_choose_folder_returns_path_via_import(self, mock_import):
        """Returns path when user selects folder (via import mock)."""
        mock_appkit = MagicMock()
        mock_panel = MagicMock()
        mock_appkit.NSOpenPanel.openPanel.return_value = mock_panel
        mock_panel.runModal.return_value = 1  # NSModalResponseOK
        
        mock_url = MagicMock()
        mock_url.path.return_value = "/Users/test/Documents"
        mock_panel.URLs.return_value = [mock_url]
        
        def import_side_effect(name, *args, **kwargs):
            if name == "AppKit":
                return mock_appkit
            return __import__(name, *args, **kwargs)
        
        mock_import.side_effect = import_side_effect
        
        result = choose_folder_dialog()
        
        assert result == "/Users/test/Documents"

    @patch("builtins.__import__")
    def test_choose_folder_cancelled(self, mock_import):
        """Returns None when user cancels."""
        mock_appkit = MagicMock()
        mock_panel = MagicMock()
        mock_appkit.NSOpenPanel.openPanel.return_value = mock_panel
        mock_panel.runModal.return_value = 0  # Cancelled
        
        def import_side_effect(name, *args, **kwargs):
            if name == "AppKit":
                return mock_appkit
            return __import__(name, *args, **kwargs)
        
        mock_import.side_effect = import_side_effect
        
        result = choose_folder_dialog()
        
        assert result is None

    @patch("builtins.__import__", side_effect=ImportError("No module named AppKit"))
    def test_choose_folder_fallback_without_appkit(self, mock_import):
        """Returns None when AppKit not available."""
        result = choose_folder_dialog()
        
        assert result is None


class TestAboutDialog:
    """Test About dialog."""

    @patch("src.ui.dialogs.rumps.alert")
    def test_show_about_dialog(self, mock_alert):
        """About dialog shows correct information."""
        show_about_dialog()
        
        mock_alert.assert_called_once()
        call_args = mock_alert.call_args
        assert "About Timshel" in call_args[1]["title"] or call_args[0][0] == "About Timshel"
        assert TEXTS["about_message"] in call_args[1]["message"] or call_args[0][1] == TEXTS["about_message"]

