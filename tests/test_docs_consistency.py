"""Regression guard: keep the public FREE/BYOK/PRO story coherent.

These tests encode the product-owner acceptance criteria for the doc rewrite
that moved Malinche's PRO value proposition from "hosted Claude proxy" to
"MCP integration". They run on pure text (no imports from ``src``) so they are
fast and stable, and they fail loudly if a future edit reintroduces a
contradiction across README.md, BACKLOG.md and Docs/PUBLIC-DISTRIBUTION-PLAN.md.

What "PO-ready" means here:
  1. One pricing story — no declared price; every price token sits in a
     "still undecided" context (TBD / considered / open question).
  2. No stale hosted-AI framing (PRO is MCP, not a Claude proxy).
  3. MCP is visibly the PRO flagship in every public doc.
  4. The three usage levels (FREE / BYOK / PRO) are described everywhere.
  5. No leftover per-tier minute caps from the old subscription model.
  6. No leaks of the private personal-AI workspace (Cortex / Obsidian).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

DOCS = {
    "README.md": REPO_ROOT / "README.md",
    "BACKLOG.md": REPO_ROOT / "BACKLOG.md",
    "PUBLIC-DISTRIBUTION-PLAN.md": REPO_ROOT / "Docs" / "PUBLIC-DISTRIBUTION-PLAN.md",
}

# Product price tokens that, if present on a line, must be framed as undecided.
PRICE_TOKENS = ("$79", "$5–$12", "$5-$12", "lifetime")

# Markers that make a price line acceptable (it is clearly not a final decision).
UNDECIDED_MARKERS = ("tbd", "considered", "open", "vs ", "amount", "decision")

# Lines that mention a price but are infrastructure cost, not a product price.
INFRA_LINE_MARKERS = ("supabase", "workers", "embedding", "at scale", "hosting")

# Stale framing from the old "PRO = hosted AI" model — must never reappear.
STALE_FRAMING = (
    "hosted claude",
    "claude api proxy",
    "server-side ai summar",
    "/v1/summarize",
    "/v1/tags",
)

# Per-tier minute caps were tied to the hosted-AI model and are now gone.
STALE_MINUTE_CAPS = (
    "300 min",
    "1000+ min",
    "1000 min",
    "minutes of processing",
    "minutes / month",
)

# Private personal-AI workspace must not leak into the public repo docs.
PRIVATE_LEAKS = ("cortex", "personal-ai-system")

# Old project names must not reappear in the public docs.
LEGACY_NAMES = ("olympus", "transrec")

# Matches inline markdown links: [text](target). Captures the target.
MD_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _read(name: str) -> str:
    path = DOCS[name]
    assert path.exists(), f"Expected doc is missing: {path}"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", DOCS)
def test_doc_exists_and_nonempty(name: str):
    assert _read(name).strip(), f"{name} is empty"


@pytest.mark.parametrize("name", DOCS)
def test_no_declared_price(name: str):
    """Every line with a product price token must be framed as undecided."""
    offenders: list[str] = []
    for line in _read(name).splitlines():
        low = line.lower()
        if any(tok.lower() in low for tok in PRICE_TOKENS):
            if any(m in low for m in INFRA_LINE_MARKERS):
                continue  # infra cost line, not a product price
            if not any(m in low for m in UNDECIDED_MARKERS):
                offenders.append(line.strip())
    assert (
        offenders == []
    ), f"{name}: price stated as if decided (must be TBD/considered):\n" + "\n".join(
        offenders
    )


@pytest.mark.parametrize("name", DOCS)
def test_no_stale_hosted_ai_framing(name: str):
    low = _read(name).lower()
    hits = [s for s in STALE_FRAMING if s in low]
    assert hits == [], f"{name}: stale hosted-AI framing found: {hits}"


@pytest.mark.parametrize("name", DOCS)
def test_no_stale_minute_caps(name: str):
    low = _read(name).lower()
    hits = [s for s in STALE_MINUTE_CAPS if s in low]
    assert hits == [], f"{name}: stale per-tier minute cap found: {hits}"


@pytest.mark.parametrize("name", DOCS)
def test_mcp_is_the_flagship(name: str):
    """MCP must be mentioned several times in each public doc."""
    count = _read(name).lower().count("mcp")
    assert count >= 3, f"{name}: MCP mentioned only {count}x (expected >= 3)"


@pytest.mark.parametrize("name", DOCS)
def test_three_usage_levels_present(name: str):
    text = _read(name)
    for token in ("FREE", "BYOK", "PRO"):
        assert token in text, f"{name}: missing usage level '{token}'"


@pytest.mark.parametrize("name", DOCS)
def test_no_private_workspace_leak(name: str):
    low = _read(name).lower()
    hits = [s for s in PRIVATE_LEAKS if s in low]
    assert hits == [], f"{name}: private workspace leaked into public doc: {hits}"


def test_pricing_options_match_across_docs():
    """BACKLOG and the distribution plan must offer the same pricing options."""
    backlog = _read("BACKLOG.md").lower()
    plan = _read("PUBLIC-DISTRIBUTION-PLAN.md").lower()
    for token in ("$5–$12/mo", "$25/mo", "$79 lifetime"):
        t = token.lower()
        assert t in backlog, f"BACKLOG.md missing pricing option '{token}'"
        assert (
            t in plan
        ), f"PUBLIC-DISTRIBUTION-PLAN.md missing pricing option '{token}'"


def test_byok_explained_not_just_named():
    """Each doc must explain BYOK keeps AI features in MIT, not behind PRO."""
    for name in DOCS:
        low = _read(name).lower()
        assert "anthropic_api_key" in low, f"{name}: BYOK key env var not shown"


@pytest.mark.parametrize("name", DOCS)
def test_no_legacy_project_names(name: str):
    low = _read(name).lower()
    hits = [s for s in LEGACY_NAMES if s in low]
    assert hits == [], f"{name}: legacy project name found: {hits}"


@pytest.mark.parametrize("name", DOCS)
def test_internal_links_resolve(name: str):
    """Relative markdown links in each doc must point to existing files."""
    doc_path = DOCS[name]
    broken: list[str] = []
    for target in MD_LINK.findall(_read(name)):
        # Skip external links and in-page anchors.
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        path_part = target.split("#", 1)[0]  # drop any #anchor
        if not path_part:
            continue
        resolved = (doc_path.parent / path_part).resolve()
        if not resolved.exists():
            broken.append(target)
    assert broken == [], f"{name}: broken internal links: {broken}"
