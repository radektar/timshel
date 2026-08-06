"""The manual digest ("deep scan") asks every time, and says what it costs.

The old behaviour ran silently whenever the local gate judged the material
sufficient, and only asked when it did not — so a scan over a big backlog and
one over nothing looked identical from the outside. This is the one paid action
a user can trigger at will, so it now always states how much new material there
is, how many scans the month has used, and whether the material is the same as
last time.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import src.menu_app as ma
from src.menu_app import TimshelMenuApp


@pytest.fixture
def app(tmp_path, monkeypatch):
    from src.config import config as global_config

    monkeypatch.setattr(global_config, "USAGE_LEDGER_FILE", tmp_path / "ledger.json")
    monkeypatch.setattr(global_config, "DEEP_SCAN_MONTHLY_LIMIT", 10)
    instance = TimshelMenuApp.__new__(TimshelMenuApp)
    instance.transcriber = SimpleNamespace()
    return instance


def _potential(window=2, ok=True, unseen_total=5, window_sig="sig-a"):
    return SimpleNamespace(
        window=window,
        neighbors=0,
        ok=ok,
        unseen_total=unseen_total,
        window_sig=window_sig,
    )


def _usage(deep_scans=0):
    return SimpleNamespace(deep_scans=deep_scans)


def _text(app, monkeypatch, potential, usage, last_sig=None, digest_runs=3):
    monkeypatch.setattr(
        TimshelMenuApp, "_last_digest_window_sig", staticmethod(lambda: last_sig)
    )
    monkeypatch.setattr(
        TimshelMenuApp, "_digest_runs", staticmethod(lambda: digest_runs)
    )
    return app._deep_scan_dialog_text(potential, usage)


# --- what the dialog says --------------------------------------------------


def test_states_how_much_is_new(app, monkeypatch):
    text = _text(app, monkeypatch, _potential(unseen_total=7), _usage())
    assert "7 new notes since your last digest" in text
    assert "Deep scans: 0/10 this month" in text
    assert "Costs one Claude run" in text


def test_singular_for_one_note(app, monkeypatch):
    text = _text(app, monkeypatch, _potential(unseen_total=1), _usage())
    assert "1 new note since" in text


def test_nothing_new_is_stated_plainly(app, monkeypatch):
    text = _text(app, monkeypatch, _potential(unseen_total=0), _usage())
    assert "Nothing new since your last digest" in text


def test_low_potential_keeps_the_old_warning(app, monkeypatch):
    text = _text(app, monkeypatch, _potential(unseen_total=1, ok=False), _usage())
    assert "1 new note since" in text
    assert "likely find nothing" in text


def test_same_window_as_last_time_is_flagged(app, monkeypatch):
    text = _text(
        app, monkeypatch, _potential(window_sig="sig-a"), _usage(), last_sig="sig-a"
    )
    assert "same material your last digest read" in text


def test_different_window_is_not_flagged(app, monkeypatch):
    text = _text(
        app, monkeypatch, _potential(window_sig="sig-b"), _usage(), last_sig="sig-a"
    )
    assert "same material" not in text


def test_over_the_monthly_count_says_so_but_still_offers_the_run(app, monkeypatch):
    text = _text(app, monkeypatch, _potential(), _usage(deep_scans=10))
    assert "10/10 — monthly limit reached" in text
    assert text.rstrip().endswith("Run a deep scan?")


def test_failed_preview_still_produces_a_dialog(app, monkeypatch):
    text = _text(app, monkeypatch, None, _usage())
    assert "Couldn't check what's new" in text
    assert "Run a deep scan?" in text


# --- what confirming / cancelling does -------------------------------------


def _drive(app, monkeypatch, *, answer, potential=None, paid=True):
    """Run the handler synchronously, capturing whether the digest fired.

    ``paid`` models whether the run consumed a window: the scheduler fires
    ``on_paid`` only then, and a free bail never calls it.
    """
    ran = []
    monkeypatch.setattr(ma, "_run_on_main_thread", lambda fn: fn())
    monkeypatch.setattr(ma.rumps, "alert", lambda *a, **kw: answer)
    monkeypatch.setattr(ma, "send_notification", lambda *a, **kw: None)
    monkeypatch.setattr(
        "src.connections.scheduler.estimate_digest_potential",
        lambda *a, **kw: potential or _potential(),
    )
    monkeypatch.setattr(TimshelMenuApp, "_digest_runs", staticmethod(lambda: 3))

    def _fake_run(*_a, on_paid=None, **_kw):
        ran.append(1)
        if paid and on_paid is not None:
            on_paid()
        return None

    monkeypatch.setattr("src.connections.run_digest_if_due", _fake_run)

    class _Thread:
        def __init__(self, target=None, **_kw):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr("threading.Thread", _Thread)
    app._generate_digest_now(None)
    return ran


def test_confirming_runs_the_scan_and_counts_it(app, monkeypatch):
    from src import usage_ledger

    ran = _drive(app, monkeypatch, answer=1)
    assert ran == [1]
    assert usage_ledger.read_usage().deep_scans == 1


def test_cancelling_runs_nothing_and_counts_nothing(app, monkeypatch):
    from src import usage_ledger

    ran = _drive(app, monkeypatch, answer=0)
    assert ran == []
    assert usage_ledger.read_usage().deep_scans == 0


def test_a_run_that_bails_for_free_is_not_charged(app, monkeypatch):
    """force=True skips the cadence and the $0 gate, not the free bails: no
    API key, AI disabled, digest lock held, <2 notes. A tester without a key
    could otherwise click the monthly allowance to 10/10 without one API
    call — and that count is the pricing-calibration signal."""
    from src import usage_ledger

    ran = _drive(app, monkeypatch, answer=1, paid=False)
    assert ran == [1]  # the attempt happened
    assert usage_ledger.read_usage().deep_scans == 0  # but nothing was paid


def test_dialog_is_shown_even_when_the_gate_would_pass(app, monkeypatch):
    """Previously this path ran silently — the paid action must always ask."""
    asked = []
    monkeypatch.setattr(ma, "_run_on_main_thread", lambda fn: fn())
    monkeypatch.setattr(
        ma.rumps, "alert", lambda *a, **kw: (asked.append(kw or a), 0)[1]
    )
    monkeypatch.setattr(ma, "send_notification", lambda *a, **kw: None)
    monkeypatch.setattr(
        "src.connections.scheduler.estimate_digest_potential",
        lambda *a, **kw: _potential(ok=True),
    )

    class _Thread:
        def __init__(self, target=None, **_kw):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr("threading.Thread", _Thread)
    app._generate_digest_now(None)
    assert len(asked) == 1


def test_another_writer_bumping_the_run_counter_does_not_charge_us(app, monkeypatch):
    """digest_runs is process-wide: the daemon finishing its own digest while
    ours bails on the lock must not land on the user's bill. Billing keys off
    on_paid, which only OUR run can fire."""
    from src import usage_ledger

    monkeypatch.setattr(ma, "_run_on_main_thread", lambda fn: fn())
    monkeypatch.setattr(ma.rumps, "alert", lambda *a, **kw: 1)
    monkeypatch.setattr(ma, "send_notification", lambda *a, **kw: None)
    monkeypatch.setattr(
        "src.connections.scheduler.estimate_digest_potential",
        lambda *a, **kw: _potential(),
    )
    counts = iter([4, 9])  # someone else's digest lands mid-call
    monkeypatch.setattr(
        TimshelMenuApp, "_digest_runs", staticmethod(lambda: next(counts, 9))
    )
    # Our run bails for free: on_paid is never invoked.
    monkeypatch.setattr("src.connections.run_digest_if_due", lambda *a, **kw: None)

    class _Thread:
        def __init__(self, target=None, **_kw):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr("threading.Thread", _Thread)
    app._generate_digest_now(None)
    assert usage_ledger.read_usage().deep_scans == 0


def test_first_ever_scan_does_not_claim_a_previous_digest(app, monkeypatch):
    """On a fresh vault unseen_total is the whole corpus and no digest has run
    — "since your last digest" would invent one."""
    text = _text(
        app, monkeypatch, _potential(unseen_total=247), _usage(), digest_runs=0
    )
    assert "247 new notes in your vault" in text
    assert "since your last digest" not in text


def test_after_a_digest_the_wording_is_relative_to_it(app, monkeypatch):
    text = _text(app, monkeypatch, _potential(unseen_total=5), _usage(), digest_runs=3)
    assert "5 new notes since your last digest" in text
