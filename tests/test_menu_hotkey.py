"""The recall hotkey chord predicate — exactly ⌃⌥Space, exclusive of other mods."""

from __future__ import annotations

from src.menu_app import _is_recall_chord

SPACE = 49
SHIFT, CONTROL, OPTION, COMMAND, CAPS = 1 << 17, 1 << 18, 1 << 19, 1 << 20, 1 << 16


def test_control_option_space_matches():
    assert _is_recall_chord(SPACE, CONTROL | OPTION) is True


def test_plain_option_space_does_not_match():
    # ⌥Space is the macOS non-breaking-space key — binding it would hijack typing.
    assert _is_recall_chord(SPACE, OPTION) is False


def test_superset_chords_do_not_match():
    assert _is_recall_chord(SPACE, CONTROL | OPTION | COMMAND) is False
    assert _is_recall_chord(SPACE, CONTROL | OPTION | SHIFT) is False


def test_wrong_key_does_not_match():
    assert _is_recall_chord(48, CONTROL | OPTION) is False  # not Space


def test_caps_lock_bit_is_ignored():
    assert _is_recall_chord(SPACE, CONTROL | OPTION | CAPS) is True
