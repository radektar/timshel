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
        b"proClicked:",
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


def test_build_returns_none_without_appkit():
    if status_panel._APPKIT_AVAILABLE:
        pytest.skip("AppKit present")
    assert status_panel.build_status_panel({}) is None
