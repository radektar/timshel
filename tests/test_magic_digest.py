"""Thin insurance that magic_digest wires the prototype knobs correctly."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from src.config import config

_SPEC = importlib.util.spec_from_file_location(
    "magic_digest",
    Path(__file__).resolve().parents[1] / "scripts" / "magic_digest.py",
)
md = importlib.util.module_from_spec(_SPEC)
sys.modules["magic_digest"] = md
_SPEC.loader.exec_module(md)


def test_main_sets_overrides_and_forces_run(tmp_path, monkeypatch):
    calls = {}

    def fake_run(transcriber=None, force=False):
        calls["force"] = force
        calls["verdict"] = config.VERDICT_ENABLED
        calls["tester"] = config.PROTOTYPE_TESTER_MODE
        calls["model_synth"] = config.LLM_MODEL_SYNTHESIS
        calls["model_verdict"] = config.LLM_MODEL_VERDICT
        return None

    import src.connections.scheduler as sched

    monkeypatch.setattr(config, "TRANSCRIBE_DIR", tmp_path)
    monkeypatch.setattr(config, "LLM_API_KEY", "k")
    monkeypatch.setattr(sched, "run_digest_if_due", fake_run)
    monkeypatch.setattr(sys, "argv", ["magic_digest.py"])

    assert md.main() == 0
    assert calls["force"] is True
    assert calls["verdict"] is True
    assert calls["tester"] is True
    assert calls["model_synth"] == "claude-opus-4-8"
    assert calls["model_verdict"] == "claude-opus-4-8"


def test_no_verdict_flag(tmp_path, monkeypatch):
    seen = {}

    def fake_run(transcriber=None, force=False):
        seen["verdict"] = config.VERDICT_ENABLED
        return None

    import src.connections.scheduler as sched

    monkeypatch.setattr(config, "TRANSCRIBE_DIR", tmp_path)
    monkeypatch.setattr(config, "LLM_API_KEY", "k")
    monkeypatch.setattr(sched, "run_digest_if_due", fake_run)
    monkeypatch.setattr(sys, "argv", ["magic_digest.py", "--no-verdict"])

    assert md.main() == 0
    assert seen["verdict"] is False


def test_aborts_without_api_key(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TRANSCRIBE_DIR", tmp_path)
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    monkeypatch.setattr(sys, "argv", ["magic_digest.py"])
    assert md.main() == 1
