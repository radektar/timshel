"""Unit tests for connection candidate assembly (no API)."""

from pathlib import Path

import pytest

from src.config import config
from src.connections.candidate_assembly import (
    NoteRef,
    _bm25_ranked,
    _entity_neighbors,
    assemble_candidates,
    load_corpus,
)
from src.connections.dismissals import DismissalStore


def _write_note(
    vault, name, date, tags="", summary="", transcript="foo bar baz", extra=""
):
    body = (
        f'---\ntitle: "{name}"\ndate: {date}\ntags: [{tags}]\n'
        f"fingerprint: sha256:{name}\n{extra}---\n\n"
    )
    if summary:
        body += f"## Podsumowanie\n{summary}\n\n"
    body += f"## Transkrypcja\n{transcript}\n"
    (vault / f"{name}.md").write_text(body, encoding="utf-8")


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TRANSCRIBE_DIR", tmp_path)
    return tmp_path


def _note(basename, date, tags=(), summary=""):
    return NoteRef(
        md_path=Path(f"/x/{basename}.md"),
        basename=basename,
        title=basename,
        date=date,
        tags=list(tags),
        norm_tags=set(tags),
        summary_md=summary,
        fingerprint="sha256:x",
    )


def test_first_run_window_is_recent(vault):
    for i in range(5):
        _write_note(vault, f"note{i}", f"2026-06-1{i}", summary="alpha beta gamma")
    cs = assemble_candidates(vault, None, DismissalStore(vault), first_run_window=3)
    assert len(cs.window_basenames) == 3
    # newest three by date
    assert "note4" in cs.window_basenames and "note0" not in cs.window_basenames


def test_window_filters_by_last_digest_date(vault):
    _write_note(vault, "old", "2026-06-01", summary="alpha")
    _write_note(vault, "fresh", "2026-06-20", summary="alpha")
    cs = assemble_candidates(vault, "2026-06-10T00:00:00", DismissalStore(vault))
    assert "fresh" in cs.window_basenames
    assert "old" not in cs.window_basenames


def test_tag_bridge_pulls_older_sharing_tag(vault):
    _write_note(vault, "new", "2026-06-20", tags="sauna", summary="cokolwiek nowego")
    _write_note(vault, "older_shared", "2026-05-01", tags="sauna", summary="stare ale")
    _write_note(
        vault, "older_other", "2026-05-01", tags="ogrod", summary="rosliny tutaj"
    )
    cs = assemble_candidates(vault, "2026-06-10T00:00:00", DismissalStore(vault))
    names = {n.basename for n in cs.notes}
    assert "older_shared" in names  # tag bridge


def test_digest_folder_and_type_excluded(vault):
    _write_note(vault, "real", "2026-06-20", summary="alpha beta")
    digest_dir = vault / config.DIGEST_DIR_NAME
    digest_dir.mkdir()
    (digest_dir / "2026-06-20 Synthesis.md").write_text(
        "---\ntype: malinche-digest\n---\n\nbody", encoding="utf-8"
    )
    # A stray digest-typed note at top level must also be skipped.
    (vault / "stray.md").write_text(
        "---\ntype: malinche-digest\n---\n\nbody", encoding="utf-8"
    )
    corpus = load_corpus(vault)
    names = {n.basename for n in corpus}
    assert names == {"real"}


def test_muted_note_excluded(vault):
    _write_note(vault, "a", "2026-06-20", tags="t", summary="alpha")
    _write_note(vault, "b", "2026-06-20", tags="t", summary="alpha")
    store = DismissalStore(vault).load()
    store.mute_note("b")
    cs = assemble_candidates(vault, None, store)
    assert "b" not in {n.basename for n in cs.notes}


def test_summary_or_excerpt_without_summary_block(vault):
    # No "## Transkrypcja" marker, no summary -> body excerpt is used.
    (vault / "raw.md").write_text(
        '---\ntitle: "raw"\ndate: 2026-06-20\ntags: []\n---\n\njust some body text here',
        encoding="utf-8",
    )
    corpus = load_corpus(vault)
    assert corpus and corpus[0].summary_md.strip() == "just some body text here"


def test_bm25_ranks_lexically_related_first():
    window = [
        _note("W", "2026-06-20", summary="alembik destylacja temperatura chlodzenie")
    ]
    related = _note(
        "related", "2026-05-01", summary="destylacja temperatura ciecz chlodzenie"
    )
    unrelated = _note(
        "unrelated", "2026-05-01", summary="ogrodnictwo warzywa kompost grzadki"
    )
    ranked = _bm25_ranked(window, [unrelated, related])
    assert ranked and ranked[0].basename == "related"


