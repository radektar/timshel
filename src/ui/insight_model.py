"""Pure data model for the Insights dashboard (Direction B).

The "Konstelacja" window is a thin AppKit renderer over this data: a queue of
connections Timshel found across notes (contradictions over time, shared
threads, emergent ideas), each carrying the full rationale / source notes /
directions that the digest produces. Keeping it pure (no AppKit) makes
navigation and keep/dismiss fully unit-testable — the view-model / renderer
split.

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
class EvidenceItem:
    """The 'ground' layer for one note: a dated verbatim fragment.

    Frozen/hashable so :class:`InsightConnection` stays hashable. Mirrors
    ``synthesis.Evidence`` but lives in the AppKit-free UI model.
    """

    note: str
    date: str = ""
    quote: str = ""


@dataclass(frozen=True)
class InsightConnection:
    """One connection between notes — the unit the reader displays.

    ``notes`` are basenames (2+); ``rationale`` is the high-level spark;
    ``evidence`` is the dated quote per note (the 'ground' layer revealed on
    demand); ``directions`` are 2–4 non-directive questions. ``conn_type`` is one
    of the module constants (the *display* type). ``synthesis_type`` and ``sig``
    are carried from the sidecar so the window can log a precomputed canonical
    signature without recomputing (ADR-004). ``label``/``tcolor`` default from the
    type metadata but may be overridden.
    """

    conn_type: str
    rationale: str
    notes: Tuple[str, ...]
    directions: Tuple[str, ...] = ()
    evidence: Tuple[EvidenceItem, ...] = ()
    snippet: str = ""
    label: str = ""
    tcolor: str = ""
    synthesis_type: str = ""
    sig: str = ""

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
    evidence: Optional[List[EvidenceItem]] = None,
    synthesis_type: str = "",
    sig: str = "",
) -> InsightConnection:
    """Build an :class:`InsightConnection`, tupling the list fields so the
    dataclass stays hashable/frozen. ``snippet`` falls back to a clipped
    rationale for the rail's two-line preview."""
    return InsightConnection(
        conn_type=conn_type,
        rationale=rationale,
        notes=tuple(notes),
        directions=tuple(directions or ()),
        evidence=tuple(evidence or ()),
        snippet=snippet or _clip(rationale, 86),
        label=label,
        tcolor=tcolor,
        synthesis_type=synthesis_type,
        sig=sig,
    )


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


# --------------------------------------------------------------------------- #
# The deck — stateful queue the window navigates.
# --------------------------------------------------------------------------- #


# Triage states a connection can be in. The window's rail filters by these.
NEW = "new"
KEPT = "kept"
DISMISSED = "dismissed"
VIEWS = (NEW, KEPT, DISMISSED)


