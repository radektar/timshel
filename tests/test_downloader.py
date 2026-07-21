"""Unit tests for dependency downloader."""

import hashlib
import io
import shutil
import socket
import tarfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
from urllib.error import HTTPError, URLError

import pytest

from src.setup.downloader import DependencyDownloader, MAX_RETRIES
from src.setup.errors import (
    ChecksumError,
    DependencyRuntimeError,
    DiskSpaceError,
    DownloadError,
    NetworkError,
)


class TestDependencyDownloader:
    """Testy dla klasy DependencyDownloader."""

    @pytest.fixture
    def downloader(self, tmp_path, monkeypatch):
        """Fixture tworzący downloader z tymczasowym katalogiem."""
        # Utwórz downloader i nadpisz ścieżki
        d = DependencyDownloader()
        d.support_dir = tmp_path / "Malinche"
        d.bin_dir = d.support_dir / "bin"
        d.models_dir = d.support_dir / "models"
        d.downloads_dir = d.support_dir / "downloads"

        # Utwórz katalogi
        d.bin_dir.mkdir(parents=True, exist_ok=True)
        d.models_dir.mkdir(parents=True, exist_ok=True)
        d.downloads_dir.mkdir(parents=True, exist_ok=True)

        return d

    def test_check_network_online(self, downloader, monkeypatch):
        """Test sprawdzania połączenia sieciowego - online."""
        # Mock socket.create_connection - sukces
        mock_connection = Mock()
        monkeypatch.setattr(
            socket, "create_connection", lambda *args, **kwargs: mock_connection
        )

        result = downloader.check_network()
        assert result is True

    def test_check_network_offline(self, downloader, monkeypatch):
        """Test sprawdzania połączenia sieciowego - offline."""

        # Mock socket.create_connection - błąd
        def mock_connection(*args, **kwargs):
            raise OSError("Network unreachable")

        monkeypatch.setattr(socket, "create_connection", mock_connection)

        with pytest.raises(NetworkError, match="No internet"):
            downloader.check_network()

    def test_check_disk_space_ok(self, downloader, monkeypatch):
        """Test sprawdzania miejsca na dysku - wystarczająco."""
        # Mock shutil.disk_usage - wystarczająco miejsca
        mock_usage = Mock()
        mock_usage.free = 1_000_000_000  # 1GB
        monkeypatch.setattr(shutil, "disk_usage", lambda path: mock_usage)

        result = downloader.check_disk_space()
        assert result is True

    def test_check_disk_space_full(self, downloader, monkeypatch):
        """Test sprawdzania miejsca na dysku - za mało."""
        # Mock shutil.disk_usage - za mało miejsca
        mock_usage = Mock()
        mock_usage.free = 100_000_000  # 100MB (< 500MB wymagane)
        monkeypatch.setattr(shutil, "disk_usage", lambda path: mock_usage)

        with pytest.raises(DiskSpaceError, match="Not enough disk space"):
            downloader.check_disk_space()

    def test_verify_checksum_valid(self, downloader, tmp_path):
        """Test weryfikacji checksum - poprawny."""
        # Utwórz plik testowy
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(b"test content")

        # Oblicz SHA256
        sha256 = hashlib.sha256()
        sha256.update(b"test content")
        expected_checksum = sha256.hexdigest()

        result = downloader.verify_checksum(test_file, expected_checksum)
        assert result is True

    def test_verify_checksum_invalid(self, downloader, tmp_path):
        """Test weryfikacji checksum - błędny."""
        # Utwórz plik testowy
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(b"test content")

        # Błędny checksum
        wrong_checksum = "wrong" * 16

        result = downloader.verify_checksum(test_file, wrong_checksum)
        assert result is False

    def test_verify_checksum_sha1_prefixed(self, downloader, tmp_path):
        """Test weryfikacji checksum SHA-1 z prefiksem algorytmu."""
        test_file = tmp_path / "test-sha1.bin"
        payload = b"sha1 payload"
        test_file.write_bytes(payload)
        expected_sha1 = hashlib.sha1(payload).hexdigest()

        result = downloader.verify_checksum(test_file, f"sha1:{expected_sha1}")
        assert result is True

    def test_verify_checksum_empty(self, downloader, tmp_path):
        """Test weryfikacji checksum - brak checksum (pomija weryfikację)."""
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(b"test content")

        # Pusty checksum - powinno zwrócić True (pomija weryfikację)
        result = downloader.verify_checksum(test_file, "")
        assert result is True

    def test_is_whisper_installed_true(self, downloader):
        """Test sprawdzania whisper - zainstalowany."""
        # Utwórz plik whisper-cli
        whisper_path = downloader.bin_dir / "whisper-cli"
        whisper_path.write_bytes(b"fake binary")
        whisper_path.chmod(0o755)

        result = downloader.is_whisper_installed()
        assert result is True

    def test_is_whisper_installed_false(self, downloader):
        """Test sprawdzania whisper - nie zainstalowany."""
        result = downloader.is_whisper_installed()
        assert result is False

    def test_is_ffmpeg_installed_true(self, downloader):
        """Test sprawdzania ffmpeg - zainstalowany."""
        # Utwórz plik ffmpeg
        ffmpeg_path = downloader.bin_dir / "ffmpeg"
        ffmpeg_path.write_bytes(b"fake binary")
        ffmpeg_path.chmod(0o755)

        result = downloader.is_ffmpeg_installed()
        assert result is True

    def test_is_ffmpeg_installed_false(self, downloader):
        """Test sprawdzania ffmpeg - nie zainstalowany."""
        result = downloader.is_ffmpeg_installed()
        assert result is False

    def test_is_model_installed_true(self, downloader):
        """Test sprawdzania modelu - zainstalowany."""
        # Utwórz plik modelu
        model_path = downloader.models_dir / "ggml-small.bin"
        model_path.write_bytes(b"fake model")

        result = downloader.is_model_installed()
        assert result is True

    def test_is_model_installed_false(self, downloader):
        """Test sprawdzania modelu - nie zainstalowany."""
        result = downloader.is_model_installed()
        assert result is False

    def test_check_all_true(self, downloader, monkeypatch):
        """Test check_all - wszystkie zainstalowane."""
        # Utwórz wszystkie pliki
        (downloader.bin_dir / "whisper-cli").write_bytes(b"fake")
        (downloader.bin_dir / "ffmpeg").write_bytes(b"fake")
        (downloader.models_dir / "ggml-small.bin").write_bytes(b"fake")

        # Mock checksum verification to return True (test files don't have real checksums)
        monkeypatch.setattr(downloader, "verify_checksum", lambda path, checksum: True)
        monkeypatch.setattr(downloader, "verify_whisper_runtime", lambda: None)
        monkeypatch.setattr(downloader, "_whisper_distribution", lambda: "static")
        monkeypatch.setattr(downloader, "_selected_model", lambda: "small")

        result = downloader.check_all()
        assert result is True

    def test_check_all_requires_selected_model(self, downloader, monkeypatch):
        """check_all musi respektować model wybrany w ustawieniach."""
        (downloader.bin_dir / "whisper-cli").write_bytes(b"fake")
        (downloader.bin_dir / "ffmpeg").write_bytes(b"fake")
        (downloader.models_dir / "ggml-small.bin").write_bytes(b"fake")

        monkeypatch.setattr(downloader, "verify_checksum", lambda path, checksum: True)
        monkeypatch.setattr(downloader, "verify_whisper_runtime", lambda: None)
        monkeypatch.setattr(downloader, "_whisper_distribution", lambda: "static")
        monkeypatch.setattr(downloader, "_selected_model", lambda: "medium")

        assert downloader.check_all() is False

    def test_download_all_downloads_selected_model(self, downloader, monkeypatch):
        """download_all powinien pobierać model wybrany w ustawieniach."""
        monkeypatch.setattr(downloader, "check_network", lambda: True)
        monkeypatch.setattr(
            downloader, "check_disk_space", lambda *args, **kwargs: True
        )
        monkeypatch.setattr(downloader, "is_whisper_installed", lambda: True)
        monkeypatch.setattr(downloader, "verify_whisper_runtime", lambda: None)
        monkeypatch.setattr(downloader, "is_ffmpeg_installed", lambda: True)
        monkeypatch.setattr(downloader, "_selected_model", lambda: "medium")
        monkeypatch.setattr(downloader, "is_model_installed", lambda model: False)

        download_model_mock = Mock(return_value=True)
        monkeypatch.setattr(downloader, "download_model", download_model_mock)

        assert downloader.download_all() is True
        download_model_mock.assert_called_once_with("medium")

    def test_download_model_medium_uses_medium_artifact(self, downloader, monkeypatch):
        """download_model('medium') pobiera właściwy artefakt."""
        called = {}

        def _fake_download(url, dest, name, expected_size=None, expected_checksum=None):
            called["url"] = url
            called["dest"] = dest
            called["name"] = name
            called["expected_size"] = expected_size
            called["expected_checksum"] = expected_checksum

        monkeypatch.setattr(downloader, "is_model_installed", lambda model=None: False)
        monkeypatch.setattr(downloader, "_download_file", _fake_download)
        monkeypatch.setattr(downloader, "download_model_encoder", lambda model: True)

        assert downloader.download_model("medium") is True
        assert called["name"] == "model-medium"
        assert str(called["dest"]).endswith("ggml-medium.bin")
        assert called["url"].endswith("/ggml-medium.bin")

    def test_download_model_large_uses_large_v3_alias(self, downloader, monkeypatch):
        """download_model('large') używa kanonicznego large-v3."""
        called = {}

        def _fake_download(url, dest, name, expected_size=None, expected_checksum=None):
            called["url"] = url
            called["dest"] = dest
            called["name"] = name
            called["expected_size"] = expected_size
            called["expected_checksum"] = expected_checksum

        monkeypatch.setattr(downloader, "is_model_installed", lambda model=None: False)
        monkeypatch.setattr(downloader, "_download_file", _fake_download)
        monkeypatch.setattr(downloader, "download_model_encoder", lambda model: True)

        assert downloader.download_model("large") is True
        assert called["name"] == "model-large-v3"
        assert str(called["dest"]).endswith("ggml-large-v3.bin")
        assert called["url"].endswith("/ggml-large-v3.bin")

    def test_download_all_checks_disk_space_for_missing_components_only(
        self, downloader, monkeypatch
    ):
        """download_all używa rozmiaru tylko brakujących komponentów."""
        monkeypatch.setattr(
            "src.setup.downloader.SIZES",
            {
                "whisper-cli": 10,
                "ffmpeg-arm64": 20,
                "ggml-medium.bin": 30,
                "ggml-large-v3.bin": 3000,
            },
        )
        monkeypatch.setattr(downloader, "check_network", lambda: True)
        monkeypatch.setattr(downloader, "is_whisper_installed", lambda: False)
        monkeypatch.setattr(downloader, "is_ffmpeg_installed", lambda: False)
        monkeypatch.setattr(downloader, "_selected_model", lambda: "medium")
        monkeypatch.setattr(
            downloader,
            "is_model_installed",
            lambda model=None: False,
        )
        monkeypatch.setattr(downloader, "download_whisper", lambda: True)
        monkeypatch.setattr(downloader, "download_ffmpeg", lambda: True)
        monkeypatch.setattr(downloader, "download_model", lambda model: True)
        monkeypatch.setattr(downloader, "verify_whisper_runtime", lambda: None)

        required_sizes = []

        def _capture_disk_space(required_bytes):
            required_sizes.append(required_bytes)
            return True

        monkeypatch.setattr(downloader, "check_disk_space", _capture_disk_space)

        assert downloader.download_all() is True
        assert required_sizes == [60]

    def test_check_all_false(self, downloader):
        """Test check_all - brakuje zależności."""
        result = downloader.check_all()
        assert result is False

    def test_check_all_false_when_runtime_check_fails(self, downloader, monkeypatch):
        """check_all zwraca False gdy whisper-cli nie uruchamia się."""
        (downloader.bin_dir / "whisper-cli").write_bytes(b"fake")
        (downloader.bin_dir / "ffmpeg").write_bytes(b"fake")
        (downloader.models_dir / "ggml-small.bin").write_bytes(b"fake")

        monkeypatch.setattr(downloader, "verify_checksum", lambda path, checksum: True)

        def _raise_runtime() -> None:
            raise DependencyRuntimeError("dyld: Library not loaded")

        monkeypatch.setattr(downloader, "verify_whisper_runtime", _raise_runtime)

        assert downloader.check_all() is False

    def test_verify_whisper_runtime_passes_when_help_exits_zero(
        self, downloader, monkeypatch
    ):
        """verify_whisper_runtime przechodzi gdy --help kończy się kodem 0."""
        whisper_path = downloader.bin_dir / "whisper-cli"
        whisper_path.write_bytes(b"fake")
        whisper_path.chmod(0o755)

        completed = Mock(returncode=0, stderr=b"", stdout=b"usage")
        monkeypatch.setattr(
            "src.setup.downloader.subprocess.run", lambda *args, **kwargs: completed
        )

        downloader.verify_whisper_runtime()

    def test_verify_whisper_runtime_raises_on_dyld_error(self, downloader, monkeypatch):
        """verify_whisper_runtime zgłasza błąd gdy dyld nie ładuje biblioteki."""
        whisper_path = downloader.bin_dir / "whisper-cli"
        whisper_path.write_bytes(b"fake")
        whisper_path.chmod(0o755)

        completed = Mock(
            returncode=1,
            stderr=b"dyld: Library not loaded: @rpath/libwhisper.1.dylib",
            stdout=b"",
        )
        monkeypatch.setattr(
            "src.setup.downloader.subprocess.run", lambda *args, **kwargs: completed
        )

        with pytest.raises(DependencyRuntimeError, match="Library not loaded"):
            downloader.verify_whisper_runtime()

    def test_download_whisper_bundled_extracts_dylibs(self, downloader, monkeypatch):
        """download_whisper rozpakowuje whisper-cli i dylibs z archiwum."""
        archive_name = "whisper-bundled-arm64.tar.gz"
        libs = [
            "libwhisper.1.dylib",
            "libwhisper.coreml.dylib",
            "libggml.0.dylib",
            "libggml-base.0.dylib",
            "libggml-cpu.0.dylib",
            "libggml-blas.0.dylib",
            "libggml-metal.0.dylib",
        ]

        def _fake_download(url, dest, name, expected_size=None, expected_checksum=None):
            del url, name, expected_size, expected_checksum
            with tarfile.open(dest, "w:gz") as tar:
                payload = {
                    "whisper-cli": b"binary",
                    **{lib_name: b"lib" for lib_name in libs},
                }
                for member_name, content in payload.items():
                    info = tarfile.TarInfo(member_name)
                    info.size = len(content)
                    tar.addfile(info, io.BytesIO(content))

        monkeypatch.setattr(downloader, "_whisper_distribution", lambda: "bundled")
        monkeypatch.setattr(downloader, "_download_file", _fake_download)
        monkeypatch.setattr(downloader, "verify_whisper_runtime", lambda: None)
        monkeypatch.setattr("src.setup.downloader.URLS", {"whisper": "http://test"})
        monkeypatch.setattr("src.setup.downloader.SIZES", {archive_name: 0})
        monkeypatch.setattr("src.setup.downloader.CHECKSUMS", {archive_name: ""})
        monkeypatch.setattr("platform.machine", lambda: "arm64")

        assert downloader.download_whisper() is True
        assert (downloader.bin_dir / "whisper-cli").exists()
        for lib_name in libs:
            assert (downloader.bin_dir / lib_name).exists()
        assert not (downloader.downloads_dir / archive_name).exists()

    @pytest.mark.skip(
        reason="Wymaga przepisania na httpx - używamy testów integracyjnych"
    )
    @patch("src.setup.downloader.urlopen")
    def test_download_with_retry_success(self, mock_urlopen, downloader, monkeypatch):
        """Test pobierania z retry - sukces po retry."""
        # Mock check_network i check_disk_space
        monkeypatch.setattr(downloader, "check_network", lambda: True)
        monkeypatch.setattr(downloader, "check_disk_space", lambda *args: True)

        # Pierwsza próba - HTTP 500, druga - sukces
        mock_response_200 = MagicMock()
        mock_response_200.status = 200
        mock_response_200.headers.get.return_value = "10"
        mock_response_200.read.side_effect = [b"data", b""]
        mock_response_200.__enter__ = Mock(return_value=mock_response_200)
        mock_response_200.__exit__ = Mock(return_value=False)

        mock_urlopen.side_effect = [
            HTTPError("url", 500, "Internal Server Error", None, None),
            mock_response_200,
        ]

        # Mock URLS
        with patch("src.setup.downloader.URLS", {"whisper": "http://test.com/file"}):
            with patch("src.setup.downloader.SIZES", {"whisper-cli-arm64": 10}):
                with patch("src.setup.downloader.CHECKSUMS", {}):
                    with patch("platform.machine", return_value="arm64"):
                        downloader.download_whisper()

        assert mock_urlopen.call_count == 2

    @pytest.mark.skip(
        reason="Wymaga przepisania na httpx - używamy testów integracyjnych"
    )
    @patch("src.setup.downloader.urlopen")
    def test_download_max_retries_exceeded(self, mock_urlopen, downloader, monkeypatch):
        """Test pobierania - przekroczono max retries."""
        # Mock check_network i check_disk_space
        monkeypatch.setattr(downloader, "check_network", lambda: True)
        monkeypatch.setattr(downloader, "check_disk_space", lambda *args: True)

        # Wszystkie próby - HTTP 500
        mock_urlopen.side_effect = HTTPError(
            "url", 500, "Internal Server Error", None, None
        )

        # Mock URLS
        with patch("src.setup.downloader.URLS", {"whisper": "http://test.com/file"}):
            with patch("src.setup.downloader.SIZES", {"whisper-cli-arm64": 10}):
                with patch("src.setup.downloader.CHECKSUMS", {}):
                    with patch("platform.machine", return_value="arm64"):
                        with pytest.raises(DownloadError):
                            downloader.download_whisper()

        assert mock_urlopen.call_count == MAX_RETRIES

    @pytest.mark.skip(
        reason="Wymaga przepisania na httpx - używamy testów integracyjnych"
    )
    def test_download_progress_callback(self, downloader, monkeypatch):
        """Test progress callback podczas pobierania."""
        callback_calls = []

        def progress_callback(name: str, progress: float):
            callback_calls.append((name, progress))

        downloader.progress_callback = progress_callback

        # Mock urlopen z context manager support
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.headers.get.return_value = "20"  # 20 bajtów
        mock_response.read.side_effect = [b"x" * 10, b"x" * 10, b""]
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        mock_urlopen = Mock(return_value=mock_response)

        with patch("src.setup.downloader.urlopen", mock_urlopen):
            monkeypatch.setattr(downloader, "check_network", lambda: True)
            monkeypatch.setattr(downloader, "check_disk_space", lambda *args: True)

            with patch("src.setup.downloader.URLS", {"whisper": "http://test.com"}):
                with patch("src.setup.downloader.SIZES", {"whisper-cli-arm64": 20}):
                    with patch("src.setup.downloader.CHECKSUMS", {}):
                        with patch("platform.machine", return_value="arm64"):
                            downloader.download_whisper()

        # Sprawdź czy callback był wywoływany
        assert len(callback_calls) > 0
        assert all(0.0 <= progress <= 1.0 for _, progress in callback_calls)

    @pytest.mark.skip(
        reason="Wymaga przepisania na httpx - używamy testów integracyjnych"
    )
    def test_resume_partial_download(self, downloader, monkeypatch):
        """Test wznowienia częściowego pobierania."""
        # Utwórz częściowy plik .tmp
        temp_file = downloader.downloads_dir / "whisper-cli.tmp"
        temp_file.write_bytes(b"partial")

        # Mock urlopen z Range header
        mock_response = MagicMock()
        mock_response.status = 206  # Partial Content
        mock_response.headers.get.return_value = "10"
        mock_response.read.side_effect = [b"complete", b""]
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        mock_urlopen = Mock(return_value=mock_response)

        with patch("src.setup.downloader.urlopen", mock_urlopen):
            monkeypatch.setattr(downloader, "check_network", lambda: True)
            monkeypatch.setattr(downloader, "check_disk_space", lambda *args: True)

            with patch("src.setup.downloader.URLS", {"whisper": "http://test.com"}):
                with patch("src.setup.downloader.SIZES", {"whisper-cli-arm64": 20}):
                    with patch("src.setup.downloader.CHECKSUMS", {}):
                        with patch("platform.machine", return_value="arm64"):
                            downloader.download_whisper()

        # Sprawdź czy Range header był użyty
        if mock_urlopen.called:
            call_args = mock_urlopen.call_args
            if call_args and len(call_args[0]) > 0:
                request = call_args[0][0]
                if hasattr(request, "headers"):
                    assert "Range" in request.headers or request.headers.get("Range")

    @pytest.mark.skip(
        reason="Wymaga przepisania na httpx - używamy testów integracyjnych"
    )
    def test_cleanup_temp_files(self, downloader, monkeypatch):
        """Test usuwania plików tymczasowych po sukcesie."""
        # Mock urlopen
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.headers.get.return_value = "10"
        mock_response.read.side_effect = [b"data", b""]
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        mock_urlopen = Mock(return_value=mock_response)

        with patch("src.setup.downloader.urlopen", mock_urlopen):
            monkeypatch.setattr(downloader, "check_network", lambda: True)
            monkeypatch.setattr(downloader, "check_disk_space", lambda *args: True)

            with patch("src.setup.downloader.URLS", {"whisper": "http://test.com"}):
                with patch("src.setup.downloader.SIZES", {"whisper-cli-arm64": 10}):
                    with patch("src.setup.downloader.CHECKSUMS", {}):
                        with patch("platform.machine", return_value="arm64"):
                            downloader.download_whisper()

        # Sprawdź czy pliki .tmp zostały usunięte (plik został przeniesiony do bin_dir)
        temp_files = list(downloader.downloads_dir.glob("*.tmp"))
        assert len(temp_files) == 0
        # Sprawdź czy plik docelowy istnieje
        assert (downloader.bin_dir / "whisper-cli").exists()


