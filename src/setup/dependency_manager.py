"""Async dependency orchestration shared by wizard and menu app."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Optional

from src.logger import logger
from src.setup.checksums import CHECKSUMS
from src.setup.downloader import DependencyDownloader
from src.setup.errors import DependencyRuntimeError

ProgressCallback = Callable[[str, float], None]
DoneCallback = Callable[[], None]
ErrorCallback = Callable[[Exception], None]


@dataclass
class DependencyStatus:
    """Snapshot of dependency state for selected model."""

    ready: bool
    missing: list[tuple[str, int]]

    @property
    def total_missing_size(self) -> int:
        return sum(size for _, size in self.missing)


@dataclass
class HealthStatus:
    """Result of deep integrity check (existence + checksum + runtime)."""

    ok: bool
    reason: Optional[str] = None
    needs_whisper_repair: bool = False


class DependencyManager:
    """Single source of truth for dependency checks and background downloads."""

    def __init__(self, downloader: Optional[DependencyDownloader] = None):
        self._downloader = downloader or DependencyDownloader()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._is_downloading = False
        self._last_error: Optional[Exception] = None

    def status(self) -> DependencyStatus:
        """Return current dependency status for selected model."""
        missing = self._downloader.missing_for_selected_model()
        return DependencyStatus(ready=len(missing) == 0, missing=missing)

    def needed(self) -> list[tuple[str, int]]:
        """Alias: list missing artifacts."""
        return self.status().missing

    def health_check(self) -> HealthStatus:
        """Deep integrity check: existence, checksums, runtime startup.

        Wykrywa scenariusz w którym whisper-cli istnieje fizycznie, ale
        nie startuje (np. broken @rpath, mismatch wersji), albo plik
        zostawiony przez wcześniejszą wersję ma niezgodny checksum.

        Płytki `status()` (oparty o samo istnienie pliku) tego nie wykryje.
        """
        # Plik fizycznie obecny + ffmpeg + model dla wybranej konfiguracji.
        if not self.status().ready:
            return HealthStatus(
                ok=False,
                reason="Brakuje wymaganych zależności (whisper / ffmpeg / model).",
                needs_whisper_repair=False,
            )

        whisper_path = self._downloader.bin_dir / "whisper-cli"
        whisper_checksum = CHECKSUMS.get("whisper-cli")
        if whisper_checksum and not self._downloader.verify_checksum(
            whisper_path, whisper_checksum
        ):
            return HealthStatus(
                ok=False,
                reason="Plik whisper-cli ma niezgodny checksum (uszkodzony lub stary build).",
                needs_whisper_repair=True,
            )

        try:
            self._downloader.verify_whisper_runtime()
        except DependencyRuntimeError as exc:
            return HealthStatus(
                ok=False,
                reason=f"whisper-cli nie startuje: {exc}",
                needs_whisper_repair=True,
            )

        return HealthStatus(ok=True)

    def repair_whisper_async(
        self,
        on_progress: Optional[ProgressCallback] = None,
        on_done: Optional[DoneCallback] = None,
        on_error: Optional[ErrorCallback] = None,
    ) -> bool:
        """Wymuś usunięcie i ponowne pobranie whisper-cli w tle.

        Returns False gdy w tle coś już jest pobierane.
        """
        with self._lock:
            if self._is_downloading:
                return False
            self._is_downloading = True
            self._last_error = None

        def run() -> None:
            try:
                self._downloader.progress_callback = on_progress
                # force=True: cleanup dzieje się WEWNĄTRZ locka instalacyjnego
                # downloadera. Zewnętrzny _cleanup_bundled_whisper() potrafił
                # skasować świeżo rozpakowane binarki równoległej instalacji
                # (trzy instancje DependencyManagera żyją w jednym procesie).
                self._downloader.download_whisper(force=True)
                if on_done:
                    on_done()
            except Exception as exc:
                logger.error("Whisper repair failed: %s", exc, exc_info=True)
                with self._lock:
                    self._last_error = exc
                if on_error:
                    on_error(exc)
            finally:
                with self._lock:
                    self._is_downloading = False

        self._thread = threading.Thread(target=run, daemon=True, name="WhisperRepair")
        self._thread.start()
        return True

    def is_downloading(self) -> bool:
        with self._lock:
            return self._is_downloading

    def last_error(self) -> Optional[Exception]:
        with self._lock:
            return self._last_error

    def download_async(
        self,
        on_progress: Optional[ProgressCallback] = None,
        on_done: Optional[DoneCallback] = None,
        on_error: Optional[ErrorCallback] = None,
    ) -> bool:
        """Start dependency download in background thread.

        Returns False when download is already in progress.
        """
        with self._lock:
            if self._is_downloading:
                return False
            self._is_downloading = True
            self._last_error = None

        def run() -> None:
            try:
                self._downloader.progress_callback = on_progress
                self._downloader.download_all()
                if on_done:
                    on_done()
            except Exception as exc:  # pragma: no cover - guarded by callers
                logger.error("Dependency download failed: %s", exc, exc_info=True)
                with self._lock:
                    self._last_error = exc
                if on_error:
                    on_error(exc)
            finally:
                with self._lock:
                    self._is_downloading = False

        self._thread = threading.Thread(
            target=run, daemon=True, name="DependencyDownload"
        )
        self._thread.start()
        return True
