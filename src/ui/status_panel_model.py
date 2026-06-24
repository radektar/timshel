"""Pure view-model for the menu-bar status panel (L4 phase 2b).

The NSPopover panel that replaces the flat dropdown is a thin renderer over this
data: given the app's state it produces a header, an optional active-work row,
a list of recent transcriptions, and the footer actions. Keeping it pure (no
AppKit) makes the panel's behaviour fully unit-testable — the strategy doc's L4
"split UI logic into pure functions" — and lets the design be reviewed against
the approved mock without launching the app.

See ``Docs/UI-REDESIGN-L4-PLAN.md`` (phase 2). The AppKit renderer lives
elsewhere and consumes :class:`PanelModel`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from src.app_status import AppStatus
from src.ui import style


@dataclass(frozen=True)
class PanelRow:
    """One line in the panel: an SF Symbol + a title and optional subtitle."""

    symbol: str
    title: str
    subtitle: str = ""


@dataclass(frozen=True)
class PanelModel:
    """Everything the status panel needs to render, derived from app state."""

    header_title: str
    status_text: str
    status_symbol: str
    status_role: str  # "ready" | "active" | "error"
    active_row: Optional[PanelRow] = None
    progress: Optional[float] = None  # 0.0–1.0 for the active work, if known
    recent_rows: List[PanelRow] = field(default_factory=list)
    pro_active: bool = False
    #: Staged audio file names available for re-transcription (newest first).
    #: Rendered as the expandable "Re-transcribe" section in the panel footer.
    retranscribe_files: List[str] = field(default_factory=list)


#: Human-readable status line per state. Active states get a verb; the active
#: file name (when present) is appended by :func:`build_panel_model`.
_STATUS_TEXT = {
    AppStatus.IDLE: "Idle",
    AppStatus.SCANNING: "Scanning for recordings…",
    AppStatus.TRANSCRIBING: "Transcribing…",
    AppStatus.DOWNLOADING: "Downloading…",
    AppStatus.MIGRATING: "Updating index…",
    AppStatus.RECORDER_IDLE: "Recorder connected",
    AppStatus.RECORDER_PENDING: "Recordings waiting",
    AppStatus.ERROR: "Error",
}

#: States that represent in-progress work and therefore get an "active row".
_ACTIVE_STATES = {
    AppStatus.SCANNING,
    AppStatus.TRANSCRIBING,
    AppStatus.DOWNLOADING,
    AppStatus.MIGRATING,
}

#: How many recent items the panel shows.
RECENT_LIMIT = 5


def status_text(status: AppStatus, error_message: Optional[str] = None) -> str:
    """The status line for *status* (uses *error_message* when in ERROR)."""
    if status == AppStatus.ERROR and error_message:
        return error_message
    return _STATUS_TEXT.get(status, "Idle")


def build_panel_model(
    status: AppStatus,
    current_file: Optional[str] = None,
    progress: Optional[float] = None,
    recent: Optional[List[PanelRow]] = None,
    pro_active: bool = False,
    error_message: Optional[str] = None,
    recorder_name: Optional[str] = None,
    pending_count: Optional[int] = None,
    retranscribe_files: Optional[List[str]] = None,
) -> PanelModel:
    """Derive the full :class:`PanelModel` from current app state.

    Pure and deterministic. The active row appears only for in-progress states
    and only when a current file is known; ``recent`` is clamped to
    :data:`RECENT_LIMIT` newest-first (caller supplies order).
    """
    text = status_text(status, error_message)
    if status == AppStatus.RECORDER_PENDING and pending_count:
        text = f"{pending_count} recording{'s' if pending_count != 1 else ''} waiting"
    elif (
        status in (AppStatus.RECORDER_IDLE, AppStatus.RECORDER_PENDING)
        and recorder_name
    ):
        text = f"{text} · {recorder_name}"

    active_row: Optional[PanelRow] = None
    if status in _ACTIVE_STATES and current_file:
        active_row = PanelRow(
            symbol=style.symbol_name_for_status(status),
            title=current_file,
            subtitle=_STATUS_TEXT.get(status, "").rstrip("…"),
        )

    rows = list(recent or [])[:RECENT_LIMIT]

    return PanelModel(
        header_title="Malinche",
        status_text=text,
        status_symbol=style.symbol_name_for_status(status),
        status_role=style.role_for_status(status),
        active_row=active_row,
        progress=progress if status in _ACTIVE_STATES else None,
        recent_rows=rows,
        pro_active=pro_active,
        retranscribe_files=list(retranscribe_files or []),
    )
