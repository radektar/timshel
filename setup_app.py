"""Setup configuration for py2app to build Timshel.app bundle."""

import os
import subprocess
from datetime import datetime
from setuptools import setup
import py2app
from pathlib import Path

APP_VERSION = "2.0.0-beta.17"


def _build_stamp() -> str:
    """git SHA (+dirty) and build time, baked into Info.plist.

    The app logs this on startup, so "which build am I actually running" is
    answered by the first lines of the log instead of guesswork.
    """
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip()
        dirty = subprocess.run(
            ["git", "diff", "--quiet", "HEAD"], check=False
        ).returncode != 0
        if dirty:
            sha += "+dirty"
    except Exception:
        sha = "unknown"
    return f"{sha} {datetime.now().strftime('%Y-%m-%d %H:%M')}"


BUILD_STAMP = _build_stamp()

# Tester build: `make build-app-tester` / `release-tester` export TESTER_BUILD=1,
# which stamps an Info.plist marker the app reads on first launch to turn on H1
# instrumentation (src/bootstrap.py adoption -> UserSettings.tester_mode).
TESTER_BUILD = os.environ.get("TESTER_BUILD") == "1"

# Entry point - menu bar application
APP = ['src/menu_app.py']

# Data files (icons, etc.)
DATA_FILES = []

# Add icon if it exists
icon_path = Path('assets/icon.icns')
if icon_path.exists():
    DATA_FILES.append(('', [str(icon_path)]))
menu_icons = sorted(Path("assets/menu_bar").glob("*.png"))
if menu_icons:
    DATA_FILES.append(("menu_bar", [str(icon) for icon in menu_icons]))
brand_icons = sorted(Path("assets/brands").glob("*.svg"))
if brand_icons:
    DATA_FILES.append(("brands", [str(icon) for icon in brand_icons]))
dmg_background = Path("assets/dmg_background.png")
if dmg_background.exists():
    DATA_FILES.append(("", [str(dmg_background)]))

# py2app options
OPTIONS = {
    'argv_emulation': False,  # Menu bar app doesn't need command line args
    'iconfile': 'assets/icon.icns' if icon_path.exists() else None,
    'plist': {
        'CFBundleName': 'Timshel',
        'CFBundleDisplayName': 'Timshel',
        'CFBundleIdentifier': 'com.timshel.app',
        'CFBundleVersion': APP_VERSION,
        'CFBundleShortVersionString': APP_VERSION,
        'LSUIElement': True,  # Menu bar only, no dock icon
        'LSMinimumSystemVersion': '12.0',  # macOS Monterey+
        'NSRequiresAquaSystemAppearance': False,  # Dark mode support
        'NSHighResolutionCapable': True,
        'NSAppleEventsUsageDescription': (
            'Timshel needs to control system events for file monitoring.'
        ),
        'NSFullDiskAccessUsageDescription': (
            'Timshel needs Full Disk Access to automatically detect '
            'external recorders and SD cards for transcription.'
        ),
        'TimshelTesterBuild': TESTER_BUILD,
        'TimshelBuildStamp': BUILD_STAMP,
    },
    'packages': [
        'rumps',
        'mutagen',
        'httpx',
        'anthropic',
        'dotenv',
        'click',
        'PIL',  # Pillow — renders the menu-bar wave sigil (menu_app)
        'src',  # Include entire src package
    ],
    'includes': [
        'MacFSEvents',  # FSEvents wrapper
        'src.config',
        'src.config.settings',
        'src.config.defaults',
        'src.logger',
        'src.app_core',
        'src.app_status',
        'src.state_manager',
        'src.transcriber',
        'src.file_monitor',
        'src.markdown_generator',
        'src.summarizer',
        'src.tagger',
        'src.tag_index',
        'src.setup',
        'src.setup.downloader',
        'src.setup.wizard',
        'src.setup.permissions',
        'src.setup.errors',
        'src.setup.checksums',
        'src.env_loader',
    ],
    'excludes': [
        'tkinter',  # GUI not used
        'matplotlib',  # Graphics not used
        'numpy',  # Scientific computing not used
        'scipy',  # Scientific computing not used
        'pandas',  # Data analysis not used
        'IPython',  # Interactive shell not used
        'jupyter',  # Notebooks not used
        'test',  # Test modules
        'tests',  # Test modules
        'pytest',  # Test framework
        'unittest',  # Test framework
        'distutils',
        'lib2to3',
        'docutils',
        'setuptools._vendor',
        'pkg_resources._vendor',
    ],
    'arch': 'arm64',  # Apple Silicon only
    'optimize': 2,  # Bytecode optimization for smaller bundle
    'strip': True,  # Strip symbols to reduce bundle size
}

setup(
    name='Timshel',
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)

