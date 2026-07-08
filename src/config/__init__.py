"""User configuration module."""

# Import UserSettings and defaults from this package
from src.config.settings import UserSettings
from src.config.defaults import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_WATCH_MODE,
    DEFAULT_LANGUAGE,
    DEFAULT_MODEL,
    SUPPORTED_LANGUAGES,
    SUPPORTED_MODELS,
    WATCH_MODES,
    SYSTEM_VOLUMES,
    CONFIG_DIR,
    CONFIG_FILE,
    APP_SUPPORT_DIR,
    APP_SUPPORT_DIR_NAME,
    SIDECAR_DIR_NAME,
)

# Import Config and config from config.py module
# Using normal import instead of dynamic importlib to ensure single module instance
# This prevents issues with module reloading in tests and ensures deterministic behavior
from src.config.config import Config, config
from src.config.features import FeatureFlags, FeatureTier
from src.config.license import license_manager

__all__ = [
    "UserSettings",
    "Config",
    "config",
    "FeatureFlags",
    "FeatureTier",
    "license_manager",
    "DEFAULT_OUTPUT_DIR",
    "DEFAULT_WATCH_MODE",
    "DEFAULT_LANGUAGE",
    "DEFAULT_MODEL",
    "SUPPORTED_LANGUAGES",
    "SUPPORTED_MODELS",
    "WATCH_MODES",
    "SYSTEM_VOLUMES",
    "CONFIG_DIR",
    "CONFIG_FILE",
    "APP_SUPPORT_DIR",
    "APP_SUPPORT_DIR_NAME",
    "SIDECAR_DIR_NAME",
]
