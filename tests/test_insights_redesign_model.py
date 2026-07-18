"""Data layer of the 17.07 Konstelacja redesign (U1–U10).

Covers the pieces the window builds on: ask-history store (U8), the deck's
first-non-empty start rule (U9), index-addressed retag (U4 auto-Zachowaj +
toast „Cofnij"), and the ``reset`` signal target that makes undo survive a
restart (triage replay).
"""

from datetime import datetime
from pathlib import Path

from src.connections import ask_history
from src.connections.validation_signal import (
    TARGET_NONE,
    TARGET_RESET,
    TARGET_SAVE,
    record_action,
    triage_state_by_sig,
)
from src.ui import insight_model as im


# --------------------------------------------------------------------------- #
# ask_history (U8)
# --------------------------------------------------------------------------- #


def test_ask_history_roundtrip(tmp_path):
    assert ask_history.load(tmp_path) == []
    assert ask_history.append("wyceny fixed price", 6, vault_dir=tmp_path)
    assert ask_history.append("Helios integracja", 2, vault_dir=tmp_path)
    entries = ask_history.load(tmp_path)
    assert [e["query"] for e in entries] == ["Helios integracja", "wyceny fixed price"]
    assert entries[1]["fragmentCount"] == 6
    assert ask_history.count(tmp_path) == 2


def test_ask_history_reask_moves_to_top(tmp_path):
    ask_history.append("a", 1, vault_dir=tmp_path)
    ask_history.append("b", 2, vault_dir=tmp_path)
    ask_history.append("a", 3, vault_dir=tmp_path)
    entries = ask_history.load(tmp_path)
    assert [e["query"] for e in entries] == ["a", "b"]
    assert entries[0]["fragmentCount"] == 3  # refreshed, not duplicated


def test_ask_history_recent_and_clear(tmp_path):
    for i in range(8):
        ask_history.append(f"q{i}", i, vault_dir=tmp_path)
    assert len(ask_history.recent(5, tmp_path)) == 5
    assert ask_history.clear(tmp_path)
    assert ask_history.count(tmp_path) == 0


def test_ask_history_corrupt_file_is_empty(tmp_path):
    p = tmp_path / ".timshel" / "ask_history.json"
    p.parent.mkdir(parents=True)
    p.write_text("{nope", encoding="utf-8")
    assert ask_history.load(tmp_path) == []


# --------------------------------------------------------------------------- #
# deck: first-non-empty start (U9) + retag_index (U4 / undo)
# --------------------------------------------------------------------------- #


def _deck(states):
    conns = [
        im.make_connection(
            "contradiction-over-time",
            rationale=f"teza {i}",
            notes=[f"n{i}.md"],
            directions=["k1", "k2"],
        )
        for i in range(len(states))
    ]
    deck = im.InsightDeck(conns)
    for i, st in enumerate(states):
        deck._state[i] = st
    return deck


def test_focus_first_nonempty_skips_empty_new():
    deck = _deck([im.KEPT, im.KEPT, im.DISMISSED])
    deck.focus_first_nonempty()
    assert deck.view == im.KEPT
    assert deck.active() is not None


def test_focus_first_nonempty_prefers_new():
    deck = _deck([im.KEPT, im.NEW])
    deck.focus_first_nonempty()
    assert deck.view == im.NEW


def test_retag_index_nonactive_moves_between_views():
    deck = _deck([im.NEW, im.NEW, im.NEW])
    deck.retag_index(2, im.KEPT)
    assert deck.counts() == {im.NEW: 2, im.KEPT: 1, im.DISMISSED: 0}
    assert deck.active_index == 0  # pointer untouched


def test_retag_index_active_advances_like_keep():
    deck = _deck([im.NEW, im.NEW])
    deck.retag_index(0, im.KEPT)  # handoff auto-keep on the active card
    assert deck.state_at(0) == im.KEPT
    assert deck.active_index == 1  # next Nowy loaded


# --------------------------------------------------------------------------- #
# reset target: undo that survives restart (triage replay)
# --------------------------------------------------------------------------- #


def _log(tmp_path) -> Path:
    return tmp_path / "signal.jsonl"


def test_reset_clears_triage(tmp_path):
    log = _log(tmp_path)
    t0 = datetime(2026, 7, 18, 10, 0, 0)
    record_action(TARGET_SAVE, sig="s1", conn_type="t", path=log, now=t0)
    assert triage_state_by_sig(log) == {"s1": "kept"}
    record_action(
        TARGET_RESET, sig="s1", conn_type="t", path=log,
        now=t0.replace(minute=1),
    )
    assert triage_state_by_sig(log) == {}


def test_reset_then_new_decision_wins(tmp_path):
    log = _log(tmp_path)
    t0 = datetime(2026, 7, 18, 10, 0, 0)
    record_action(TARGET_NONE, sig="s2", conn_type="t", path=log, now=t0)
    record_action(TARGET_RESET, sig="s2", conn_type="t", path=log, now=t0.replace(minute=1))
    record_action(TARGET_SAVE, sig="s2", conn_type="t", path=log, now=t0.replace(minute=2))
    assert triage_state_by_sig(log) == {"s2": "kept"}
