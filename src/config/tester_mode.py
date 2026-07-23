"""Prototype tester-mode configuration, shared by the dogfood CLI scripts.

One definition of the "full prototype pipeline" knobs, so every dogfood entry
point (``make magic-digest``, ``make digest-archive``) measures the SAME
configuration and their rows in ``metrics.jsonl`` stay comparable. In-process
overrides only — they die with the process and never touch a user's settings.
"""

from __future__ import annotations

from src.config import config


def apply_tester_overrides(model: str) -> None:
    """Switch this process to the full prototype pipeline.

    Turns on tester labelling, metrics and the verdict pass, enables the
    distance channels that are off in the production baseline (unvalidated —
    the dogfood is what validates them), and routes synthesis + verdict to
    ``model``.
    """
    config.PROTOTYPE_TESTER_MODE = True
    config.INSIGHT_METRICS_ENABLED = True
    config.VERDICT_ENABLED = True
    config.SYNTHESIS_ENTITY_COUNT = 4
    config.SYNTHESIS_DENSE_COUNT = 6
    config.SYNTHESIS_GRAPH_COUNT = 6
    config.SYNTHESIS_STANCE_COUNT = 4
    config.LLM_MODEL_SYNTHESIS = model
    config.LLM_MODEL_VERDICT = model
