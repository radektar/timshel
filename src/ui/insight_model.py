"""Pure data model for the Insights dashboard (Direction B).

The "Konstelacja" window is a thin AppKit renderer over this data: a queue of
connections Malinche found across notes (contradictions over time, shared
threads, emergent ideas), each carrying the full rationale / source notes /
directions that the digest produces. Keeping it pure (no AppKit) makes
navigation and keep/dismiss fully unit-testable, the same split as
``status_panel_model.py``.

Spec: ``design-system/pages/dashboard-screens.html`` + ``insights-engine.js``.
The AppKit window (``dashboard_window.py``) consumes :class:`InsightDeck`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- #
# Connection types. Three kinds, each with a constellation layout, a Polish
# label and an accent (the literal hex from the design — these are dark-surface
# tints, brighter than the canonical brand tokens on purpose).
# --------------------------------------------------------------------------- #

CONTRADICTION = "contradiction"
SHARED = "shared"
EMERGENT = "emergent"

#: Layout key per type (drives the constellation geometry).
_LAYOUT_FOR_TYPE: Dict[str, str] = {
    CONTRADICTION: "contradiction",
    SHARED: "thread",
    EMERGENT: "triad",
}


@dataclass(frozen=True)
class TypeMeta:
    """Display metadata for a connection type."""

    label: str
    tcolor: str  # hex, dark-surface tint
    layout: str


TYPE_META: Dict[str, TypeMeta] = {
    CONTRADICTION: TypeMeta("Sprzeczność w czasie", "#E0633A", "contradiction"),
    SHARED: TypeMeta("Wspólny wątek", "#D6B033", "thread"),
    EMERGENT: TypeMeta("Emergentny pomysł", "#E3C16B", "triad"),
}


def layout_for_type(conn_type: str) -> str:
    """Constellation layout key for a connection *type* (falls back to thread)."""
    return _LAYOUT_FOR_TYPE.get(conn_type, "thread")


def meta_for_type(conn_type: str) -> TypeMeta:
    """Display metadata for a *type* (falls back to the shared-thread look)."""
    return TYPE_META.get(conn_type, TYPE_META[SHARED])


# --------------------------------------------------------------------------- #
# One connection.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class InsightConnection:
    """One connection between notes — the unit the reader displays.

    ``notes`` are basenames (2+); ``rationale`` is one sentence; ``directions``
    are 2–4 non-directive questions. ``conn_type`` is one of the module
    constants. ``label``/``tcolor``/``layout`` default from the type metadata so
    callers can pass just the type, but may override (the digest may supply its
    own label).
    """

    conn_type: str
    rationale: str
    notes: Tuple[str, ...]
    directions: Tuple[str, ...] = ()
    snippet: str = ""
    label: str = ""
    tcolor: str = ""

    def resolved_label(self) -> str:
        return self.label or meta_for_type(self.conn_type).label

    def resolved_tcolor(self) -> str:
        return self.tcolor or meta_for_type(self.conn_type).tcolor

    def layout(self) -> str:
        return layout_for_type(self.conn_type)


def make_connection(
    conn_type: str,
    rationale: str,
    notes: List[str],
    directions: Optional[List[str]] = None,
    snippet: str = "",
    label: str = "",
    tcolor: str = "",
) -> InsightConnection:
    """Build an :class:`InsightConnection`, tupling the list fields so the
    dataclass stays hashable/frozen. ``snippet`` falls back to a clipped
    rationale for the rail's two-line preview."""
    return InsightConnection(
        conn_type=conn_type,
        rationale=rationale,
        notes=tuple(notes),
        directions=tuple(directions or ()),
        snippet=snippet or _clip(rationale, 86),
        label=label,
        tcolor=tcolor,
    )


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


# --------------------------------------------------------------------------- #
# The deck — stateful queue the window navigates.
# --------------------------------------------------------------------------- #


