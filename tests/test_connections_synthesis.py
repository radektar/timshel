"""Unit tests for synthesis schema + synthesizer (mocked Claude, no API)."""

from pathlib import Path
from unittest.mock import patch

import pytest

from src.config import config
from src.connections import synthesis as synth_module
from src.connections.candidate_assembly import CandidateSet, NoteRef
from src.connections.synthesis import (
    Connection,
    ConnectionSynthesizer,
    Evidence,
    _parse_payload,
    get_synthesizer,
)
from src.summarizer import APIBillingError


def _candidates(count=2):
    notes = [
        NoteRef(
            md_path=Path(f"/x/n{i}.md"),
            basename=f"n{i}",
            title=f"n{i}",
            date="2026-06-20",
            tags=[],
            norm_tags=set(),
            summary_md="alpha beta gamma",
            fingerprint="sha256:x",
        )
        for i in range(count)
    ]
    return CandidateSet(notes, {notes[0].basename})


def _patch_client(monkeypatch, payload=None, raise_exc=None, stop_reason=None):
    block = type(
        "Block",
        (),
        {
            "type": "tool_use",
            "name": "emit_connections",
            "input": payload or {"connections": []},
        },
    )()

    class FakeMessages:
        def create(self, *_a, **_k):
            if raise_exc:
                raise raise_exc
            return type(
                "Msg", (), {"content": [block], "stop_reason": stop_reason}
            )()

    class FakeClient:
        def __init__(self, *_a, **_k):
            self.messages = FakeMessages()

    monkeypatch.setattr(synth_module, "Anthropic", FakeClient)


def test_connection_normalizes_wikilink_notes():
    # Models echo ids inconsistently ('[[X]]' vs 'X'); the validator normalizes
    # so the known-filter, dismiss signatures and digest wikilinks all agree.
    c = Connection(
        type="shared-thread",
        notes=["[[Cooling v1]]", " Cooling v2 "],
        rationale="x",
        directions=["A: ?", "B: ?"],
    )
    assert c.notes == ["Cooling v1", "Cooling v2"]


def test_connection_carries_evidence():
    # The 'ground' layer: each note gets a dated verbatim fragment. Note ids
    # are normalized the same way as Connection.notes so signatures agree.
    c = Connection(
        type="contradiction-over-time",
        notes=["A", "B"],
        rationale="the assumption shifted",
        evidence=[
            {"note": "[[A]]", "date": "17.06", "quote": "stands on quality"},
            {"note": "B", "date": "18.06", "quote": "budget 2x, lower quality?"},
        ],
        directions=["Could you name what shifted?", "Defend or revise the pillars?"],
    )
    assert [e.note for e in c.evidence] == ["A", "B"]
    assert isinstance(c.evidence[0], Evidence)


def test_connection_evidence_optional():
    # A model that under-provides evidence must not lose the whole connection —
    # the deck degrades to an empty ground layer, it does not reject.
    c = Connection(
        type="shared-thread",
        notes=["a", "b"],
        rationale="x",
        directions=["A: ?", "B: ?"],
    )
    assert c.evidence == []


def test_connection_drops_evidence_for_unknown_notes():
    # Evidence referencing a note not in the connection is filtered out, not
    # fatal — grounded-only, but lenient like _parse_payload.
    c = Connection(
        type="shared-thread",
        notes=["a", "b"],
        rationale="x",
        evidence=[
            {"note": "a", "date": "01.06", "quote": "real"},
            {"note": "ghost", "date": "02.06", "quote": "stray"},
        ],
        directions=["A: ?", "B: ?"],
    )
    assert [e.note for e in c.evidence] == ["a"]


def test_parse_payload_is_lenient():
    payload = {
        "connections": [
            {
                "type": "shared-thread",
                "notes": ["a", "b"],
                "rationale": "x",
                "directions": ["A: ?", "B: ?"],
            },
            {
                "type": "shared-thread",
                "notes": ["only"],
                "rationale": "bad",
                "directions": ["A: ?", "B: ?"],
            },
        ]
    }
    assert len(_parse_payload(payload).connections) == 1
    assert _parse_payload("not a dict").connections == []
    assert _parse_payload({"connections": []}).connections == []


def test_connection_schema_constraints():
    with pytest.raises(Exception):
        Connection(
            type="shared-thread",
            notes=["only"],
            rationale="x",
            directions=["A: ?", "B: ?"],
        )
    with pytest.raises(Exception):
        Connection(
            type="shared-thread", notes=["a", "b"], rationale="x", directions=["one"]
        )


def test_synthesize_returns_connections(monkeypatch):
    _patch_client(
        monkeypatch,
        {
            "connections": [
                {
                    "type": "shared-thread",
                    "notes": ["n0", "n1"],
                    "rationale": "x",
                    "directions": ["A: ?", "B: ?"],
                }
            ]
        },
    )
    out = ConnectionSynthesizer(api_key="k", model="m").synthesize(_candidates())
    assert out is not None and len(out.connections) == 1


def test_synthesize_returns_none_on_truncation(monkeypatch):
    # A truncated forced-tool call must be recoverable (None), not an empty
    # ConnectionList — otherwise the caller marks the run done and resets the
    # weekly trigger on what was really a token-ceiling failure.
    _patch_client(
        monkeypatch,
        payload={
            "connections": [
                {
                    "type": "shared-thread",
                    "notes": ["a", "b"],
                    "rationale": "x",
                    "directions": ["A: ?", "B: ?"],
                }
            ]
        },
        stop_reason="max_tokens",
    )
    out = ConnectionSynthesizer(api_key="k", model="m").synthesize(_candidates())
    assert out is None


def test_synthesize_skips_small_corpus(monkeypatch):
    _patch_client(monkeypatch)
    out = ConnectionSynthesizer(api_key="k", model="m").synthesize(_candidates(1))
    assert out.connections == []


def test_synthesize_raises_on_billing(monkeypatch):
    class Billing(Exception):
        status_code = 400
        message = "Your credit balance is too low"

        def __str__(self):
            return self.message

    _patch_client(monkeypatch, raise_exc=Billing())
    with pytest.raises(APIBillingError):
        ConnectionSynthesizer(api_key="k", model="m").synthesize(_candidates())


def test_get_synthesizer_no_key_returns_none(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "claude")
    monkeypatch.setattr(config, "LLM_API_KEY", None)
    monkeypatch.setattr(config, "ENABLE_CONNECTION_SYNTHESIS", True)
    assert get_synthesizer() is None


def test_get_synthesizer_builds_with_key(monkeypatch):
    """Tier gating removed: a Claude key alone yields a synthesizer."""
    monkeypatch.setattr(config, "LLM_PROVIDER", "claude")
    monkeypatch.setattr(config, "LLM_API_KEY", "sk-test")
    monkeypatch.setattr(config, "ENABLE_CONNECTION_SYNTHESIS", True)
    monkeypatch.setattr(config, "LLM_MODEL", "claude-haiku-4-5-20251001")
    with patch("src.connections.synthesis.ConnectionSynthesizer"):
        assert get_synthesizer() is not None
