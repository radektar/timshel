"""Unit tests for the post-wizard first-session flow (menu_app logic, no UI).

The AppKit/rumps layer is not exercised — these tests target the pure logic:
the batch import engine, the pending-flag consumption, and the gates that
decide whether the paid first digest is offered at all.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.config import UserSettings
from src.transcriber import RetranscribeLockBusyError


@pytest.fixture
def app():
    """A bare TimshelMenuApp-alike carrying only what the logic needs."""
    from src.menu_app import TimshelMenuApp

    instance = object.__new__(TimshelMenuApp)  # skip rumps __init__
    instance.transcriber = Mock()
    return instance


def _paths(tmp_path, names):
    out = []
    for n in names:
        p = tmp_path / n
        p.write_text("body", encoding="utf-8")
        out.append(p)
    return out


class TestImportBatch:
    def test_counts_imported_duplicates_failed(self, app, tmp_path):
        paths = _paths(tmp_path, ["a.md", "b.md", "c.md", "d.md"])
        statuses = iter([{}, {"duplicate": True}, ValueError("bad"), {}])

        def _import(path, status=None):
            st = next(statuses)
            if isinstance(st, Exception):
                raise st
            if status is not None:
                status.update(st)
            return True

        app.transcriber.import_text_file.side_effect = _import
        imported, dupes, failed, aborted = app._import_batch(paths)
        assert (imported, dupes, failed, aborted) == (2, 1, 1, False)

    def test_per_file_error_does_not_abort(self, app, tmp_path):
        paths = _paths(tmp_path, ["a.md", "b.md"])
        app.transcriber.import_text_file.side_effect = [RuntimeError("boom"), True]
        imported, dupes, failed, aborted = app._import_batch(paths)
        assert (imported, failed, aborted) == (1, 1, False)

    def test_lock_abort_returns_partial(self, app, tmp_path):
        paths = _paths(tmp_path, ["a.md", "b.md", "c.md"])
        app.transcriber.import_text_file.side_effect = [
            True,
            RetranscribeLockBusyError("busy"),
        ]
        imported, dupes, failed, aborted = app._import_batch(paths)
        assert (imported, aborted) == (1, True)

    def test_progress_callback_fires_and_never_breaks(self, app, tmp_path):
        paths = _paths(tmp_path, ["a.md", "b.md"])
        app.transcriber.import_text_file.return_value = True
        seen = []

        def _progress(i, total, p):
            seen.append((i, total, p.name))
            raise RuntimeError("UI hiccup must not break the import")

        imported, *_ = app._import_batch(paths, progress=_progress)
        assert imported == 2
        assert seen == [(1, 2, "a.md"), (2, 2, "b.md")]


class TestMaybeStartFirstSession:
    def test_noop_without_flag(self, app, tmp_path, monkeypatch):
        config_file = tmp_path / "config.json"
        monkeypatch.setattr(
            UserSettings, "config_path", staticmethod(lambda: config_file)
        )
        started = []
        monkeypatch.setattr(
            "threading.Thread",
            lambda *a, **kw: started.append(kw) or Mock(),
        )
        app._maybe_start_first_session()
        assert started == []

    def test_flag_spawns_thread(self, app, tmp_path, monkeypatch):
        config_file = tmp_path / "config.json"
        monkeypatch.setattr(
            UserSettings, "config_path", staticmethod(lambda: config_file)
        )
        UserSettings(pending_import_dir=str(tmp_path)).save()
        started = []
        monkeypatch.setattr(
            "threading.Thread",
            lambda *a, **kw: started.append(kw) or Mock(start=lambda: None),
        )
        app._maybe_start_first_session()
        assert len(started) == 1
        assert started[0]["name"] == "FirstSession"


class TestFirstSessionSequence:
    def _run(self, app, tmp_path, monkeypatch, *, api_key="sk-test", files=("a.md",)):
        """Drive _run_first_session synchronously with everything stubbed."""
        import src.menu_app as menu_mod

        config_file = tmp_path / "config.json"
        monkeypatch.setattr(
            UserSettings, "config_path", staticmethod(lambda: config_file)
        )
        UserSettings(pending_import_dir=str(tmp_path)).save()

        folder = tmp_path / "notes"
        folder.mkdir()
        for n in files:
            (folder / n).write_text("body", encoding="utf-8")

        monkeypatch.setattr(menu_mod.config, "LLM_API_KEY", api_key)
        monkeypatch.setattr(menu_mod.config, "LLM_PROVIDER", "claude")
        monkeypatch.setattr(
            menu_mod.config, "ENABLE_CONNECTION_SYNTHESIS", True, raising=False
        )
        monkeypatch.setattr(menu_mod, "DownloadWindow", lambda *a, **kw: Mock())
        monkeypatch.setattr(menu_mod, "send_notification", Mock())
        # Alerts run their callback immediately (main-thread hop stubbed).
        monkeypatch.setattr(menu_mod, "_run_on_main_thread", lambda fn: fn())

        offers = []
        monkeypatch.setattr(
            menu_mod.rumps, "alert", lambda *a, **kw: offers.append(kw) or 1
        )

        digests = []
        monkeypatch.setattr(
            "src.connections.scheduler.run_onboarding_digest",
            lambda transcriber: digests.append(transcriber) or (None, "empty"),
        )
        monkeypatch.setattr(
            "src.connections.scheduler.estimate_digest_potential",
            lambda onboarding=False: SimpleNamespace(window=2, neighbors=2, ok=True),
        )
        # First-digest thread runs inline.
        monkeypatch.setattr(
            "threading.Thread",
            lambda *a, **kw: SimpleNamespace(start=kw["target"]),
        )
        app.transcriber.import_text_file.return_value = True
        app.transcriber.state = SimpleNamespace(digest_ready=None)

        app._run_first_session(folder)
        return offers, digests

    def test_flag_consumed_and_digest_offered(self, app, tmp_path, monkeypatch):
        offers, digests = self._run(app, tmp_path, monkeypatch)
        assert UserSettings.load().pending_import_dir is None  # once-only
        assert offers  # the offer dialog was shown
        assert len(digests) == 1  # accepted -> onboarding digest ran

    def test_no_key_skips_offer(self, app, tmp_path, monkeypatch):
        offers, digests = self._run(app, tmp_path, monkeypatch, api_key="")
        assert digests == []  # no paid run without a key

    def test_auto_digest_hold_released(self, app, tmp_path, monkeypatch):
        from src.connections.scheduler import get_scheduler, reset_scheduler_for_tests

        monkeypatch.setattr(
            __import__("src.menu_app", fromlist=["config"]).config,
            "CONNECTIONS_STATE_FILE",
            tmp_path / "cs.json",
            raising=False,
        )
        reset_scheduler_for_tests()
        try:
            self._run(app, tmp_path, monkeypatch)
            assert get_scheduler().auto_digest_suspended is False
        finally:
            reset_scheduler_for_tests()


class TestOfferDecline:
    def test_later_starts_weekly_clock_and_releases_hold(
        self, app, tmp_path, monkeypatch
    ):
        import src.menu_app as menu_mod
        from src.connections.scheduler import (
            get_scheduler,
            reset_scheduler_for_tests,
        )

        monkeypatch.setattr(
            menu_mod.config,
            "CONNECTIONS_STATE_FILE",
            tmp_path / "cs.json",
            raising=False,
        )
        reset_scheduler_for_tests()
        try:
            config_file = tmp_path / "config.json"
            monkeypatch.setattr(
                UserSettings, "config_path", staticmethod(lambda: config_file)
            )
            UserSettings(pending_import_dir=str(tmp_path)).save()
            folder = tmp_path / "notes"
            folder.mkdir()
            (folder / "a.md").write_text("body", encoding="utf-8")

            monkeypatch.setattr(menu_mod.config, "LLM_API_KEY", "sk-test")
            monkeypatch.setattr(menu_mod.config, "LLM_PROVIDER", "claude")
            monkeypatch.setattr(
                menu_mod.config, "ENABLE_CONNECTION_SYNTHESIS", True, raising=False
            )
            monkeypatch.setattr(menu_mod, "DownloadWindow", lambda *a, **kw: Mock())
            monkeypatch.setattr(menu_mod, "send_notification", Mock())
            monkeypatch.setattr(menu_mod, "_run_on_main_thread", lambda fn: fn())
            monkeypatch.setattr(menu_mod.rumps, "alert", lambda *a, **kw: 0)  # Later
            monkeypatch.setattr(
                "src.connections.scheduler.estimate_digest_potential",
                lambda onboarding=False: SimpleNamespace(
                    window=1, neighbors=2, ok=True
                ),
            )
            digests = []
            monkeypatch.setattr(
                "src.connections.scheduler.run_onboarding_digest",
                lambda transcriber: digests.append(1) or (None, "empty"),
            )
            app.transcriber.import_text_file.return_value = True

            app._run_first_session(folder)
            s = get_scheduler()
            assert digests == []  # declined -> no paid run
            assert s.auto_digest_suspended is False  # hold released on decline
            assert s.last_digest_at is not None  # weekly clock started
        finally:
            reset_scheduler_for_tests()


class TestPostImportSettle:
    def test_error_path_leaves_no_unconsented_paid_run(
        self, app, tmp_path, monkeypatch
    ):
        """The review's headline scenario: the paid onboarding run fails and
        the next tick must NOT fire a weekly digest the user never approved."""
        import src.menu_app as menu_mod
        from src.connections.scheduler import (
            get_scheduler,
            reset_scheduler_for_tests,
        )

        monkeypatch.setattr(
            menu_mod.config,
            "CONNECTIONS_STATE_FILE",
            tmp_path / "cs.json",
            raising=False,
        )
        reset_scheduler_for_tests()
        try:
            config_file = tmp_path / "config.json"
            monkeypatch.setattr(
                UserSettings, "config_path", staticmethod(lambda: config_file)
            )
            UserSettings(pending_import_dir=str(tmp_path)).save()
            folder = tmp_path / "notes"
            folder.mkdir()
            for i in range(8):  # >= pattern trigger, the escalation case
                (folder / f"n{i}.md").write_text("body", encoding="utf-8")

            monkeypatch.setattr(menu_mod.config, "LLM_API_KEY", "sk-test")
            monkeypatch.setattr(menu_mod.config, "LLM_PROVIDER", "claude")
            monkeypatch.setattr(
                menu_mod.config, "ENABLE_CONNECTION_SYNTHESIS", True, raising=False
            )
            monkeypatch.setattr(menu_mod, "DownloadWindow", lambda *a, **kw: Mock())
            monkeypatch.setattr(menu_mod, "send_notification", Mock())
            monkeypatch.setattr(menu_mod, "_run_on_main_thread", lambda fn: fn())
            monkeypatch.setattr(menu_mod.rumps, "alert", lambda *a, **kw: 1)
            monkeypatch.setattr(
                "src.connections.scheduler.estimate_digest_potential",
                lambda onboarding=False: SimpleNamespace(
                    window=8, neighbors=3, ok=True
                ),
            )
            # The paid onboarding run fails (transient API error).
            monkeypatch.setattr(
                "src.connections.scheduler.run_onboarding_digest",
                lambda transcriber: (None, "error"),
            )
            monkeypatch.setattr(
                "threading.Thread",
                lambda *a, **kw: SimpleNamespace(start=kw["target"]),
            )
            app.transcriber.import_text_file.return_value = True
            app.transcriber.state = SimpleNamespace(digest_ready=None)
            for i in range(8):  # the import bumps the trigger counter
                get_scheduler().register_new_notes(1)

            app._run_first_session(folder)

            from datetime import datetime, timedelta

            s = get_scheduler()
            now = datetime.now()
            assert s.last_digest_at is not None  # clock started at settle
            assert s.new_notes < 6  # counter clamped below the pattern trigger
            assert s.is_due(now) is False  # no paid run on the next tick
            assert s.is_due(now + timedelta(days=3)) is False  # no 2-day escalation
            assert s.auto_digest_on_hold(now) is False  # hold released
        finally:
            reset_scheduler_for_tests()
