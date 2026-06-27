"""Unit tests for digest rendering/writing (no API)."""

import json

from src.config import config
from src.connections.digest_writer import render_digest, write_digest_note
from src.connections.signature import connection_signature
from src.connections.synthesis import Connection


def _conn(conn_type="shared-thread", notes=("a", "b"), evidence=None):
    return Connection(
        type=conn_type,
        notes=list(notes),
        rationale="why these connect",
        evidence=evidence or [],
        directions=["A: a path?", "B: another?"],
    )


def test_render_has_frontmatter_links_and_dismiss_tokens():
    body = render_digest([_conn()], 5)
    assert "type: malinche-digest" in body
    assert "dismissed: []" in body
    assert "[[a]]" in body and "[[b]]" in body
    assert "`dismiss: 1`" in body
    assert "Shared thread" in body


def test_render_type_labels():
    body = render_digest([_conn("contradiction-over-time"), _conn("emergent-idea")], 5)
    assert "Contradiction over time" in body
    assert "Emergent idea" in body


def test_write_digest_returns_meta_and_is_collision_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TRANSCRIBE_DIR", tmp_path)
    p1, meta1 = write_digest_note([_conn()], 5)
    p2, meta2 = write_digest_note([_conn()], 5)
    assert p1.exists() and p2.exists() and p1 != p2  # collision-safe
    assert meta1[0]["type"] == "shared-thread"
    assert set(meta1[0].keys()) == {"sig", "notes", "type"}
    assert (tmp_path / config.DIGEST_DIR_NAME).is_dir()


def test_sidecar_carries_evidence_and_canonical_sig(tmp_path, monkeypatch):
    # The UI contract (ADR-004): insights-latest.json must round-trip the evidence
    # and a precomputed canonical sig that insight_pipeline.latest_deck consumes.
    monkeypatch.setattr(config, "TRANSCRIBE_DIR", tmp_path)
    from src.connections.synthesis import Evidence

    conn = _conn(
        "contradiction-over-time",
        notes=("Note A", "Note B"),
        evidence=[
            Evidence(note="Note A", date="17.06", quote="quality first"),
            Evidence(note="Note B", date="18.06", quote="budget 2x"),
        ],
    )
    write_digest_note([conn], 5)
    sidecar = json.loads(
        (tmp_path / ".malinche" / "insights-latest.json").read_text(encoding="utf-8")
    )
    c0 = sidecar["connections"][0]
    assert c0["sig"] == connection_signature(["Note A", "Note B"], "contradiction-over-time")
    assert [e["date"] for e in c0["evidence"]] == ["17.06", "18.06"]
    assert c0["evidence"][0]["quote"] == "quality first"


def test_render_includes_evidence_block():
    from src.connections.synthesis import Evidence

    body = render_digest(
        [_conn(evidence=[Evidence(note="a", date="01.06", quote="the fragment")])], 3
    )
    assert "Based on:" in body
    assert "the fragment" in body
