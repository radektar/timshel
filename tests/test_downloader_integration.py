"""Integration tests for dependency downloader.

Uwaga: Te testy wymagają połączenia z internetem i są wolne.
Uruchamiaj tylko przed merge do develop.
"""

import pytest

from src.setup.downloader import DependencyDownloader
from src.setup.errors import NetworkError


class TestDownloaderIntegration:
    """Testy integracyjne dla DependencyDownloader."""

    @pytest.fixture
    def downloader(self):
        """Fixture tworzący downloader."""
        return DependencyDownloader()

    @pytest.mark.slow
    @pytest.mark.integration
    def test_download_whisper_real(self, downloader):
        """Test prawdziwego pobierania whisper-cli z GitHub."""
        # Skip jeśli brak internetu
        try:
            downloader.check_network()
        except NetworkError:
            pytest.skip("Brak połączenia z internetem")

        # Usuń istniejący plik jeśli istnieje (dla czystego testu)
        whisper_path = downloader.bin_dir / "whisper-cli"
        if whisper_path.exists():
            whisper_path.unlink()

        # Pobierz whisper-cli
        assert downloader.download_whisper() is True
        assert downloader.is_whisper_installed() is True

        # Sprawdź czy plik jest wykonywalny
        assert whisper_path.stat().st_mode & 0o111 != 0

    @pytest.mark.slow
    @pytest.mark.integration
    def test_download_ffmpeg_real(self, downloader):
        """Test prawdziwego pobierania ffmpeg."""
        # Skip jeśli brak internetu
        try:
            downloader.check_network()
        except NetworkError:
            pytest.skip("Brak połączenia z internetem")

        # Usuń istniejący plik jeśli istnieje (dla czystego testu)
        ffmpeg_path = downloader.bin_dir / "ffmpeg"
        if ffmpeg_path.exists():
            ffmpeg_path.unlink()

        # Pobierz ffmpeg
        assert downloader.download_ffmpeg() is True
        assert downloader.is_ffmpeg_installed() is True

        # Sprawdź czy plik jest wykonywalny
        assert ffmpeg_path.stat().st_mode & 0o111 != 0

    @pytest.mark.slow
    @pytest.mark.integration
    def test_download_model_small_real(self, downloader):
        """Test prawdziwego pobierania modelu small z HuggingFace."""
        # Skip jeśli brak internetu
        try:
            downloader.check_network()
        except NetworkError:
            pytest.skip("Brak połączenia z internetem")

        # Usuń istniejący plik jeśli istnieje (dla czystego testu)
        model_path = downloader.models_dir / "ggml-small.bin"
        if model_path.exists():
            model_path.unlink()

        # Pobierz model (to może potrwać kilka minut - 465MB)
        assert downloader.download_model("small") is True
        assert downloader.is_model_installed("small") is True

        # Sprawdź czy plik ma odpowiedni rozmiar
        assert model_path.stat().st_size > 400_000_000  # >400MB

    @pytest.mark.slow
    @pytest.mark.integration
    def test_verify_checksum_real(self, downloader, tmp_path):
        """Test weryfikacji checksum na prawdziwym pliku."""
        # Utwórz plik testowy
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(b"test content for checksum")

        # Oblicz SHA256
        import hashlib

        sha256 = hashlib.sha256()
        sha256.update(b"test content for checksum")
        expected_checksum = sha256.hexdigest()

        # Weryfikuj
        assert downloader.verify_checksum(test_file, expected_checksum) is True
        assert downloader.verify_checksum(test_file, "wrong" * 16) is False

    @pytest.mark.slow
    @pytest.mark.integration
    def test_full_download_workflow(self, downloader):
        """Test pełnego workflow pobierania wszystkich zależności."""
        # Skip jeśli brak internetu
        try:
            downloader.check_network()
        except NetworkError:
            pytest.skip("Brak połączenia z internetem")

        # Sprawdź miejsce na dysku
        downloader.check_disk_space()

        # Pobierz wszystkie zależności
        downloader.download_whisper()
        downloader.download_ffmpeg()
        downloader.download_model("small")

        # Sprawdź czy wszystko jest zainstalowane
        assert downloader.is_whisper_installed() is True
        assert downloader.is_ffmpeg_installed() is True
        assert downloader.is_model_installed("small") is True
