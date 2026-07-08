"""Setup utilities for Timshel."""

from src.setup.downloader import DependencyDownloader
from src.setup.dependency_manager import DependencyManager, DependencyStatus
from src.setup.errors import (
    DownloadError,
    ChecksumError,
    NetworkError,
    DiskSpaceError,
    DependencyRuntimeError,
)
from src.setup.wizard import SetupWizard, WizardStep
from src.setup.permissions import (
    check_full_disk_access,
    open_fda_preferences,
    check_volume_access,
)

__all__ = [
    "DependencyDownloader",
    "DependencyManager",
    "DependencyStatus",
    "DownloadError",
    "ChecksumError",
    "NetworkError",
    "DiskSpaceError",
    "DependencyRuntimeError",
    "SetupWizard",
    "WizardStep",
    "check_full_disk_access",
    "open_fda_preferences",
    "check_volume_access",
]