class InsightDeck:
    """Ordered queue of connections with selection + keep/dismiss.

    Mutable (the user navigates and triages); the window re-reads it after each
    action. ``keep`` marks the active connection saved (it stays in the list,
    dimmed) and advances to the next un-kept one; ``dismiss`` removes it. Both
    clamp the active index so :meth:`active` is always valid or ``None``.
    """

    def __init__(self, connections: Optional[List[InsightConnection]] = None) -> None:
        self._items: List[InsightConnection] = list(connections or [])
        self._kept: List[bool] = [False] * len(self._items)
        self._active = 0 if self._items else -1

    # -- queries ------------------------------------------------------------ #

    def __len__(self) -> int:
        return len(self._items)

    @property
    def items(self) -> Tuple[InsightConnection, ...]:
        return tuple(self._items)

    @property
    def active_index(self) -> int:
        return self._active

    def active(self) -> Optional[InsightConnection]:
        if 0 <= self._active < len(self._items):
            return self._items[self._active]
        return None

    def is_kept(self, index: int) -> bool:
        return 0 <= index < len(self._kept) and self._kept[index]

    @property
    def unseen_count(self) -> int:
        """Connections not yet kept — the rail header's 'N niezobaczonych'."""
        return sum(1 for k in self._kept if not k)

    @property
    def is_empty(self) -> bool:
        return not self._items

    # -- navigation --------------------------------------------------------- #

    def select(self, index: int) -> None:
        if 0 <= index < len(self._items):
            self._active = index

    def next(self) -> None:
        if self._active < len(self._items) - 1:
            self._active += 1

    def prev(self) -> None:
        if self._active > 0:
            self._active -= 1

    # -- triage ------------------------------------------------------------- #

    def keep(self) -> None:
        """Mark the active connection kept and advance to the next un-kept one."""
        if not (0 <= self._active < len(self._items)):
            return
        self._kept[self._active] = True
        self._advance_to_unkept()

    def dismiss(self) -> None:
        """Remove the active connection; show the next (or previous at the end)."""
        if not (0 <= self._active < len(self._items)):
            return
        del self._items[self._active]
        del self._kept[self._active]
        if self._active >= len(self._items):
            self._active = len(self._items) - 1

    @property
    def _next_unkept_from_active(self) -> int:
        for i in range(self._active + 1, len(self._items)):
            if not self._kept[i]:
                return i
        for i in range(0, self._active):
            if not self._kept[i]:
                return i
        return self._active

    def _advance_to_unkept(self) -> None:
        self._active = self._next_unkept_from_active


# --------------------------------------------------------------------------- #
# Placeholder data — the real 8moons digest connections, used by the window
# until the pipeline carries rationale/directions/notes from the digest. Mirrors
# the `QUEUE` in design-system/pages/insights-engine.js so the build matches the
# approved mock. Replace with live digest data once the pipeline lands.
# --------------------------------------------------------------------------- #


def sample_deck() -> "InsightDeck":
    """An :class:`InsightDeck` of the real digest connections (placeholder)."""
    return InsightDeck(
        [
            make_connection(
                CONTRADICTION,
                "17.06 projekt stoi na naturalnych materiałach i jakości dla "
                "świadomego klienta; 18.06 — budżet przekroczony 2×, rozważasz "
                "obniżenie jakości materiałów.",
                ["Haetta — rozmowa z konstruktorem", "8Moons — filmiki 2"],
                [
                    "Co wymusiło zmianę założenia jakościowego?",
                    "Czy filary projektu trzeba zrewidować, czy bronić mimo budżetu?",
                ],
                snippet="Założenie o jakości przesunęło się w miesiąc — budżet 2× w górę.",
            ),
            make_connection(
                SHARED,
                "Okna wracają w obu notatkach jako krytyczne wąskie gardło — brak "
                "odpowiedzi producentów i niepewna dostępność przed sierpniem.",
                [
                    "Planowanie budowy domu — materiały okna dach",
                    "Przygotowania do Eight Moons — okna i fundamenty",
                ],
                [
                    "Poszukać alternatywnych producentów już teraz?",
                    "Jak wyglądałby plan B na okna?",
                ],
                snippet="Okna jako wąskie gardło wracają w dwóch notatkach.",
            ),
            make_connection(
                EMERGENT,
                "W różnych projektach wraca ten sam dylemat: skalować przez "
                "automatyzację, czy utrzymać ręczny udział kosztem skali.",
                [
                    "Strategia TekTutoreski",
                    "8Moons — filmiki 2",
                    "Harmonogram 2-tyg. projektu",
                ],
                [
                    "Czy to jedna „zasada skalowania”, którą stosujesz wszędzie?",
                    "Gdzie hands-on buduje jakość, a gdzie tylko blokuje skalę?",
                ],
                snippet="Ten sam dylemat skali wraca w różnych projektach.",
            ),
        ]
    )
