# CLAUDE.md

Project-level guidance for Claude Code working on this repository. The global `~/.claude/CLAUDE.md` still applies; this file overrides only where it conflicts.

## What this project is

**Malinche** — automatic audio transcription system for macOS. Detects any USB recorder or SD card containing audio files, transcribes via whisper.cpp (Core ML on Apple Silicon), and writes transcripts as Markdown with YAML frontmatter.

- Repo: https://github.com/radektar/malinche (remote: `origin`)
- Stack: Python 3.12+, whisper.cpp, ffmpeg, macOS LaunchAgent, native menu bar app
- Current version: v2.0.0-beta.8 (dev) → v2.0.0 (in prep)

Note: legacy strings still reference "Olympus Transcriber" / `olympus-transcriber` (plist names, log paths, internal comments). Treat these as historical — don't rename them unless the task asks for it.

## Layout

- `src/` — application code (single package, flat layout)
  - `main.py`, `app_core.py`, `menu_app.py` — entry points (CLI / daemon / menu bar app)
  - `transcriber.py`, `file_monitor.py`, `volume_identity.py` — core pipeline
  - `markdown_generator.py`, `markdown_frontmatter.py`, `tagger.py`, `summarizer.py` — output side
  - `config/`, `setup/`, `ui/` — submodules
- `tests/` — pytest suite (`test_*.py`)
- `Docs/` — architecture, API, dev/testing guides; planning docs in `Docs/future/`
- `scripts/` — daemon control, build helpers
- `Makefile` — primary task runner
- `setup_app.py` — py2app bundle builder

## Commands

Everything routes through the Makefile. Prefer `make <target>` over invoking tools directly:

- `make install` — install deps from `requirements.txt` + `requirements-dev.txt`
- `make run` — run locally (`python src/main.py`)
- `make test` — pytest
- `make lint` — flake8 + mypy on `src/`
- `make format` — black + isort on `src/` and `tests/`
- `make build-app` / `make build-dmg` / `make release` — distribution pipeline
- `make setup-daemon` / `make stop-daemon` / `make reload-daemon` — LaunchAgent control
- `make logs` — tail `~/Library/Logs/olympus_transcriber.log`

Lint config: black line-length 88, isort black profile, mypy with `ignore_missing_imports`.

## Conventions

- Python 3.12+ required at runtime; mypy is configured against 3.8 baseline so avoid 3.9+-only typing syntax in code that needs to pass type checks.
- Tests use pytest markers `slow` and `integration` — skip with `-m "not slow"`.
- Single-package layout under `src/`, imported as the `src` package — every module uses the `src.` prefix (`from src.config import config`, `from src.transcriber import ...`). All 59 modules follow this; match it. (Tests run from the repo root, where `src` is importable.)
- Versioned releases: bump in `CHANGELOG.md` + git tag; `v2.0.0-beta.N` is the active series.

## Things to know before editing

- The daemon and menu app share state through files written by `state_manager.py` / `vault_index.py` — changes to either must keep formats compatible or migrate.
- whisper.cpp and ffmpeg are auto-installed on first launch (`runtime_deps.py`); don't add them as hard dependencies.
- macOS-only project. Don't add Linux/Windows compatibility shims unless asked.
- Full Disk Access is required for the menu bar app; see `Docs/FULL_DISK_ACCESS_SETUP.md`.
