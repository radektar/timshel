import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from src.config.license import LicenseManager
from src.config.features import FeatureTier


class TestLicenseManager:
    @pytest.fixture
    def mock_paths(self, tmp_path):
        """Mock license and cache paths to use a temporary directory."""
        license_dir = tmp_path / "Malinche"
        license_dir.mkdir()

        with patch.object(
            LicenseManager, "_license_path", return_value=license_dir / "license.json"
        ), patch.object(
            LicenseManager,
            "_cache_path",
            return_value=license_dir / "license_cache.json",
        ):
            yield license_dir

    def test_default_tier_is_pro_during_beta(self, mock_paths):
        """Beta grants PRO to every install (no licensing backend yet)."""
        manager = LicenseManager()
        assert manager.get_current_tier() == FeatureTier.PRO
        assert manager.get_features().ai_summaries is True

    def test_get_features_returns_correct_flags(self, mock_paths):
        """get_features should return flags for the current tier."""
        manager = LicenseManager()
        # Mocking verify to return PRO
        with patch.object(manager, "_verify_license", return_value=FeatureTier.PRO):
            features = manager.get_features()
            assert features.ai_summaries is True

    def test_activate_license_placeholder(self, mock_paths):
        """activate_license should return failure in v2.0.0 FREE placeholder."""
        manager = LicenseManager()
        success, message = manager.activate_license("TEST-KEY")
        assert success is False
        assert "nie jest jeszcze dostępna" in message

    def test_deactivate_license(self, mock_paths):
        """deactivate_license should clear key, tier and files."""
        license_file = mock_paths / "license.json"
        cache_file = mock_paths / "license_cache.json"

        license_file.write_text(json.dumps({"key": "test"}), encoding="utf-8")
        cache_file.write_text(
            json.dumps({"tier": "pro", "expires": "2099-01-01"}), encoding="utf-8"
        )

        manager = LicenseManager()
        # Force cache load
        manager.get_current_tier()

        manager.deactivate_license()
        assert manager._license_key is None
        assert manager._cached_tier == FeatureTier.FREE
        assert not license_file.exists()
        assert not cache_file.exists()

    def test_offline_cache_grace_period(self, mock_paths):
        """Cache should be respected if not expired."""
        cache_file = mock_paths / "license_cache.json"
        from datetime import datetime, timedelta

        future = (datetime.now() + timedelta(days=5)).isoformat()

        cache_file.write_text(
            json.dumps({"tier": "pro", "expires": future}), encoding="utf-8"
        )

        manager = LicenseManager()
        assert manager.get_current_tier() == FeatureTier.PRO

    def test_expired_cache_ignored(self, mock_paths):
        """Expired cache should be ignored."""
        cache_file = mock_paths / "license_cache.json"
        from datetime import datetime, timedelta

        past = (datetime.now() - timedelta(days=1)).isoformat()

        cache_file.write_text(
            json.dumps({"tier": "pro", "expires": past}), encoding="utf-8"
        )

        manager = LicenseManager()
        # Expired cache is ignored, falling back to the beta PRO default.
        assert manager.get_current_tier() == FeatureTier.PRO

    def test_get_usage_limits(self, mock_paths):
        """get_usage_limits should return correct limits for each tier."""
        manager = LicenseManager()

        with patch.object(manager, "get_current_tier", return_value=FeatureTier.FREE):
            limits = manager.get_usage_limits()
            assert limits["minutes_monthly"] == 0

        with patch.object(manager, "get_current_tier", return_value=FeatureTier.PRO):
            limits = manager.get_usage_limits()
            assert limits["minutes_monthly"] == 300

        with patch.object(
            manager, "get_current_tier", return_value=FeatureTier.PRO_ORG
        ):
            limits = manager.get_usage_limits()
            assert limits["minutes_monthly"] == 1000
            assert limits["unlimited"] is True

    def test_save_license(self, mock_paths):
        """_save_license should write key to file."""
        manager = LicenseManager()
        manager._license_key = "SAVE-TEST-KEY"
        manager._save_license()

        license_file = mock_paths / "license.json"
        assert license_file.exists()
        data = json.loads(license_file.read_text(encoding="utf-8"))
        assert data["key"] == "SAVE-TEST-KEY"

    def test_save_cache(self, mock_paths):
        """_save_cache should write tier and expiry to file."""
        manager = LicenseManager()
        manager._save_cache(FeatureTier.PRO_ORG)

        cache_file = mock_paths / "license_cache.json"
        assert cache_file.exists()
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert data["tier"] == "pro_org"
        assert "expires" in data

    def test_corrupted_files_handling(self, mock_paths):
        """Manager should handle corrupted json files gracefully."""
        license_file = mock_paths / "license.json"
        cache_file = mock_paths / "license_cache.json"

        license_file.write_text("not json", encoding="utf-8")
        cache_file.write_text("{invalid json", encoding="utf-8")

        manager = LicenseManager()
        assert manager._license_key is None
        # Corrupt files are ignored gracefully → beta PRO default applies.
        assert manager.get_current_tier() == FeatureTier.PRO
