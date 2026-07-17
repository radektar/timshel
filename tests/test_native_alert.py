"""Tests for the crash-safe rumps.alert replacement (src/ui/native_alert)."""

from src.ui.native_alert import _FIRST_BUTTON, map_response


class TestMapResponse:
    def test_ok_button_maps_to_rumps_one(self):
        assert map_response(_FIRST_BUTTON) == 1

    def test_cancel_button_maps_to_rumps_zero(self):
        assert map_response(_FIRST_BUTTON + 1) == 0

    def test_other_button_maps_to_rumps_minus_one(self):
        assert map_response(_FIRST_BUTTON + 2) == -1

    def test_unknown_code_passes_through(self):
        # NSModalResponseStop etc. — a caller comparing == 1 must fail safe.
        assert map_response(-1000) == -1000
        assert map_response(0) == 0


class TestInstall:
    def test_install_patches_rumps_alert_when_available(self, monkeypatch):
        import types

        fake_rumps = types.SimpleNamespace(alert=lambda **kw: 1)
        import sys

        monkeypatch.setitem(sys.modules, "rumps", fake_rumps)
        try:
            import AppKit  # noqa: F401
        except ImportError:
            import pytest

            pytest.skip("AppKit unavailable — install() is a documented no-op")
        from src.ui.native_alert import alert, install

        assert install() is True
        assert fake_rumps.alert is alert
