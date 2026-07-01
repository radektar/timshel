"""Persisting a synthesized recall answer to the vault."""

from __future__ import annotations

import types

from src.connections.recall import answer_writer as aw


def _answer(answered=True):
    return types.SimpleNamespace(
        answered=answered,
        thesis="Dostawa okien jest opozniona, dach czeka.",
        evidence=[
            types.SimpleNamespace(note="okna", date="14.06", quote="dostawa niepewna"),
            types.SimpleNamespace(note="dach", date="", quote="dach stoi w miejscu"),
        ],
        directions=["Co z alternatywnym dostawca?"],
    )


def test_render_has_frontmatter_thesis_evidence_directions():
    md = aw.render_answer_md("co z oknami", _answer(), date_str="26-07-01")
    assert "type: malinche-recall-answer" in md
    assert 'question: "co z oknami"' in md
    assert "Dostawa okien jest opozniona" in md
    assert "[[okna]]" in md and "> dostawa niepewna" in md
    assert "14.06 · [[okna]]" in md          # dated evidence
    assert "[[dach]]" in md                    # undated evidence still links
    assert "## Kierunki" in md and "Co z alternatywnym dostawca?" in md


def test_render_flags_unanswered():
    md = aw.render_answer_md("q", _answer(answered=False), date_str="26-07-01")
    assert "nie pokrywają tego pytania" in md


def test_save_answer_writes_under_recall_subdir(tmp_path):
    path = aw.save_answer("co z oknami i dachem?", _answer(), tmp_path, date_str="26-07-01")
    assert path.exists()
    assert path.parent.name == aw.RECALL_DIR_NAME
    assert path.name.startswith("26-07-01 Recall - ")
    assert path.suffix == ".md"
    body = path.read_text(encoding="utf-8")
    assert "type: malinche-recall-answer" in body and "[[okna]]" in body


def test_save_answer_slug_strips_punctuation(tmp_path):
    path = aw.save_answer("co/z: oknami???", _answer(), tmp_path, date_str="26-07-01")
    assert "/" not in path.name and "?" not in path.name and ":" not in path.name


def test_frontmatter_survives_quotes_and_newlines():
    import yaml

    md = aw.render_answer_md('czy on powiedzial "nie"? \\ i nowa\nlinia', _answer(), date_str="26-07-01")
    fm = md.split("---")[1]
    parsed = yaml.safe_load(fm)  # must not raise on quote/backslash/newline in the query
    assert parsed["type"] == "malinche-recall-answer"
    assert "nie" in parsed["question"]


def test_multiline_evidence_quote_stays_quoted():
    ans = types.SimpleNamespace(
        answered=True, thesis="t", directions=[],
        evidence=[types.SimpleNamespace(note="n", date="", quote="linia1\nlinia2")],
    )
    md = aw.render_answer_md("q", ans, date_str="26-07-01")
    assert "  > linia1" in md and "  > linia2" in md  # every physical line quoted


def test_save_answer_avoids_silent_overwrite(tmp_path):
    p1 = aw.save_answer("co z oknami", _answer(), tmp_path, date_str="26-07-01")
    p2 = aw.save_answer("co z oknami", _answer(), tmp_path, date_str="26-07-01")
    assert p1 != p2 and p1.exists() and p2.exists()  # second save doesn't clobber first
    assert "(2)" in p2.name
