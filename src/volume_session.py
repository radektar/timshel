"""Process-wide registry of volumes approved "Once" for the current session.

"Once" means: trust this disk *while it stays mounted*, and forget it the
moment it is ejected. The decision is deliberately **not** persisted to
``UserSettings`` — that is what "Yes/trusted" is for. Keeping it here, in a
single process-wide registry, lets both sides of the detection pipeline agree:

- the authorization gate (``FileMonitor._authorize_volume``), and
- recorder discovery (``volume_utils.should_process_volume`` →
  ``Transcriber.find_recorders``)

both consult this registry, so an "Once" disk is actually transcribed — not
just waved through the gate and then dropped by the worker. Eject-and-replug
re-prompts, because :func:`prune_to` forgets any approved UUID that is no
longer mounted.

Keyed by the stable volume UUID (see ``volume_identity.get_volume_uuid``).
"""

from __future__ import annotations

import threading
from typing import Set

_lock = threading.Lock()
_once_uuids: Set[str] = set()


def approve_once(uuid: str) -> None:
    """Mark *uuid* as trusted for the current mount session."""
    with _lock:
        _once_uuids.add(uuid)


def is_approved_once(uuid: str) -> bool:
    """Return True if *uuid* was approved "Once" and is still in the session."""
    with _lock:
        return uuid in _once_uuids


def forget(uuid: str) -> None:
    """Drop a single *uuid* from the session registry (e.g. on eject)."""
    with _lock:
        _once_uuids.discard(uuid)


def prune_to(mounted_uuids: Set[str]) -> Set[str]:
    """Forget every approved UUID not present in *mounted_uuids*.

    Called with the set of currently-mounted volume UUIDs so that ejected
    "Once" disks are forgotten (and therefore re-prompted on remount).

    Returns the set of UUIDs that were forgotten (mainly for logging/tests).
    """
    with _lock:
        gone = {u for u in _once_uuids if u not in mounted_uuids}
        _once_uuids.difference_update(gone)
        return gone


def all_approved() -> Set[str]:
    """Return a copy of the currently approved-once UUID set."""
    with _lock:
        return set(_once_uuids)


def clear() -> None:
    """Forget all session approvals (used at shutdown and in tests)."""
    with _lock:
        _once_uuids.clear()
