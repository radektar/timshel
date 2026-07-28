"""Tests for dependency manager orchestration."""

import threading

from src.setup.dependency_manager import DependencyManager


class FakeDownloader:
    def __init__(self):
        self.progress_callback = None
        self.download_called = False

    def missing_for_selected_model(self):
        return [("ffmpeg-arm64", 100)]

    def download_all(self):
        self.download_called = True
        if self.progress_callback:
            self.progress_callback("ffmpeg", 1.0)


def test_status_reports_missing_artifacts():
    manager = DependencyManager(downloader=FakeDownloader())
    status = manager.status()
    assert status.ready is False
    assert status.total_missing_size == 100


def test_download_async_calls_callbacks():
    downloader = FakeDownloader()
    manager = DependencyManager(downloader=downloader)
    done = threading.Event()
    progress = []

    started = manager.download_async(
        on_progress=lambda name, pct: progress.append((name, pct)),
        on_done=lambda: done.set(),
    )

    assert started is True
    assert done.wait(timeout=2)
    assert downloader.download_called is True
    assert progress and progress[-1][1] == 1.0
