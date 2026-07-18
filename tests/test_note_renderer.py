"""Tests for the in-app markdown reader's rendering path (note_renderer)."""

from pathlib import Path

import pytest

from src.ui import note_renderer as nr

# --------------------------------------------------------------------------- #
# Frontmatter stripping
# --------------------------------------------------------------------------- #


def test_strip_frontmatter_removes_block():
    text = '---\ntitle: "X"\ndate: 2026-07-18\n---\n\n# Body\n'
    assert nr.strip_frontmatter(text) == "# Body"


def test_strip_frontmatter_no_block_passthrough():
    assert nr.strip_frontmatter("# Just body\n") == "# Just body\n"


def test_strip_frontmatter_unclosed_block_passthrough():
    text = "---\ntitle: broken\n\n# Body"
    assert nr.strip_frontmatter(text) == text


# --------------------------------------------------------------------------- #
# Wikilinks
# --------------------------------------------------------------------------- #


def test_wikilink_renders_inapp_anchor():
    html = nr.render_body("Zobacz [[Rozmowa z Heliosem]].")
    assert 'href="timshel-note://Rozmowa%20z%20Heliosem"' in html
    assert 'class="wikilink"' in html
    assert ">Rozmowa z Heliosem</a>" in html


def test_wikilink_with_label():
    html = nr.render_body("[[Nordfab 2026|notatka Nordfab]]")
    assert 'href="timshel-note://Nordfab%202026"' in html
    assert ">notatka Nordfab</a>" in html


def test_unclosed_wikilink_left_as_text():
    html = nr.render_body("Tekst [[bez zamkniecia")
    assert "timshel-note" not in html
    assert "[[bez zamkniecia" in html


def test_wikilink_target_roundtrip():
    assert nr.wikilink_target("timshel-note://Rozmowa%20z%20Heliosem") == (
        "Rozmowa z Heliosem"
    )
    assert nr.wikilink_target("https://example.com") is None
    assert nr.wikilink_target("timshel-note://") is None


# --------------------------------------------------------------------------- #
# Hardening: no raw HTML, no remote fetches
# --------------------------------------------------------------------------- #


def test_raw_html_is_escaped():
    html = nr.render_body("<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_images_become_links_never_img_tags():
    html = nr.render_body("![zdjecie](https://evil.example/x.png)")
    assert "<img" not in html
    assert 'class="image-link"' in html
    assert ">zdjecie</a>" in html


# --------------------------------------------------------------------------- #
# GFM coverage + anchors
# --------------------------------------------------------------------------- #


def test_table_renders():
    html = nr.render_body("| a | b |\n|---|---|\n| 1 | 2 |\n")
    assert "<table>" in html and "<td>1</td>" in html


def test_headings_get_anchor_ids():
    html = nr.render_body("## Transkrypcja\n\ntekst\n")
    assert '<h2 id="transkrypcja">' in html


def test_heading_slug_handles_polish():
    assert nr.heading_slug("Wątki otwarte — część 2") == "watki-otwarte-czesc-2"


# --------------------------------------------------------------------------- #
# Full page assembly
# --------------------------------------------------------------------------- #


def _write_note(tmp_path: Path, body: str, title: str = "Testowa notatka") -> Path:
    p = tmp_path / "note.md"
    p.write_text(
        f'---\ntitle: "{title}"\ndate: 2026-07-18\nduration: 00:12:30\n---\n\n{body}',
        encoding="utf-8",
    )
    return p


def test_note_page_title_from_frontmatter(tmp_path):
    p = _write_note(tmp_path, "Podsumowanie.\n\n## Transkrypcja\n\nZapis.\n")
    html = nr.note_page_html(p)
    assert '<h1 class="note-title">Testowa notatka</h1>' in html
    assert "00:12:30" in html


def test_note_page_jump_link_only_with_transcript_section(tmp_path):
    with_t = nr.note_page_html(
        _write_note(tmp_path, "Tekst.\n\n## Transkrypcja\n\nZapis.\n")
    )
    assert '#transkrypcja">' in with_t

    without_t = _write_note(tmp_path, "Samo podsumowanie.\n")
    assert '#transkrypcja">' not in nr.note_page_html(without_t)


def test_note_page_is_self_contained(tmp_path):
    html = nr.note_page_html(_write_note(tmp_path, "Tekst."))
    assert "<style>" in html
    assert "http" not in html.split("<article>")[1]  # no external refs in body


def test_note_page_missing_file_raises(tmp_path):
    with pytest.raises(OSError):
        nr.note_page_html(tmp_path / "nope.md")


def test_note_page_title_falls_back_to_stem(tmp_path):
    p = tmp_path / "2026-07-18 - bez frontmattera.md"
    p.write_text("Tresc bez frontmattera.\n", encoding="utf-8")
    html = nr.note_page_html(p)
    assert "bez frontmattera" in html
