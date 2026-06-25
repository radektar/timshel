# Insights Dashboard — build plan (Direction B)

Implementing the chosen design (`design-system/pages/dashboard-screens.html`) as a
native AppKit window. Branch: `feat/insights-dashboard`. Loop-driven; check items
off as they land. Pattern: **pure model + geometry (testable) → thin AppKit view**,
mirroring `status_panel.py` / `status_panel_model.py`.

Spec source of truth: `design-system/pages/dashboard-screens.html` + `insights-engine.js`.
v1 scope = czytnik + szyna + sygnał. Activity tab + skeleton are in-design but lower priority.

## Checklist

- [x] **Pure data model** — `src/ui/insight_model.py`: `InsightConnection` (type, label,
      layout, snippet, notes, rationale, directions, tcolor) + `InsightDeck`
      (queue, active index, navigate, keep/dismiss, unseen count). AppKit-free. + tests. ✅ 12 tests
- [x] **Constellation geometry** — `src/ui/constellation_geometry.py`: pure node/arc/bloom
      coordinates per layout (contradiction/thread/triad), scaled. Port of `insights-engine.js`
      `LAY` + arc control points. + tests. ✅ 8 tests
- [x] **Constellation view** — `NSView.drawRect_` (Core Graphics): nodes (radial glow),
      arcs (quadratic bézier + glow), golden bloom. ✅ `constellation_view.py`, 8 ui tests,
      offscreen render verified vs mock. Entrance animation deferred to the window pass.
- [ ] **Dashboard window shell** — `src/ui/dashboard_window.py`: `NSWindow` + dark chrome,
      grid (rail | reader). Focused/unfocused/min-width states. AppKit-optional guard.
- [ ] **Rail (connection list)** — `NSTableView`: dot + label + 2-line snippet; active = gold
      rail; kept = dimmed + ✓. "Ostatnie transkrypty" foot (reuse `PanelModel`).
- [ ] **Reader** — constellation stage + type + rationale (display font) + note chips +
      directions + Zachowaj/Odrzuć. Keep flash; dismiss → next.
- [ ] **States** — empty ("Cisza w korpusie"), transcribing skeleton.
- [ ] **Activity tab** — recent transcripts + connection counts (reuse `PanelModel`). [v1.1]
- [ ] **Menu integration** — native `NSMenu` becomes the click surface again; add
      `✦ Nowy insight (N)` + `Otwórz Malinche` entries opening the window; retire popover-as-click.
- [ ] **Signal** — gold dot on menu-bar icon when unseen insight; notification carries thesis;
      click opens window on that connection.
- [ ] **Pipeline** — carry full `rationale`/`directions`/`notes`/`type` from digest →
      `menu_app`/`state` → window. Today only the filename flows.
- [ ] **Token reconciliation (Faza 0)** — decide jade `#057857` vs `#46B17E`; dark-surface
      insight tokens in `theme.py`; native titlebar vs custom dark chrome.
- [ ] **Wire into `menu_app.py`** + `make lint` + `make test` green.
