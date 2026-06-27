# ADR-004: Insight → action integration spec

**Status:** Accepted · **Date:** 2026-06-27 · **Deciders:** Radek
**Consulted:** code-architecture, radek-product
**Reads with:** `insight-to-action-plan.md` (the phase), `insights-ui-redesign-brief.md`
(the UI), `POSITIONING.md` (the locks), Claude Design `insights-dashboard-redesign.html`
(the implemented surface).

## Context

The gate passed: synthesis is validated (N=3, all good). The next phase turns a
surfaced insight into a **handed-off action**, and the dashboard redesign is
approved. This ADR is the plan-mandated spec that precedes code — it fixes the
four contracts the implementation must share so the UI, the synthesis output,
and the validation instrument don't drift:

1. the synthesis **output contract** (what a connection carries),
2. the **canonical signature** (so every subsystem identifies a connection the same way),
3. the **`action_taken`** instrument (what we log),
4. the **handoff mechanisms** (how each target is invoked).

Current state (surveyed): three signature functions disagree — `signal_key`
(notes-only, `\n`, sha1[:8], no type) vs `connection_signature` (notes+type,
`|`, full sha1, used by **both** the dismissal store and the digest sidecar
`conn_meta.sig`). `deck_from_dicts` maps `synthesis_type`→UI constant and
**drops the original**, so the window cannot reconstruct the type-inclusive
signature. The synthesis `Connection` emits `type/notes/rationale/directions`
only — **no evidence**, and `directions` are terse.

---

## Decision 1 — Synthesis output contract (Track B)

`Connection` (synthesis.py) and the sidecar gain an **evidence** layer and
fuller directions. The rationale stays high-level; dated specifics move down.

```python
class Evidence(BaseModel):
    note: str        # exact [[basename]] id, one of Connection.notes
    date: str        # the note's date as supplied (YYYY-MM-DD or as-given)
    quote: str       # a SHORT verbatim fragment from that note's summary — grounded-only

class Connection(BaseModel):
    type: Literal["shared-thread", "contradiction-over-time", "emergent-idea"]
    notes: List[str]            # ≥2 exact basenames (unchanged)
    rationale: str              # HIGH-LEVEL claim — the spark; NOT the dated detail
    evidence: List[Evidence]    # one per linked note, the grounding fragment + date
    directions: List[str]       # 2-4 fuller invitations (~1-2 sentences), still questions
```

Rules baked into the prompt:
- **`rationale` is the spark, not the receipt.** A high-level synthesized claim
  ("the quality assumption shifted within a month"), never the dated quotes —
  those live in `evidence`. This is what lets the card read calmly and cures the
  freshness dependency (detail is one chevron away, not crammed into the thesis).
- **`evidence`: grounded-only.** Each item quotes verbatim from the supplied
  note summary; the model may not paraphrase into a quote or invent a date. One
  item per linked note (≈`len(notes)`). On a model that omits evidence, the deck
  renders the ground layer empty (degrade, don't fabricate).
- **`directions`: fuller, still non-prescriptive.** ~1-2 sentences each, phrased
  as invitations/questions ("A: Could you…?"). The POSITIONING lock holds —
  fuller ≠ bossier. Clean single language, no dropped foreign words.

Validation: `evidence[].note` must be one of `notes` (drop stray items, don't
reject the whole connection — mirror the existing lenient `_parse_payload`).
`SYNTHESIS_MAX_TOKENS` rises to fit evidence (the truncation guard already
skips+retries a `max_tokens` stop, so the failure mode is safe).

## Decision 2 — One canonical signature

Collapse the three implementations onto the **type-inclusive full-SHA1** form
already used by the dismissal store and the digest sidecar (it is the de-facto
standard; only `signal_key` disagreed).

- New module `src/connections/signature.py`:
  ```python
  def connection_signature(notes: Iterable[str], synthesis_type: str) -> str:
      key = synthesis_type.strip().lower() + "|" + "|".join(sorted(n.strip() for n in notes))
      return hashlib.sha1(key.encode("utf-8")).hexdigest()
  ```
  `dismissals.py` and `digest_writer.py` import it (behaviour-identical — no data
  migration). `validation_signal.signal_key` is **retired** in favour of passing
  a precomputed `sig`.
- **Carry the sig, don't recompute it.** The digest precomputes `sig` per
  connection and writes it into the insights sidecar (`insights-latest.json`);
  `deck_from_dicts` carries `sig` **and** `synthesis_type` onto
  `InsightConnection`; the window passes `connection.sig` straight into the
  action log. No subsystem recomputes identity → no drift, even though the UI
  still maps `synthesis_type`→a display constant for rendering.

Sidecar contract (`insights-latest.json`) gains two fields per connection:
```python
{ "type": "...", "notes": [...], "rationale": "...", "directions": [...],
  "evidence": [{"note","date","quote"}, ...],   # Decision 1
  "sig": "<full sha1>" }                          # Decision 2
```
`InsightConnection` gains `sig: str = ""` and `synthesis_type: str = ""`
(display `conn_type` mapping unchanged).

## Decision 3 — `action_taken` instrument

`signal.jsonl` migrates from kept/dismissed to **`action_taken`** (schema `v:2`;
the reader tolerates old `v:1` lines). Selection is multi, so the record names
the direction subset.

```json
{"v": 2, "ts": "2026-06-27T10:00:00", "action": "action_taken",
 "kind": "develop", "target": "llm",
 "conn_type": "contradiction-over-time", "sig": "<full sha1>",
 "directions": [0, 1], "n_dir": 2, "tool": "claude"}
```

- `kind` = `develop | do | decide | none` — derived from `target`:
  llm→develop, task→do, calendar→decide, clipboard→develop, dismiss→none.
- `target` = `llm | task | calendar | clipboard | none`.
- `sig` = canonical signature (joins the event back to the connection).
- `directions` = indices of the selected directions; `n_dir` their count.
- `tool` = active connected LLM (`claude|chatgpt|gemini`) when target=llm.
- **"Odrzuć" → `{kind:none, target:none}`** — a signal, not a suppressor. It
  does **not** write to the dismissal store; durable suppression stays the
  Obsidian-native `dismissed:` frontmatter path. ("nie wróci" copy is dropped.)
- "Zachowaj" stays as a quiet secondary; logged as `{kind:none, target:save}`
  (distinct from dismiss — "not now, remember it" ≠ "wrong").

Recorder lives in `validation_signal.py` (same best-effort write+swallow+warn,
shared `.malinche` dir). KPI = **action-rate** (share of surfaced connections
producing ≥1 non-`none` action).

## Decision 4 — Handoff mechanisms

A handoff packages `insight + evidence + selected directions` into a seeded
payload and throws it at the target. **Zero OAuth in v1.** The seeded prompt:

```
Mam wgląd z moich notatek głosowych.

[TYP]: „{rationale}"

Oparte na:
- {date} · {note}: „{quote}"
  …

Chcę rozwinąć:
1. {direction}
2. {direction}

Pomóż mi to przemyśleć — bez gotowych odpowiedzi, raczej dobre pytania.
```

| Target | Mechanism | Notes |
|---|---|---|
| **LLM — Claude** | `https://claude.ai/new?q=<urlenc>` | prefill works |
| **LLM — ChatGPT** | `https://chatgpt.com/?q=<urlenc>` | prefill works |
| **LLM — Gemini** | clipboard-seed + `open https://gemini.google.com/app` | **no public prompt-prefill URL** — copy payload, open, toast "prompt skopiowany — wklej" |
| **Calendar** | write `.ics` (VEVENT, no fixed time) to temp → `open` | Calendar.app shows the add dialog so the user sets the time; summary = first selected direction, description = full payload |
| **Task** | AppleScript → Reminders.app (`osascript`) | local, no OAuth; title = first direction, body = payload |
| **Clipboard** | `pbcopy` the markdown payload | universal fallback |

Engineering guards:
- **URL length cap.** `claude.ai/new?q=` / `chatgpt.com/?q=` truncate very long
  queries. If the encoded payload exceeds **~6000 chars**, fall back to
  clipboard-seed + open the bare tool URL (same as Gemini). Log nothing silently
  — the toast tells the user the prompt was copied.
- **`open` only.** All targets use macOS `open` / `osascript` — no network calls
  from Malinche itself; the browser/app does the talking. On-brand for a
  local-first Mac app.

**Connected-LLM setting.** New `config.LLM_HANDOFF_TOOL ∈ {claude,chatgpt,gemini}`
(default `claude`), surfaced in `settings_window` and live-switchable from the
window's primary-CTA caret (⌄). All three ship in v1 (Radek's call).

