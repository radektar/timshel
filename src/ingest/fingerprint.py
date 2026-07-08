"""Content fingerprint for imported text.

Audio fingerprints hash the file bytes; imported text has no audio, so we hash
the normalized text plus the source name. Same format prefix (``sha256:``) as
:func:`src.fingerprint.compute_fingerprint` so the vault index treats both the
same — dedup, versioning and lookups work unchanged. Collision across the two
inputs requires a SHA-256 collision (negligible).
"""

from __future__ import annotations

import hashlib


def text_fingerprint(text: str, source_name: str) -> str:
    """Deterministic ``sha256:<hex>`` for imported text.

    Keyed on both the content and the source filename so two different files
    with identical text still get distinct notes, while re-importing the same
    file dedups (the vault index already holds the fingerprint).
    """
    payload = f"{source_name}\0{text}".encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()
