"""Package a tester's H1 feedback into a single zip for the operator.

The H1 instruments (``signal.jsonl`` = kept/dismissed/handoff, ``metrics.jsonl``
= cost/coverage) and the digests being rated live inside the tester's own vault
with no telemetry path out. This collects them — plus a manifest — into one zip
the tester emails back. Pure and testable: it never touches AppKit or the OS
beyond reading the vault and writing the zip.

Privacy: the bundle carries digest text, note titles, and the vocabulary — and
nothing else. App logs are deliberately excluded.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import List

from src.config import config
from src.hostinfo import get_hostname
from src.ui.constants import APP_VERSION


class NothingToExportError(RuntimeError):
    """Raised when the vault holds no feedback artefacts yet (no digest run)."""


# Sidecar files worth collecting, in the order they appear in the manifest.
_SIDECAR_FILES = (
    "signal.jsonl",  # the H1 action instrument (kept/dismissed/handoff)
    "metrics.jsonl",  # per-digest cost + coverage
    "connections.json",  # dismissal / digest history
    "insights-latest.json",  # structured latest digest
    "vocabulary.json",  # user glossary (context for interpreting misses)
)


def build_feedback_zip(vault: Path, dest_dir: Path, *, timestamp: str) -> Path:
    """Zip the vault's H1 artefacts into ``dest_dir``; return the zip path.

    ``timestamp`` is passed in (``YYYYMMDD-HHMM``) rather than read from the
    clock so the function stays pure/deterministic for tests. Missing artefacts
    are skipped silently; if NOTHING is found, ``NothingToExportError`` is
    raised so the caller can tell the tester to generate a digest first.
    """
    vault = Path(vault)
    sidecar = vault / config.SIDECAR_DIR_NAME
    digest_dir = vault / config.DIGEST_DIR_NAME

    members: List[tuple] = []  # (arcname, absolute path)
    for name in _SIDECAR_FILES:
        p = sidecar / name
        if p.is_file():
            members.append((f"sidecar/{name}", p))

    digests = sorted(digest_dir.glob("*.md")) if digest_dir.is_dir() else []
    for p in digests:
        members.append((f"digests/{p.name}", p))

    if not members:
        raise NothingToExportError(
            "No feedback yet — generate a digest and rate a few connections first."
        )

    manifest = {
        "app_version": APP_VERSION,
        "created": timestamp,
        "hostname": get_hostname(),
        "tester_mode": bool(getattr(config, "PROTOTYPE_TESTER_MODE", False)),
        "counts": {
            "sidecar_files": sum(1 for a, _ in members if a.startswith("sidecar/")),
            "digests": len(digests),
        },
        "files": [a for a, _ in members],
    }

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / f"Timshel-feedback-{timestamp}.zip"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
        )
        for arcname, path in members:
            zf.write(path, arcname)

    return zip_path
