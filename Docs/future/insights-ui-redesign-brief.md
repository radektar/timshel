# Insights UI — redesign brief (v2, dogfood-driven)

**For:** Claude Design
**From:** product (radek-product + visual-identity sparring), 2026-06-27
**Status:** Brief — supersedes the pre-dogfood Insights window direction
**Reads with:** `insight-to-action-plan.md` (the phase this UI serves),
`POSITIONING.md` (synthesis design locks).

---

## What just happened (why this brief exists)

We ran the gate: a real digest on the real vault, N=3 connections.
**All three landed as genuinely good** — the synthesis quality is validated.
The bottleneck has moved. It is no longer "is there a signal?" It is **"can
the user extract the value the signal contains?"** — and the current window
can't. This is a redesign, not a polish.

The validating user's verbatim feedback, and what each item actually means:

1. **"I understand them now because the context is fresh — but they're
   described very high-level, I can't go into detail."**
   → The card shows the *spark* and nothing under it. There is no evidence
   layer (which notes said what, when). The insight's comprehension depends on
   the user's working memory. **This is a time bomb under validation:** the
   validation window is 2–4 weeks, and an insight you can't reconstruct in two
   weeks is dead — you don't act on what you no longer understand.

2. **"The graphic element, which is so prominent here, gets in my way more
   than it helps. We must reduce its importance."**
   → The animated constellation is the visual hero but carries the least
   actionable information. It steals the hero slot and pushes real content
   (thesis, directions, actions) down and off-screen (the primary action is
   cropped at the bottom edge). Beautiful poster; the user needs a workbench.

3. **"'Kierunki' [directions] are a great idea, but again so short you can't
   tell what they're about."**
   → `directions` are one-line questions, styled as a passive footer. They are
   too thin to understand and therefore too thin to *act on* — which matters
   because in the next phase **these directions become the action payload.**

## The root cause (read before designing)

**Two of these three are not UI problems — they are thin-data problems.**

The synthesis schema (`Connection`) emits exactly: `type`, `notes` (ids),
`rationale` (one sentence), `directions` (2–4 short invitations). There is no
per-note evidence, and directions are capped terse by design. **No layout can
make thin data deep.** So this phase is *two parallel tracks that ship as one*:

- **Track A — UI redesign** (this brief, Claude Design).
- **Track B — richer synthesis output** (eng): add an evidence layer, fatten
  directions — see "Data contract" below.

If we redesign without Track B, we get a prettier frame around the same
high-level text. Don't.

## The job this UI does

From the plan: Malinche is an **action engine, not a thinking mirror.** An
insight's value is realized only when it is *metabolized into an action* —
a decision made, an idea developed, a thing committed to. The window's job is
therefore three moves, in order:

