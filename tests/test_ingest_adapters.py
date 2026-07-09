"""Tests for the ingest source adapters (pure parsing, no transcriber)."""

from datetime import datetime

import pytest

from src.ingest.adapters import ImportedDoc, parse


def test_parse_plain_txt(tmp_path):
    f = tmp_path / "My Note.txt"
    f.write_text("pierwsza myśl\ndruga myśl", encoding="utf-8")

    doc = parse(f)

    assert isinstance(doc, ImportedDoc)
    assert doc.text == "pierwsza myśl\ndruga myśl"
    assert doc.title == "My Note"
    assert doc.origin == "txt"
    assert doc.source_name == "My Note.txt"
    assert isinstance(doc.recorded_at, datetime)


def test_parse_md_uses_stem_title(tmp_path):
    f = tmp_path / "spotkanie_2026.md"
    f.write_text("treść notatki", encoding="utf-8")

    doc = parse(f)

    assert doc.origin == "md"
    assert doc.title == "spotkanie 2026"


def test_parse_vtt_strips_scaffolding(tmp_path):
    f = tmp_path / "zoom-call.vtt"
    f.write_text(
        "WEBVTT\n"
        "\n"
        "NOTE recorded by Zoom\n"
        "\n"
        "1\n"
        "00:00:01.000 --> 00:00:04.000\n"
        "<v Radek>Musimy zdecydować o prefabrykatach.\n"
        "\n"
        "2\n"
        "00:00:04.000 --> 00:00:07.000 align:start\n"
        "Klient nie chce prefabrykatów.\n",
        encoding="utf-8",
    )

    doc = parse(f)

    assert doc.origin == "vtt"
    # Header, NOTE, indices, timings and <v> tags gone; spoken text kept.
    assert "WEBVTT" not in doc.text
    assert "-->" not in doc.text
    assert "00:00" not in doc.text
    assert "<v" not in doc.text
    assert "Musimy zdecydować o prefabrykatach." in doc.text
    assert "Klient nie chce prefabrykatów." in doc.text


def test_parse_vtt_collapses_duplicate_lines(tmp_path):
    f = tmp_path / "dup.vtt"
    f.write_text(
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:03.000\nsame line\n\n"
        "00:00:03.000 --> 00:00:05.000\nsame line\n",
        encoding="utf-8",
    )
    doc = parse(f)
    assert doc.text.count("same line") == 1


def test_parse_unsupported_suffix_raises(tmp_path):
    f = tmp_path / "scan.pdf"
    f.write_bytes(b"%PDF-1.4 ...")
    with pytest.raises(ValueError):
        parse(f)


def test_parse_empty_content_raises(tmp_path):
    f = tmp_path / "blank.txt"
    f.write_text("   \n  \n", encoding="utf-8")
    with pytest.raises(ValueError):
        parse(f)


def test_parse_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        parse(tmp_path / "nope.txt")
