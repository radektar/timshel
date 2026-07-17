"""Application bootstrap and one-time legacy migration."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from src.config.settings import UserSettings
from src.env_loader import load_env_file
from src.runtime_deps import ensure_importable
from src.ui.constants import APP_VERSION


def _logger() -> logging.Logger:
    """Return bootstrap logger without importing runtime config."""
    return logging.getLogger("timshel")


def _safe_json_read(path: Path) -> Dict[str, Any]:
    """Read JSON file and return empty dict on failures."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


def _legacy_paths(home: Path) -> Dict[str, Path]:
    """Resolve all legacy and target paths for migration.

    The app-support container was renamed Malinche→Timshel. ``timshel_root`` is
    the live target; ``malinche_root`` is now a *legacy* root migrated on first
    launch (see :func:`_migrate_app_support`). All ``new_*`` targets hang off
    ``timshel_root``.
    """
    support = home / "Library" / "Application Support"
    timshel_root = support / "Timshel"
    malinche_root = support / "Malinche"
    transrec_root = support / "Transrec"
    return {
        "home": home,
        "timshel_root": timshel_root,
        "malinche_root": malinche_root,
        "transrec_root": transrec_root,
        "legacy_runtime_root": home / ".olympus_transcriber",
        "legacy_state_file": home / ".olympus_transcriber_state.json",
        "legacy_log_file": home / "Library" / "Logs" / "olympus_transcriber.log",
        "new_config_file": timshel_root / "config.json",
        "new_state_file": timshel_root / "state.json",
        "new_runtime_dir": timshel_root / "runtime",
        "new_lock_file": timshel_root / "runtime" / "transcriber.lock",
        "new_recordings_dir": timshel_root / "recordings",
        "new_logs_dir": timshel_root / "logs",
        "new_log_file": timshel_root / "logs" / "timshel.log",
    }


# Items that make up an app-support container (used for a partial per-item
# merge when BOTH the old and new roots exist).
_APP_SUPPORT_ITEMS = (
    "config.json",
    "state.json",
    "connections_state.json",
    "license.json",
    "license_cache.json",
    "bin",
    "models",
    "logs",
    "runtime",
    "recordings",
)


def _migrate_app_support(malinche_root: Path, timshel_root: Path) -> int:
    """One-time Malinche→Timshel app-support migration (order-critical).

    Runs BEFORE any ``UserSettings.load()`` so config/state resolve from the new
    root. When the new root does not exist yet, the whole dir is moved wholesale
    (near-atomic on one volume — no 700 MB re-download of bin/models). When both
    roots exist (a half-migrated or reinstalled state), items are merged
    per-item without ever overwriting an existing target. Idempotent: a no-op
    once ``timshel_root`` is populated and ``malinche_root`` is gone.
    """
    if not malinche_root.exists():
        return 0

    if not timshel_root.exists():
        timshel_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(malinche_root), str(timshel_root))
        _logger().info(
            "[bootstrap] migrated app-support %s -> %s (wholesale)",
            malinche_root,
            timshel_root,
        )
        return 1

    moved = 0
    for name in _APP_SUPPORT_ITEMS:
        target = timshel_root / name
        # A fresh Timshel root can hold EMPTY dirs (logs/runtime/recordings)
        # created by the logger/config at import time, before this migration
        # runs. Clear an empty target dir so the real item moves in cleanly
        # instead of being treated as a collision and archived.
        if target.is_dir():
            try:
                next(target.iterdir())
            except StopIteration:
                target.rmdir()
            except OSError:  # pragma: no cover - defensive
                pass
        moved += int(
            _move_with_backup(malinche_root / name, target, ".malinche.bak")
        )
    _cleanup_legacy_root(malinche_root, timshel_root)
    if moved:
        _logger().info(
            "[bootstrap] merged %s app-support items %s -> %s",
            moved,
            malinche_root,
            timshel_root,
        )
    return moved


def _migrate_vault_sidecars(vault: Path) -> int:
    """Rename the per-vault Malinche artefacts to their Timshel names.

    Each move is guarded (source present, target absent) and never merges, so
    running twice — or on a vault that only ever knew Timshel — is a no-op.
    """
    if not vault or not vault.exists():
        return 0
    renames = [
        (vault / ".malinche", vault / ".timshel"),
        (vault / "Malinche Digests", vault / "Timshel Digests"),
        (vault / "Malinche Recall", vault / "Timshel Recall"),
    ]
    moved = 0
    for src, dst in renames:
        if src.exists() and not dst.exists():
            try:
                shutil.move(str(src), str(dst))
                _logger().info("[bootstrap] vault sidecar %s -> %s", src, dst)
                moved += 1
            except OSError as exc:  # pragma: no cover - defensive
                _logger().warning("[bootstrap] sidecar move failed %s: %s", src, exc)
    return moved


