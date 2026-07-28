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
