"""Tests for the pure Insights data model (src/ui/insight_model.py)."""

from __future__ import annotations

from src.ui import insight_model as im


def test_make_connection_tuples_and_defaults():
    c = im.make_connection(
        im.CONTRADICTION,
        "A long rationale sentence that explains the connection clearly.",
        ["Note A", "Note B"],
        ["Question one?", "Question two?"],
    )
    assert isinstance(c.notes, tuple)
    assert isinstance(c.directions, tuple)
    assert c.notes == ("Note A", "Note B")
    # label / colour / layout resolve from the type metadata
    assert c.resolved_label() == "Sprzeczność w czasie"
    assert c.resolved_tcolor() == "#E0633A"
    assert c.layout() == "contradiction"


def test_snippet_falls_back_to_clipped_rationale():
    long = "x" * 200
    c = im.make_connection(im.SHARED, long, ["A", "B"])
    assert c.snippet.endswith("…")
    assert len(c.snippet) <= 86


def test_explicit_label_and_colour_override_type_defaults():
    c = im.make_connection(
        im.EMERGENT, "r", ["A", "B"], label="Custom", tcolor="#123456"
    )
    assert c.resolved_label() == "Custom"
    assert c.resolved_tcolor() == "#123456"
    # layout still derives from the type
    assert c.layout() == "triad"


def test_layout_for_each_type():
    assert im.layout_for_type(im.CONTRADICTION) == "contradiction"
    assert im.layout_for_type(im.SHARED) == "thread"
    assert im.layout_for_type(im.EMERGENT) == "triad"
    assert im.layout_for_type("nonsense") == "thread"


def test_empty_deck():
    deck = im.InsightDeck()
    assert len(deck) == 0
    assert deck.is_empty
    assert deck.active() is None
    assert deck.unseen_count == 0
    # navigation/triage on empty is a no-op, never raises
    deck.next()
    deck.prev()
    deck.keep()
    deck.dismiss()
    assert deck.active() is None


def _deck3():
    return im.InsightDeck(
        [
            im.make_connection(im.CONTRADICTION, "r1", ["A", "B"]),
            im.make_connection(im.SHARED, "r2", ["C", "D"]),
            im.make_connection(im.EMERGENT, "r3", ["E", "F"]),
        ]
    )


def test_navigation_clamps():
    deck = _deck3()
    assert deck.active_index == 0
    deck.prev()
    assert deck.active_index == 0  # clamped low
    deck.next()
    deck.next()
    assert deck.active_index == 2
    deck.next()
    assert deck.active_index == 2  # clamped high
    deck.select(1)
    assert deck.active().rationale == "r2"
    deck.select(99)  # out of range — ignored
    assert deck.active_index == 1


def test_keep_marks_and_advances():
    deck = _deck3()
    assert deck.unseen_count == 3
    deck.keep()  # keep #0
    assert deck.is_kept(0)
    assert deck.unseen_count == 2
    # advanced to the next un-kept (#1)
    assert deck.active_index == 1


def test_keep_wraps_to_earlier_unkept():
    deck = _deck3()
    deck.select(2)
    deck.keep()  # keep last; no later un-kept → wrap to #0
    assert deck.active_index == 0
    assert deck.unseen_count == 2


def test_dismiss_removes_and_shows_next():
    deck = _deck3()
    deck.select(1)
    deck.dismiss()  # remove #1 (r2); r3 shifts into slot 1
    assert len(deck) == 2
    assert deck.active_index == 1
    assert deck.active().rationale == "r3"


def test_dismiss_at_end_steps_back():
    deck = _deck3()
    deck.select(2)
    deck.dismiss()
    assert len(deck) == 2
    assert deck.active_index == 1
    assert deck.active().rationale == "r2"


def test_dismiss_until_empty():
    deck = _deck3()
    deck.dismiss()
    deck.dismiss()
    deck.dismiss()
    assert deck.is_empty
    assert deck.active() is None


def test_sample_deck_is_the_three_real_connections():
    deck = im.sample_deck()
    assert len(deck) == 3
    types = [c.conn_type for c in deck.items]
    assert types == [im.CONTRADICTION, im.SHARED, im.EMERGENT]
    # every connection carries full content for the reader
    for c in deck.items:
        assert c.rationale
        assert len(c.notes) >= 2
        assert len(c.directions) >= 2
