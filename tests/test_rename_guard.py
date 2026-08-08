"""Guard: no stray pre-rename ``malinche`` references leak back into src/.

The project was renamed Malinche→Timshel. A blanket sweep converted every
user-visible string, path, class and marker. A handful of references are kept
*deliberately* — migration code that must recognise the old names, external
identifiers, and a back-compat digest marker — enumerated in ``_ALLOWLIST``.
Any NEW occurrence outside that set is almost certainly an oversight and fails
this test, so the rename cannot silently regress.
"""

from __future__ import annotations

import re
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"

# file (relative to src/) -> why its ``malinche`` mentions are intentional.
_ALLOWLIST = {
    # The migration itself must reference the old container / sidecar / agent.
    "bootstrap.py",
    # External license endpoint (beta short-circuits before calling it).
    "config/license.py",
    # Back-compat: reconciliation must skip a stray pre-rename ``.malinche``
    # sidecar dir when walking a migrated vault, or its files read as
    # transcripts.
    "transcriber.py",
    # Back-compat: still exclude a pre-rename ``malinche-digest`` note and
    # skip the old ``.malinche`` sidecar when walking a migrated vault.
    "connections/candidate_assembly.py",
    "menu_app.py",
    # Same back-compat marker, one place: NON_SOURCE_TYPES lists the pre-rename
    # digest type so the tag index and the glossary both skip a stray
    # pre-rename digest at the vault's top level.
    "tag_index.py",
}

_MALINCHE = re.compile(r"malinche", re.IGNORECASE)


def test_no_stray_malinche_references():
    offenders = []
    for path in _SRC.rglob("*.py"):
        rel = path.relative_to(_SRC).as_posix()
        if rel in _ALLOWLIST:
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if _MALINCHE.search(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()}")

    assert not offenders, "Stray pre-rename references found:\n" + "\n".join(offenders)
