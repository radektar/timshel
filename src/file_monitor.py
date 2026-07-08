"""File system monitoring for Malinche using FSEvents."""

import threading
import time
from typing import Callable, Optional
from pathlib import Path

try:
    from fsevents import Observer, Stream
    FSEVENTS_AVAILABLE = True
except ImportError:
    FSEVENTS_AVAILABLE = False

from src.logger import logger
from src.config import config
from src.config.settings import UserSettings
from src.config.defaults import defaults
from src.volume_identity import get_volume_uuid
from src.volume_utils import (
    find_matching_volumes,
    has_audio_files,
    should_process_volume,
)
from src import volume_session


# Decyzja zwracana przez ``on_unknown_volume`` callback do file monitora.
DECISION_TRUSTED = "trusted"
DECISION_BLOCKED = "blocked"
DECISION_ONCE = "once"
# Brak decyzji (timeout dialogu, błąd UI): NIE persystuj niczego — periodic
# scan zapyta ponownie. Trwałe "blocked" wolno zapisać wyłącznie po realnym
# kliknięciu użytkownika.
DECISION_NONE = "none"
# ``UnknownVolumeCallback`` przyjmuje (volume_path, uuid) i zwraca jedną
# z wartości powyżej.
UnknownVolumeCallback = Callable[[Path, str], str]

# Per-UUID guard: FSEvents (on_change) i periodic checker (scan_unknown_volumes)
# działają na osobnych wątkach — bez tego ten sam nieznany dysk potrafił
# dostać DWA dialogi naraz (drugi wątek mijał stale'owy snapshot ustawień,
# zanim pierwszy dialog został rozstrzygnięty).
_PROMPTS_IN_FLIGHT: set = set()
_PROMPTS_LOCK = threading.Lock()