def _remove_legacy_launch_agent(home: Path) -> None:
    """Best-effort removal of the pre-rename ``com.malinche.app`` LaunchAgent.

    The new bundle re-registers under ``com.timshel.app`` when the user has
    launch-at-login on; the stale agent must not linger pointing at a moved app.
    """
    plist = home / "Library" / "LaunchAgents" / "com.malinche.app.plist"
    if not plist.exists():
        return
    try:
        subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}/com.malinche.app"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except Exception:  # noqa: BLE001 - launchctl absence/failure is non-fatal
        pass
    try:
        plist.unlink()
        _logger().info("[bootstrap] removed legacy LaunchAgent %s", plist)
    except OSError:
        pass


def bundle_build_stamp() -> str:
    """The build stamp baked into Info.plist (``TimshelBuildStamp``).

    Returns "" in a dev/CLI run (no bundle / PyObjC missing) — callers log
    something like "dev (no bundle)" instead.
    """
    try:
        from Foundation import NSBundle

        value = NSBundle.mainBundle().objectForInfoDictionaryKey_(
            "TimshelBuildStamp"
        )
        return str(value) if value else ""
    except Exception:  # noqa: BLE001 - not a bundle / PyObjC missing
        return ""


def _bundle_tester_flag() -> bool:
    """True when running from a tester DMG (Info.plist ``TimshelTesterBuild``).

    Exception-safe: in a dev/CLI run there is no app bundle (or PyObjC), so this
    returns False and the flag can still be set by hand in config.json.
    """
    try:
        from Foundation import NSBundle

        value = NSBundle.mainBundle().objectForInfoDictionaryKey_(
            "TimshelTesterBuild"
        )
        return bool(value)
    except Exception:  # noqa: BLE001 - not a bundle / PyObjC missing
        return False


def _adopt_tester_build_flag(
    settings: UserSettings, already_configured: bool
) -> bool:
    """One-shot: a tester DMG defaults ``tester_mode`` on at first launch.

    Only fires when the persisted config had NOT yet recorded a ``tester_mode``
    value AND the bundle is a tester build, so a user who later flips it off in
    config.json is respected. ``already_configured`` MUST be captured from the
    raw config.json *before* any ``save()`` this run — ``to_dict`` always writes
    the key, so a save materialises it as ``false`` and re-reading here would
    always see it (the flag would never enable). Returns True when it changed
    and saved settings.
    """
    if already_configured:
        return False  # user/config already has an explicit value — respect it
    if not _bundle_tester_flag():
        return False
    settings.tester_mode = True
    settings.save()
    _logger().info("[bootstrap] tester build: enabled tester_mode")
    return True


def _newer_or_equal(src: Path, dst: Path) -> bool:
    """Return True when destination is newer or same age as source."""
    if not dst.exists():
        return False
    try:
        return dst.stat().st_mtime >= src.stat().st_mtime
    except OSError:
        return False


def _move_with_backup(
    src: Path,
    dst: Path,
    backup_suffix: str = ".transrec.bak",
) -> bool:
    """Move file/dir from src to dst, preserving collisions with source backup."""
    if not src.exists():
        return False

    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        backup = src.with_name(f"{src.name}{backup_suffix}")
        if backup.exists():
            return False
        shutil.move(str(src), str(backup))
        _logger().warning("[bootstrap] collision: moved %s -> %s", src, backup)
        return True

    shutil.move(str(src), str(dst))
    _logger().info("[bootstrap] moved %s -> %s", src, dst)
    return True


def _cleanup_legacy_root(legacy_root: Path, malinche_root: Path) -> int:
    """Remove empty legacy root or archive remaining leftovers."""
    if not legacy_root.exists():
        return 0

    moved = 0
    try:
        next(legacy_root.iterdir())
    except StopIteration:
        legacy_root.rmdir()
        _logger().info("[bootstrap] removed empty legacy dir %s", legacy_root)
        return 0
    except OSError:
        return 0

    stamp = datetime.now().strftime("%Y%m%d")
    archive_root = malinche_root / f".legacy-{stamp}" / legacy_root.name
    archive_root.mkdir(parents=True, exist_ok=True)

    for item in list(legacy_root.iterdir()):
        target = archive_root / item.name
        if _move_with_backup(item, target, backup_suffix=".legacy.bak"):
            moved += 1

    try:
        legacy_root.rmdir()
        _logger().info("[bootstrap] removed legacy dir %s", legacy_root)
    except OSError:
        pass

    return moved


