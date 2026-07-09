"""Dependency downloader for whisper.cpp and ffmpeg."""

import hashlib
import platform
import shutil
import socket
import subprocess
import tarfile
import time
import zipfile
from pathlib import Path
from typing import Callable, Optional

import httpx

from src.config.settings import UserSettings
from src.logger import logger
from src.setup.checksums import CHECKSUMS, MODEL_ALIASES, SIZES, URLS, VERSIONS
from src.setup.errors import (
    ChecksumError,
    DependencyRuntimeError,
    DiskSpaceError,
    DownloadError,
    NetworkError,
)

# Minimalna ilość miejsca na dysku (500MB)
MIN_DISK_SPACE_BYTES = 500_000_000

# Timeouty
CHUNK_TIMEOUT = 30  # sekundy
TOTAL_TIMEOUT = 1800  # 30 minut dla dużego modelu
MAX_RETRIES = 3


class DependencyDownloader:
    """Pobieranie i weryfikacja zależności."""

    def __init__(
        self,
        progress_callback: Optional[Callable[[str, float], None]] = None,
    ):
        """Inicjalizacja downloadera.

        Args:
            progress_callback: Funkcja wywoływana z postępem pobierania.
                               Przyjmuje (name: str, progress: float 0.0-1.0)
        """
        self.progress_callback = progress_callback
        self.support_dir = (
            Path.home() / "Library" / "Application Support" / "Timshel"
        )
        self.bin_dir = self.support_dir / "bin"
        self.models_dir = self.support_dir / "models"
        self.downloads_dir = self.support_dir / "downloads"

        # Utwórz katalogi
        self.bin_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)

    def check_network(self) -> bool:
        """Sprawdź czy jest połączenie z internetem.

        Returns:
            True jeśli połączenie dostępne, False w przeciwnym razie

        Raises:
            NetworkError: Jeśli brak połączenia
        """
        try:
            # Try connecting to Google DNS
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            return True
        except OSError:
            raise NetworkError("No internet connection")

    def check_disk_space(self, required_bytes: int = MIN_DISK_SPACE_BYTES) -> bool:
        """Sprawdź czy jest wystarczająco miejsca na dysku.

        Args:
            required_bytes: Wymagana ilość miejsca w bajtach

        Returns:
            True jeśli jest wystarczająco miejsca

        Raises:
            DiskSpaceError: Jeśli brak miejsca
        """
        stat = shutil.disk_usage(self.support_dir)
        free_bytes = stat.free

        if free_bytes < required_bytes:
            raise DiskSpaceError(
                f"Not enough disk space. "
                f"Available: {free_bytes / 1_000_000:.1f}MB, "
                f"Required: {required_bytes / 1_000_000:.1f}MB"
            )

        return True

    def verify_checksum(self, file_path: Path, expected_checksum: str) -> bool:
        """Zweryfikuj checksum pliku (sha256 lub sha1).

        Args:
            file_path: Ścieżka do pliku
            expected_checksum: Oczekiwany checksum (sha256/sha1)

        Returns:
            True jeśli checksum się zgadza, False w przeciwnym razie
        """
        if not expected_checksum:
            logger.warning(
                f"Brak checksum dla {file_path.name}, pomijam weryfikację"
            )
            return True

        algo = "sha256"
        expected_hash = expected_checksum.lower()
        if ":" in expected_hash:
            algo, expected_hash = expected_hash.split(":", 1)

        try:
            digest = hashlib.new(algo)
        except ValueError:
            logger.error(f"Nieobsługiwany algorytm checksum: {algo}")
            return False

        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    digest.update(chunk)
        except IOError as e:
            logger.error(f"Błąd podczas czytania pliku {file_path}: {e}")
            return False

        actual_checksum = digest.hexdigest()
        return actual_checksum == expected_hash

    def is_whisper_installed(self) -> bool:
        """Sprawdź czy whisper.cpp jest zainstalowany.

        Returns:
            True jeśli whisper-cli istnieje i ma rozmiar > 0
        """
        whisper_path = self.bin_dir / "whisper-cli"
        return whisper_path.exists() and whisper_path.stat().st_size > 0

    def _expected_whisper_dylibs(self) -> list[str]:
        """Return dylibs required by bundled whisper distribution."""
        return [
            "libwhisper.1.dylib",
            "libwhisper.coreml.dylib",
            "libggml.0.dylib",
            "libggml-base.0.dylib",
            "libggml-cpu.0.dylib",
            "libggml-blas.0.dylib",
            "libggml-metal.0.dylib",
        ]

    def _whisper_distribution(self) -> str:
        """Return selected whisper distribution mode.

        Supported values:
            - "static": single standalone binary
            - "bundled": tar.gz with whisper-cli + dylibs
        """
        return VERSIONS.get("whisper_distribution", "static")

    def _is_bundled_install_complete(self) -> bool:
        """Check if bundled installation has all companion dylibs."""
        if not self.is_whisper_installed():
            return False
        return all((self.bin_dir / name).exists() for name in self._expected_whisper_dylibs())

    def is_ffmpeg_installed(self) -> bool:
        """Sprawdź czy ffmpeg jest zainstalowany.

        Returns:
            True jeśli ffmpeg istnieje i ma rozmiar > 0
        """
        ffmpeg_path = self.bin_dir / "ffmpeg"
        return ffmpeg_path.exists() and ffmpeg_path.stat().st_size > 0

    def _selected_model(self) -> str:
        """Return model selected in user settings, fallback to small."""
        try:
            model = UserSettings.load().whisper_model
        except Exception:
            return "small"
        return model or "small"

    def _canonical_model(self, model: Optional[str] = None) -> str:
        """Map user-facing model key to canonical whisper.cpp artifact key."""
        selected = model or self._selected_model()
        return MODEL_ALIASES.get(selected, selected)

    def is_model_installed(self, model: Optional[str] = None) -> bool:
        """Sprawdź czy model jest pobrany.

        Args:
            model: Nazwa modelu; gdy None, używa ustawienia użytkownika.

        Returns:
            True jeśli model istnieje
        """
        selected_model = self._canonical_model(model)
        model_path = self.models_dir / f"ggml-{selected_model}.bin"
        return model_path.exists()

    def is_model_encoder_installed(self, model: Optional[str] = None) -> bool:
        """Sprawdź czy CoreML encoder dla modelu jest zainstalowany.

        Args:
            model: Nazwa modelu; gdy None, używa ustawienia użytkownika.

        Returns:
            True jeśli katalog encodera istnieje lub model nie ma encodera
        """
        canonical = self._canonical_model(model)
        if not URLS.get(f"model_{canonical}_encoder") and not URLS.get(f"model_{model}_encoder"):
            return True  # Model nie ma encodera — nie wymagany
        encoder_dir = self.models_dir / f"ggml-{canonical}-encoder.mlmodelc"
        return encoder_dir.exists() and encoder_dir.is_dir()

    def download_model_encoder(self, model: str) -> bool:
        """Pobierz i zainstaluj CoreML encoder dla modelu.

        Encoder jest wymagany gdy whisper-cli skompilowano z WHISPER_COREML=ON.
        Plik zip jest pobierany do downloads_dir, rozpakowywany do models_dir,
        a następnie usuwany.

        Args:
            model: Nazwa modelu (np. "small", "base", "medium").

        Returns:
            True jeśli encoder zainstalowany lub nie jest wymagany dla tego modelu.
        """
        canonical = self._canonical_model(model)
        url_key = f"model_{model}_encoder"
        url = URLS.get(url_key)
        if not url:
            logger.debug(f"Brak CoreML encodera dla modelu {model} — pomijam")
            return True

        if self.is_model_encoder_installed(model):
            logger.info(f"CoreML encoder dla {model} już zainstalowany")
            return True

        zip_key = f"ggml-{canonical}-encoder.mlmodelc.zip"
        expected_size = SIZES.get(zip_key)
        expected_checksum = CHECKSUMS.get(zip_key)

        zip_dest = self.downloads_dir / zip_key
        self._download_file(url, zip_dest, f"encoder-{canonical}", expected_size, expected_checksum)

        logger.info(f"Rozpakowywanie CoreML encodera dla {model}...")
        with zipfile.ZipFile(zip_dest, "r") as zf:
            zf.extractall(self.models_dir)

        zip_dest.unlink(missing_ok=True)
        logger.info(f"✓ CoreML encoder dla {model} zainstalowany")
        return True

    def missing_for_selected_model(self) -> list[tuple[str, int]]:
        """Return missing artifacts required for current selected model.

        Returns:
            List of tuples (artifact_key, expected_size_bytes).
        """
        missing: list[tuple[str, int]] = []

        whisper_ok = (
            self._is_bundled_install_complete()
            if self._whisper_distribution() == "bundled"
            else self.is_whisper_installed()
        )
        if not whisper_ok:
            whisper_key = (
                "whisper-bundled-arm64.tar.gz"
                if self._whisper_distribution() == "bundled"
                else "whisper-cli"
            )
            missing.append((whisper_key, int(SIZES.get(whisper_key, 0))))

        if not self.is_ffmpeg_installed():
            missing.append(("ffmpeg-arm64", int(SIZES.get("ffmpeg-arm64", 0))))

        selected_model = self._selected_model()
        canonical_model = self._canonical_model(selected_model)
        model_key = f"ggml-{canonical_model}.bin"
        if not self.is_model_installed(selected_model):
            missing.append((model_key, int(SIZES.get(model_key, 0))))

        encoder_key = f"ggml-{canonical_model}-encoder.mlmodelc.zip"
        if not self.is_model_encoder_installed(selected_model) and SIZES.get(encoder_key):
            missing.append((encoder_key, int(SIZES.get(encoder_key, 0))))

        return missing

    def required_size_for_selected_model(self) -> int:
        """Total expected download size in bytes for currently missing artifacts."""
        return sum(size for _, size in self.missing_for_selected_model())

    def check_all(self) -> bool:
        """Sprawdź czy wszystkie zależności są zainstalowane i zweryfikowane.

        Returns:
            True jeśli wszystkie zależności są dostępne i mają poprawne checksumy
        """
        # Sprawdź czy pliki istnieją
        if self._whisper_distribution() == "bundled":
            whisper_present = self._is_bundled_install_complete()
        else:
            whisper_present = self.is_whisper_installed()

        selected_model = self._canonical_model(self._selected_model())
        if not (
            whisper_present
            and self.is_ffmpeg_installed()
            and self.is_model_installed(selected_model)
        ):
            return False
        
        # Weryfikuj checksumy
        whisper_path = self.bin_dir / "whisper-cli"
        ffmpeg_path = self.bin_dir / "ffmpeg"
        model_path = self.models_dir / f"ggml-{selected_model}.bin"
        
        whisper_checksum = CHECKSUMS.get("whisper-cli")
        ffmpeg_checksum = CHECKSUMS.get("ffmpeg-arm64")
        model_checksum = CHECKSUMS.get(f"ggml-{selected_model}.bin")
        
        # Weryfikuj whisper-cli
        if whisper_checksum:
            if not self.verify_checksum(whisper_path, whisper_checksum):
                logger.warning(
                    "Checksum whisper-cli się nie zgadza - plik może być uszkodzony"
                )
                return False
        
        # Weryfikuj ffmpeg
        if ffmpeg_checksum:
            if not self.verify_checksum(ffmpeg_path, ffmpeg_checksum):
                logger.warning(
                    "Checksum ffmpeg się nie zgadza - plik może być uszkodzony"
                )
                return False
        
        # Weryfikuj model
        if model_checksum:
            if not self.verify_checksum(model_path, model_checksum):
                logger.warning(
                    "Checksum modelu się nie zgadza - plik może być uszkodzony"
                )
                return False
        
        try:
            self.verify_whisper_runtime()
        except DependencyRuntimeError as error:
            logger.warning("Runtime check whisper-cli failed in check_all(): %s", error)
            return False

        return True

    def verify_whisper_runtime(self) -> None:
        """Ensure whisper-cli can start and link runtime dependencies."""
        binary = self.bin_dir / "whisper-cli"
        if not binary.exists():
            raise DependencyRuntimeError("whisper-cli does not exist")

        try:
            result = subprocess.run(
                [str(binary), "--help"],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise DependencyRuntimeError(
                f"Cannot launch whisper-cli: {error}"
            ) from error

        if result.returncode == 0:
            return

        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        stdout = result.stdout.decode("utf-8", errors="replace").strip()
        details = stderr or stdout or f"exit code {result.returncode}"
        raise DependencyRuntimeError(
            f"whisper-cli installed but cannot start: {details}"
        )

    def _cleanup_bundled_whisper(self) -> None:
        """Remove whisper binary and companion dylibs before reinstall."""
        for name in ["whisper-cli", *self._expected_whisper_dylibs()]:
            target = self.bin_dir / name
            try:
                if target.exists():
                    target.unlink()
            except OSError:
                logger.debug("Could not remove previous bundled artifact: %s", target)

    def _extract_whisper_bundle(self, archive_path: Path) -> None:
        """Extract bundled whisper tarball into bin directory safely."""
        self.bin_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "r:gz") as tar:
            for member in tar.getmembers():
                member_path = Path(member.name)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise DownloadError(
                        f"Unsafe path in whisper archive: {member.name}"
                    )
            try:
                tar.extractall(self.bin_dir, filter="data")
            except TypeError:
                tar.extractall(self.bin_dir)

        whisper_path = self.bin_dir / "whisper-cli"
        if whisper_path.exists():
            whisper_path.chmod(0o755)

    def _download_file(
        self,
        url: str,
        dest: Path,
        name: str,
        expected_size: Optional[int] = None,
        expected_checksum: Optional[str] = None,
    ) -> None:
        """Pobierz plik z progress callback i retry logic.

        Args:
            url: URL do pobrania
            dest: Ścieżka docelowa
            name: Nazwa pliku (dla progress callback)
            expected_size: Oczekiwany rozmiar pliku (opcjonalnie)
            expected_checksum: Oczekiwany checksum (opcjonalnie)

        Raises:
            DownloadError: Jeśli pobieranie się nie powiodło
            ChecksumError: Jeśli checksum się nie zgadza
        """
        temp_path = self.downloads_dir / f"{dest.name}.tmp"

        # Sprawdź czy istnieje częściowe pobieranie
        resume_from = 0
        if temp_path.exists():
            resume_from = temp_path.stat().st_size
            if expected_size and resume_from >= expected_size:
                # Plik wydaje się kompletny, sprawdź checksum
                logger.info(f"Znaleziono kompletny plik tymczasowy {temp_path}")
                if expected_checksum and self.verify_checksum(
                    temp_path, expected_checksum
                ):
                    # Przenieś do docelowej lokalizacji
                    temp_path.rename(dest)
                    dest.chmod(0o755)
                    logger.info(f"✓ Pobrano {name}")
                    return
                else:
                    # Uszkodzony, usuń i zacznij od nowa
                    logger.warning("Uszkodzony plik tymczasowy, usuwam")
                    temp_path.unlink()
                    resume_from = 0

        # Sprawdź połączenie sieciowe
        self.check_network()

        # Sprawdź miejsce na dysku
        if expected_size:
            self.check_disk_space(expected_size)

        # Pobieranie z retry
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info(
                    f"Pobieranie {name} (próba {attempt}/{MAX_RETRIES})..."
                )

                # Przygotuj headers
                headers = {"User-Agent": "Timshel/2.0.0 (macOS; ARM64)"}
                if resume_from > 0:
                    headers["Range"] = f"bytes={resume_from}-"
                    logger.info(f"Wznawianie pobierania od bajtu {resume_from}")

                # Pobierz plik przez httpx (z automatycznym follow redirects)
                with httpx.stream(
                    "GET",
                    url,
                    headers=headers,
                    timeout=CHUNK_TIMEOUT,
                    follow_redirects=True,
                ) as response:
                    # Sprawdź kod odpowiedzi
                    if response.status_code == 416:  # Range Not Satisfiable
                        # Plik już kompletny, usuń .tmp i sprawdź
                        if temp_path.exists():
                            temp_path.unlink()
                        resume_from = 0
                        continue

                    # Sprawdź czy sukces
                    response.raise_for_status()

                    # Otwórz plik w trybie append jeśli resume
                    mode = "ab" if resume_from > 0 else "wb"
                    with open(temp_path, mode) as f:
                        total_size = (
                            int(response.headers.get("Content-Length", 0))
                            + resume_from
                        )
                        downloaded = resume_from
                        last_reported_percent = -1

                        # Pobierz w chunkach
                        for chunk in response.iter_bytes(chunk_size=8192):
                            f.write(chunk)
                            downloaded += len(chunk)

                            # Progress callback - tylko gdy procent się zmieni
                            if self.progress_callback and total_size > 0:
                                current_percent = int(downloaded * 100 / total_size)
                                if current_percent != last_reported_percent:
                                    last_reported_percent = current_percent
                                    progress = downloaded / total_size
                                    self.progress_callback(name, progress)

                # Przenieś do docelowej lokalizacji
                temp_path.rename(dest)
                dest.chmod(0o755)

                # Weryfikuj checksum jeśli dostępny
                if expected_checksum:
                    if not self.verify_checksum(dest, expected_checksum):
                        logger.error(f"Błędny checksum dla {name}")
                        dest.unlink()
                        raise ChecksumError(
                            f"Checksum nie zgadza się dla {name}"
                        )

                logger.info(f"✓ Pobrano {name}")
                return

            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500 and attempt < MAX_RETRIES:
                    # Serwer niedostępny, retry z backoff
                    wait_time = 2 ** (attempt - 1)
                    logger.warning(
                        f"Server unavailable ({e.response.status_code}), "
                        f"retry in {wait_time}s…"
                    )
                    time.sleep(wait_time)
                    continue
                raise DownloadError(
                    f"HTTP error {e.response.status_code}: {e.response.reason_phrase}"
                )

            except (httpx.NetworkError, httpx.ConnectError) as e:
                if attempt < MAX_RETRIES:
                    wait_time = 2 ** (attempt - 1)
                    logger.warning(
                        f"Connection error, retry in {wait_time}s…"
                    )
                    time.sleep(wait_time)
                    continue
                raise NetworkError(f"Connection error: {e}")

            except (httpx.TimeoutException, TimeoutError):
                if attempt < MAX_RETRIES:
                    logger.warning(f"Timeout, retry {attempt + 1}/{MAX_RETRIES}")
                    continue
                raise DownloadError(f"Timeout while downloading {name}")

            except Exception as e:
                logger.error(f"Unexpected error while downloading {name}: {e}")
                if attempt < MAX_RETRIES:
                    continue
                raise DownloadError(f"Error while downloading {name}: {e}")

        raise DownloadError(
            f"Failed to download {name} after {MAX_RETRIES} attempts"
        )

    def download_whisper(self) -> bool:
        """Pobierz whisper.cpp binary.

        Returns:
            True jeśli pobieranie się powiodło

        Raises:
            RuntimeError: Jeśli architektura nie jest ARM64
            DownloadError: Jeśli pobieranie się nie powiodło
        """
        arch = platform.machine()
        if arch != "arm64":
            raise RuntimeError(f"Nieobsługiwana architektura: {arch}")

        distribution = self._whisper_distribution()
        url = URLS["whisper"]
        dest = self.bin_dir / "whisper-cli"
        expected_size = SIZES.get("whisper-cli")
        expected_checksum = CHECKSUMS.get("whisper-cli")

        if distribution == "bundled":
            archive_name = "whisper-bundled-arm64.tar.gz"
            archive_dest = self.downloads_dir / archive_name
            expected_size = SIZES.get(archive_name)
            expected_checksum = CHECKSUMS.get(archive_name)

            # Broken migration: existing bare whisper-cli from old deps-v1.0.0.
            if self.is_whisper_installed() and not self._is_bundled_install_complete():
                logger.warning(
                    "Wykryto niekompletną instalację whisper-cli (brak dylib), "
                    "wymuszam ponowne pobranie"
                )
                self._cleanup_bundled_whisper()

            if self._is_bundled_install_complete():
                if expected_checksum and self.verify_checksum(archive_dest, expected_checksum):
                    logger.info("Bundled whisper archive już zweryfikowany")
                try:
                    self.verify_whisper_runtime()
                    logger.info("whisper bundled already installed and healthy")
                    return True
                except DependencyRuntimeError:
                    logger.warning("Bundled whisper runtime broken, reinstalling")
                    self._cleanup_bundled_whisper()

            self._download_file(
                url,
                archive_dest,
                archive_name,
                expected_size,
                expected_checksum,
            )
            self._cleanup_bundled_whisper()
            self._extract_whisper_bundle(archive_dest)
            try:
                archive_dest.unlink(missing_ok=True)
            except OSError:
                logger.debug("Could not remove whisper archive: %s", archive_dest)
            self.verify_whisper_runtime()
            return True

        # Sprawdź czy plik istnieje, ma poprawny checksum i działa w runtime
        if self.is_whisper_installed():
            if expected_checksum and self.verify_checksum(dest, expected_checksum):
                try:
                    self.verify_whisper_runtime()
                    logger.info("whisper-cli już zainstalowany i zweryfikowany")
                    return True
                except DependencyRuntimeError as exc:
                    logger.warning(
                        "whisper-cli przeszedł checksum, ale runtime nie startuje (%s) — pobieranie ponownie",
                        exc,
                    )
                    dest.unlink(missing_ok=True)
            else:
                # Plik istnieje ale checksum się nie zgadza - usuń i pobierz ponownie
                logger.warning(
                    "whisper-cli istnieje ale checksum się nie zgadza - pobieranie ponownie"
                )
                dest.unlink()

        self._download_file(url, dest, "whisper-cli", expected_size, expected_checksum)
        self.verify_whisper_runtime()
        return True

    def download_ffmpeg(self) -> bool:
        """Pobierz ffmpeg binary.

        Returns:
            True jeśli pobieranie się powiodło

        Raises:
            RuntimeError: Jeśli architektura nie jest ARM64
            DownloadError: Jeśli pobieranie się nie powiodło
        """
        arch = platform.machine()
        if arch != "arm64":
            raise RuntimeError(f"Nieobsługiwana architektura: {arch}")

        url = URLS["ffmpeg"]
        dest = self.bin_dir / "ffmpeg"
        expected_size = SIZES.get("ffmpeg-arm64")
        expected_checksum = CHECKSUMS.get("ffmpeg-arm64")

        # Sprawdź czy plik istnieje i ma poprawny checksum
        if self.is_ffmpeg_installed():
            if expected_checksum and self.verify_checksum(dest, expected_checksum):
                logger.info("ffmpeg już zainstalowany i zweryfikowany")
                return True
            else:
                # Plik istnieje ale checksum się nie zgadza - usuń i pobierz ponownie
                logger.warning(
                    "ffmpeg istnieje ale checksum się nie zgadza - pobieranie ponownie"
                )
                dest.unlink()

        self._download_file(url, dest, "ffmpeg", expected_size, expected_checksum)
        return True

    def download_model(self, model: str) -> bool:
        """Pobierz model whisper.

        Args:
            model: Nazwa modelu

        Returns:
            True jeśli pobieranie się powiodło

        Raises:
            ValueError: Jeśli nieznany model
            DownloadError: Jeśli pobieranie się nie powiodło
        """
        canonical_model = self._canonical_model(model)
        url = URLS.get(f"model_{model}")
        if not url:
            raise ValueError(f"Nieznany model: {model}")

        dest = self.models_dir / f"ggml-{canonical_model}.bin"
        expected_size = SIZES.get(f"ggml-{canonical_model}.bin")
        expected_checksum = CHECKSUMS.get(f"ggml-{canonical_model}.bin")

        # Sprawdź czy plik istnieje i ma poprawny checksum
        if self.is_model_installed(model):
            if expected_checksum and self.verify_checksum(dest, expected_checksum):
                logger.info(
                    f"Model {model} ({canonical_model}) już zainstalowany i zweryfikowany"
                )
                return True
            else:
                # Plik istnieje ale checksum się nie zgadza - usuń i pobierz ponownie
                logger.warning(
                    f"Model {model} ({canonical_model}) istnieje ale checksum się nie zgadza - pobieranie ponownie"
                )
                dest.unlink()

        self._download_file(
            url, dest, f"model-{canonical_model}", expected_size, expected_checksum
        )
        self.download_model_encoder(model)
        return True

    def download_all(self) -> bool:
        """Pobierz wszystkie brakujące zależności.

        Returns:
            True jeśli wszystkie zależności zostały pobrane

        Raises:
            DownloadError: Jeśli pobieranie się nie powiodło
        """
        try:
            # Sprawdź połączenie sieciowe
            self.check_network()

            # Sprawdź miejsce na dysku tylko dla brakujących zależności.
            total_size = 0
            if not self.is_whisper_installed():
                total_size += SIZES.get("whisper-cli", 0)
            if not self.is_ffmpeg_installed():
                total_size += SIZES.get("ffmpeg-arm64", 0)

            selected_model = self._selected_model()
            canonical_model = self._canonical_model(selected_model)
            if not self.is_model_installed(selected_model):
                total_size += SIZES.get(
                    f"ggml-{canonical_model}.bin",
                    MIN_DISK_SPACE_BYTES,
                )
            if not self.is_model_encoder_installed(selected_model):
                total_size += SIZES.get(
                    f"ggml-{canonical_model}-encoder.mlmodelc.zip", 0
                )
            self.check_disk_space(total_size)

            # Pobierz brakujące zależności
            if not self.is_whisper_installed():
                self.download_whisper()
            else:
                self.verify_whisper_runtime()

            if not self.is_ffmpeg_installed():
                self.download_ffmpeg()

            if not self.is_model_installed(selected_model):
                self.download_model(selected_model)
            elif not self.is_model_encoder_installed(selected_model):
                # Model .bin już jest, ale brakuje encodera CoreML
                self.download_model_encoder(selected_model)

            logger.info("✓ Wszystkie zależności zainstalowane")
            return True

        except (NetworkError, DiskSpaceError, DownloadError) as e:
            logger.error(f"Błąd podczas pobierania zależności: {e}")
            raise

