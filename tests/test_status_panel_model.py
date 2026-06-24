"""Unit tests for the status-panel view-model (`src/ui/status_panel_model.py`).

Pure logic — the data the NSPopover panel renders. No AppKit needed.
"""

from __future__ import annotations

import pytest

from src.app_status import AppStatus
from src.ui import status_panel_model as panel
from src.ui.status_panel_model import PanelRow, build_panel_model


def test_idle_model_has_no_active_row_or_progress():
    model = build_panel_model(AppStatus.IDLE)
    assert model.header_title == "Malinche"
    assert model.status_role == "ready"
    assert model.active_row is None
    assert model.progress is None


def test_transcribing_model_has_active_row_with_file():
    model = build_panel_model(
        AppStatus.TRANSCRIBING, current_file="rec_014.m4a", progress=0.68
    )
    assert model.status_role == "active"
    assert model.active_row is not None
    assert model.active_row.title == "rec_014.m4a"
    assert model.progress == pytest.approx(0.68)


def test_progress_is_dropped_for_non_active_states():
    # A stale progress value must not leak into idle/error rendering.
    model = build_panel_model(AppStatus.IDLE, progress=0.5)
    assert model.progress is None


def test_active_row_requires_a_current_file():
    model = build_panel_model(AppStatus.TRANSCRIBING, current_file=None)
    assert model.active_row is None


def test_error_uses_the_error_message():
    model = build_panel_model(AppStatus.ERROR, error_message="Disk not readable")
    assert model.status_role == "error"
    assert model.status_text == "Disk not readable"


def test_pending_count_pluralisation():
    one = build_panel_model(AppStatus.RECORDER_PENDING, pending_count=1)
    many = build_panel_model(AppStatus.RECORDER_PENDING, pending_count=3)
    assert one.status_text == "1 recording waiting"
    assert many.status_text == "3 recordings waiting"


def test_recorder_name_is_appended_when_idle():
    model = build_panel_model(AppStatus.RECORDER_IDLE, recorder_name="LS-P1")
    assert "LS-P1" in model.status_text


def test_recent_is_clamped_to_limit_and_preserves_order():
    rows = [PanelRow(symbol="doc", title=f"note {i}") for i in range(10)]
    model = build_panel_model(AppStatus.IDLE, recent=rows)
    assert len(model.recent_rows) == panel.RECENT_LIMIT
    assert model.recent_rows[0].title == "note 0"  # newest-first preserved


def test_pro_flag_passes_through():
    assert build_panel_model(AppStatus.IDLE, pro_active=True).pro_active is True
    assert build_panel_model(AppStatus.IDLE).pro_active is False


def test_retranscribe_files_pass_through():
    files = ["b.wav", "a.mp3"]
    model = build_panel_model(AppStatus.IDLE, retranscribe_files=files)
    assert model.retranscribe_files == files
    # Defaults to an empty list, never None.
    assert build_panel_model(AppStatus.IDLE).retranscribe_files == []


@pytest.mark.parametrize("status", list(AppStatus))
def test_model_builds_for_every_status(status):
    model = build_panel_model(status, current_file="x.wav", progress=0.5)
    assert model.status_text
    assert model.status_symbol
    assert model.status_role in {"ready", "active", "error"}