---

## Trade-off analysis

- **Type-inclusive full SHA1 over notes-only sha1[:8].** Two connections over the
  same note set but different types (shared-thread vs emergent-idea) are
  genuinely different insights and must dedup/log apart — notes-only would
  collide them. Full digest removes the (tiny) truncation-collision risk for a
  few bytes per line. Cost: `signal.jsonl` keys get longer — irrelevant.
- **Carry sig vs recompute in the window.** Recompute would need the window to
  hold the synthesis_type and re-implement the hash — two more drift surfaces.
  Carrying a precomputed string is one field and is drift-proof. Cost: sidecar
  grows; trivial.
- **Default LLM target vs neutral menu.** Trades preference-signal purity for
  usability; accepted for N=1, flagged for the router phase (Decision in plan +
  POSITIONING). The instrument still records the *actual* target, so truth is
  preserved; only the prior is biased.
- **Reminders/Calendar via open/AppleScript vs API.** No OAuth, no accounts, no
  network — fits local-first and ships now. Cost: no two-way sync, no
  confirmation the event/task persisted. Acceptable: API integrations are
  explicitly gated on conversion (plan §4).

## Consequences

- **Easier:** every subsystem speaks one connection identity; the window logs a
  rich, joinable action event; the ground layer has real data to render.
- **Harder / to revisit:** the synthesis prompt grows (evidence + fuller
  directions) and must stay within token budget; Gemini's no-prefill caveat and
  the URL cap mean two handoff code paths (prefill vs clipboard-seed); the
  `action_taken` analysis tooling (the `jq` one-liner) needs updating for `v:2`.

## Action items

1. [ ] `signature.py` (canonical) — repoint `dismissals.py`, `digest_writer.py`; retire `signal_key`.
2. [ ] Synthesis: `Evidence` model + `evidence` field + prompt rewrite (rationale high-level, fuller directions); raise `SYNTHESIS_MAX_TOKENS`.
3. [ ] Sidecar + `deck_from_dicts`: carry `evidence`, `sig`, `synthesis_type`; `InsightConnection` gains `sig`, `synthesis_type`, `evidence`.
4. [ ] `validation_signal`: `record_action(kind,target,sig,conn_type,directions,tool)` writing `v:2`; reader tolerates `v:1`.
5. [ ] Handoff module: per-tool URL builders + length cap, `.ics` writer, Reminders AppleScript, clipboard; seeded-prompt template.
6. [ ] `config.LLM_HANDOFF_TOOL` + window caret switcher. (A separate
   `settings_window` picker is deferred — the in-context caret is the
   discoverable control; the caret persists via `UserSettings.ai_handoff_tool`,
   so a settings duplicate adds no capability before N=1.)
7. [ ] UI port (separate task) consumes the above.
