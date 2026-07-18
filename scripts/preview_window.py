"""Render the Konstelacja window in canonical states and screenshot each.

Visual-QA harness (``make preview-window``): every UI round renders these
states to PNGs BEFORE anything is shown to a human — pixel review replaces
"it should look right". In-process capture via bitmap caching, so it needs
no Screen Recording permission.

States:
  1. Nowe + directions bar (two directions ticked)
  2. Zachowane (keep disabled as "Zachowano")
  3. Odrzucone (recall banner)
  4. In-app note reader (WKWebView) — window chrome + a separate webview
     snapshot (WKWebView renders out-of-process, so the cached window bitmap
     can't see its pixels; ``takeSnapshot`` can).

Output: ``dist/preview/`` (override with ``PREVIEW_OUT=dir``).
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from AppKit import NSApplication  # noqa: E402
from Foundation import NSDate, NSRunLoop  # noqa: E402

from src.ui import dashboard_window as dw  # noqa: E402
from src.ui import insight_model as im  # noqa: E402

OUT = Path(os.environ.get("PREVIEW_OUT", "dist/preview"))
OUT.mkdir(parents=True, exist_ok=True)

SAMPLE_NOTE = """---
title: "Rozmowa z Heliosem — oferta serwisowa"
date: 2026-07-18
duration: 00:14:20
language: pl
---

**Sedno:** Helios chce przejść z modelu projektowego na abonament serwisowy.

## Stanowiska

- [[Nordfab]] — sceptycznie o abonamentach („nikt tego nie kupi w przemyśle").
- Helios — odwrotnie: przewidywalny koszt wygrywa z niską ceną.

| Wariant | Marża | Ryzyko |
|---|---|---|
| Projektowy | 22% | niska powtarzalność |
| Abonament | 31% | churn po 12 mies. |

## Transkrypcja

Pełny zapis rozmowy o ofercie serwisowej i porównaniu wariantów
rozliczeń. Fragment z odsyłaczem: zob. [[Vantage 2026]].
"""


def settle(t=0.6):
    NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(t))


def shot(ctrl, name):
    settle()
    view = ctrl._window.contentView()
    b = view.bounds()
    rep = view.bitmapImageRepForCachingDisplayInRect_(b)
    view.cacheDisplayInRect_toBitmapImageRep_(b, rep)
    data = rep.representationUsingType_properties_(4, None)  # NSPNGFileType
    data.writeToFile_atomically_(str(OUT / f"{name}.png"), True)
    print("shot", name)


def shot_webview(web, name, timeout=6.0):
    """Async out-of-process snapshot of the reader's WKWebView."""
    done = {}

    def handler(image, error):
        done["image"], done["error"] = image, error

    waited = 0.0
    while web.isLoading() and waited < timeout:
        settle(0.1)
        waited += 0.1
    web.takeSnapshotWithConfiguration_completionHandler_(None, handler)
    waited = 0.0
    while "image" not in done and waited < timeout:
        settle(0.1)
        waited += 0.1
    image = done.get("image")
    if image is None:
        print("shot", name, "FAILED:", done.get("error"))
        return False
    tiff = image.TIFFRepresentation()
    from AppKit import NSBitmapImageRep

    rep = NSBitmapImageRep.imageRepWithData_(tiff)
    data = rep.representationUsingType_properties_(4, None)
    data.writeToFile_atomically_(str(OUT / f"{name}.png"), True)
    print("shot", name)
    return True


def main():
    NSApplication.sharedApplication()
    deck = im.sample_deck()
    ctrl = dw.build_dashboard_window(deck=deck)
    ctrl._ensure_window()
    ctrl.showWindow()

    # 1. Nowe with two directions ticked → inline dirbar + footer.
    ctrl._selected = {0, 1}
    ctrl._render()
    shot(ctrl, "qa-1-nowe-dirbar")

    # 2. Zachowane → footer shows the "Zachowano" state.
    ctrl._selected = set()
    ctrl._deck.keep()
    ctrl._deck.set_view(im.KEPT)
    ctrl._render()
    shot(ctrl, "qa-2-zachowane")

    # 3. Odrzucone → recall banner + constant footer labels.
    ctrl._deck.set_view(im.NEW)
    ctrl._deck.dismiss()
    ctrl._deck.set_view(im.DISMISSED)
    ctrl._render()
    shot(ctrl, "qa-3-odrzucone")

    # 4. In-app note reader.
    tmp = Path(tempfile.mkdtemp())
    note = tmp / "2026-07-18 - Rozmowa z Heliosem.md"
    note.write_text(SAMPLE_NOTE, encoding="utf-8")
    ctrl._deck.set_view(im.NEW)
    ctrl._open_note_in_reader(note)
    shot(ctrl, "qa-4-notatka-okno")
    ok = True
    if ctrl._webview is not None:
        ok = shot_webview(ctrl._webview, "qa-4-notatka-tresc")
    print("done ->", OUT)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