def migrate_from_old_config() -> Optional[UserSettings]:
    """Build settings object from v1 legacy files/env."""
    paths = _legacy_paths(Path.home())
    old_config = _safe_json_read(paths["legacy_state_file"])

    settings = UserSettings()
    env_dir = (
        os.getenv("TIMSHEL_TRANSCRIBE_DIR")
        or os.getenv("MALINCHE_TRANSCRIBE_DIR")
        or os.getenv("OLYMPUS_TRANSCRIBE_DIR")
    )
    if env_dir:
        settings.output_dir = Path(env_dir).expanduser().resolve()
    elif old_config.get("transcribe_dir"):
        settings.output_dir = Path(old_config["transcribe_dir"]).expanduser().resolve()

    if old_config.get("language"):
        settings.language = str(old_config["language"])
    if old_config.get("whisper_model"):
        settings.whisper_model = str(old_config["whisper_model"])

    ai_api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")
    if ai_api_key:
        settings.enable_ai_summaries = True
        settings.ai_api_key = ai_api_key

    old_recorder_names = old_config.get(
        "recorder_names", ["LS-P1", "OLYMPUS", "RECORDER"]
    )
    if old_recorder_names:
        settings.watch_mode = "specific"
        settings.watched_volumes = list(old_recorder_names)

    if old_config or env_dir:
        settings.setup_completed = True
        return settings
    return None


def ensure_ready() -> UserSettings:
    """Ensure runtime is initialized and legacy paths migrated."""
    load_env_file()
    home = Path.home()
    paths = _legacy_paths(home)

    # Step 0 (order-critical): move the pre-rename Malinche app-support dir to
    # Timshel BEFORE any config/state read below resolves the new root. A move
    # failure (locked file, cross-volume partial copy) must never brick startup
    # — degrade to "no migration this run" and let the app come up on defaults
    # rather than crash before the menu bar loads.
    try:
        app_support_moved = _migrate_app_support(
            paths["malinche_root"], paths["timshel_root"]
        )
    except Exception as exc:  # noqa: BLE001
        _logger().error("[bootstrap] app-support migration failed: %s", exc)
        app_support_moved = 0
    _remove_legacy_launch_agent(home)

    # Capture whether tester_mode was ALREADY in config.json before any save()
    # this run — to_dict always writes the key, so a save would materialise it
    # and defeat the first-launch adoption below.
    tester_preconfigured = "tester_mode" in _safe_json_read(paths["new_config_file"])

    # Fast path: config exists and migration flag set — skip legacy scan.
    if paths["new_config_file"].exists():
        fast_settings = UserSettings.load()
        if getattr(fast_settings, "legacy_migrated", False):
            ensure_importable("anthropic")
            # Vault-side rename is independent of app-support: still guard it on
            # the fast path (guarded + cheap — a no-op once renamed).
            _migrate_vault_sidecars(Path(fast_settings.output_dir))
            _adopt_tester_build_flag(fast_settings, tester_preconfigured)
            if fast_settings.setup_version != APP_VERSION:
                fast_settings.setup_version = APP_VERSION
                fast_settings.save()
            return fast_settings

    moved_count = 0

    settings: UserSettings
    if paths["new_config_file"].exists():
        settings = UserSettings.load()
    else:
        transrec_config = paths["transrec_root"] / "config.json"
        if transrec_config.exists():
            data = _safe_json_read(transrec_config)
            settings = UserSettings(**data) if data else UserSettings()
            settings.save()
        else:
            migrated = migrate_from_old_config()
            if migrated is None:
                settings = UserSettings()
            else:
                settings = migrated
                settings.save()

    moved_count += app_support_moved

    transrec_root = paths["transrec_root"]
    timshel_root = paths["timshel_root"]
    if transrec_root.exists():
        for name in ("bin", "models", "config.json", "state.json"):
            moved_count += int(
                _move_with_backup(
                    transrec_root / name, timshel_root / name, ".transrec.bak"
                )
            )

    legacy_state = paths["legacy_state_file"]
    if legacy_state.exists() and not _newer_or_equal(legacy_state, paths["new_state_file"]):
        moved_count += int(_move_with_backup(legacy_state, paths["new_state_file"]))

    legacy_lock = paths["legacy_runtime_root"] / "transcriber.lock"
    moved_count += int(_move_with_backup(legacy_lock, paths["new_lock_file"]))

    legacy_recordings = paths["legacy_runtime_root"] / "recordings"
    moved_count += int(_move_with_backup(legacy_recordings, paths["new_recordings_dir"]))

    legacy_log = paths["legacy_log_file"]
    if legacy_log.exists() and not paths["new_log_file"].exists():
        moved_count += int(_move_with_backup(legacy_log, paths["new_log_file"]))

    moved_count += _cleanup_legacy_root(paths["legacy_runtime_root"], timshel_root)
    moved_count += _cleanup_legacy_root(paths["transrec_root"], timshel_root)

    # Best-effort safeguard: do not block startup when offline.
    ensure_importable("anthropic")

    settings = UserSettings.load()
    settings.legacy_migrated = True
    settings.setup_version = APP_VERSION
    settings.save()

    # Vault-side rename (independent of app-support): guarded, non-destructive.
    moved_count += _migrate_vault_sidecars(Path(settings.output_dir))
    _adopt_tester_build_flag(settings, tester_preconfigured)

    if moved_count:
        _logger().info("[bootstrap] migrated %s items", moved_count)
    else:
        _logger().info("[bootstrap] nothing to migrate")

    return UserSettings.load()
