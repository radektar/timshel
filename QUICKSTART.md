# Timshel — Quick Start

Get Timshel running locally in about 5 minutes.

## Requirements

- macOS 12+ (Apple Silicon recommended for Core ML acceleration)
- Python 3.12+
- About 1.5 GB of free disk space (whisper model + ffmpeg)
- **Optional:** Anthropic API key for AI summaries (PRO)

## 1. Clone and create a virtual environment

```bash
git clone https://github.com/radektar/malinche.git
cd malinche

python3 -m venv venv
source venv/bin/activate
```

## 2. Install Python dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt   # only for development
```

## 3. (Optional) Configure Claude API for AI summaries

```bash
cp .env.example .env
# edit .env and add: ANTHROPIC_API_KEY=sk-ant-...
```

Without an API key the app still runs — it just falls back to filename-based titles instead of AI-generated ones.

Get a key at <https://console.anthropic.com/>.

## 4. Run the app

```bash
python -m src.menu_app
```

On first launch the wizard will:
1. Ask which recorder you use (Olympus LS-P1, generic SD card, etc.)
2. Download whisper-cli, ffmpeg, the chosen Whisper model **and its Core ML
   encoder** (~700 MB total for `small` — the encoder is a separate download)
3. Prompt for Full Disk Access if needed (see [Docs/FULL_DISK_ACCESS_SETUP.md](Docs/FULL_DISK_ACCESS_SETUP.md))

Once setup completes, the app appears in the macOS menu bar. Click the icon for status, settings, logs, and PRO activation.

## 5. Test it

1. Plug in your recorder (or insert an SD card with audio files).
2. The app status changes to "Scanning recorder…" then "Processing: <filename>".
3. Open the log viewer (menu bar → Open logs) to watch progress live.
4. Transcripts land in your configured output folder (default: `~/Documents/Transcriptions`).

## Output format

Transcripts are saved as `.md` files with YAML frontmatter, ready for Obsidian:

```markdown
---
title: "Project planning conversation"
date: 2026-05-05
recording_date: 2026-05-05T14:30:00
source: REC001.mp3
duration: 00:15:32
tags: [transcription]
---

## Summary

[AI-generated summary, only if Claude API is configured.]

## Transcript

[Full whisper.cpp transcript here.]
```

## Useful commands

```bash
# Run all unit tests
pytest tests/ -v

# Lint
ruff check src/

# Build a DMG (unsigned, for development)
make release

# Build a TESTER DMG (H1 instrumentation baked on)
make release-tester

# Seed a vault from already-transcribed text (txt/md/vtt)
make import-text SRC=<path>

# Read the H1 action-rate signal from a tester's export
./venv312/bin/python -m src.connections.signal_report --json <path>/signal.jsonl

# Open the user data directory
open ~/Library/Application\ Support/Timshel/
```

See `Docs/TESTER-ONBOARDING.md`, `Docs/H1-TEST-PROTOCOL.md`, and
`Docs/TESTER-BUILD-VERIFY.md` for the tester program.

## Troubleshooting

### whisper.cpp not found

Re-trigger downloads from the menu bar: **Settings → Maintenance → "Re-download dependencies"**.

### Recorder not detected

1. Check that the volume is mounted: `ls /Volumes/`
2. Open the log viewer (menu bar → Open logs) and look for "Recorder detected" or "Waiting for recorder".

### Whisper Metal error (-6)

The app detects genuine Metal errors (`ggml_metal_init: error`, a command buffer
that `failed with status`, …) and retries the recording with the GPU off
(`-ng`). Lines like `ggml_metal_device_init: tensor API disabled` or
`Core ML model loaded` are normal output of a healthy run, not failures.

After two independent failures — another boot, or another day — the GPU is
switched off for good on this machine; the verdict lives in
`~/Library/Application Support/Timshel/coreml_status.json`. A single recorded
failure is dropped as soon as a GPU run succeeds. Once the verdict stands the
GPU is no longer tried, so it only lifts when whisper, the model, or macOS
changes — or when you delete that file to force a re-probe.

### Transcription hangs ("Transkrypcja utknęła")

A GPU can also wedge without reporting anything. The app watches whisper's
output — a decoded segment per ~30 s of audio, plus a progress line every 5% —
and if **nothing** arrives for 4.5 minutes it kills the run and retries the
recording once with the GPU off. For short recordings the window widens
automatically — it is computed from the recording's length and the hour budget,
so an old Mac grinding through a 4-minute memo gets 7.5 minutes of tolerance
(capped at 15 minutes, however short the clip). Two phases are silent by nature and get their own budget: startup
(15 minutes) and the first Core ML encoder compile for a model on this machine,
which whisper announces in the log and which can take a while on `large`.

If whisper wedges *after* saving the transcript — a Metal teardown that never
returns — the finished file is kept and nothing is re-run. A wedge *during* the
write leaves a partial file, which is discarded rather than kept: the recording
is retried instead of being filed with a fragment of its content.

Nothing is recorded permanently here: a stall can come from a loaded CPU or a
sleeping disk just as easily as from Metal, so the GPU stays enabled for the
next recording. If the retry with the GPU off stalls too, the message says so.
Note that `-ng` moves only the decoder to the CPU — the encoder always runs
through Core ML — so a stall that survives the retry points at the model or its
Core ML encoder (try a smaller model, or **Settings → Maintenance →
"Re-download dependencies"**) as much as at the machine (disk, memory, a stuck
iCloud sync).

Note there is no way to turn Core ML off: `WHISPER_COREML` and
`GGML_METAL_DISABLE` are whisper.cpp *build* switches and do nothing in the
environment. This build always runs the encoder through Core ML — `-ng` only
moves the decoder to the CPU. If the log says
`failed to load Core ML model`, the encoder itself is missing or damaged:
re-run **Settings → Maintenance → "Re-download dependencies"**.

### Process locked

If logs say `Skipping process_recorder because another instance holds lock`:

```bash
ls ~/Library/Application\ Support/Timshel/runtime/transcriber.lock
rm ~/Library/Application\ Support/Timshel/runtime/transcriber.lock   # only if you're sure no instance is running
```

## Key locations

| What | Where |
|---|---|
| App config | `~/Library/Application Support/Timshel/config.json` |
| App logs | `~/Library/Application Support/Timshel/logs/timshel.log` |
| State file | `~/Library/Application Support/Timshel/state.json` |
| Whisper binaries | `~/Library/Application Support/Timshel/bin/` |
| Whisper models | `~/Library/Application Support/Timshel/models/` |
| Output directory | configurable, default `~/Documents/Transcriptions/` |

## Multi-Mac (iCloud vault)

- Set `MALINCHE_TRANSCRIBE_DIR` to a folder inside your iCloud Drive (`~/Library/Mobile Documents/…`).
- Timshel writes a deduplication index to `.malinche/index.json` inside the vault.
- A second Mac sees the same audio file's fingerprint and skips it.
- FREE: dedup/skip. PRO: versioned retranscription (`.v2.md`, `.v3.md`).

## Further reading

- [README.md](README.md) — feature overview
- [Docs/ARCHITECTURE.md](Docs/ARCHITECTURE.md) — system architecture
- [Docs/DEVELOPMENT.md](Docs/DEVELOPMENT.md) — developer guide
- [Docs/API.md](Docs/API.md) — module API reference
- [CHANGELOG.md](CHANGELOG.md) — release history
