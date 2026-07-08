"""Domyślne wartości konfiguracji użytkownika."""

from dataclasses import dataclass
from pathlib import Path

# Ścieżki
# Neutralny domyślny katalog wyjściowy — wcześniej wskazywał prywatny vault
# Obsidian dewelopera (iCloud), co u zewnętrznego usera tworzyło widmowe drzewo
# iCloud~md~obsidian. Wizard nadal pozwala wskazać dowolny folder (w tym vault
# Obsidian użytkownika).
DEFAULT_OUTPUT_DIR = Path.home() / "Documents" / "Timshel"

# Single point of truth for the app-support container name. The project was
# renamed Timshel→Timshel; the old "Timshel" dir is migrated on first launch
# (src/bootstrap.py). Change here, not scattered across modules.
APP_SUPPORT_DIR_NAME = "Timshel"
APP_SUPPORT_DIR = (
    Path.home() / "Library" / "Application Support" / APP_SUPPORT_DIR_NAME
)
# Hidden per-vault sidecar dir (metrics/signal/vocabulary/dismissals live here).
SIDECAR_DIR_NAME = ".timshel"

CONFIG_DIR = APP_SUPPORT_DIR
CONFIG_FILE = CONFIG_DIR / "config.json"

# Tryby monitorowania
# "auto" zostało usunięte w v2.0.0-beta.2 ze względów bezpieczeństwa —
# domyślne skanowanie dowolnego dysku z plikami audio prowadziło do
# nieautoryzowanej transkrypcji. Migracja istniejących userów odbywa się
# w UserSettings.__post_init__ (auto → manual + onboarding).
WATCH_MODES = ["manual", "specific"]
DEFAULT_WATCH_MODE = "manual"
# Alias used across code/tests
WATCH_MODE = DEFAULT_WATCH_MODE

# Języki
SUPPORTED_LANGUAGES = {
    "pl": "Polski",
    "en": "English",
    "auto": "Automatyczne wykrywanie",
}
DEFAULT_LANGUAGE = "pl"

# Modele Whisper
SUPPORTED_MODELS = {
    "tiny": "Tiny (szybki, niska jakość)",
    "base": "Base (szybki, średnia jakość)",
    "small": "Small (zalecany)",
    "medium": "Medium (wolny, wysoka jakość)",
    "large": "Large (large-v3, najwyższa jakość)",
}
DEFAULT_MODEL = "small"

# Alias for backwards compatibility (tests/code may expect this name)
DEFAULT_WHISPER_MODEL = DEFAULT_MODEL

# UI / wizard defaults
DEFAULT_ENABLE_AI_SUMMARIES = False
DEFAULT_SHOW_NOTIFICATIONS = True
DEFAULT_START_AT_LOGIN = False
DEFAULT_SETUP_COMPLETED = False
DEFAULT_LEGACY_MIGRATED = False

# Audio detection defaults
# Keep this set in sync with legacy Config expectations.
# .dss/.ds2 are Olympus Digital Speech Standard (dictaphone) formats — ffmpeg
# can *decode* them (so `_convert_to_wav` handles them) but not encode them,
# so the test audio factory can't render them (see test_audio_factory).
AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".wma", ".flac", ".aac", ".ogg", ".dss", ".ds2"
}

# Limit recursive scan depth under a volume root (performance safeguard).
MAX_SCAN_DEPTH = 3

# Systemowe volumeny do ignorowania
SYSTEM_VOLUMES = {
    "Macintosh HD",
    "Recovery",
    "Preboot",
    "VM",
    "Data",
    "Update",
    "Shared",
    "System",
    "com.apple.TimeMachine.localsnapshots",
}


@dataclass(frozen=True)
class Defaults:
    """Namespace-style access to default values.

    This exists for backward compatibility with older code/tests that expect
    an object named `defaults` with attributes (e.g. `defaults.DEFAULT_LANGUAGE`).
    """

    DEFAULT_OUTPUT_DIR: Path = DEFAULT_OUTPUT_DIR
    APP_SUPPORT_DIR: Path = APP_SUPPORT_DIR
    APP_SUPPORT_DIR_NAME: str = APP_SUPPORT_DIR_NAME
    SIDECAR_DIR_NAME: str = SIDECAR_DIR_NAME
    CONFIG_DIR: Path = CONFIG_DIR
    CONFIG_FILE: Path = CONFIG_FILE

    WATCH_MODES: list[str] = None  # type: ignore[assignment]
    WATCH_MODE: str = WATCH_MODE
    DEFAULT_WATCH_MODE: str = DEFAULT_WATCH_MODE

    SUPPORTED_LANGUAGES: dict[str, str] = None  # type: ignore[assignment]
    DEFAULT_LANGUAGE: str = DEFAULT_LANGUAGE

    SUPPORTED_MODELS: dict[str, str] = None  # type: ignore[assignment]
    DEFAULT_MODEL: str = DEFAULT_MODEL
    DEFAULT_WHISPER_MODEL: str = DEFAULT_WHISPER_MODEL

    DEFAULT_ENABLE_AI_SUMMARIES: bool = DEFAULT_ENABLE_AI_SUMMARIES
    DEFAULT_SHOW_NOTIFICATIONS: bool = DEFAULT_SHOW_NOTIFICATIONS
    DEFAULT_START_AT_LOGIN: bool = DEFAULT_START_AT_LOGIN
    DEFAULT_SETUP_COMPLETED: bool = DEFAULT_SETUP_COMPLETED
    DEFAULT_LEGACY_MIGRATED: bool = DEFAULT_LEGACY_MIGRATED

    AUDIO_EXTENSIONS: set[str] = None  # type: ignore[assignment]
    MAX_SCAN_DEPTH: int = MAX_SCAN_DEPTH
    SYSTEM_VOLUMES: set[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        # Dataclass is frozen; use object.__setattr__ to set default mutable fields.
        object.__setattr__(self, "WATCH_MODES", WATCH_MODES)
        object.__setattr__(self, "SUPPORTED_LANGUAGES", SUPPORTED_LANGUAGES)
        object.__setattr__(self, "SUPPORTED_MODELS", SUPPORTED_MODELS)
        object.__setattr__(self, "AUDIO_EXTENSIONS", AUDIO_EXTENSIONS)
        object.__setattr__(self, "SYSTEM_VOLUMES", SYSTEM_VOLUMES)


# Backwards compatible instance used across the codebase/tests.
defaults = Defaults()
