# Timshel

> **Version:** v2.0.0-beta.8 (development) → v2.0.0 (in preparation)

Automatic audio transcription system for any USB recorder or SD card on macOS.

Local-first audio transcription for macOS — coming v2.1.0 with MCP integration (your transcripts, searchable natively inside Claude, Cursor, Continue and other MCP-aware tools).

## Features

Timshel has three usage levels. The application code is fully open source (MIT). Adding your own Anthropic key unlocks AI features locally; a future PRO subscription adds the hosted transcript database and MCP integration.

| Feature | FREE | + BYOK (`ANTHROPIC_API_KEY`) | + PRO subscription (v2.1.0) |
|---|:---:|:---:|:---:|
| Auto-detect recorders / SD cards | ✓ | ✓ | ✓ |
| Local transcription (whisper.cpp + Core ML) | ✓ | ✓ | ✓ |
| Markdown export with YAML frontmatter | ✓ | ✓ | ✓ |
| Basic tags | ✓ | ✓ | ✓ |
| Menu bar app + first-run wizard + Settings UI | ✓ | ✓ | ✓ |
| AI summaries (Claude) | — | ✓ | ✓ (your key) |
| AI smart tags | — | ✓ | ✓ |
| AI naming (auto-title) | — | ✓ | ✓ |
| Markdown versioning / Retranscribe | — | ✓ | ✓ |
| **Auto-pipeline transcript → cloud DB** | — | — | ⭐ PRO |
| **Local MCP server** | — | — | ⭐ PRO |
| **Semantic search across transcripts** | — | — | ⭐ PRO |
| **Auto-config for Claude Desktop / Cursor / Continue / Claude Code** | — | — | ⭐ PRO |
| **Cross-device sync** | — | — | ⭐ PRO |

> **BYOK (Bring Your Own Key):** set `ANTHROPIC_API_KEY` in your environment and all AI features run locally against your own Anthropic account — no subscription needed. PRO does not replace BYOK: the fullest experience is **PRO + BYOK** (local AI summaries via your key + a hosted, MCP-searchable transcript database via the subscription).

## Requirements

- macOS 12+ (Apple Silicon recommended for Core ML)
- Python 3.12+
- ffmpeg (installed automatically)
- whisper.cpp (installed automatically on first launch)

## Quick Start

For full instructions see **[QUICKSTART.md](QUICKSTART.md)**.

```bash
# 1. Clone the repository
git clone https://github.com/radektar/malinche.git
cd malinche

# 2. Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the app (whisper.cpp + ffmpeg are downloaded by the first-run wizard)
python -m src.menu_app
```

## Project Structure

```
src/                    source code (menu bar app, transcription, AI summary, UI)
tests/                  automated tests — run with: pytest
tests/integration/      E2E shell + Python integration scripts (require recorder)
scripts/                asset generators (icon, DMG background) + release pipeline
assets/                 icons, DMG background, menu bar template PNGs
Docs/                   architecture, beta plans, public distribution plan
Docs/testing-archive/   historical manual test checklists (alpha → milestones)
Docs/test-reports/      milestone test reports (M1, M2, M5)
Docs/archive/           legacy notes (Obsidian setup, migration summary)
setup_app.py            py2app entry — produces Timshel.app + DMG
Makefile                `make release` orchestrates build_release.sh
```

## Usage

### Menu bar app (recommended)

```bash
python -m src.menu_app
```

The app appears in the macOS menu bar with:
- Real-time status
- Open logs
- Retranscribe submenu
- Settings (General / Transcription / Disks / Maintenance tabs)
- PRO activation
- Quit

### CLI mode

```bash
python -m src.main
```

## Configuration

Configuration lives in the user settings file (managed via the Settings window) or via environment variables:

| Variable | Description | Default |
|---|---|---|
| `MALINCHE_TRANSCRIBE_DIR` | Output folder for transcripts | `~/Documents/Transcriptions` |
| `WHISPER_MODEL` | Whisper model | `small` |
| `WHISPER_LANGUAGE` | Transcription language | `pl` |

