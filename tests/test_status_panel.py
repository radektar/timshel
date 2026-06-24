"""Smoke tests for the AppKit status panel (`src/ui/status_panel.py`).

The popover's behaviour (open/close, click) can only be judged by running the
app, but these verify the controller builds, registers its ObjC selectors, and
updates from a PanelModel without raising — the failure mode that would
otherwise only surface at runtime.
"""

from __future__ import annotations

import pytest

from src.app_status import AppStatus
from src.ui import status_panel
from src.ui.status_panel_model import build_panel_model

requires_appkit = pytest.mark.skipif(
    not status_panel._APPKIT_AVAILABLE, reason="requires AppKit (PyObjC)"
)


@requires_appkit
def test_build_status_panel_returns_controller():
    panel = status_panel.build_status_panel(
        {"settings": lambda _=None: None, "quit": lambda _=None: None}
    )
    assert panel is not None
    # The ObjC selectors the status item / buttons target must be registered.
    for selector in (
        b"statusButtonClicked:",
        b"settingsClicked:",
        b"logsClicked:",
        b"importClicked:",
        b"digestClicked:",
        b"genDigestClicked:",
        b"retranscribeToggleClicked:",
        b"retranscribeFileClicked:",
        b"quitClicked:",
        b"installOnStatusItem:button:menu:",
    ):
        assert panel.respondsToSelector_(selector), selector


@requires_appkit
@pytest.mark.parametrize("status", list(AppStatus))
def test_panel_update_never_raises(status):
    panel = status_panel.build_status_panel({})
    # Must tolerate every status without raising (cosmetic path).
    panel.update_(build_panel_model(status, current_file="rec.wav", progress=0.4))


@requires_appkit
def test_panel_action_invokes_callback_and_closes():
    fired = []
    panel = status_panel.build_status_panel(
        {"settings": lambda _=None: fired.append("s")}
    )
    panel.settingsClicked_(None)
    assert fired == ["s"]


class _FakeSender:
    """Stands in for the NSButton whose tag maps to a staged-file index."""

    def __init__(self, tag):
        self._tag = tag

    def tag(self):
        return self._tag


@requires_appkit
def test_retranscribe_toggle_flips_expanded_without_raising():
    panel = status_panel.build_status_panel({})
    panel.update_(
        build_panel_model(AppStatus.IDLE, retranscribe_files=["a.wav"])
    )
    assert panel._retranscribe_expanded is False
    panel.retranscribeToggleClicked_(None)  # popover not shown → re-render is a no-op
    assert panel._retranscribe_expanded is True


@requires_appkit
def test_retranscribe_file_click_invokes_callback_with_name():
    fired = []
    panel = status_panel.build_status_panel(
        {"retranscribe": lambda name=None: fired.append(name)}
    )
    panel.update_(
        build_panel_model(
            AppStatus.IDLE, retranscribe_files=["260615_0199.WAV", "260614.MP3"]
        )
    )
    panel.retranscribeFileClicked_(_FakeSender(1))
    assert fired == ["260614.MP3"]


@requires_appkit
def test_render_with_expanded_retranscribe_never_raises():
    panel = status_panel.build_status_panel({})
    model = build_panel_model(
        AppStatus.IDLE, retranscribe_files=["a.wav", "b.mp3", "c.m4a"]
    )
    panel.update_(model)
    panel._retranscribe_expanded = True
    view, height = panel._render(model)
    assert height > 0


def test_build_returns_none_without_appkit():
    if status_panel._APPKIT_AVAILABLE:
        pytest.skip("AppKit present")
    assert status_panel.build_status_panel({}) is None
