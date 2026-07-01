"""Pure tests for the Obsidian deep-link helper (no AppKit, no real Obsidian)."""

from __future__ import annotations

from src.ui import obsidian_link as ol


def test_obsidian_url_is_path_form_and_encoded(tmp_path):
    f = tmp_path / "My Note.md"
    f.write_text("x", encoding="utf-8")
    url = ol.obsidian_url(f)
    assert url.startswith("obsidian://open?path=")
    # spaces are percent-encoded, and the absolute resolved path is embedded
    assert "%20" in url
    assert "/" not in url.split("path=", 1)[1]  # fully encoded, no raw separators


def test_resolve_note_path_direct_hit(tmp_path):
    (tmp_path / "Cooling v1.md").write_text("x", encoding="utf-8")
    got = ol.resolve_note_path("Cooling v1", tmp_path)
    assert got == tmp_path / "Cooling v1.md"


def test_resolve_note_path_searches_subfolders(tmp_path):
    sub = tmp_path / "2026" / "transcripts"
    sub.mkdir(parents=True)
    note = sub / "Deep Note.md"
    note.write_text("x", encoding="utf-8")
    assert ol.resolve_note_path("Deep Note", tmp_path) == note


def test_resolve_note_path_strips_wikilink_brackets(tmp_path):
    (tmp_path / "Bracketed.md").write_text("x", encoding="utf-8")
    assert ol.resolve_note_path("[[Bracketed]]", tmp_path) == tmp_path / "Bracketed.md"


def test_resolve_note_path_missing_returns_none(tmp_path):
    assert ol.resolve_note_path("Nope", tmp_path) is None
    assert ol.resolve_note_path("", tmp_path) is None


def test_resolve_note_path_tolerates_case_and_whitespace(tmp_path):
    note = tmp_path / "Cooling V1.md"
    note.write_text("x", encoding="utf-8")
    # different case + collapsed/extra spaces still resolves to the real file
    assert ol.resolve_note_path("cooling  v1", tmp_path) == note


def test_resolve_note_path_exact_wins_over_normalized(tmp_path):
    exact = tmp_path / "Note.md"
    exact.write_text("x", encoding="utf-8")
    (tmp_path / "note.md").write_text("y", encoding="utf-8")
    assert ol.resolve_note_path("Note", tmp_path) == exact


# ── opener strategies (pure argv builder, no OS) ────────────────────────────

def test_file_open_argv_obsidian_is_default(tmp_path):
    f = tmp_path / "T.md"
    f.write_text("x", encoding="utf-8")
    argv = ol.file_open_argv(f)  # default opener == "obsidian"
    assert argv[0] == "open"
    assert argv[1].startswith("obsidian://open?path=")


def test_file_open_argv_finder_reveals(tmp_path):
    f = tmp_path / "T.md"
    f.write_text("x", encoding="utf-8")
    assert ol.file_open_argv(f, "finder") == ["open", "-R", str(f.resolve())]


def test_file_open_argv_default_handler(tmp_path):
    f = tmp_path / "T.md"
    f.write_text("x", encoding="utf-8")
    assert ol.file_open_argv(f, "default") == ["open", str(f.resolve())]


def test_file_open_argv_named_app(tmp_path):
    f = tmp_path / "T.md"
    f.write_text("x", encoding="utf-8")
    assert ol.file_open_argv(f, "app:Pile") == ["open", "-a", "Pile", str(f.resolve())]


def test_file_open_argv_unknown_falls_back_to_obsidian(tmp_path):
    f = tmp_path / "T.md"
    f.write_text("x", encoding="utf-8")
    argv = ol.file_open_argv(f, "mystery")
    assert argv[0] == "open"
    assert argv[1].startswith("obsidian://open?path=")


# ── open_note / open_path delegate through the single _run_open OS seam ──────

def test_open_note_opens_resolved_path(tmp_path, monkeypatch):
    (tmp_path / "Hit.md").write_text("x", encoding="utf-8")
    seen = {}
    monkeypatch.setattr(ol, "_run_open", lambda argv, what: seen.update(argv=argv) or True)
    assert ol.open_note("Hit", tmp_path) is True
    assert seen["argv"][1].startswith("obsidian://open?path=")


def test_open_note_respects_configured_opener(tmp_path, monkeypatch):
    (tmp_path / "Hit.md").write_text("x", encoding="utf-8")
    seen = {}
    monkeypatch.setattr(ol, "_run_open", lambda argv, what: seen.update(argv=argv) or True)
    assert ol.open_note("Hit", tmp_path, opener="app:Pile") is True
    assert seen["argv"][:3] == ["open", "-a", "Pile"]


def test_open_note_falls_back_to_search_when_missing(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(ol, "open_url", lambda url: seen.update(url=url) or True)
    assert ol.open_note("Ghost", tmp_path) is True
    assert seen["url"] == "obsidian://search?query=Ghost"


def test_open_note_missing_non_obsidian_opener_is_noop(tmp_path, monkeypatch):
    called = {}
    monkeypatch.setattr(ol, "open_url", lambda url: called.setdefault("url", url) or True)
    monkeypatch.setattr(ol, "_run_open", lambda argv, what: called.setdefault("argv", argv) or True)
    # No file, opener has no search equivalent → best-effort no-op, nothing opened.
    assert ol.open_note("Ghost", tmp_path, opener="finder") is False
    assert "url" not in called and "argv" not in called


def test_open_path_builds_argv_and_delegates(tmp_path, monkeypatch):
    f = tmp_path / "T.md"
    f.write_text("x", encoding="utf-8")
    seen = {}
    monkeypatch.setattr(ol, "_run_open", lambda argv, what: seen.update(argv=argv) or True)
    assert ol.open_path(f) is True
    assert seen["argv"] == ["open", ol.obsidian_url(f)]
