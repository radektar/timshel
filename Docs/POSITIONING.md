# Positioning — Malinche (the wedge)

**Status:** Locked (sparring session) · **Date:** 2026-06-17 · **Supersedes:** the "non-technical
ambient-memory / MCP-first PRO" framing in PUBLIC-DISTRIBUTION-PLAN.md (to be rewritten in Phase C
only after the wedge is validated — see `~/.claude/plans/poczekaj-zxeby-mialo-sens-*.md`).

**Lead update (locked 2026-06-23):** the *promise* now leads with connection/synthesis, not trust.
Trust is reframed as *proof* and the *build-floor* — not the marketing hook. See
[ONE-PAGER.md](ONE-PAGER.md). The wedge, ICP, killer-ladder, PRO definition and kill-condition below
are unchanged in substance; only the headline emphasis moved.

## The wedge (one sentence)

**Malinche turns a dedicated audio recorder (USB dictaphone / SD card) into Obsidian-native
transcripts — fully on your Mac, audio never leaves the machine.**

This is the one job no competitor does. Everyone else records *meetings off your computer's mic*.
Malinche ingests *physical recording hardware* and writes Markdown straight into your vault.

## The lead (locked 2026-06-23) — promise vs. build order

Two axes were being conflated; separating them dissolves the trust-vs-synthesis tension:

- **Promise (what we lead with / dramatize):** connection & synthesis — *"your recordings lie dead →
  the system draws the pattern you'd never connect."* In 2026, transcription, recall and "remember for
  me" all commoditize; the only ownable hook is emergent synthesis over your private corpus. **Trust
  does not lead** — nobody wakes up wanting "trust"; it is a reason-to-believe.
- **Proof (reason-to-believe):** trust — local · your files · open source · "we can't lose what we
  never hold."
- **Build order (separate axis):** floor first — completeness + directed recall (low-risk, mostly
  built) — with connection-push as the signature v1.x bet. The killer-ladder below still holds; only
  the *headline* moved off trust.

The landing measures which layer the market pulls hardest on, and that decides build order.

## ICP — who this is for

Prosumers who already own and use a dedicated recorder, and live in a note system:

- **Journalists / reporters** — field interviews on a handheld recorder → searchable notes.
- **Lawyers / professionals who dictate** — long dictation, confidentiality matters (local = no cloud).
- **Field recordists / researchers / ethnographers** — hours of SD-card audio to process in batch.
- **Podcasters / creators** — raw recorder takes → transcripts in their workflow.

Common thread: they have *hardware*, a *privacy reason* to stay local, and an *Obsidian/Markdown*
home for the output. **Not** the pure non-technical ambient-memory consumer (that market is crowding
toward free, on-device assistants — and the privacy-positioned incumbent, Limitless, just died into Meta).

## Anti-positioning (why we win against both camps)

| Camp | Examples | Their model | Where Malinche wins |
|---|---|---|---|
| Cloud AI memory | Plaud, Otter, Granola, Fireflies, Bee, Limitless (†) | subscription, cloud, often HW-tethered | local-first (audio never uploaded); no recurring-for-episodic-value; owns your files |
| Local meeting assistants | BB Recorder, Thoth, Veroi, MacWhisper | on-device, mic/meeting capture, often free | **hardware/SD ingest** + **Obsidian-native output** — neither camp does this |

We do **not** compete as "ask your recordings assistant" (crowded, commoditizing to free). We compete
as "the cleanest pipe from your recorder into your knowledge base, privately."

## Killer feature (locked, sparring 2026-06-17)

**Guaranteed, zero-config "your spoken thinking is captured reliably and made permanently recallable
in your own Claude — so you never lose a thought, and your past self resurfaces when it's relevant."**

