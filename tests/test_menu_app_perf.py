"""Perf-guard tests for the menu app hot paths (P3-B).

The 2 s status timer and 10 s submenu refresh used to re-read the icon PNG,
rebuild the whole submenu, and rglob the vault on every tick. These verify the
guards skip that work when nothing changed.
"""

from pathlib import Path

from src.menu_app import MalincheMenuApp


def _bare():
    return MalincheMenuApp.__new__(MalincheMenuApp)


class _FakeSubmenu:
    def __init__(self):
        self.title = ""
        self._menu = object()
        self.cleared = 0
        self.added = []

    def clear(self):
        self.cleared += 1
        self.added = []

    def add(self, item):
        self.added.append(item)


def test_recent_transcripts_from_disk_is_ttl_cached(tmp_path, monkeypatch):
    from src import menu_app as m

    (tmp_path / "a.md").write_text("---\ntitle: a\n---\nx", encoding="utf-8")
    (tmp_path / "b.md").write_text("---\ntitle: b\n---\nx", encoding="utf-8")
    monkeypatch.setattr(m.config, "TRANSCRIBE_DIR", tmp_path, raising=False)
    monkeypatch.setattr(m.config, "DIGEST_DIR_NAME", "_digests", raising=False)

    app = _bare()
    first = app._recent_transcripts_from_disk()
    assert {d["label"] for d in first} == {"a", "b"}

    # A new file must NOT appear until the TTL expires — proves the cache served
    # the second call without a fresh rglob.
    (tmp_path / "c.md").write_text("---\ntitle: c\n---\nx", encoding="utf-8")
    second = app._recent_transcripts_from_disk()
    assert {d["label"] for d in second} == {"a", "b"}  # cached, c not seen

    # Force expiry → fresh scan picks up c.
    app._recent_disk_cache = (0.0, 5, second)  # monotonic 0 = long ago
    third = app._recent_transcripts_from_disk()
    assert "c" in {d["label"] for d in third}


def test_retranscribe_menu_skips_rebuild_when_unchanged(tmp_path, monkeypatch):
    app = _bare()
    app.retranscribe_menu = _FakeSubmenu()
    app._retranscription_in_progress = False
    app._retranscription_file = None

    f = tmp_path / "rec.wav"
    f.write_bytes(b"x")
    monkeypatch.setattr(app, "_get_staged_files", lambda: [f])

    app._refresh_retranscribe_menu(None)
    assert app.retranscribe_menu.cleared == 1  # first build
    assert len(app.retranscribe_menu.added) == 1

    # Nothing changed → second refresh must be a no-op (no clear/rebuild).
    app._refresh_retranscribe_menu(None)
    assert app.retranscribe_menu.cleared == 1  # unchanged

    # A new staged file changes the snapshot → rebuild.
    g = tmp_path / "rec2.wav"
    g.write_bytes(b"y")
    monkeypatch.setattr(app, "_get_staged_files", lambda: [f, g])
    app._refresh_retranscribe_menu(None)
    assert app.retranscribe_menu.cleared == 2  # rebuilt


def test_update_icon_guard_skips_repeat_status(monkeypatch):
    """Identical (status, badge) must not re-assign the icon (PNG re-read)."""
    from src.app_status import AppStatus

    app = _bare()
    app._icon_paths = {AppStatus.IDLE: "/tmp/idle.png"}
    app._icon_paths_dot = {}
    app._unseen_insights = 0
    app._dashboard = None

    icon_sets = []

    # rumps stores the icon via a property; emulate with a plain attribute that
    # records every assignment.
    monkeypatch.setattr(type(app), "icon", property(
        lambda self: getattr(self, "_icon_val", None),
        lambda self, v: (icon_sets.append(v), setattr(self, "_icon_val", v)),
    ), raising=False)
    monkeypatch.setattr(type(app), "title", property(
        lambda self: None, lambda self, v: None,
    ), raising=False)
    monkeypatch.setattr(type(app), "template", property(
        lambda self: None, lambda self, v: None,
    ), raising=False)
    monkeypatch.setattr(app, "_apply_status_icon", lambda s: None)

    app._update_icon(AppStatus.IDLE)
    app._update_icon(AppStatus.IDLE)  # same key → skipped
    assert icon_sets == ["/tmp/idle.png"]  # assigned once, not twice
