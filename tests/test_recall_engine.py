"""RecallEngine facade: backfill a real vault -> hybrid search; dim-change rebuild."""

from __future__ import annotations

import hashlib
import math
import sqlite3
from pathlib import Path

import pytest

# sqlite-vec needs a Python built with loadable sqlite extensions; the
# setup-python CPython on GitHub runners is not. Recall is optional at
# runtime (seam degrades gracefully), so skip rather than fail there.
pytestmark = pytest.mark.skipif(
    not hasattr(sqlite3.Connection, "enable_load_extension"),
    reason="Python built without loadable sqlite extensions (sqlite-vec)",
)

from src.connections.recall import engine as engine_mod


class FakeEmbedder:
    def __init__(self, dim: int = 96):
        self.dim = dim
        self.model_id = f"fake-{dim}"

    def _vec(self, text):
        v = [0.0] * self.dim
        for raw in text.lower().replace("\n", " ").split():
            tok = "".join(c for c in raw if c.isalnum())
            if tok:
                v[int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16) % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


def _note(root, name, title, date, body):
    (Path(root) / f"{name}.md").write_text(
        f'---\ntitle: "{title}"\ndate: {date}\n---\n\n{body}\n', encoding="utf-8"
    )


@pytest.fixture()
def vault(tmp_path):
    _note(tmp_path, "okna", "Okna i fundamenty", "14.06",
          "Dostepnosc okien niepewna, producenci okien nie odpowiadaja, dach stoi.")
    _note(tmp_path, "skala", "Skalowanie", "01.06",
          "Automatyzacja daje zasieg ale gubi reczna robote.")
    # a digest note in the subfolder must be ignored by backfill
    d = tmp_path / "Timshel Digests"
    d.mkdir()
    (d / "digest.md").write_text("---\ntype: timshel-digest\n---\n\nignore me okien", encoding="utf-8")
    return tmp_path


def test_backfill_and_search(vault, monkeypatch):
    monkeypatch.setattr(engine_mod, "resolve_embedder", lambda *a, **k: FakeEmbedder())
    eng = engine_mod.RecallEngine(vault)
    try:
        n = eng.backfill()
        assert n == 2  # digest folder excluded
        assert eng.count() >= 2
        res = eng.search("dostawa okien dach", k=5)
        assert res and res[0].note_id == "okna"
    finally:
        eng.close()


def test_dim_change_rebuilds_store(vault, monkeypatch):
    monkeypatch.setattr(engine_mod, "resolve_embedder", lambda *a, **k: FakeEmbedder(32))
    e1 = engine_mod.RecallEngine(vault)
    e1.backfill()
    assert e1.count() == 2
    e1.close()

    # reopen with a different-dim model -> store rebuilt (empty), no crash/corruption
    monkeypatch.setattr(engine_mod, "resolve_embedder", lambda *a, **k: FakeEmbedder(48))
    e2 = engine_mod.RecallEngine(vault)
    try:
        assert e2.count() == 0
    finally:
        e2.close()


def test_cli_backfill_then_ask(tmp_path, monkeypatch, capsys):
    """The deployed entrypoint (`make ask` / `make backfill-embeddings`) end to end."""
    from src.config.config import (
        config as config_proxy,  # delegates to the get_config() singleton
    )

    _note(tmp_path, "okna", "Okna", "14.06", "Producenci okien nie odpowiadaja, dach stoi w miejscu.")
    from src.connections.recall import cli as cli_mod

    monkeypatch.setattr(engine_mod, "resolve_embedder", lambda *a, **k: FakeEmbedder())
    monkeypatch.setattr(config_proxy, "TRANSCRIBE_DIR", tmp_path)

    assert cli_mod.main(["backfill"]) == 0
    assert cli_mod.main(["ask", "dostawa okien dach"]) == 0
    out = capsys.readouterr().out
    assert "okna" in out
    assert "okien" in out.lower()


@pytest.mark.integration
@pytest.mark.slow
def test_engine_end_to_end_real_embedder(vault):
    """The P2.5 gate: real local embedder, PL query -> right PL note, offline."""
    eng = engine_mod.RecallEngine(vault)  # configured default multilingual model
    try:
        eng.backfill()
        res = eng.search("co z dostawą okien i opóźnieniem dachu?", k=5)
        assert res and res[0].note_id == "okna"
        assert res[0].quote
    finally:
        eng.close()


def test_backfill_incremental_skips_unchanged_reindexes_edited(vault, monkeypatch):
    monkeypatch.setattr(engine_mod, "resolve_embedder", lambda *a, **k: FakeEmbedder())
    eng = engine_mod.RecallEngine(vault)
    try:
        assert eng.backfill() == 2                     # first pass indexes both notes
        assert eng.backfill(incremental=True) == 0     # nothing changed → nothing reindexed
        # edit one note's body → only that note re-embeds
        (Path(vault) / "okna.md").write_text(
            '---\ntitle: "Okna"\ndate: 14.06\n---\n\nZupelnie nowa tresc o czym innym.\n',
            encoding="utf-8")
        assert eng.backfill(incremental=True) == 1
        assert eng.backfill(incremental=True) == 0     # and now it's current again
    finally:
        eng.close()