class TestDownloadFileHardening:
    """Regresje z testu Gatekeepera 2026-07-21: wyścig dwóch downloaderów
    na jednym .tmp + stale resume po błędzie checksumy."""

    @pytest.fixture
    def downloader(self, tmp_path):
        d = DependencyDownloader()
        d.support_dir = tmp_path / "Timshel"
        d.bin_dir = d.support_dir / "bin"
        d.models_dir = d.support_dir / "models"
        d.downloads_dir = d.support_dir / "downloads"
        for p in (d.bin_dir, d.models_dir, d.downloads_dir):
            p.mkdir(parents=True, exist_ok=True)
        return d

    def _fake_stream(self, payloads):
        """httpx.stream stub: each call yields the next payload; records
        the Range header each attempt sent."""
        calls = []

        class _Resp:
            def __init__(self, data):
                self._data = data
                self.status_code = 200
                self.headers = {"Content-Length": str(len(data))}

            def raise_for_status(self):
                pass

            def iter_bytes(self, chunk_size=8192):
                yield self._data

        class _Ctx:
            def __init__(self, data):
                self._data = data

            def __enter__(self):
                return _Resp(self._data)

            def __exit__(self, *a):
                return False

        def stream(method, url, headers=None, timeout=None, follow_redirects=True):
            calls.append(dict(headers or {}))
            data = payloads[min(len(calls) - 1, len(payloads) - 1)]
            return _Ctx(data)

        return stream, calls

    def test_checksum_retry_restarts_from_zero(self, downloader, monkeypatch):
        # Próba 1: złe bajty -> checksum pada. Próba 2 NIE może wysłać
        # Range (stale resume pobierał sam ogon i pętlił błąd) — musi
        # pobrać całość od zera i przejść.
        import hashlib as _h

        good = b"good-bytes"
        bad = b"bad--bytes"
        good_sum = _h.sha256(good).hexdigest()
        stream, calls = self._fake_stream([bad, good])
        monkeypatch.setattr("src.setup.downloader.httpx.stream", stream)
        monkeypatch.setattr(downloader, "check_network", lambda: None)

        dest = downloader.bin_dir / "artifact"
        downloader._download_file(
            "http://x/a",
            dest,
            "artifact",
            expected_size=len(good),
            expected_checksum=good_sum,
        )
        assert dest.read_bytes() == good
        assert "Range" not in calls[0]
        assert "Range" not in calls[1]  # retry po checksumie = od zera
        assert not (downloader.downloads_dir / "artifact.tmp").exists()

    def test_failed_checksum_never_touches_dest(self, downloader, monkeypatch):
        # Weryfikacja idzie na .tmp PRZED rename — po porażce dest nie
        # istnieje (nie ma okna, w którym leży tam uszkodzony plik).
        from src.setup.errors import DownloadError

        stream, _calls = self._fake_stream([b"bad"])
        monkeypatch.setattr("src.setup.downloader.httpx.stream", stream)
        monkeypatch.setattr(downloader, "check_network", lambda: None)

        dest = downloader.bin_dir / "artifact"
        with pytest.raises(DownloadError):
            downloader._download_file(
                "http://x/a",
                dest,
                "artifact",
                expected_size=3,
                expected_checksum="0" * 64,
            )
        assert not dest.exists()

    def test_second_caller_waits_and_reuses_finished_download(
        self, downloader, monkeypatch
    ):
        # Dwóch pobierających ten sam artefakt (wizard + auto-naprawa
        # daemona): drugi czeka na locku i zastaje gotowy plik — zero
        # drugiego pobierania, zero przeplotu na .tmp.
        import hashlib as _h
        import threading as th

        good = b"payload"
        good_sum = _h.sha256(good).hexdigest()
        started = th.Event()
        release = th.Event()
        stream_calls = {"count": 0}

        class _Resp:
            status_code = 200
            headers = {"Content-Length": str(len(good))}

            def raise_for_status(self):
                pass

            def iter_bytes(self, chunk_size=8192):
                started.set()
                release.wait(timeout=5)
                yield good

        class _Ctx:
            def __enter__(self):
                return _Resp()

            def __exit__(self, *a):
                return False

        def stream(*a, **k):
            stream_calls["count"] += 1
            return _Ctx()

        monkeypatch.setattr("src.setup.downloader.httpx.stream", stream)
        monkeypatch.setattr(downloader, "check_network", lambda: None)

        dest = downloader.bin_dir / "artifact"

        def _first():
            downloader._download_file(
                "http://x/a",
                dest,
                "artifact",
                expected_size=len(good),
                expected_checksum=good_sum,
            )

        t1 = th.Thread(target=_first)
        t1.start()
        assert started.wait(timeout=5)  # pierwszy trzyma lock, pisze .tmp
        release.set()

        # Drugi downloader (osobna instancja — jak w apce) na ten sam plik.
        d2 = DependencyDownloader()
        d2.downloads_dir = downloader.downloads_dir
        d2.bin_dir = downloader.bin_dir
        d2._download_file(
            "http://x/a",
            dest,
            "artifact",
            expected_size=len(good),
            expected_checksum=good_sum,
        )
        t1.join(timeout=5)
        assert dest.read_bytes() == good
        assert stream_calls["count"] == 1  # drugi NIE pobierał ponownie
