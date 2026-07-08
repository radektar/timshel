#!/usr/bin/env python3
"""Helper script for manual wizard testing - checks files and config."""

import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional

CONFIG_DIR = Path.home() / "Library" / "Application Support" / "Timshel"
CONFIG_FILE = CONFIG_DIR / "config.json"
BIN_DIR = CONFIG_DIR / "bin"
MODELS_DIR = CONFIG_DIR / "models"
LOG_FILE = CONFIG_DIR / "logs" / "timshel.log"


def check_config_file() -> tuple[bool, Optional[Dict[str, Any]]]:
    """Sprawdź czy config.json istnieje i jest poprawny."""
    if not CONFIG_FILE.exists():
        return False, None
    
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        return True, config
    except (json.JSONDecodeError, IOError) as e:
        print(f"❌ Błąd odczytu config.json: {e}")
        return False, None


def check_dependencies() -> Dict[str, bool]:
    """Sprawdź czy zależności są zainstalowane."""
    results = {}
    
    # whisper-cli
    whisper_cli = BIN_DIR / "whisper-cli"
    results["whisper-cli"] = whisper_cli.exists() and whisper_cli.is_file()
    
    # ffmpeg
    ffmpeg = BIN_DIR / "ffmpeg"
    results["ffmpeg"] = ffmpeg.exists() and ffmpeg.is_file()
    
    # Model
    model = MODELS_DIR / "ggml-small.bin"
    results["ggml-small.bin"] = model.exists() and model.is_file()
    
    return results


def check_logs() -> tuple[bool, list[str]]:
    """Sprawdź logi pod kątem komunikatów wizarda."""
    if not LOG_FILE.exists():
        return False, []
    
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        wizard_lines = [
            line.strip() for line in lines[-50:]  # Ostatnie 50 linii
            if "wizard" in line.lower() or "Wizard" in line or "setup" in line.lower()
        ]
        return True, wizard_lines
    except IOError:
        return False, []


def print_status(test_id: str, config: Optional[Dict[str, Any]] = None):
    """Wypisz status dla konkretnego testu."""
    print(f"\n{'='*60}")
    print(f"TEST {test_id} - Status sprawdzenia")
    print(f"{'='*60}")
    
    # Config file
    config_exists, config_data = check_config_file()
    print(f"\n📄 Config file:")
    print(f"   Istnieje: {'✅' if config_exists else '❌'}")
    
    if config_exists and config_data:
        print(f"   setup_completed: {config_data.get('setup_completed', 'N/A')}")
        print(f"   watch_mode: {config_data.get('watch_mode', 'N/A')}")
        print(f"   output_dir: {config_data.get('output_dir', 'N/A')}")
        print(f"   language: {config_data.get('language', 'N/A')}")
        print(f"   enable_ai_summaries: {config_data.get('enable_ai_summaries', 'N/A')}")
    
    # Dependencies
    deps = check_dependencies()
    print(f"\n📦 Zależności:")
    for name, exists in deps.items():
        print(f"   {name}: {'✅' if exists else '❌'}")
    
    # Logs
    logs_exist, wizard_lines = check_logs()
    print(f"\n📋 Logi:")
    print(f"   Plik istnieje: {'✅' if logs_exist else '❌'}")
    if wizard_lines:
        print(f"   Ostatnie wpisy wizarda ({len(wizard_lines)}):")
        for line in wizard_lines[-5:]:  # Ostatnie 5
            print(f"      {line}")


def main():
    """Main function."""
    if len(sys.argv) < 2:
        print("Użycie: python test_wizard_helper.py <TEST_ID>")
        print("\nPrzykład: python test_wizard_helper.py M3.1")
        sys.exit(1)
    
    test_id = sys.argv[1]
    print_status(test_id)


if __name__ == "__main__":
    main()