class InsightDeck:
    """Connections with a three-state triage model and a current view filter.

    Every connection is in exactly one of :data:`NEW` / :data:`KEPT` /
    :data:`DISMISSED`. The window shows one **view** at a time (the rail's
    segmented control); ``keep`` / ``dismiss`` retag the active connection and
    advance to the next one *still in the current view* (so triaging the New
    queue flows forward, and recovering a Dismissed item moves it out of that
    view). Nothing is deleted — Odrzuć is reversible, which is the whole point of
    the Dismissed view.

    ``dismiss`` is a *signal*, not a suppressor: it never writes the dismissal
    store. Cross-session state is seeded from the signal log via ``triage`` (a
    ``sig -> state`` map), so the user's last Zachowaj / Odrzuć survives a restart.
    """

    def __init__(
        self,
        connections: Optional[List[InsightConnection]] = None,
        *,
        triage: Optional[Dict[str, str]] = None,
    ) -> None:
        self._items: List[InsightConnection] = list(connections or [])
        self._state: List[str] = []
        for conn in self._items:
            st = NEW
            sig = getattr(conn, "sig", "") or ""
            if triage and sig:  # an empty sig can't be joined to a logged action
                cand = triage.get(sig)
                if cand in VIEWS:
                    st = cand
            self._state.append(st)
        self._view = NEW
        self._active = self._first_in_view(NEW)

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
        if 0 <= self._active < len(self._items) and self._state[self._active] == self._view:
            return self._items[self._active]
        return None

    def state_at(self, index: int) -> Optional[str]:
        return self._state[index] if 0 <= index < len(self._state) else None

    def is_kept(self, index: int) -> bool:
        return self.state_at(index) == KEPT

    def counts(self) -> Dict[str, int]:
        """Per-view connection counts, for the rail's segmented control."""
        return {v: sum(1 for s in self._state if s == v) for v in VIEWS}

    @property
    def view(self) -> str:
        return self._view

    def visible(self) -> List[Tuple[int, InsightConnection]]:
        """``(index, connection)`` pairs in the current view, in deck order."""
        return [
            (i, self._items[i])
            for i, s in enumerate(self._state)
            if s == self._view
        ]

    @property
    def visible_count(self) -> int:
        return sum(1 for s in self._state if s == self._view)

    @property
    def unseen_count(self) -> int:
        """Connections still in the New queue — the rail's 'Nowe' badge."""
        return sum(1 for s in self._state if s == NEW)

    @property
    def is_empty(self) -> bool:
        return not self._items

    # -- navigation --------------------------------------------------------- #

    def set_view(self, view: str) -> None:
        """Switch the rail filter; active resets to the first item in that view."""
        if view in VIEWS and view != self._view:
            self._view = view
            self._active = self._first_in_view(view)

    def select(self, index: int) -> None:
        if 0 <= index < len(self._items) and self._state[index] == self._view:
            self._active = index

    def next(self) -> None:
        nxt = self._next_in_view(forward=True, wrap=False)
        if nxt != -1:
            self._active = nxt

    def prev(self) -> None:
        nxt = self._next_in_view(forward=False, wrap=False)
        if nxt != -1:
            self._active = nxt

    # -- triage ------------------------------------------------------------- #

    def keep(self) -> None:
        """Mark the active connection Zachowane and advance within the view."""
        self._retag(KEPT)

    def dismiss(self) -> None:
        """Mark the active connection Odrzucone (reversible) and advance."""
        self._retag(DISMISSED)

    def _retag(self, new_state: str) -> None:
        if not (0 <= self._active < len(self._items)):
            return
        leaving_view = self._state[self._active] == self._view and new_state != self._view
        self._state[self._active] = new_state
        if leaving_view:
            # The active item left the current view → show the next one in it.
            self._active = self._next_in_view(forward=True)

    # -- helpers ------------------------------------------------------------ #

    def _first_in_view(self, view: str) -> int:
        for i, s in enumerate(self._state):
            if s == view:
                return i
        return -1

    def _next_in_view(self, *, forward: bool, wrap: bool = True) -> int:
        n = len(self._items)
        if n == 0:
            return -1
        start = self._active if 0 <= self._active < n else (0 if forward else n - 1)
        step = 1 if forward else -1
        for off in range(1, n + 1):
            raw = start + off * step
            if not wrap and not (0 <= raw < n):
                break
            i = raw % n
            if self._state[i] == self._view:
                return i
        return -1


# --------------------------------------------------------------------------- #
# No-digest fallback — the window shows this only when no real digest sidecar
# exists yet (insight_pipeline.latest_deck returns None). Content mirrors the
# approved dashboard redesign (high-level spark + evidence + fuller directions),
# so even the empty-corpus first run looks like the real thing.
# --------------------------------------------------------------------------- #


