"""Tests for the process-wide 'Once' approval registry (volume_session)."""

from src import volume_session


def test_approve_and_query():
    volume_session.approve_once("UUID-A")
    assert volume_session.is_approved_once("UUID-A") is True
    assert volume_session.is_approved_once("UUID-B") is False


def test_forget_single():
    volume_session.approve_once("UUID-A")
    volume_session.forget("UUID-A")
    assert volume_session.is_approved_once("UUID-A") is False


def test_prune_to_drops_unmounted():
    volume_session.approve_once("UUID-A")
    volume_session.approve_once("UUID-B")

    forgotten = volume_session.prune_to({"UUID-A"})

    assert forgotten == {"UUID-B"}
    assert volume_session.is_approved_once("UUID-A") is True
    assert volume_session.is_approved_once("UUID-B") is False


def test_prune_to_empty_forgets_all():
    volume_session.approve_once("UUID-A")
    volume_session.approve_once("UUID-B")

    forgotten = volume_session.prune_to(set())

    assert forgotten == {"UUID-A", "UUID-B"}
    assert volume_session.all_approved() == set()


def test_clear():
    volume_session.approve_once("UUID-A")
    volume_session.clear()
    assert volume_session.all_approved() == set()
