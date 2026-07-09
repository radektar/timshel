"""Regression tests for menu app async dependency downloads."""

from types import SimpleNamespace

from src.menu_app import TimshelMenuApp


def test_download_dependencies_starts_async_manager(monkeypatch):
    started = {"value": False}

    class FakeManager:
        def download_async(self, on_progress=None, on_done=None, on_error=None):
            started["value"] = True
            if on_progress:
                on_progress("ffmpeg", 0.5)
            return True

    class FakeWindow:
        def __init__(self, title, detail):
            self.title = title
            self.detail = detail
            self.shown = False

        def show(self):
            self.shown = True

        def update(self, detail=None, progress=None):
            return None

        def close(self):
            return None

    app = TimshelMenuApp.__new__(TimshelMenuApp)
    app._download_active = False
    app._download_manager = FakeManager()
    app.status_item = SimpleNamespace(title="")
    app._download_window = None
    app._update_icon = lambda _status: None

    monkeypatch.setattr("src.menu_app.DownloadWindow", FakeWindow)

    TimshelMenuApp._download_dependencies(app)

    assert started["value"] is True
    assert "Downloading" in app.status_item.title
    assert app._download_active is True

