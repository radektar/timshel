#!/usr/bin/env python3
"""Automatyczny test pobierania zależności dla TEST M1."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.setup.downloader import DependencyDownloader
from src.setup.errors import NetworkError, DiskSpaceError, DownloadError
from src.logger import logger


def progress_callback(name: str, progress: float):
    """Progress callback dla pobierania."""
    percent = int(progress * 100)
    print(f"  [{percent:3d}%] Pobieranie {name}...", end="\r")
    if progress >= 1.0:
        print()  # Nowa linia po zakończeniu


def test_m1_download():
    """Test M1: Pierwsze uruchomienie - pobieranie wszystkich zależności."""
    print("=" * 60)
    print("TEST M1: Pierwsze uruchomienie (czysta instalacja)")
    print("=" * 60)

    # Sprawdź stan początkowy
    downloader = DependencyDownloader()
    print("\n1. Sprawdzanie stanu początkowego...")
    print(f"   whisper-cli: {downloader.is_whisper_installed()}")
    print(f"   ffmpeg: {downloader.is_ffmpeg_installed()}")
    print(f"   model: {downloader.is_model_installed()}")
    print(f"   check_all(): {downloader.check_all()}")

    if downloader.check_all():
        print("   ⚠️  UWAGA: Wszystkie zależności już zainstalowane!")
        print(
            "   Usuń katalog Transrec przed testem: rm -rf ~/Library/Application\\ Support/Transrec/"
        )
        return False

    # Sprawdź network
    print("\n2. Sprawdzanie połączenia z internetem...")
    try:
        downloader.check_network()
        print("   ✓ Połączenie z internetem OK")
    except NetworkError as e:
        print(f"   ✗ Brak połączenia: {e}")
        return False

    # Sprawdź disk space
    print("\n3. Sprawdzanie miejsca na dysku...")
    try:
        downloader.check_disk_space()
        print("   ✓ Wystarczająco miejsca na dysku")
    except DiskSpaceError as e:
        print(f"   ✗ Brak miejsca: {e}")
        return False

    # Pobierz wszystkie zależności
    print("\n4. Pobieranie zależności...")
    print("   (To może zająć kilka minut, szczególnie model ~466MB)")

    try:
        downloader_with_progress = DependencyDownloader(
            progress_callback=progress_callback
        )
        downloader_with_progress.download_all()
        print("   ✓ Wszystkie zależności pobrane")
    except (NetworkError, DiskSpaceError, DownloadError) as e:
        print(f"   ✗ Błąd pobierania: {e}")
        return False

    # Weryfikacja plików
    print("\n5. Weryfikacja pobranych plików...")

    # Sprawdź whisper-cli
    whisper_path = downloader.bin_dir / "whisper-cli"
    if whisper_path.exists():
        size = whisper_path.stat().st_size
        print(f"   ✓ whisper-cli: {size:,} bajtów ({size/1024:.1f} KB)")

        # Sprawdź uprawnienia
        import stat

        is_executable = whisper_path.stat().st_mode & stat.S_IEXEC != 0
        print(f"      Uprawnienia wykonywania: {'✓' if is_executable else '✗'}")

        # Test działania
        import subprocess

        try:
            result = subprocess.run(
                [str(whisper_path), "-h"], capture_output=True, timeout=5
            )
            print(f"      Test działania: {'✓' if result.returncode == 0 else '✗'}")
        except Exception as e:
            print(f"      Test działania: ✗ ({e})")
    else:
        print("   ✗ whisper-cli nie istnieje")
        return False

    # Sprawdź ffmpeg
    ffmpeg_path = downloader.bin_dir / "ffmpeg"
    if ffmpeg_path.exists():
        size = ffmpeg_path.stat().st_size
        print(f"   ✓ ffmpeg: {size:,} bajtów ({size/1024/1024:.1f} MB)")

        # Sprawdź uprawnienia
        import stat

        is_executable = ffmpeg_path.stat().st_mode & stat.S_IEXEC != 0
        print(f"      Uprawnienia wykonywania: {'✓' if is_executable else '✗'}")

        # Test działania
        import subprocess

        try:
            result = subprocess.run(
                [str(ffmpeg_path), "-version"], capture_output=True, timeout=5
            )
            print(f"      Test działania: {'✓' if result.returncode == 0 else '✗'}")
        except Exception as e:
            print(f"      Test działania: ✗ ({e})")
    else:
        print("   ✗ ffmpeg nie istnieje")
        return False

    # Sprawdź model
    model_path = downloader.models_dir / "ggml-small.bin"
    if model_path.exists():
        size = model_path.stat().st_size
        print(f"   ✓ model (ggml-small.bin): {size:,} bajtów ({size/1024/1024:.1f} MB)")

        # Weryfikuj checksum
        from src.setup.checksums import CHECKSUMS

        expected_checksum = CHECKSUMS.get("ggml-small.bin", "")
        if expected_checksum:
            checksum_ok = downloader.verify_checksum(model_path, expected_checksum)
            print(f"      Checksum: {'✓' if checksum_ok else '✗'}")
            if not checksum_ok:
                print(f"      Oczekiwany: {expected_checksum}")
                # Oblicz aktualny
                import hashlib

                sha256 = hashlib.sha256()
                with open(model_path, "rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        sha256.update(chunk)
                actual = sha256.hexdigest()
                print(f"      Aktualny:  {actual}")
    else:
        print("   ✗ model nie istnieje")
        return False

    # Finalna weryfikacja
    print("\n6. Finalna weryfikacja...")
    if downloader.check_all():
        print("   ✓ Wszystkie zależności zainstalowane i zweryfikowane")
        print("\n" + "=" * 60)
        print("TEST M1: PASS ✓")
        print("=" * 60)
        return True
    else:
        print("   ✗ Niektóre zależności nie są zainstalowane")
        print("\n" + "=" * 60)
        print("TEST M1: FAIL ✗")
        print("=" * 60)
        return False


if __name__ == "__main__":
    success = test_m1_download()
    sys.exit(0 if success else 1)
