"""End-to-end user-journey simulation for the recall lens.

Walks the whole path a real user takes — record → index → ask → open → synthesize →
save — through the ACTUAL dashboard controller, with callbacks backed by the REAL
engine (real embedder + sqlite-vec) over a realistic Polish fixture vault. Only the
LLM (synthesis) is stubbed deterministically; everything else is the shipping code.

Marked slow+integration: loads the local embedding model. Run with
``venv312/bin/python -m pytest tests/test_recall_e2e_user.py -m integration``.
"""

from __future__ import annotations

import importlib.util

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.integration, pytest.mark.ui]

from src.ui import dashboard_window as dw  # noqa: E402

if not dw._APPKIT_AVAILABLE:  # pragma: no cover - non-mac
    pytest.skip("AppKit unavailable", allow_module_level=True)
if not (importlib.util.find_spec("fastembed") and importlib.util.find_spec("sqlite_vec")):
    pytest.skip("recall deps (fastembed/sqlite-vec) unavailable", allow_module_level=True)

from AppKit import NSImage  # noqa: E402
from Foundation import NSMakeSize  # noqa: E402

from src.connections.recall.answer_writer import save_answer  # noqa: E402
from src.connections.recall.engine import RecallEngine  # noqa: E402
from src.connections.recall.synthesis import AnswerEvidence, RecallAnswer  # noqa: E402

# Realistic Polish transcripts mirroring the user's own topics (building, projects, AI).
FIXTURE = {
    "26-06-05 - Planowanie budowy domu - okna i dach": (
        "Dostepnosc okien przed sierpniem niepewna, producenci okien nie odpowiadaja "
        "na zapytania. Dach czeka, bez okien nie ruszymy z wykonczeniem."),
    "26-06-17 - Haetta - rozmowa z konstruktorem": (
        "Rozmowa z konstruktorem projektu Haetta o nosnosci belek i harmonogramie prac "
        "na dachu tiny house."),
    "26-06-24 - BOS demo generowania assetow AI": (
        "Przygotowanie dema generowania grafik AI dla banku BOS, porownanie silnikow."),
    "26-05-13 - Platforma personalizowanego serwisu rowerowego": (
        "Pomysl na platforme do personalizowanego serwisowania rowerow z dokumentacja."),
    "26-04-30 - Cyfryzacja dokumentacji medycznej NFZ": (
        "Automatyzacja bledow NFZ i cyfryzacja dokumentacji medycznej w placowkach."),
}


def _write_note(root, name, body):
    p = root / f"{name}.md"
    p.write_text(f'---\ntitle: "{name}"\n---\n\n{body}\n', encoding="utf-8")
    return p


@pytest.fixture()
def vault_engine(tmp_path):
    for name, body in FIXTURE.items():
        _write_note(tmp_path, name, body)
    engine = RecallEngine(tmp_path)
    engine.backfill()
    yield tmp_path, engine
    engine.close()


def _search_cb(engine):
    """Exactly the seam.search_detailed contract, backed by the fixture engine."""
    def cb(q):
        try:
            if engine.count() == 0:
                return [], 0.0, "empty"
            res, conf = engine.search_scored(q, k=8)
            return res, conf, "ok"
        except Exception:  # pragma: no cover - defensive
            return [], 0.0, "unavailable"
    return cb


def _stub_synth(query, results):
    """Deterministic stand-in for the LLM: a grounded card built from the real hits."""
    ev = [AnswerEvidence(note=r.note_id, date="", quote=(r.quote or "")[:80]) for r in results[:2]]
    return RecallAnswer(
        answered=True,
        thesis=f"Podsumowanie dla: {query}",
        evidence=ev,
        directions=["Co dalej z tym watkiem?"],
    )


def _paint(ctrl):
    ctrl._ensure_window()
    cv = ctrl._window.contentView()
    img = NSImage.alloc().initWithSize_(NSMakeSize(900, 600))
    img.lockFocus()
    try:
        cv.displayRectIgnoringOpacity_(cv.bounds())
    finally:
        img.unlockFocus()


def _ask(ctrl, query):
    """Drive the real search worker synchronously (no run loop in tests)."""
    ctrl._query = query
    ctrl._mode = "recall"
    ctrl._recall_loading = True
    ctrl._epoch += 1
    ctrl._recall_worker_(query, ctrl._epoch)
    ctrl.applyRecall_(None)


def _synthesize(ctrl):
    ctrl._answer_loading = True
    ctrl._synth_worker_(ctrl._query, list(ctrl._recall_raw), ctrl._epoch)
    ctrl.applyAnswer_(None)


def test_full_user_journey_record_ask_open_synthesize_save(vault_engine):
    vault, engine = vault_engine
    opened = []
    saved = {}

    def _save_cb(q, a):
        p = save_answer(q, a, vault, date_str="26-07-01")
        saved["path"] = p
        return p

    ctrl = dw.build_dashboard_window(callbacks={
        "recall_search": _search_cb(engine),
        "recall_synthesize": _stub_synth,
        "recall_save_answer": _save_cb,
        "open_note": lambda name: opened.append(name),
    })
    ctrl._ensure_window()

    # 1. The user records a NEW note mid-session → it must become searchable at once.
    new = _write_note(vault, "26-06-25 - Case EEG mozgu na landing page",
                      "Pomysl by badanie EEG mozgu pokazac jako historie na stronie.")
    engine.index_path(new)

    # 2. User asks a paraphrased question → the right note surfaces, cited.
    _ask(ctrl, "co ustalilismy w sprawie dostawy okien i dachu")
    assert ctrl._recall_status == "ok" and not ctrl._recall.is_empty
    assert ctrl._recall.rows[0].note_id.startswith("26-06-05")
    assert ctrl._recall.rows[0].quote  # a verbatim citation, not generated prose
    _paint(ctrl)

    # the just-recorded note is findable too (incremental index works)
    _ask(ctrl, "badanie EEG mozgu jako historia na strone")
    assert any("EEG" in r.note_id for r in ctrl._recall.rows)

    # 3. User asks something genuinely absent → honest abstinence, no invention.
    _ask(ctrl, "przepis na sernik z rodzynkami")
    assert ctrl._recall.is_empty and ctrl._recall_status == "ok"
    _paint(ctrl)

    # 4. Back to a real query, open the top cited source → opener fires with its id.
    _ask(ctrl, "rozmowa z konstruktorem projektu Haetta")
    _paint(ctrl)
    top_id = ctrl._recall_note_ids[0]

    class _Sender:
        def __init__(self, t):
            self._t = t

        def tag(self):
            return self._t

    ctrl.recallOpenClicked_(_Sender(0))
    assert opened and opened[-1] == top_id

    # 5. User escalates → grounded answer card built from the real hits.
    _synthesize(ctrl)
    assert ctrl._answer is not None and ctrl._answer.answered
    assert ctrl._answer.evidence  # cites the retrieved passages
    _paint(ctrl)

    # 6. User saves the answer → a parseable, linkable note lands in the vault.
    ctrl.saveAnswerClicked_(None)
    assert saved.get("path") and saved["path"].exists()
    body = saved["path"].read_text(encoding="utf-8")
    assert "type: timshel-recall-answer" in body and "[[" in body

    # frontmatter must be valid YAML even though the query is free text
    import yaml

    fm = body.split("---")[1]
    assert yaml.safe_load(fm)["type"] == "timshel-recall-answer"