1. **Spark** — land the insight (we do this well; keep it).
2. **Ground** — let the user drop into the evidence and *trust/understand* it
   without fresh memory. (Missing today. Feedback #1.)
3. **Act** — hand the grounded insight off to an external tool
   (LLM thread / calendar / task / clipboard). (The next phase. Feedback #3
   is its seed — directions are the action candidates.)

The current UI does (1), skips (2), and buries (3) under decoration. Rebalance
the whole hierarchy around spark → ground → act.

---

## Design direction (opinionated — push back if you disagree)

### 1. Demote the constellation: from hero to sigil

The type-coded visual language (red = contradiction, gold = shared/emergent,
the node relationships) is *good* and worth keeping — as **wayfinding, not as a
scene.** The animated glow is exactly the part that steals attention from
content, so it's exactly the part to cut.

**Recommended:** shrink the constellation to a small (~28–36px) **static
sigil** that lives inline next to the type label in the card header. The
*shape* still encodes the relationship type — an opposition/axis for
contradiction-over-time, a converging triad for shared-thread, a branching
spark for emergent-idea — so we keep the semantic, lose the real-estate cost.
No animation, or barely-there.

Alternatives if you want to argue them: (B) a tiny per-connection thumbnail in
the left rail; (C) a faint, large, low-contrast watermark behind the thesis.
I lean hard to (A) — (C) still competes for the eye, which is the whole
problem. The reclaimed vertical space goes to the evidence + action layers.

### 2. Add the ground layer (progressive disclosure)

Give the card depth, revealed on demand so the default view stays calm:

- **Always visible:** thesis (the `rationale`, large — it's the spark) +
  the note chips.
- **One gesture deeper — Evidence:** per linked note, the actual fragment(s)
  that triggered the connection, with date. For the contradiction example:
  `17.06 — "…stoi na naturalnych materiałach i jakości…"` /
  `18.06 — "…budżet 2×, rozważasz obniżenie jakości…"`. This is the single
  most important addition — it's what cures the freshness dependency.
- **One gesture deeper still — Source:** open the note in Obsidian (plumbing
  already built; keep the chips clickable).

Shape the disclosure however reads best (inline expand, a detail drawer, a
second pane). Constraint: the **default** card must not become a wall of text —
spark stays clean; evidence is a deliberate step down, not always-on.

### 3. Promote directions into the action layer

This is where Track A and the next phase meet. Each direction stops being a
terse footer bullet and becomes a **first-class, actionable unit:**

- A fuller line (1–2 sentences — see Track B) that's self-explanatory without
  fresh context.
- An attached **handoff control** — the flat action menu from the plan:
  `[Rozwiń → LLM]  [Zadanie]  [Kalendarz]  [Kopiuj]`. Flat, human-decides, no
  model-suggested default (we want unbiased preference data).
- Visually this becomes the lower-center of the card — the place the eye lands
  after the thesis — not the cropped bottom strip.

Note the lock: directions stay **invitations, never prescriptions**
(POSITIONING.md). Fuller ≠ bossier. "Co wymusiło zmianę założenia jakościowego,
i czy to jednorazowy kompromis czy trwała zmiana kierunku?" — still a question,
just one you can actually act on.

### 4. Demote "Zachowaj", keep "Odrzuć"

Per the plan: keep-rate is a vanity signal; action-rate is the real one. So
"Zachowaj" drops to a quiet secondary/archive affordance, and the action menu
above becomes the primary gesture. "Odrzuć" stays (it's a `kind:none` signal,
not a suppressor — copy should not promise "won't come back").

---

## Information hierarchy (target)

Top to bottom, in descending visual weight:

```
[type sigil] TYPE LABEL                                    connection N of M
THESIS — the rationale, large, the spark                            (hero text)
  ⌄ Evidence (on demand): per-note fragment + date                  (ground)
NOTE CHIPS → open in Obsidian
DIRECTIONS — each a fuller line + [Rozwiń][Zadanie][Kalendarz][Kopiuj]  (act)
                                              Odrzuć        ·  Zachowaj (quiet)
```

The constellation is *gone from this column* — it's the small sigil up top.

## Data contract this requires (Track B — hand to eng, not design)

The redesign assumes the synthesis emits more. Flagged here so design and eng
move together:

- **`evidence`** (new): per note in the connection, the grounding fragment(s)
  + date. Enables the ground layer. Must stay *quoted from the source*
  (grounded-only claim lock).
- **`directions`** (enrich): from bare one-liners to self-contained
  invitations (≈1–2 sentences each), still non-prescriptive. Consider whether
  a direction becomes a small object (`{ prompt, lens }`) so the action handoff
  can seed a good LLM prompt from it.
- **Signature carry-through** (from the plan's design locks): the deck/sidecar
  must carry the canonical `signature(notes, synthesis_type)` so an
  `action_taken` event can be joined back to the connection it measures.
  `deck_from_dicts` currently drops `synthesis_type` — fix in this phase.

## Constraints (non-negotiable)

- **Native macOS, dark surface.** AppKit/PyObjC window. Keep the existing deep
  near-black surface + warm amber/gold accent + type-coded node colors
  (red = contradiction, gold = shared/emergent). SF Pro. Polish diacritics
  must render (they do).
- **No new heavy framework.** This renders in the existing dashboard window.
- **"Empty is fine."** No connections → the calm "Cisza w korpusie" empty
  state stays; don't design it away.
- **Quiet by default.** This is a once-a-week surface, not a feed. Calm,
  recessive, earns attention — not a dashboard that demands it.

## Open questions for the designer

1. Evidence layer: inline expand vs. a detail drawer vs. a dedicated second
   pane? Which keeps the default card calm while making "go deeper" one cheap
   gesture?
2. Where do the four handoff actions live per direction — inline buttons, a
   hover affordance, an overflow menu? They must not turn the card into a
   button farm.
3. Does the sigil stay per-type (3 shapes) or also encode note-count? (Lean:
   type only — count is in "N of M".)
4. Left rail: the recent-transcripts list at the bottom — does it survive this
   redesign, or does the reclaimed space change its role?

## Out of scope (don't design these now)

- API integrations (Linear/Calendar auto-create) — gated on conversion, later.
- The smart-default "first move" router — we deliberately collect unbiased
  choices first.
- In-app LLM hosting — handoff only; the conversation lives in the user's tool.
