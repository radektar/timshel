"""Launch-at-login management via LaunchAgent plist.

macOS 12+ compatible (no SMAppService dependency). Generates a user
LaunchAgent plist in ``~/Library/LaunchAgents/com.timshel.app.plist``
and loads/unloads it via ``launchctl``. Detects whether the running
process is an installed ``Timshel.app`` bundle — autostart only makes
sense for installed bundles, not for ``python -m src.menu_app`` dev
runs (where there is no stable executable to point at).
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Optional

from src.logger import logger

BUNDLE_IDENTIFIER = "com.timshel.app"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = LAUNCH_AGENTS_DIR / f"{BUNDLE_IDENTIFIER}.plist"


def is_app_bundle() -> bool:
    """True if running from an installed Timshel.app bundle."""
    return get_executable_path() is not None


def get_executable_path() -> Optional[Path]:
    """Return the absolute path to the Timshel bundle's MacOS binary.

    Walks up from ``sys.executable`` looking for the canonical
    ``.app/Contents/MacOS/Timshel`` layout. Returns None when running
    in dev mode (``python -m src.menu_app``).
    """
    exe = Path(sys.executable).resolve()
    for parent in (exe, *exe.parents):
        if parent.suffix == ".app" and parent.name == "Timshel.app":
            candidate = parent / "Contents" / "MacOS" / "Timshel"
            if candidate.exists():
                return candidate
            return None
    return None


def _build_plist(executable: Path) -> bytes:
    payload = {
        "Label": BUNDLE_IDENTIFIER,
        "ProgramArguments": [str(executable)],
        "RunAtLoad": True,
        "KeepAlive": False,
        "ProcessType": "Interactive",
    }
    return plistlib.dumps(payload)


def _launchctl(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["launchctl", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        check=False,
    )


def _gui_target() -> str:
    return f"gui/{os.getuid()}"


def enable_launch_at_login() -> bool:
    """Install the LaunchAgent plist and load it into launchd.

    Returns True on success. Returns False (and logs a warning) when
    the app is not installed as a bundle — there is no stable
    executable path to put into ProgramArguments.
    """
    executable = get_executable_path()
    if executable is None:
        logger.warning(
            "Cannot enable launch at login: not running from an installed "
            "Timshel.app bundle (sys.executable=%s)",
            sys.executable,
        )
        return False

    try:
        LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
        PLIST_PATH.write_bytes(_build_plist(executable))
    except OSError as error:
        logger.error("Could not write %s: %s", PLIST_PATH, error)
        return False

    # bootstrap is the modern verb (macOS 11+); fall back to load -w on
    # older systems or when the agent is already loaded (bootstrap fails
    # if a service with this Label is already registered).
    target = _gui_target()
    result = _launchctl(["bootstrap", target, str(PLIST_PATH)])
    if result.returncode != 0:
        # Probably already bootstrapped — try kickstart to reload, fall
        # back to legacy load -w as last resort.
        kick = _launchctl(["kickstart", "-k", f"{target}/{BUNDLE_IDENTIFIER}"])
        if kick.returncode != 0:
            legacy = _launchctl(["load", "-w", str(PLIST_PATH)])
            if legacy.returncode != 0:
                logger.warning(
                    "launchctl bootstrap/kickstart/load all failed for %s: "
                    "bootstrap=%s, kickstart=%s, load=%s",
                    PLIST_PATH,
                    result.stderr.strip(),
                    kick.stderr.strip(),
                    legacy.stderr.strip(),
                )
                # Plist is on disk — RunAtLoad will still pick it up on
                # next login even if we couldn't load it right now.
    logger.info("Launch at login enabled (%s)", PLIST_PATH)
    return True


def disable_launch_at_login() -> bool:
    """Unload the LaunchAgent and remove its plist."""
    target = _gui_target()
    _launchctl(["bootout", f"{target}/{BUNDLE_IDENTIFIER}"])
    _launchctl(["unload", str(PLIST_PATH)])  # legacy, ignore failures
    try:
        if PLIST_PATH.exists():
            PLIST_PATH.unlink()
    except OSError as error:
        logger.error("Could not remove %s: %s", PLIST_PATH, error)
        return False
    logger.info("Launch at login disabled")
    return True


def is_launch_at_login_enabled() -> bool:
    """True iff the LaunchAgent plist is present on disk."""
    return PLIST_PATH.exists()


def _plist_executable_matches(executable: Path) -> bool:
    """True if PLIST_PATH points at ``executable``."""
    try:
        with open(PLIST_PATH, "rb") as f:
            data = plistlib.load(f)
    except (OSError, plistlib.InvalidFileException):
        return False
    args = data.get("ProgramArguments") or []
    return bool(args) and Path(args[0]) == executable


def sync_with_settings(settings) -> None:
    """Reconcile on-disk plist state with ``settings.start_at_login``.

    Called once at app start. Idempotent: noop when the on-disk state
    already matches the user's preference. Also rewrites a stale plist
    if the bundle was moved (e.g. user dragged Timshel.app to a
    different folder).
    """
    enabled_on_disk = is_launch_at_login_enabled()
    want_enabled = bool(getattr(settings, "start_at_login", False))

    if not want_enabled:
        if enabled_on_disk:
            disable_launch_at_login()
        return

    executable = get_executable_path()
    if executable is None:
        if enabled_on_disk:
            logger.debug(
                "Launch-at-login plist present but not running as bundle; "
                "leaving plist untouched (next bundle run will use it)."
            )
        return

    if not enabled_on_disk or not _plist_executable_matches(executable):
        enable_launch_at_login()
