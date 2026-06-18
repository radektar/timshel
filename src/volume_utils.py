"""Shared utilities for detecting audio-containing volumes on macOS.

Centralizes the logic used by both ``FileMonitor`` (mount event filtering)
and ``Transcriber`` (recorder discovery) so that the two components stay
consistent with the user's ``watch_mode`` setting.
"""

from pathlib import Path
from typing import Iterable, List, Optional

from src.config.defaults import defaults
from src.config.settings import UserSettings
from src.logger import logger
from src.volume_identity import get_volume_uuid
from src import volume_session


def has_audio_files(
    path: Path,
    audio_extensions: Optional[Iterable[str]] = None,
    max_depth: Optional[int] = None,
) -> bool:
    """Return True if *path* contains at least one audio file within ``max_depth``.

    Args:
        path: Root directory to scan (typically a volume under ``/Volumes``).
        audio_extensions: Iterable of lowercase suffixes (e.g. ``{".mp3"}``).
            Defaults to ``defaults.AUDIO_EXTENSIONS``.
        max_depth: Maximum directory depth to recurse. Defaults to
            ``defaults.MAX_SCAN_DEPTH``.

    Returns:
        True when an audio file is found, False otherwise (including errors).
    """
    extensions = set(audio_extensions) if audio_extensions else set(defaults.AUDIO_EXTENSIONS)
    depth_limit = max_depth if max_depth is not None else defaults.MAX_SCAN_DEPTH

    try:
        for item in path.rglob("*"):
            try:
                relative = item.relative_to(path)
                dir_depth = len(relative.parts) - 1
                if dir_depth > depth_limit:
                    continue
            except ValueError:
                continue

            if item.is_file() and item.suffix.lower() in extensions:
                logger.debug(f"Found audio file: {item}")
                return True
    except PermissionError:
        logger.debug(f"Permission denied accessing {path}")
        return False
    except Exception as error:  # noqa: BLE001
        logger.debug(f"Error scanning {path}: {error}")
        return False

    return False


def should_process_volume(
    volume_path: Path,
    settings: UserSettings,
    audio_extensions: Optional[Iterable[str]] = None,
    max_depth: Optional[int] = None,
) -> bool:
    """Determine whether *volume_path* should be treated as a recorder.

    Strict UUID-based whitelist. Wcześniej zatwierdzona decyzja
    użytkownika (``trusted`` / ``blocked``) ma pierwszeństwo nad
    ``watch_mode``. Dla nieznanych dysków:

    * ``manual`` — odmawia (nadrzędny dialog Tak/Nie/Raz wywoływany
      przez ``FileMonitor`` poprzez callback ``on_unknown_volume``).
    * ``specific`` — legacy, akceptuje gdy nazwa volume jest na
      liście ``settings.watched_volumes``.

    Args:
        volume_path: Candidate volume path (e.g. ``/Volumes/MY_SD``).
        settings: Current ``UserSettings`` instance.
        audio_extensions: Nieużywane (zostawione dla zgodności wywołań
            z testami starszej wersji).
        max_depth: Jak wyżej.

    Returns:
        True when the volume should be processed, False otherwise.
    """
    del audio_extensions, max_depth  # zachowane w sygnaturze dla back-compat

    volume_name = volume_path.name

    if volume_name in defaults.SYSTEM_VOLUMES:
        return False

    uuid = get_volume_uuid(volume_path)
    trusted = settings.find_trusted_volume(uuid)
    if trusted is not None:
        if trusted.decision == "blocked":
            logger.debug(f"Skipping blocked volume: {volume_name} (uuid={uuid})")
            return False
        if trusted.decision == "trusted":
            return True
        # Nieznana decyzja w danych — bezpieczny default to nie-skanuj.
        logger.warning(
            f"Unknown decision '{trusted.decision}' for volume {volume_name}; "
            "treating as untrusted"
        )
        return False

    # "Once": zatwierdzony na czas tej sesji podłączenia (nie persystowany).
    # Sprawdzane *po* persisted trusted/blocked, by trwała decyzja miała
    # pierwszeństwo. Dzięki temu zarówno gate (FileMonitor) jak i worker
    # (find_recorders) traktują dysk jednakowo — i "Once" faktycznie
    # transkrybuje, zamiast przejść bramkę i zostać odrzucony przy skanie.
    if volume_session.is_approved_once(uuid):
        return True

    match settings.watch_mode:
        case "manual":
            # Decyzja podejmowana przez UI (dialog Tak/Nie/Raz). Tu odmawiamy.
            return False
        case "specific":
            return volume_name in settings.watched_volumes
        case _:
            logger.warning(f"Unknown watch_mode: {settings.watch_mode}")
            return False


def find_matching_volumes(
    settings: UserSettings,
    volumes_root: Path = Path("/Volumes"),
    audio_extensions: Optional[Iterable[str]] = None,
    max_depth: Optional[int] = None,
) -> List[Path]:
    """Return every mounted volume that matches the current ``watch_mode``.

    Volumes are returned sorted alphabetically by name so iteration order
    is deterministic across runs.

    Args:
        settings: Current ``UserSettings`` instance.
        volumes_root: Directory where macOS mounts external volumes.
            Parameterised so tests can point at a ``tmp_path``.
        audio_extensions: Override for audio extensions (mainly for tests).
        max_depth: Override for scan depth (mainly for tests).

    Returns:
        List of matching volume paths, possibly empty.
    """
    if not volumes_root.exists():
        logger.debug(f"Volumes root does not exist: {volumes_root}")
        return []

    matching: List[Path] = []
    try:
        candidates = sorted(volumes_root.iterdir(), key=lambda p: p.name)
    except OSError as error:
        logger.debug(f"Could not list {volumes_root}: {error}")
        return []

    for candidate in candidates:
        if not candidate.is_dir():
            continue
        if should_process_volume(candidate, settings, audio_extensions, max_depth):
            matching.append(candidate)

    return matching
