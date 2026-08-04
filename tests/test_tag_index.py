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


class TestIndexScope:
    """The tagger's reuse pool must reflect LIVE notes, nothing else."""

    def _note(self, path: Path, tags: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"---\ntitle: n\ntags: [{tags}]\n---\n\nbody\n", encoding="utf-8"
        )

    def test_subfolders_are_not_indexed(self, tmp_path: Path) -> None:
        """.timshel holds whole COPIES of notes; digests are app output.

        Measured on a real vault, the recursive scan gave 704 distinct tags
        instead of 488 and counted `transcription` 311 times for 153 notes —
        so the frequency order that existing_tags_ranked depends on was
        decided by backup copies.
        """
        root = tmp_path / "vault"
        self._note(root / "live.md", "transcription, sauna")
        self._note(
            root / ".timshel" / "resummarize-backup" / "x" / "live.md",
            "transcription, stary-tag",
        )
        self._note(
            root / "Timshel Digests" / "2026-06-25 Synthesis.md", "timshel-digest"
        )

        index = TagIndex(root_dir=root)
        tags = index.existing_tags()

        assert "sauna" in tags
        assert "stary-tag" not in tags
        assert "timshel-digest" not in tags
        # df counts live notes, not copies.
        assert index._df["transcription"] == 1

    def test_stray_digest_at_top_level_is_skipped(self, tmp_path: Path) -> None:
        """Its tags are the app's bookkeeping, and signal_tags only strips
        GENERATED_TAG — so a digest marker reused on a user note would become
        a full connection signal."""
        root = tmp_path / "vault"
        self._note(root / "live.md", "transcription, sauna")
        (root / "stray.md").write_text(
            "---\ntitle: d\ntype: timshel-digest\ntags: [timshel-digest]\n---\n\nbody\n",
            encoding="utf-8",
        )
        (root / "old.md").write_text(
            '---\ntitle: d\ntype: "malinche-digest"\ntags: [malinche-digest]\n---\n\nb\n',
            encoding="utf-8",
        )

        tags = TagIndex(root_dir=root).existing_tags()

        assert "sauna" in tags
        assert "timshel-digest" not in tags
        assert "malinche-digest" not in tags  # quoted type value too
