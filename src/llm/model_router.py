"""Per-stage LLM model resolution.

Malinche is model-agnostic: any model can be plugged at any stage of the
pipeline (summary / tags / synthesis / judge). A stage reads its own
``LLM_MODEL_<STAGE>`` override from config and falls back to the global
``LLM_MODEL`` when the override is unset.

This keeps the model choice for the *synthesis* stage (the differentiating,
quality-sensitive step) independent from the cheap summary/tag stages, and
lets an eval pick the winner (Opus 4.8 vs Sonnet 4.6) without touching code.
"""

from __future__ import annotations

from typing import Tuple

from src.config.config import config

# Recognised pipeline stages. Explicit so a typo raises instead of silently
# falling back to the global default.
STAGES: Tuple[str, ...] = ("summary", "tags", "synthesis", "judge", "results_synthesis")


def resolve_model(stage: str) -> str:
    """Return the model id configured for *stage*, else the global default.

    Args:
        stage: one of :data:`STAGES`.

    Returns:
        The model identifier string (e.g. ``"claude-sonnet-4-6"``).

    Raises:
        ValueError: if *stage* is not a recognised stage.
    """
    if stage not in STAGES:
        raise ValueError(f"Unknown LLM stage: {stage!r} (expected one of {STAGES})")
    override = getattr(config, f"LLM_MODEL_{stage.upper()}", None)
    return str(override or config.LLM_MODEL)