User data lives at `~/Library/Application Support/Timshel/` (config, logs, models, runtime).

For details see **[Docs/API.md](Docs/API.md)**.

## Documentation

| Document | Description |
|---|---|
| **[QUICKSTART.md](QUICKSTART.md)** | Quick start for developers |
| **[CHANGELOG.md](CHANGELOG.md)** | Release history |
| **[BACKLOG.md](BACKLOG.md)** | Planned features |
| **[Docs/ARCHITECTURE.md](Docs/ARCHITECTURE.md)** | System architecture |
| **[Docs/API.md](Docs/API.md)** | Module API reference |
| **[Docs/DEVELOPMENT.md](Docs/DEVELOPMENT.md)** | Developer guide |
| **[Docs/FULL_DISK_ACCESS_SETUP.md](Docs/FULL_DISK_ACCESS_SETUP.md)** | Full Disk Access setup |
| **[Docs/PUBLIC-DISTRIBUTION-PLAN.md](Docs/PUBLIC-DISTRIBUTION-PLAN.md)** | v2.0.0 distribution plan |
| **[Docs/TESTING-PRO-MCP.md](Docs/TESTING-PRO-MCP.md)** | PRO / MCP integration test plan (v2.1.0) |
| **[Docs/READINESS-CRITERIA.md](Docs/READINESS-CRITERIA.md)** | Definition of Done for the doc-strategy rewrite |

## Development

```bash
# Tests
pytest tests/ -v

# Linting
ruff check src/

# Build a signed DMG
make release
```

For details see **[Docs/DEVELOPMENT.md](Docs/DEVELOPMENT.md)**.

## Roadmap

### v2.0.0 FREE
- [x] Universal recorder support
- [x] First-run wizard
- [x] py2app packaging
- [x] DMG release (unsigned beta)
- [ ] Code signing & notarization

### v2.1.0 PRO (MCP integration)
- [ ] Local MCP server (search/get/list transcripts) for Claude Desktop, Cursor, Continue, Claude Code, Zed
- [ ] Cloud transcript DB + embeddings (Supabase + Cloudflare Workers)
- [ ] Auto-config wizard for MCP clients
- [ ] Cross-device sync
- [ ] License management (LemonSqueezy)

> AI summaries, smart tags and naming are **not** PRO features — they run locally in MIT via BYOK (`ANTHROPIC_API_KEY`).

For details see **[Docs/PUBLIC-DISTRIBUTION-PLAN.md](Docs/PUBLIC-DISTRIBUTION-PLAN.md)**.

## Troubleshooting

### App does not detect the volume

1. Check that the volume is mounted: `ls /Volumes/`
2. Check the log: `tail -f ~/Library/Application\ Support/Timshel/logs/malinche.log`
3. Confirm the app has **Full Disk Access**: see **[Docs/FULL_DISK_ACCESS_SETUP.md](Docs/FULL_DISK_ACCESS_SETUP.md)**

### whisper.cpp not found

The first-run wizard downloads whisper-cli automatically. To re-trigger downloads, open Settings → Maintenance → "Re-download dependencies".

## License

MIT License

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/name`
3. Commit with a descriptive message ending with `[tests: pass]`
4. Open a Pull Request against `main`

For workflow details see **[Docs/DEVELOPMENT.md](Docs/DEVELOPMENT.md)**.

---

> **Related documents:**
> - Architecture: [Docs/ARCHITECTURE.md](Docs/ARCHITECTURE.md)
> - API: [Docs/API.md](Docs/API.md)
> - Development: [Docs/DEVELOPMENT.md](Docs/DEVELOPMENT.md)
> - v2.0.0 plan: [Docs/PUBLIC-DISTRIBUTION-PLAN.md](Docs/PUBLIC-DISTRIBUTION-PLAN.md)