def test_entity_neighbors_join_on_shared_proper_noun():
    # "hit" shares the entity; "miss" shares nothing. Topic words differ.
    window = [
        _note("W", "2026-06-20", summary="rozmowa z Bank Ochrony Środowiska wczoraj")
    ]
    hit = _note(
        "hit", "2026-05-01", summary="znowu Bank Ochrony Środowiska, zmiana planu"
    )
    miss = _note("miss", "2026-05-01", summary="ogrodnictwo kompost grzadki warzywa")
    res = _entity_neighbors(window, [miss, hit], {"W"}, max_n=2)
    assert [n.basename for n in res] == ["hit"]


def test_entity_neighbors_respects_exclude_and_zero():
    window = [_note("W", "2026-06-20", summary="Bank Ochrony Środowiska")]
    older = [_note("hit", "2026-05-01", summary="Bank Ochrony Środowiska znów")]
    assert _entity_neighbors(window, older, {"W", "hit"}, 2) == []  # excluded
    assert _entity_neighbors(window, older, {"W"}, 0) == []  # channel off


def test_entity_channel_attributed_in_channel_map(vault):
    _write_note(
        vault,
        "new",
        "2026-06-20",
        summary="Ustalenia Bank Ochrony Środowiska poszly ok",
    )
    _write_note(
        vault,
        "older_ent",
        "2026-05-01",
        summary="Bank Ochrony Środowiska wraca, zmiana",
    )
    cs = assemble_candidates(
        vault, "2026-06-10T00:00:00", DismissalStore(vault), inject_entities=3
    )
    names = {n.basename for n in cs.notes}
    assert "older_ent" in names
    assert "entity" in cs.channel_map.get("older_ent", set())
    assert cs.channel_map.get("new") == {"window"}


def test_entities_off_by_default_no_entity_channel(vault):
    _write_note(vault, "new", "2026-06-20", summary="Bank Ochrony Środowiska poszlo ok")
    _write_note(
        vault, "older_ent", "2026-05-01", summary="Bank Ochrony Środowiska wraca"
    )
    cs = assemble_candidates(vault, "2026-06-10T00:00:00", DismissalStore(vault))
    # inject_entities defaults to 0 -> no note is attributed to the entity channel
    all_channels = set().union(*cs.channel_map.values()) if cs.channel_map else set()
    assert "entity" not in all_channels


def test_as_of_excludes_future_notes(vault):
    _write_note(vault, "past", "2026-05-01", tags="t", summary="alpha")
    _write_note(vault, "cutoff_day", "2026-06-10", tags="t", summary="alpha")
    _write_note(vault, "future", "2026-06-20", tags="t", summary="alpha")
    corpus = load_corpus(vault, as_of="2026-06-10")
    assert {n.basename for n in corpus} == {"past", "cutoff_day"}  # inclusive


def test_as_of_flows_through_assemble(vault):
    _write_note(vault, "old", "2026-05-01", tags="t", summary="alpha")
    _write_note(vault, "newer", "2026-06-10", tags="t", summary="alpha")
    _write_note(vault, "future", "2026-06-20", tags="t", summary="alpha")
    cs = assemble_candidates(
        vault, "2026-06-09T00:00:00", DismissalStore(vault), as_of="2026-06-10"
    )
    names = {n.basename for n in cs.notes}
    assert "future" not in names
    assert cs.window_basenames == {"newer"}


def test_char_budget_caps_total(vault, monkeypatch):
    monkeypatch.setattr(config, "MAX_SYNTHESIS_PROMPT_CHARS", 500)
    monkeypatch.setattr(config, "MAX_SYNTHESIS_NOTES", 25)
    big = "slowo " * 400  # ~2000 chars
    for i in range(6):
        _write_note(vault, f"n{i}", f"2026-06-2{i}", tags="t", summary=big)
    cs = assemble_candidates(vault, None, DismissalStore(vault), first_run_window=1)
    total = sum(len(n.summary_md) for n in cs.notes)
    # window note always kept even if it alone exceeds budget; no extras added.
    assert len(cs.window_basenames) == 1
    assert total <= len(cs.notes[0].summary_md) + 500
