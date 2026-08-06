"""Unit tests for per-stage LLM model resolution (`src/llm/model_router.py`)."""

from __future__ import annotations

import pytest

from src.config.config import config
from src.llm import model_router as mr


def test_resolve_model_falls_back_to_global_default(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODEL", "claude-default")
    monkeypatch.setattr(config, "LLM_MODEL_SYNTHESIS", None, raising=False)
    assert mr.resolve_model("synthesis") == "claude-default"


def test_resolve_model_honours_stage_override(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODEL", "claude-default")
    monkeypatch.setattr(config, "LLM_MODEL_SYNTHESIS", "claude-opus-5", raising=False)
    assert mr.resolve_model("synthesis") == "claude-opus-5"
    # a different stage without an override still gets the global default
    monkeypatch.setattr(config, "LLM_MODEL_SUMMARY", None, raising=False)
    assert mr.resolve_model("summary") == "claude-default"


def test_resolve_model_unknown_stage_raises():
    with pytest.raises(ValueError):
        mr.resolve_model("bogus-stage")


def test_all_declared_stages_resolve(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODEL", "m")
    for stage in mr.STAGES:
        monkeypatch.setattr(config, f"LLM_MODEL_{stage.upper()}", None, raising=False)
        assert mr.resolve_model(stage) == "m"