class FileMonitor:
    """Monitor /Volumes for recorder mount events using FSEvents.

    This class uses macOS FSEvents API to efficiently monitor the /Volumes
    directory for changes, watching for any external volume (USB drive, SD card, etc.)
    that the user has explicitly approved.

    Supports two watch modes:
    - ``manual`` (default): Tylko volumes z whitelist UUID są skanowane.
      Nieznany dysk wywołuje dialog Tak/Nie/Raz przez ``on_unknown_volume``.
    - ``specific``: Legacy — akceptuje volumes po nazwie z ``watched_volumes``.

    Attributes:
        callback: Function to call when recorder activity is detected
        on_unknown_volume: Optional callback to ask user about an unknown volume
        observer: FSEvents Observer instance
        is_monitoring: Flag indicating if monitoring is active
    """

    def __init__(
        self,
        callback: Callable[[], None],
        on_unknown_volume: Optional[UnknownVolumeCallback] = None,
    ):
        """Initialize the file monitor.

        Args:
            callback: Function to call when recorder activity is detected
            on_unknown_volume: Optional handler resolving Tak/Nie/Raz prompts.
                Bez tego callbacku, nieznane volumes są bezdyskusyjnie pomijane.
        """
        if not FSEVENTS_AVAILABLE:
            logger.warning(
                "⚠️  FSEvents not available. Install with: "
                "pip install MacFSEvents"
            )

        self.callback = callback
        self.on_unknown_volume = on_unknown_volume
        self.observer: Optional[Observer] = None
        self.is_monitoring = False
        self._last_trigger_time = 0.0
        self._debounce_seconds = 2.0  # Prevent multiple rapid triggers
    
    def start(self) -> None:
        """Start monitoring /Volumes for mount events."""
        if not FSEVENTS_AVAILABLE:
            logger.error("Cannot start FSEvents monitor - library not available")
            return
        
        if self.is_monitoring:
            logger.warning("Monitor already running")
            return
        
        try:
            self.observer = Observer()
            
            def on_change(path, mask):
                """Callback for FSEvents changes."""
                current_time = time.time()

                # Debounce: Skip if triggered too recently
                if current_time - self._last_trigger_time < self._debounce_seconds:
                    return

                # Ignore internal macOS housekeeping on the recorder volume
                IGNORED_DIRS = {".Spotlight-V100", ".fseventsd", ".Trashes"}

                try:
                    path_obj = Path(path)
                except (TypeError, ValueError):
                    # Defensive: if path is not a string-like or invalid, just skip
                    logger.debug(f"Invalid path in FSEvents: {path}")
                    return

                # Detect which volume root (if any) this path belongs to
                volume_root: Optional[Path] = None

                # Get user settings (load once per event)
                settings = UserSettings.load()

                volumes_path = Path("/Volumes")
                for volume_name in volumes_path.iterdir():
                    if not volume_name.is_dir():
                        continue
                    try:
                        path_obj.relative_to(volume_name)
                    except ValueError:
                        continue
                    volume_root = volume_name
                    break

                if volume_root is None:
                    return

                if not self._authorize_volume(volume_root, settings):
                    return

                # Compute relative path inside the volume
                try:
                    relative = path_obj.relative_to(volume_root)
                except ValueError:
                    # Should not happen given the check above, but be safe
                    logger.debug(f"Could not compute relative path for: {path}")
                    return

                # If the first component is a macOS system directory, ignore
                parts = relative.parts
                if parts and parts[0] in IGNORED_DIRS:
                    logger.debug(f"Ignoring system directory change: {path}")
                    return

                logger.info(f"📢 Detected volume activity: {path}")
                self._last_trigger_time = current_time

                # Wait for system to fully mount the volume or finish writes
                time.sleep(config.MOUNT_MONITOR_DELAY)

                # Trigger callback
                try:
                    self.callback()
                except Exception as e:
                    logger.error(f"Error in callback: {e}", exc_info=True)
            
            # Create stream watching /Volumes
            stream = Stream(on_change, "/Volumes", file_events=False)
            self.observer.schedule(stream)
            
            self.is_monitoring = True
            self.observer.start()
            
            logger.info("✓ FSEvents monitor started (watching /Volumes)")

            self._initial_scan()

        except Exception as e:
            logger.error(f"Failed to start FSEvents monitor: {e}", exc_info=True)
            self.is_monitoring = False

    def _initial_scan(self) -> None:
        """Po starcie sprawdź już podłączone, **zaufane** dyski.

        FSEvents fires only on mount/change events — bez tego skanu dyktafon
        podłączony przed startem nie byłby wykryty aż do unmount/remount.
        Skan respektuje istniejącą whitelist UUID. Decyzje o nieznanych dyskach
        leżą po stronie ``MalincheMenuApp._maybe_run_volume_onboarding`` (po
        starcie pokazuje banner) oraz ``on_change`` (przy późniejszym mount).

        Callback wywoływany jest co najwyżej raz, bo ``Transcriber.process_recorder``
        sam iteruje po wszystkich matching volumes (``find_recorders``).
        """
        try:
            settings = UserSettings.load()
            matching = find_matching_volumes(settings, volumes_root=Path("/Volumes"))
        except Exception as error:  # noqa: BLE001
            logger.debug(f"Initial volume scan skipped due to error: {error}")
            return

        if not matching:
            logger.info("🔎 Initial scan: no trusted volumes already mounted")
            return

        names = ", ".join(volume.name for volume in matching)
        logger.info(
            f"🔎 Initial scan: found {len(matching)} trusted volume(s): {names}"
        )

        self._last_trigger_time = time.time()
        try:
            self.callback()
        except Exception as error:  # noqa: BLE001
            logger.error(
                f"Error in callback during initial scan: {error}", exc_info=True
            )

    def _authorize_volume(self, volume_path: Path, settings: UserSettings) -> bool:
        """Klasyfikuj volume i ewentualnie zapytaj usera.

        Zwraca ``True`` gdy volume jest *teraz* (po wszystkich potencjalnych
        update'ach whitelisty) traktowany jako recorder. ``False`` w pozostałych
        przypadkach (system volume, blocked, manual+brak decyzji bez UI, lub
        user wybrał Nie/Raz-bez-decyzji).
        """
        if volume_path.name in defaults.SYSTEM_VOLUMES:
            return False

        # Najpierw sprawdź whitelist po UUID (pomijając ścieżkę dialogu).
        if should_process_volume(volume_path, settings):
            return True

        # Volume nieautoryzowany. Jeśli watch_mode != manual lub user nie
        # podpiął on_unknown_volume — nic nie robimy (legacy zachowanie).
        if settings.watch_mode != "manual":
            return False
        if self.on_unknown_volume is None:
            return False

        uuid = get_volume_uuid(volume_path)

        # "Raz" zatwierdzony w tej sesji obsługuje już should_process_volume
        # wyżej; tu pozostaje tylko ścieżka decyzji użytkownika.

        # Dla pewności — może w międzyczasie ktoś inny dopisał decyzję.
        existing = settings.find_trusted_volume(uuid)
        if existing is not None:
            return existing.decision == "trusted"

        # Jeden dialog per UUID: drugi wątek (FSEvents vs periodic) odbija się
        # tutaj, dopóki pierwszy dialog nie zostanie rozstrzygnięty.
        with _PROMPTS_LOCK:
            if uuid in _PROMPTS_IN_FLIGHT:
                logger.debug(
                    "Prompt for volume %s already in flight — skipping", uuid
                )
                return False
            _PROMPTS_IN_FLIGHT.add(uuid)

        try:
            try:
                decision = self.on_unknown_volume(volume_path, uuid)
            except Exception as error:  # noqa: BLE001
                logger.error(
                    f"on_unknown_volume failed for {volume_path}: {error}",
                    exc_info=True,
                )
                return False

            if decision == DECISION_TRUSTED:
                self._persist_decision(uuid, volume_path.name, "trusted")
                return True
            if decision == DECISION_BLOCKED:
                self._persist_decision(uuid, volume_path.name, "blocked")
                return False
            if decision == DECISION_ONCE:
                # Mount-session trust: not persisted. Both the gate and
                # find_recorders read this via should_process_volume, so the disk
                # is actually transcribed; prune_to forgets it once ejected.
                volume_session.approve_once(uuid)
                logger.info(
                    "Volume '%s' approved for this session only (uuid=%s)",
                    volume_path.name,
                    uuid,
                )
                return True
            if decision == DECISION_NONE:
                # Timeout / błąd UI: nic nie zapisuj, periodic scan zapyta znowu.
                logger.info(
                    "No decision for volume '%s' (uuid=%s) — will re-ask later",
                    volume_path.name,
                    uuid,
                )
                return False
            logger.warning(f"Unknown decision from on_unknown_volume: {decision!r}")
            return False
        finally:
            with _PROMPTS_LOCK:
                _PROMPTS_IN_FLIGHT.discard(uuid)

    def scan_unknown_volumes(self, volumes_root: Path = Path("/Volumes")) -> None:
        """Polling fallback for unknown disks + "Once" eject lifecycle.

        Runs on every periodic tick and does two things in a single ``/Volumes``
        walk:

        1. **Forget ejected "Once" disks.** A disk approved "Once" is trusted
           only while mounted; once it disappears from ``/Volumes`` it is
           dropped (``volume_session.prune_to``) so a remount re-prompts.
        2. **Surface unknown disks FSEvents missed.** A mount event can be
           coalesced, or reported against the ``/Volumes`` parent rather than
           the mountpoint, so an unknown disk can stay invisible until remount.
           In ``manual`` mode (with a handler) every unknown, non-system volume
           triggers the Tak/Nie/Raz prompt here. Newly trusted/Once disks are
           picked up by the ``process_recorder`` call that follows this scan.
        """
        try:
            settings = UserSettings.load()
        except Exception as error:  # noqa: BLE001
            logger.debug(f"scan_unknown_volumes: could not load settings: {error}")
            return

        if not volumes_root.exists():
            # Nothing is mounted — every "Once" disk is gone.
            volume_session.prune_to(set())
            return

        try:
            candidates = sorted(volumes_root.iterdir(), key=lambda p: p.name)
        except OSError as error:
            logger.debug(
                f"scan_unknown_volumes: could not list {volumes_root}: {error}"
            )
            return

        can_prompt = (
            self.on_unknown_volume is not None and settings.watch_mode == "manual"
        )
        mounted_uuids: set[str] = set()

        for candidate in candidates:
            try:
                if not candidate.is_dir():
                    continue
            except OSError:
                continue
            if candidate.name in defaults.SYSTEM_VOLUMES:
                continue

            uuid = get_volume_uuid(candidate)
            mounted_uuids.add(uuid)

            if not can_prompt:
                continue
            if volume_session.is_approved_once(uuid):
                continue
            if settings.find_trusted_volume(uuid) is not None:
                continue

            logger.info(
                "🔎 Periodic scan: unknown volume %s — prompting (FSEvents miss?)",
                candidate.name,
            )
            self._authorize_volume(candidate, settings)

        # Forget "Once" approvals for disks no longer mounted (re-ask on remount).
        forgotten = volume_session.prune_to(mounted_uuids)
        if forgotten:
            logger.info(
                "Forgot %d ejected 'Once' volume(s): %s",
                len(forgotten),
                ", ".join(sorted(forgotten)),
            )

    @staticmethod
    def _persist_decision(uuid: str, name: str, decision: str) -> None:
        """Zapisz decyzję user-a do UserSettings (atomowo, pod lockiem)."""
        try:
            UserSettings.mutate(
                lambda s: s.add_trusted_volume(uuid=uuid, name=name, decision=decision)
            )
            logger.info(
                f"Volume decision saved: name={name!r} decision={decision} uuid={uuid}"
            )
        except Exception as error:  # noqa: BLE001
            logger.error(
                f"Failed to persist trusted volume decision for {name}: {error}",
                exc_info=True,
            )

    def _should_process_volume(self, volume_path: Path, settings: UserSettings) -> bool:
        """Check if volume should be processed based on watch mode.

        Thin wrapper around :func:`src.volume_utils.should_process_volume` so
        ``Transcriber`` and ``FileMonitor`` share one source of truth.

        Args:
            volume_path: Path to the volume (e.g., /Volumes/SD_CARD)
            settings: UserSettings instance with watch configuration

        Returns:
            True if volume should be processed, False otherwise
        """
        return should_process_volume(volume_path, settings)

    def _has_audio_files(self, path: Path, max_depth: int = None) -> bool:
        """Check if folder contains audio files.

        Thin wrapper around :func:`src.volume_utils.has_audio_files` retained
        for backward compatibility with existing tests.

        Args:
            path: Path to check
            max_depth: Maximum depth to scan (defaults to defaults.MAX_SCAN_DEPTH)

        Returns:
            True if audio files found, False otherwise
        """
        return has_audio_files(path, max_depth=max_depth)
    
    def stop(self) -> None:
        """Stop monitoring."""
        if not self.observer:
            return
        
        try:
            self.observer.stop()
            self.observer.join(timeout=5.0)
            self.is_monitoring = False
            logger.info("✓ FSEvents monitor stopped")
        except Exception as e:
            logger.error(f"Error stopping monitor: {e}", exc_info=True)