The emotional core the user named is *trust / peace of mind* ("pewność że wszystko TAM jest") — but
drilling showed it is **not** capture-anxiety ("did it save?"). It is **fear of losing access to your
own past thinking**: forgetting you ever had a thought, re-deriving it from scratch, missing that you
already have something usable. The magic is **the past self resurfacing exactly when relevant** ("next
time I work on a similar topic I'm pleasantly surprised I already have something"). Framing that
differentiates: *spoken* thoughts are usually lost; typed notes you link by hand — Malinche makes spoken
thought as linkable and recallable as written, automatically.

**The value ladder** — trust and synthesis are NOT rivals; they are the floor and ceiling of one ladder.
Drilling separated pull from push:
- *Foundation — completeness.* Instrumental backend guarantee so nothing above has holes (the reliability
  the alpha changelog hardens: failed formats, abandoned staged files, retry loops, dead vault entries,
  dedup). NOT user-facing — the "capture ledger" idea is demoted to internal/diagnostic.
- *Pull — directed recall.* "Find me everything related to X." The user asks Claude over the well-tagged
  vault and trusts it won't miss. **Depends on good tagging** (Malinche already has a tagger). The felt
  proof + shippable trust floor.
- *Pull — exploratory recall.* "I don't know exactly what, but I know I need something here."
- *Push — resurfacing.* "Your thought from 3 months ago — want to do something with it?" Forgotten-but-
  relevant notes brought back unprompted.
- *Push — connection (the differentiator).* "I found several thoughts that connect into one idea — want
  to develop it?" The system mines the corpus for **latent patterns across scattered thoughts** — not
  resurfacing one note, but proposing an emergent idea. Highest value, highest noise-risk.
- *Payoff — synthesis.* Develop the surfaced idea into an artifact (e.g. the blog post the user wrote
  from a list of recordings). The top of the ladder that trust enables.

The **MCP → Claude layer is the engine for the whole pull/push ladder** (still local + BYO-LLM) — which
promotes it from "bonus" to core. Push (resurfacing/connection) is high-risk/high-reward and where
Readwise-style tools become noise — scope it deliberately.

Pricing: **zero-config** — the user pays to NOT assemble whisper + embeddings + vector store + MCP
himself. Willingness-to-pay is for *removal of work*, not a feature.

Why this wins now: **Limitless deleting EU users' data made trust the most ownable position in the
market.** Everyone competes on AI flash; Malinche competes on "we can't lose or delete your data because
we never hold it — it's on your disk, recallable from your own Claude." Wedge + killer + timing align.

Stays **100% local** for the core flow (single Mac + dedicated recorder): local vault + local vector
store (sqlite-vec/lancedb) + local MCP server → Claude. No cloud, no GDPR, no ops.

**Connection-push — design principles (resolved 2026-06-17):**
- **Non-prescriptive — offer directions, don't instruct.** It summarizes the pattern and proposes
  *several possible directions* ("I see these connect — here's a new angle; want to pursue one of
  A/B/C/D?"), leaving choice and agency with the user. A thinking-prompt, not "do this." Then it helps
  develop the chosen direction (handoff into synthesis).
- **Pattern-triggered, not time-triggered.** Fires when a genuine pattern emerges from incoming
  recordings — cadence is governed by *whether a pattern exists*, not a schedule. A weekly digest is the
  acceptable calm container so it never pesters ("żeby nie być nagabywanym").
- **False positives tolerable IF dismissible.** Wrong connections will happen and are forgivable; the
  requirement is a **"not relevant / dismiss" affordance** (ideally the system respects/learns from it).
  This is what stops a noisy feature from poisoning trust.

Note: this push design is **itself trust-preserving** — never overclaims certainty, always leaves the
user the choice, always lets him correct. The killer value (trust) holds all the way up to the
interaction level, not just the storage level.

**Resolved 2026-06-27 (a):** the synthesis handoff = **open the thread in the user's connected LLM**
(Claude / ChatGPT / Gemini, switchable), seeded with the insight + evidence + the directions the user
selected — *not* an auto-drafted outline. Malinche packages and throws over the wall; the conversation
lives in the user's tool. See `future/insight-to-action-plan.md` + `future/ADR-004-insight-action-integration.md`.

**Still open:** (b) v1 scope on the ladder — *proposed:* ship foundation + pull recall first (low-risk
trust floor), connection-push as the signature v1.x bet once recall is trusted — needs Radek's confirmation.

**Amendment 2026-06-27 — default handoff target vs. the non-prescriptive lock.** The Insights surface
now gives the handoff a **default target** (the primary CTA "Kontynuuj w [connected LLM]"). This does
**not** break the non-prescriptive principle above: the default governs *transport* (where the insight
is handed off), never *content* (the directions stay invitations/questions, the model never says "do
X"). The default-bias this introduces into the preference signal is accepted for the N=1 validation
phase and must be re-weighted/re-collected under a neutral menu before any smart-default router is
trained from `action_taken` data. (Decision: Radek, 2026-06-27.)

### What PRO sells (re-derived from the killer)
PRO = the **zero-config managed packaging** of the local "it's all there" stack (auto whisper +
embeddings + local vector + MCP auto-config + the completeness ledger). NOT hosted AI. Sync is
explicitly **demoted** — if notes live in Obsidian, "everywhere + always there" is already Obsidian's
job (Obsidian Sync / iCloud); reselling it would be selling someone else's feature. Multi-device /
iPhone capture is out of v1 scope. Monetization model/amount: deferred.

## Kill-condition for PRO

Build no backend until validated. **Pivot/kill trigger:** if the wedge-validation signal (Phase B —
landing + waitlist or 10–15 problem interviews with the ICP above) comes in below the threshold Radek
sets, PRO stays a free OSS convenience or is dropped, and we re-examine the wedge. No Supabase on faith.

## Messaging line

> **Malinche — from scattered recordings, one system that composes something of its own.**
> Your recorder's audio lands transcribed in your Obsidian vault, on your Mac — then Malinche reads it
> all together and surfaces the pattern you'd never connect by hand. No cloud, no keys.
>
> *(Trust is the proof beneath this promise, not the headline — see "The lead", above.)*
