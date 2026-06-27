"""The one canonical connection signature (ADR-004).

Every subsystem that needs to identify a connection — the dismissal store, the
digest sidecar, and the `action_taken` validation log — computes identity here,
so an `action_taken` event always joins back to the connection it measures.

Form: **type-inclusive, full SHA-1, note-order-independent.** Two connections
over the same notes but different synthesis types (shared-thread vs
emergent-idea) are genuinely different insights and must not collide.
"""

from __future__ import annotations

import hashlib
from typing import Iterable


def connection_signature(notes: Iterable[str], synthesis_type: str) -> str:
    """Stable signature for a connection, independent of note order.

    ``synthesis_type`` is the raw synthesis type string ("contradiction-over-time",
    not the UI display constant) — the sidecar carries it so the window can pass a
    precomputed sig rather than recompute (and drift).
    """
    key = synthesis_type.strip().lower() + "|" + "|".join(
        sorted(n.strip() for n in notes)
    )
    return hashlib.sha1(key.encode("utf-8")).hexdigest()
