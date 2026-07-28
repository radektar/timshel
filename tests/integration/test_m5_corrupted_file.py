#!/usr/bin/env python3
"""Automatyczny test M5: Uszkodzony plik - wykrycie i naprawa."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.setup.downloader import DependencyDownloader
from src.setup.checksums import CHECKSUMS
from src.logger import logger


def test_m5_corrupted_file():
    """Test M5: Wykrycie i naprawa uszkodzonego pliku."""
    print("=" * 60)
    print("TEST M5: Uszkodzony plik - wykrycie i naprawa")
    print("=" * 60)

    downloader = DependencyDownloader()
    whisper_path = downloader.bin_dir / "whisper-cli"
    expected_checksum = CHECKSUMS.get("whisper-cli", "")

    if not expected_checksum:
        print("✗ Brak checksum dla whisper-cli w checksums.py")
        return False

    # Krok 1: Sprawdź czy plik istnieje
    print("\n1. Sprawdzanie czy whisper-cli jest zainstalowany...")
    if not whisper_path.exists():
        print("   ✗ whisper-cli nie istnieje - najpierw wykonaj TEST M1")
        return False
    print("   ✓ whisper-cli istnieje")

    # Krok 2: Sprawdź checksum przed uszkodzeniem
    print("\n2. Weryfikacja checksum PRZED uszkodzeniem...")
    checksum_before = downloader.verify_checksum(whisper_path, expected_checksum)
    if not checksum_before:
        print("   ⚠️  Plik już ma błędny checksum - naprawiam najpierw")
        # Pobierz ponownie
        try:
            downloader.download_whisper()
            checksum_before = downloader.verify_checksum(
                whisper_path, expected_checksum
            )
            if not checksum_before:
                print("   ✗ Nie udało się naprawić pliku")
                return False
        except Exception as e:
            print(f"   ✗ Błąd podczas naprawy: {e}")
            return False

    print(f"   ✓ Checksum poprawny: {expected_checksum[:16]}...")

    # Krok 3: Uszkodź plik
    print("\n3. Uszkadzanie pliku...")
    try:
        with open(whisper_path, "ab") as f:
            f.write(b"corrupted data for test")
        print("   ✓ Plik uszkodzony (dodano dane na końcu)")
    except Exception as e:
        print(f"   ✗ Błąd podczas uszkadzania: {e}")
        return False

    # Krok 4: Sprawdź checksum po uszkodzeniu
    print("\n4. Weryfikacja checksum PO uszkodzeniu...")
    checksum_after = downloader.verify_checksum(whisper_path, expected_checksum)
    if checksum_after:
        print("   ✗ Checksum nadal się zgadza - uszkodzenie nie zadziałało")
        return False
    print("   ✓ Checksum się zmienił - plik jest uszkodzony")

    # Krok 5: Sprawdź czy check_all() wykrywa uszkodzenie
    print("\n5. Sprawdzanie czy check_all() wykrywa uszkodzenie...")
    check_result = downloader.check_all()
    if check_result:
        print("   ✗ check_all() zwróciło True - nie wykryło uszkodzenia")
        return False
    print("   ✓ check_all() zwróciło False - wykryło uszkodzenie")

    # Krok 6: Napraw plik (pobierz ponownie)
    print("\n6. Naprawa pliku (pobieranie ponownie)...")
    try:
        downloader.download_whisper()
        print("   ✓ Plik pobrany ponownie")
    except Exception as e:
        print(f"   ✗ Błąd podczas pobierania: {e}")
        return False

    # Krok 7: Weryfikacja naprawy
    print("\n7. Weryfikacja naprawy...")
    checksum_fixed = downloader.verify_checksum(whisper_path, expected_checksum)
    if not checksum_fixed:
        print("   ✗ Checksum nadal się nie zgadza po naprawie")
        return False
    print("   ✓ Checksum się zgadza - plik został naprawiony")

    # Krok 8: Finalna weryfikacja
    print("\n8. Finalna weryfikacja...")
    final_check = downloader.check_all()
    if not final_check:
        print("   ✗ check_all() nadal zwraca False")
        return False
    print("   ✓ check_all() zwraca True - wszystko działa")

    print("\n" + "=" * 60)
    print("TEST M5: PASS ✓")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = test_m5_corrupted_file()
    sys.exit(0 if success else 1)