def sample_deck() -> "InsightDeck":
    """An :class:`InsightDeck` of the real digest connections (placeholder).

    Mirrors the approved dashboard redesign: a high-level ``rationale`` (the
    spark) with the dated quotes moved into ``evidence`` (the ground layer), and
    fuller, self-contained ``directions``.
    """
    return InsightDeck(
        [
            make_connection(
                CONTRADICTION,
                "Założenie o jakości przesunęło się w miesiąc — z fundamentu "
                "projektu w pozycję do negocjacji pod presją budżetu.",
                ["Haetta — rozmowa z konstruktorem", "8Moons — filmiki 2"],
                [
                    "Co wymusiło zmianę założenia jakościowego — jednorazowy "
                    "kompromis pod presją budżetu, czy trwała zmiana kierunku, "
                    "którą warto nazwać wprost?",
                    "Filary projektu — naturalne materiały, jakość dla świadomego "
                    "klienta — bronić mimo budżetu, czy zrewidować i szukać "
                    "oszczędności gdzie indziej?",
                ],
                snippet="Założenie o jakości przesunęło się w miesiąc — budżet 2× w górę.",
                synthesis_type="contradiction-over-time",
                evidence=[
                    EvidenceItem(
                        "Haetta — rozmowa z konstruktorem", "17.06",
                        "…projekt stoi na naturalnych materiałach i jakości dla "
                        "świadomego klienta…",
                    ),
                    EvidenceItem(
                        "8Moons — filmiki 2", "18.06",
                        "…budżet przekroczony 2×, rozważasz obniżenie jakości "
                        "materiałów…",
                    ),
                ],
            ),
            make_connection(
                SHARED,
                "Okna wracają w obu notatkach jako to samo wąskie gardło — brak "
                "potwierdzeń od producentów napina sierpniowy termin z dwóch "
                "stron naraz.",
                [
                    "Planowanie budowy domu — materiały okna dach",
                    "Przygotowania do Eight Moons — okna i fundamenty",
                ],
                [
                    "Poszukać alternatywnych producentów już teraz, zanim "
                    "sierpniowy termin zacznie dyktować wybór za ciebie?",
                    "Jak wyglądałby realny plan B na okna — i który element "
                    "harmonogramu zwalnia, jeśli okna się obsuną?",
                ],
                snippet="Okna jako wąskie gardło wracają w dwóch notatkach.",
                synthesis_type="shared-thread",
                evidence=[
                    EvidenceItem(
                        "Planowanie budowy domu — materiały okna dach", "09.06",
                        "…producenci okien nie odpowiadają, a bez nich dach i tak "
                        "stoi w miejscu…",
                    ),
                    EvidenceItem(
                        "Przygotowania do Eight Moons — okna i fundamenty", "14.06",
                        "…dostępność okien przed sierpniem niepewna — to blokuje "
                        "fundamenty…",
                    ),
                ],
            ),
            make_connection(
                EMERGENT,
                "Ten sam dylemat skali wraca w trzech projektach: skalować przez "
                "automatyzację, czy utrzymać ręczny udział kosztem zasięgu — i za "
                "każdym razem rozstrzygasz go od nowa, bez nazwanej zasady.",
                [
                    "Strategia TekTutoreski",
                    "8Moons — filmiki 2",
                    "Harmonogram 2-tyg. projektu",
                ],
                [
                    "Czy to jedna „zasada skalowania”, którą stosujesz wszędzie — "
                    "a jeśli tak, jak brzmi wypowiedziana wprost, w jednym zdaniu?",
                    "Gdzie hands-on realnie buduje jakość i przewagę, a gdzie "
                    "tylko blokuje skalę z przyzwyczajenia?",
                ],
                snippet="Ten sam dylemat skali wraca w różnych projektach.",
                synthesis_type="emergent-idea",
                evidence=[
                    EvidenceItem(
                        "Strategia TekTutoreski", "03.06",
                        "…automatyzacja daje zasięg, ale gubi to, za co ludzie cię "
                        "cenią — ręczną robotę…",
                    ),
                    EvidenceItem(
                        "Harmonogram 2-tyg. projektu", "24.06",
                        "…znowu zaplanowałem ręczny montaż, mimo że plan zakładał "
                        "oddanie tego na zewnątrz…",
                    ),
                ],
            ),
        ]
    )
