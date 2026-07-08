# Timshel — Tester Onboarding

Thanks for testing Timshel. This takes ~15 minutes to set up, then ~10 minutes
once a week. The goal of the test: **are the connections Timshel surfaces across
your notes worth acting on?**

## What Timshel is (and what we're testing)

Timshel turns a plain voice recorder into an AI recorder: it transcribes audio
into Markdown notes in your vault, and a paid **Insights** layer reads your
archive and surfaces non-obvious connections and contradictions between notes.
You're testing whether that Insights layer earns its keep.

**Privacy:** the weekly feedback file you send back contains your digest text,
note titles, and your personal glossary — nothing else. Your recordings and note
bodies never leave your Mac.

## Requirements

- Apple Silicon Mac (M1 or newer). **Intel Macs are not supported.**
- macOS 12 (Monterey) or newer.
- ~2 GB free disk, ~700 MB one-time download on first launch.

## 1. Install

1. Open the DMG and drag **Timshel** to Applications.
2. The app is not notarized yet, so double-clicking is blocked. Instead:
   **right-click the app → Open → Open.** You only do this once.
   - On macOS 15+: if right-click→Open doesn't offer it, go to **System
     Settings → Privacy & Security**, scroll down, and click **Open Anyway**.

## 2. First-run wizard

The wizard walks you through everything:

1. Pick your output folder — **choose your Obsidian vault** (or any folder).
2. Confirm the ~700 MB engine download (needs internet, a few minutes).
3. **Full Disk Access** — the wizard opens System Settings. Turn on the Timshel
   checkbox, then **restart the app**. This is required: without it, Timshel
   silently sees an empty SD card and never transcribes.
4. Paste the **Claude API key** Radek gave you (Settings → Transcription).

## 3. Seed your vault

Insights need material to connect. On day one:

- Menu → **Import transcripts…** → select your existing transcripts (txt / md /
  vtt — e.g. exported meeting notes). Aim for **30+ notes**.

## 4. Daily use

Record or import as you normally would. A digest appears roughly weekly in the
**Timshel Digests** folder in your vault.

## 5. The weekly 10 minutes

Once a week (e.g. Friday):

1. If no digest appeared this week: menu → **Generate digest now**.
2. Menu → **Insights** → go through **every** connection and rate it honestly:
   **Zachowaj** (worth acting on), **Odrzuć** (noise), or hand it off to
   Claude/ChatGPT (the strongest "this is useful" signal).
3. Menu → **Export feedback** → a zip lands on your Desktop and Finder reveals
   it. **Email that zip to radoslaw.taraszka@gmail.com.**

Do this for at least three weeks.

## Troubleshooting

- **Nothing transcribes / SD card not detected** → Full Disk Access isn't on;
  grant it and restart the app.
- **No AI summaries / no digest** → API key missing or out of quota (Settings).
- **Anything else** → menu → **Open logs**, or message Radek.
