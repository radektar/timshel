# Malinche — One-Pager

> **Your spoken thinking, captured for good — and recallable from your own Claude.**
> Plug in your recorder; every recording lands transcribed and structured in your Obsidian vault,
> on your Mac. No cloud. Nothing lost.

*Status: working draft (v0.1, 2026-06-17). Live landing (PL): https://malinche-radek-taraszka.vercel.app — Vercel project `malinche`, static `site/`. Rationale + decision trail in [POSITIONING.md](POSITIONING.md).*

## The problem

You think out loud — on a walk, in a meeting, mid-project — and those thoughts vanish. Even when you
record them, a raw transcript is a wall of text you never reopen. Worse: you forget you ever had the
thought, re-derive it from scratch, and miss that you already had something usable. And the cloud tools
that promise to remember for you can't be trusted — Limitless just deleted its EU users' data and folded
into Meta.

## What Malinche is

The cleanest, most private pipe from a dedicated audio recorder (USB dictaphone / SD card) into your own
knowledge base. Transcription runs locally (whisper.cpp); notes are Markdown in your Obsidian vault;
nothing leaves your Mac. It does the one job no competitor does — everyone else records meetings off your
computer mic; **Malinche ingests your *hardware* and writes into *your* system.**

## The killer: trust, built as a ladder

The deepest need isn't a feature — it's the certainty that nothing is lost and your past self comes back
when you need it. Malinche delivers it as a value ladder, on a foundation of guaranteed completeness:

1. **Recall** — ask in your own Claude "find everything about X" → it never misses (local MCP + a
   well-tagged vault).
2. **Resurfacing** — "your thought from three months ago — want to revisit it?"
3. **Connection** — "several of your thoughts connect into one idea — want to pursue a direction?" It
   *offers* options, never dictates; a wrong hit is dismissible.
4. **Synthesis** — turn the surfaced thread into a finished artifact (the blog post written from a list
   of recordings).

Trust is the floor, synthesis the ceiling — the same value, all the way up.

## Why it wins now

- **Trust is the most ownable position in the market — and Limitless's collapse just proved it.** We
  can't lose or delete your data because we never hold it: it's on your disk, recallable from your LLM.
- **Local meeting assistants** (free, on-device) only transcribe; **cloud memory apps** (Plaud, Otter,
  Limitless†) make you rent access to your own thoughts. Malinche owns the gap between them:
  hardware-in, Obsidian-native, private, recallable.

## Who it's for

Prosumers with a recorder and a note system: journalists, dictating lawyers, field researchers,
podcasters — people with a privacy reason to stay local and an Obsidian home for the output.

## Shape

Open-source core (MIT) + your own Claude key. **PRO = zero-config packaging** of the local stack
(whisper + embeddings + vector store + MCP) — you pay to *not* assemble the pipeline yourself.
Monetization model and amount: deferred until the wedge is validated.
