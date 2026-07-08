"""Unit tests for connection candidate assembly (no API)."""

from pathlib import Path

import pytest

from src.config import config
from src.connections.candidate_assembly import (
    NoteRef,
    _bm25_ranked,
    _entity_neighbors,
    _tokenize,
    assemble_candidates,
    clear_tokenize_cache,
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


def test_graph_channel_reaches_two_hop_note(vault):
    # newer (window) shares entity with mid; mid shares entity with old.
    # newer and old share nothing directly -> only the graph channel reaches old.
    _write_raw_note(
        vault, "newer", "2026-06-20", body="Rozmowa o Bank Ochrony Środowiska teraz"
    )
    _write_raw_note(
        vault, "mid", "2026-05-15", body="Bank Ochrony Środowiska oraz Fundacja Ziemi"
    )
    _write_raw_note(vault, "old", "2026-04-01", body="Wraca temat Fundacja Ziemi znowu")
    cs = assemble_candidates(
        vault, "2026-06-10T00:00:00", DismissalStore(vault), inject_graph=5
    )
    names = {n.basename for n in cs.notes}
    assert "old" in names
    assert "graph" in cs.channel_map.get("old", set())


def test_count_cap_protects_distance_channels_over_similarity(vault, monkeypatch):
    import src.connections.candidate_assembly as ca

    monkeypatch.setattr(config, "MAX_SYNTHESIS_NOTES", 4)
    # 3 dense notes (protected) + 5 tag notes (abundant similarity). Under a
    # cap of 4 (window + 3), all 3 dense must survive; tag overflow is trimmed.
    _write_note(vault, "newer", "2026-06-20", tags="shared", summary="okno alpha")
    for i in range(3):
        _write_raw_note(vault, f"dense{i}", f"2026-05-0{i+1}", body=f"semantic {i}")
    for i in range(5):
        _write_note(vault, f"tagnote{i}", f"2026-04-0{i+1}", tags="shared", summary="t")

    class _FakeEngine:
        def knn_note_ids(self, query, k=20):
            return ["dense0", "dense1", "dense2"]

    monkeypatch.setattr(ca, "_get_recall_engine", lambda vault_dir: _FakeEngine())
    cs = assemble_candidates(
        vault, "2026-06-10T00:00:00", DismissalStore(vault), inject_dense=3
    )
    names = {n.basename for n in cs.notes}
    assert names == {"newer", "dense0", "dense1", "dense2"}  # no tag note survived


def test_round_robin_gives_each_channel_a_share():
    from src.connections.candidate_assembly import _round_robin

    a = [_note("a1", "d"), _note("a2", "d"), _note("a3", "d")]
    b = [_note("b1", "d")]
    c = [_note("c1", "d"), _note("c2", "d")]
    order = [n.basename for n in _round_robin([a, b, c])]
    # first round takes one from each populated channel before seconds
    assert order[:3] == ["a1", "b1", "c1"]
    assert set(order) == {"a1", "a2", "a3", "b1", "c1", "c2"}


def test_round_robin_two_lists_matches_interleave():
    from src.connections.candidate_assembly import _interleave, _round_robin

    a = [_note(f"a{i}", "d") for i in range(3)]
    b = [_note(f"b{i}", "d") for i in range(2)]
    assert [n.basename for n in _round_robin([a, b])] == [
        n.basename for n in _interleave(a, b)
    ]


def test_stance_channel_pairs_contradiction(vault):
    _write_raw_note(
        vault,
        "newer",
        "2026-06-20",
        body="Fundacja Ziemi to jednak zły kierunek, rezygnuję z tego",
    )
    _write_raw_note(
        vault,
        "old_flip",
        "2026-03-01",
        body="Fundacja Ziemi to świetny pomysł, zdecydowanie warto",
    )
    cs = assemble_candidates(
        vault, "2026-06-10T00:00:00", DismissalStore(vault), inject_stance=4
    )
    names = {n.basename for n in cs.notes}
    assert "old_flip" in names
    assert "stance" in cs.channel_map.get("old_flip", set())


def test_stance_channel_off_by_default(vault):
    _write_raw_note(vault, "newer", "2026-06-20", body="Fundacja Ziemi zły pomysł")
    _write_raw_note(vault, "old", "2026-03-01", body="Fundacja Ziemi świetny warto")
    cs = assemble_candidates(vault, "2026-06-10T00:00:00", DismissalStore(vault))
    all_channels = set().union(*cs.channel_map.values()) if cs.channel_map else set()
    assert "stance" not in all_channels


def test_graph_channel_off_by_default(vault):
    _write_raw_note(vault, "newer", "2026-06-20", body="Bank Ochrony Środowiska")
    _write_raw_note(vault, "old", "2026-04-01", body="Bank Ochrony Środowiska")
    cs = assemble_candidates(vault, "2026-06-10T00:00:00", DismissalStore(vault))
    all_channels = set().union(*cs.channel_map.values()) if cs.channel_map else set()
    assert "graph" not in all_channels


def test_dense_channel_uses_engine_and_attributes(vault, monkeypatch):
    import src.connections.candidate_assembly as ca

    _write_raw_note(vault, "older_sem", "2026-05-01", tags="a", body="kompost las")
    _write_raw_note(vault, "newer", "2026-06-20", tags="b", body="ogrod projekt")

    class _FakeEngine:
        def knn_note_ids(self, query, k=20):
            return ["older_sem"]

    monkeypatch.setattr(ca, "_get_recall_engine", lambda vault_dir: _FakeEngine())
    cs = assemble_candidates(
        vault, "2026-06-10T00:00:00", DismissalStore(vault), inject_dense=3
    )
    names = {n.basename for n in cs.notes}
    assert "older_sem" in names
    assert "dense" in cs.channel_map.get("older_sem", set())


def test_dense_skip_drops_nearest(vault, monkeypatch):
    import src.connections.candidate_assembly as ca

    _write_raw_note(vault, "nearest", "2026-05-02", tags="a", body="x")
    _write_raw_note(vault, "second", "2026-05-01", tags="b", body="y")
    _write_raw_note(vault, "newer", "2026-06-20", tags="c", body="z")

    class _FakeEngine:
        def knn_note_ids(self, query, k=20):
            return ["nearest", "second"]  # rank order

    monkeypatch.setattr(ca, "_get_recall_engine", lambda vault_dir: _FakeEngine())
    cs = assemble_candidates(
        vault,
        "2026-06-10T00:00:00",
        DismissalStore(vault),
        inject_dense=1,
        dense_skip=1,
    )
    names = {n.basename for n in cs.notes}
    # skip=1 drops the nearest; the second-nearest surfaces via dense instead
    assert "second" in names and "dense" in cs.channel_map.get("second", set())
    assert "dense" not in cs.channel_map.get("nearest", set())


def test_dense_channel_fails_soft_without_engine(vault, monkeypatch):
    import src.connections.candidate_assembly as ca

    _write_raw_note(vault, "older", "2026-05-01", tags="a", body="kompost")
    _write_raw_note(vault, "newer", "2026-06-20", tags="b", body="ogrod")
    monkeypatch.setattr(ca, "_get_recall_engine", lambda vault_dir: None)
    cs = assemble_candidates(
        vault, "2026-06-10T00:00:00", DismissalStore(vault), inject_dense=3
    )
    assert cs.window_basenames == {"newer"}  # no crash, channel just empty


def test_precap_basenames_records_ranked_but_cut(vault, monkeypatch):
    monkeypatch.setattr(config, "MAX_SYNTHESIS_NOTES", 2)
    _write_note(vault, "newer", "2026-06-20", tags="t", summary="alpha beta")
    _write_note(vault, "n1", "2026-05-02", tags="t", summary="alpha beta")
    _write_note(vault, "n2", "2026-05-01", tags="t", summary="alpha beta")
    cs = assemble_candidates(vault, "2026-06-10T00:00:00", DismissalStore(vault))
    kept = {n.basename for n in cs.notes}
    assert len(kept) == 2  # cap enforced
    # the cut note was still RANKED by a channel -> visible in precap
    cut = {"n1", "n2"} - kept
    assert cut and cut <= cs.precap_basenames


def _write_raw_note(vault, name, date, tags="", body=""):
    (vault / f"{name}.md").write_text(
        f'---\ntitle: "{name}"\ndate: {date}\ntags: [{tags}]\n---\n\n{body}\n',
        encoding="utf-8",
    )


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


def test_clear_tokenize_cache_releases_retained_texts():
    """clear_tokenize_cache empties the LRU so the daemon does not pin note
    texts forever after a digest pass."""
    _tokenize.cache_clear()
    _tokenize("some note text about okna i dach")
    _tokenize("another distinct note about izolacja")
    assert _tokenize.cache_info().currsize >= 2
    clear_tokenize_cache()
    assert _tokenize.cache_info().currsize == 0
