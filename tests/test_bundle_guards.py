"""Tester-log regressions: pip-in-bundle and the self-installer volume prompt.

Both bugs surfaced in the 2026-07-16 tester log: the bundled app ERROR-logged
a doomed `python -m pip` on every launch, and the volume detector prompted
"Is 'Timshel Installer' a recorder?" about its own mounted DMG.
"""

import plistlib
from pathlib import Path
from unittest.mock import MagicMock, patch

from src import runtime_deps
from src.file_monitor import is_disk_image_volume


class TestBundledPipGuard:
    def test_bundled_app_skips_pip(self, monkeypatch):
        monkeypatch.setattr(runtime_deps.sys, "frozen", "macosx_app", raising=False)
        monkeypatch.setitem(
            runtime_deps.SAFEGUARDED_PACKAGES, "surely_missing_mod", "surely-missing"
        )

        def _boom(*a, **k):  # pragma: no cover - fails the test if reached
            raise AssertionError("pip must not run inside the bundle")

        monkeypatch.setattr(runtime_deps, "_pip_install", _boom)
        assert runtime_deps.ensure_importable("surely_missing_mod") is False

    def test_dev_run_still_tries_pip(self, monkeypatch):
        monkeypatch.delattr(runtime_deps.sys, "frozen", raising=False)
        monkeypatch.setitem(
            runtime_deps.SAFEGUARDED_PACKAGES, "surely_missing_mod", "surely-missing"
        )
        calls = []
        monkeypatch.setattr(
            runtime_deps, "_pip_install", lambda spec, target: calls.append(spec) or False
        )
        assert runtime_deps.ensure_importable("surely_missing_mod") is False
        assert calls == ["surely-missing"]

    def test_already_importable_short_circuits(self, monkeypatch):
        monkeypatch.setattr(runtime_deps.sys, "frozen", "macosx_app", raising=False)
        assert runtime_deps.ensure_importable("json") is True


def _hdiutil_plist(mount_points):
    return plistlib.dumps(
        {
            "images": [
                {
                    "system-entities": [
                        {"mount-point": mp} for mp in mount_points
                    ]
                }
            ]
        }
    )


class TestDiskImageVolume:
    def test_mounted_dmg_is_detected(self):
        fake = MagicMock(returncode=0, stdout=_hdiutil_plist(["/Volumes/Timshel Installer"]))
        with patch("subprocess.run", return_value=fake):
            assert is_disk_image_volume(Path("/Volumes/Timshel Installer")) is True

    def test_real_disk_is_not_a_disk_image(self):
        fake = MagicMock(returncode=0, stdout=_hdiutil_plist(["/Volumes/Timshel Installer"]))
        with patch("subprocess.run", return_value=fake):
            assert is_disk_image_volume(Path("/Volumes/LS-P1")) is False

    def test_hdiutil_failure_fails_open(self):
        # Detection must never block a real recorder — errors mean "not an image".
        with patch("subprocess.run", side_effect=OSError("no hdiutil")):
            assert is_disk_image_volume(Path("/Volumes/LS-P1")) is False
        fake = MagicMock(returncode=1, stdout=b"")
        with patch("subprocess.run", return_value=fake):
            assert is_disk_image_volume(Path("/Volumes/LS-P1")) is False

    def test_entities_without_mount_point_are_skipped(self):
        payload = plistlib.dumps(
            {"images": [{"system-entities": [{"dev-entry": "/dev/disk4"}]}]}
        )
        fake = MagicMock(returncode=0, stdout=payload)
        with patch("subprocess.run", return_value=fake):
            assert is_disk_image_volume(Path("/Volumes/LS-P1")) is False


class TestBuildStamp:
    """bundle_build_stamp is exception-safe and empty outside a real bundle."""

    def test_returns_empty_string_in_dev_run(self):
        from src.bootstrap import bundle_build_stamp

        # In tests there is no Timshel bundle, so the plist key is absent.
        assert bundle_build_stamp() == ""

    def test_returns_plist_value_when_present(self):
        from src import bootstrap

        bundle = MagicMock()
        bundle.objectForInfoDictionaryKey_.return_value = "abc1234 2026-07-17 10:00"
        fake_foundation = MagicMock()
        fake_foundation.NSBundle.mainBundle.return_value = bundle
        with patch.dict("sys.modules", {"Foundation": fake_foundation}):
            assert bootstrap.bundle_build_stamp() == "abc1234 2026-07-17 10:00"
