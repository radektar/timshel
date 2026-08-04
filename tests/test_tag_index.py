"""Tests for TagIndex."""

from pathlib import Path

from src.tag_index import TagIndex


def test_tag_index_builds_from_markdown(tmp_path: Path) -> None:
    """TagIndex should parse tags from markdown frontmatter."""
    root = tmp_path / "notes"
    root.mkdir()

    (root / "one.md").write_text(
        "---\n"
        'title: "Pierwszy"\n'
        "tags: [transcription, sauna, Zdrowie]\n"
        "---\n\n"
        "Treść",
        encoding="utf-8",
    )

    (root / "two.md").write_text(
        "---\n"
        "title: Drugi\n"
        'tags: [praca, sauna, "Zamówienie telefoniczne"]\n'
        "---\n",
        encoding="utf-8",
    )

    index = TagIndex(root_dir=root)
    mapping = index.build_index()

    assert mapping["sauna"] == "sauna"
    assert mapping["zdrowie"] == "zdrowie"
    assert mapping["praca"] == "praca"
    assert mapping["zamowienie-telefoniczne"] == "zamowienie-telefoniczne"

    tags = index.existing_tags()
    assert "transcription" in tags
    assert "sauna" in tags
    assert "zamowienie-telefoniczne" in tags


def test_existing_tags_ranked_by_document_frequency(tmp_path: Path) -> None:
    """Most-reused tags come first — the prompt cap must keep those."""
    root = tmp_path / "notes"
    root.mkdir()

    for idx in range(3):
        (root / f"note{idx}.md").write_text(
            "---\ntags: [transcription, sauna]\n---\n", encoding="utf-8"
        )
    (root / "rare.md").write_text(
        "---\ntags: [transcription, jednorazowy]\n---\n", encoding="utf-8"
    )

    ranked = TagIndex(root_dir=root).existing_tags_ranked()

    assert ranked.index("sauna") < ranked.index("jednorazowy")
    assert ranked[0] == "transcription"  # every note carries it


def test_sanitize_keeps_multi_word_proper_names() -> None:
    """Multi-word entity names must survive as hyphenated tags."""
    assert TagIndex.sanitize_tag_value("Tech to the Rescue") == "tech-to-the-rescue"
    assert TagIndex.sanitize_tag_value("Fundacja Ziemi") == "fundacja-ziemi"


def test_sanitize_edge_cases() -> None:
    """Diacritics, punctuation and stray separators."""
    assert TagIndex.sanitize_tag_value("  Zdrowie  ") == "zdrowie"
    assert TagIndex.sanitize_tag_value("#sauna") == "sauna"
    assert TagIndex.sanitize_tag_value("data — readiness") == "data-readiness"
    assert TagIndex.sanitize_tag_value("---") == ""
    assert TagIndex.sanitize_tag_value("") == ""
