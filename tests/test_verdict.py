"""Tests for the verdict pass — pure parsing/filtering + scheduler wiring."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config import config
from src.connections import verdict as vd
from src.connections.candidate_assembly import NoteRef
from src.connections.synthesis import Connection, ConnectionList, Evidence
from src.llm.model_router import resolve_model


def _conn(notes, ctype="shared-thread"):
    return Connection(
        type=ctype,
        notes=list(notes),
        rationale="r",
        evidence=[Evidence(note=notes[0], date="2026-06-01", quote="q")],
        directions=["A: Could you...?", "B: Might it...?"],
    )


# --------------------------------------------------------------------------- #
# Pure: parsing + apply_verdicts (fail-open semantics)
# --------------------------------------------------------------------------- #
def test_parse_payload_lenient():
    payload = {
        "verdicts": [
            {"index": 1, "verdict": True},
            {"index": "bad", "verdict": False},
            {"index": 2, "verdict": False, "severity": "fatal", "reason": "x"},
        ]
    }
    out = vd._parse_payload(payload)
    assert [v.index for v in out.verdicts] == [1, 2]
    assert vd._parse_payload("junk") is None


def test_apply_verdicts_drops_only_explicit_false():
    conns = [_conn(["a", "b"]), _conn(["c", "d"]), _conn(["e", "f"])]
    verdicts = vd.VerdictList(
        verdicts=[
            vd.Verdict(index=1, verdict=True),
            vd.Verdict(index=2, verdict=False, severity="fatal", reason="fabricated"),
            # no verdict for #3 -> keep (fail open)
        ]
    )
    kept = vd.apply_verdicts(conns, verdicts)
    assert [c.notes for c in kept] == [["a", "b"], ["e", "f"]]


def test_apply_verdicts_fails_open_on_none_and_bad_index():
    conns = [_conn(["a", "b"])]
    assert vd.apply_verdicts(conns, None) == conns  # recoverable error -> keep all
    verdicts = vd.VerdictList(
        verdicts=[
            vd.Verdict(index=99, verdict=False),
            vd.Verdict(index=0, verdict=False),
        ]
    )
    assert vd.apply_verdicts(conns, verdicts) == conns  # out-of-range ignored


def test_fuller_text_reads_file_and_falls_back(tmp_path):
    md = tmp_path / "n.md"
    md.write_text(
        "---\ntitle: n\n---\n\n## Podsumowanie\nSUMMARY\n\n## Transkrypcja\nFULL BODY",
        encoding="utf-8",
    )
    note = NoteRef(
        md_path=md,
        basename="n",
        title="n",
        date="2026-06-01",
        tags=[],
        norm_tags=set(),
        summary_md="SUMMARY-ONLY",
        fingerprint="",
    )
    assert "SUMMARY" in vd._fuller_text(note, 4000)
    note_missing = NoteRef(
        md_path=tmp_path / "ghost.md",
        basename="ghost",
        title="g",
        date="",
        tags=[],
        norm_tags=set(),
        summary_md="FALLBACK",
        fingerprint="",
    )
    assert vd._fuller_text(note_missing, 4000) == "FALLBACK"


def test_get_verifier_gated_by_config(monkeypatch):
    monkeypatch.setattr(config, "VERDICT_ENABLED", False)
    assert vd.get_verifier() is None
    monkeypatch.setattr(config, "VERDICT_ENABLED", True)
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    assert vd.get_verifier() is None


def test_resolve_model_verdict_stage(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODEL_VERDICT", None)
    assert resolve_model("verdict") == config.LLM_MODEL
    monkeypatch.setattr(config, "LLM_MODEL_VERDICT", "claude-opus-4-8")
    assert resolve_model("verdict") == "claude-opus-4-8"


# --------------------------------------------------------------------------- #
# Scheduler wiring (no API — stubbed synthesizer/verifier)
# --------------------------------------------------------------------------- #
class _StubSynth:
    model = "claude-opus-4-8"
    last_usage = None

    def __init__(self, result):
        self._result = result

    def synthesize(self, candidates, dismissed=None, language=None):
        return self._result


class _StubVerifier:
    model = "claude-opus-4-8"
    last_usage = None

    def __init__(self, verdicts):
        self._verdicts = verdicts

    def verify(self, connections, notes_by_basename, language=None):
        return self._verdicts


def _write_note(vault, name, date):
    (vault / f"{name}.md").write_text(
        f'---\ntitle: "{name}"\ndate: {date}\ntags: [t]\n---\n\n'
        f"## Podsumowanie\ntekst {name}\n\n## Transkrypcja\nfoo\n",
        encoding="utf-8",
    )


@pytest.fixture
def digest_env(tmp_path, monkeypatch):
    from src.connections.scheduler import reset_scheduler_for_tests

    vault = tmp_path / "vault"
    vault.mkdir()
    _write_note(vault, "n1", "2026-07-01")
    _write_note(vault, "n2", "2026-07-02")
    monkeypatch.setattr(config, "TRANSCRIBE_DIR", vault)
    monkeypatch.setattr(config, "DIGEST_LOCK_FILE", tmp_path / "digest.lock")
    monkeypatch.setattr(config, "CONNECTIONS_STATE_FILE", tmp_path / "cs.json")
    monkeypatch.setattr(config, "INSIGHT_METRICS_ENABLED", True)
    reset_scheduler_for_tests()
    yield vault
    reset_scheduler_for_tests()


def _run(monkeypatch, synth_result, verdicts=None, enabled=True):
    import src.connections.scheduler as sched
    import src.connections.synthesis as synth_mod
    import src.connections.verdict as verdict_mod

    monkeypatch.setattr(config, "VERDICT_ENABLED", enabled)
    monkeypatch.setattr(synth_mod, "get_synthesizer", lambda: _StubSynth(synth_result))
    constructed = []

    def fake_get_verifier():
        constructed.append(True)
        return _StubVerifier(verdicts)

    monkeypatch.setattr(verdict_mod, "get_verifier", fake_get_verifier)
    return sched.run_digest_if_due(transcriber=None, force=True), constructed


def test_verdict_disabled_verifier_never_constructed(digest_env, monkeypatch):
    result = ConnectionList(connections=[_conn(["n1", "n2"])])
    path, constructed = _run(monkeypatch, result, enabled=False)
    assert path is not None and path.exists()
    assert constructed == []  # baseline untouched


def test_verdict_drops_connection_from_digest_and_sidecar(digest_env, monkeypatch):
    result = ConnectionList(
        connections=[
            _conn(["n1", "n2"], "shared-thread"),
            _conn(["n2", "n1"], "emergent-idea"),
        ]
    )
    verdicts = vd.VerdictList(
        verdicts=[
            vd.Verdict(index=1, verdict=False, severity="fatal", reason="fab"),
            vd.Verdict(index=2, verdict=True),
        ]
    )
    path, constructed = _run(monkeypatch, result, verdicts=verdicts)
    assert constructed  # verifier ran
    assert path is not None
    body = path.read_text(encoding="utf-8")
    assert "emergent-idea" in body or "Emergent" in body or "nowy" in body.lower()
    sidecar = json.loads(
        (digest_env / ".malinche" / "insights-latest.json").read_text(encoding="utf-8")
    )
    assert len(sidecar["connections"]) == 1
    assert sidecar["connections"][0]["type"] == "emergent-idea"
    metrics = [
        json.loads(ln)
        for ln in (digest_env / ".malinche" / "metrics.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert metrics[-1]["verdict_dropped"] == 1
    assert metrics[-1]["connections"] == 1
    assert metrics[-1]["verdict_model"] == "claude-opus-4-8"


def test_all_dropped_no_digest_but_metrics_written(digest_env, monkeypatch):
    result = ConnectionList(connections=[_conn(["n1", "n2"])])
    verdicts = vd.VerdictList(
        verdicts=[vd.Verdict(index=1, verdict=False, severity="fatal", reason="fab")]
    )
    path, _ = _run(monkeypatch, result, verdicts=verdicts)
    assert path is None
    digests_dir = digest_env / config.DIGEST_DIR_NAME
    assert not digests_dir.exists() or not list(digests_dir.glob("*.md"))
    metrics = [
        json.loads(ln)
        for ln in (digest_env / ".malinche" / "metrics.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert metrics[-1]["connections"] == 0
    assert metrics[-1]["verdict_dropped"] == 1
    assert metrics[-1]["digest"] == ""
