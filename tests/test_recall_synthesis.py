"""Results-synthesis: the one LLM in the pull path. Mocked client — no network."""

from __future__ import annotations

import types

import pytest

from src.connections.recall import synthesis as rs
from src.summarizer import APIBillingError


class _Result:
    def __init__(self, note_id, quote):
        self.note_id = note_id
        self.quote = quote


class _Block:
    type = "tool_use"
    name = "emit_answer"

    def __init__(self, inp):
        self.input = inp


class _Msg:
    def __init__(self, blocks, stop_reason="end_turn"):
        self.content = blocks
        self.stop_reason = stop_reason
        self.usage = None


class _Messages:
    def __init__(self, result):
        self._result = result

    def create(self, **kw):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _Client:
    def __init__(self, result):
        self.messages = _Messages(result)


def _synth(result):
    s = object.__new__(rs.RecallSynthesizer)
    s.client = _Client(result)
    s.model = "test-model"
    s.last_usage = None
    return s


_PAYLOAD = {
    "answered": True,
    "thesis": "Dostawa okien jest opozniona, dach czeka.",
    "evidence": [{"note": "okna", "date": "14.06", "quote": "dostawa niepewna"}],
    "directions": ["Co z alternatywnym dostawca okien?"],
}
_RESULTS = [_Result("okna", "dostawa okien niepewna, dach stoi")]


def test_build_user_prompt_includes_query_and_passages():
    prompt = rs._build_user_prompt("co z oknami", _RESULTS)
    assert "QUESTION: co z oknami" in prompt
    assert "[[okna]]" in prompt and "dostawa okien niepewna" in prompt


def test_synthesize_returns_grounded_answer():
    ans = _synth(_Msg([_Block(_PAYLOAD)])).synthesize("co z oknami", _RESULTS)
    assert ans is not None and ans.answered is True
    assert ans.evidence[0].note == "okna" and ans.evidence[0].quote == "dostawa niepewna"
    assert ans.directions


def test_synthesize_empty_inputs_return_none():
    s = _synth(_Msg([_Block(_PAYLOAD)]))
    assert s.synthesize("", _RESULTS) is None
    assert s.synthesize("q", []) is None


def test_synthesize_truncation_is_recoverable_none():
    ans = _synth(_Msg([_Block(_PAYLOAD)], stop_reason="max_tokens")).synthesize("q", _RESULTS)
    assert ans is None


def test_synthesize_no_tool_block_returns_none():
    plain = types.SimpleNamespace(type="text", text="hi")
    assert _synth(_Msg([plain])).synthesize("q", _RESULTS) is None


def test_synthesize_recoverable_api_error_returns_none():
    assert _synth(RuntimeError("transient")).synthesize("q", _RESULTS) is None


def test_synthesize_permanent_error_raises_billing(monkeypatch):
    monkeypatch.setattr(rs, "_is_permanent_api_error", lambda exc: "credit_balance")
    with pytest.raises(APIBillingError):
        _synth(RuntimeError("no credits")).synthesize("q", _RESULTS)


def test_synthesize_answer_safe_none_without_synthesizer(monkeypatch):
    monkeypatch.setattr(rs, "get_recall_synthesizer", lambda: None)
    assert rs.synthesize_answer_safe("q", _RESULTS) is None


def test_synthesize_answer_safe_swallows_billing(monkeypatch):
    class _Boom:
        def synthesize(self, q, r):
            raise APIBillingError("permanent")

    monkeypatch.setattr(rs, "get_recall_synthesizer", lambda: _Boom())
    assert rs.synthesize_answer_safe("q", _RESULTS) is None


def test_get_recall_synthesizer_gated_by_config(monkeypatch):
    from src.config.config import config as cfg

    monkeypatch.setattr(cfg, "LLM_API_KEY", None)
    assert rs.get_recall_synthesizer() is None
