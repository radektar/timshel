"""The 'Import transcripts…' menu action — batch text-import handler.

The importer itself (Transcriber.import_text_file) is covered elsewhere; these
pin the menu-side batching: per-file failures don't abort the run, a busy lock
stops it, and counts are reported.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.menu_app import TimshelMenuApp
from src.transcriber import RetranscribeLockBusyError


def _app(transcriber):
    app = TimshelMenuApp.__new__(TimshelMenuApp)
    app.transcriber = transcriber
    return app


def test_batch_counts_ok_and_failed():
    transcriber = MagicMock()
    # file 1 ok, file 2 ok, file 3 fails (False). The MagicMock leaves the
    # status dict untouched, so both successes count as freshly-written.
    transcriber.import_text_file.side_effect = [True, True, False]
    app = _app(transcriber)

    with patch("src.menu_app.send_notification") as notify:
        app._run_text_import([Path("a.md"), Path("b.txt"), Path("c.vtt")])

    assert transcriber.import_text_file.call_count == 3
    # Final notification summarises the batch: new / skipped, plus destination.
    final = notify.call_args_list[-1].args
    assert "2 new" in final[2]
    assert "1 skipped" in final[2]


def test_batch_reports_duplicates_separately():
    transcriber = MagicMock()

    def _imp(path, status=None):
        # b.txt is an already-indexed duplicate; the others are new.
        if status is not None:
            status["duplicate"] = path.name == "b.txt"
        return True

    transcriber.import_text_file.side_effect = _imp
    app = _app(transcriber)

    with patch("src.menu_app.send_notification") as notify:
        app._run_text_import([Path("a.md"), Path("b.txt"), Path("c.vtt")])

    final = notify.call_args_list[-1].args
    assert "2 new" in final[2]
    assert "1 already in vault" in final[2]


def test_per_file_exception_does_not_abort_batch():
    transcriber = MagicMock()
    transcriber.import_text_file.side_effect = [ValueError("bad"), True]
    app = _app(transcriber)

    with patch("src.menu_app.send_notification"):
        app._run_text_import([Path("bad.md"), Path("good.md")])

    # Both files attempted despite the first raising.
    assert transcriber.import_text_file.call_count == 2


def test_busy_lock_stops_the_run():
    transcriber = MagicMock()
    transcriber.import_text_file.side_effect = RetranscribeLockBusyError("busy")
    app = _app(transcriber)

    with patch("src.menu_app.send_notification"), patch(
        "src.menu_app._run_on_main_thread"
    ) as on_main:
        app._run_text_import([Path("a.md"), Path("b.md")])

    # Stopped after the first (busy) file; the second was never attempted.
    assert transcriber.import_text_file.call_count == 1
    on_main.assert_called_once()  # the "in progress" alert


def test_clicked_guards_when_transcriber_not_ready():
    app = _app(None)
    with patch("src.menu_app.rumps.alert") as alert, patch.object(
        TimshelMenuApp, "_choose_transcript_files"
    ) as chooser:
        app._import_transcripts_clicked(None)

    alert.assert_called_once()
    chooser.assert_not_called()  # never opens the picker when not ready
