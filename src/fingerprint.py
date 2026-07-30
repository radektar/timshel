"""Audio fingerprint utilities for cross-device deduplication."""

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from mutagen import File as MutagenFile
except ImportError:  # pragma: no cover - optional dependency in some tests
    MutagenFile = None


def _extract_recording_datetime(audio_file: Path) -> datetime:
    """Extract recording datetime from tags, fallback to mtime."""
    if MutagenFile is not None:
        try:
            audio = MutagenFile(str(audio_file))
            if audio is not None and hasattr(audio, "tags") and audio.tags:
                for key in ("TDRC", "TDOR", "TDRL", "date", "DATE", "creation_date"):
                    if key in audio.tags:
                        value = audio.tags[key]
                        if isinstance(value, list) and value:
                            value = value[0]
                        parsed = _parse_datetime(str(value))
                        if parsed:
                            return parsed
        except Exception as error:  # noqa: BLE001
            logger.debug(
                "Could not read metadata datetime for %s: %s",
                audio_file,
                error,
            )

    return datetime.fromtimestamp(audio_file.stat().st_mtime)


def _parse_datetime(raw: str) -> Optional[datetime]:
    """Parse datetime from metadata value."""
    normalized = raw.strip()
    if not normalized:
        return None
    if len(normalized) == 4 and normalized.isdigit():
        normalized = f"{normalized}-01-01T00:00:00"
    normalized = normalized.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized[:25])
    except ValueError:
        return None


def compute_fingerprint(
    audio_file: Path, recording_datetime: Optional[datetime] = None
) -> str:
    """Compute deterministic fingerprint from content + metadata.

    ``recording_datetime`` overrides the tag/mtime lookup. Callers that know the
    true recording time from a source outside the file (the Voice Memos
    connector reads it from the filename) must pass it: for a tagless .m4a the
    fallback is mtime, and iCloud rewrites mtime on re-sync — which would give
    the same recording two different fingerprints and duplicate its note.
    """
    hasher = hashlib.sha256()
    with audio_file.open("rb") as handle:
        hasher.update(handle.read(1024 * 1024))
    hasher.update(str(audio_file.stat().st_size).encode("utf-8"))
    stamp = recording_datetime or _extract_recording_datetime(audio_file)
    hasher.update(stamp.isoformat().encode("utf-8"))
    return f"sha256:{hasher.hexdigest()}"
