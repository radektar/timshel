# Development Guide

> **Version:** v2.0.0-beta.18 (development)
>
> **Related documents:**
> - [README.md](../README.md) — project overview
> - [ARCHITECTURE.md](ARCHITECTURE.md) — system architecture
> - [API.md](API.md) — module API reference
> - [TESTING-GUIDE.md](TESTING-GUIDE.md) — testing guide
> - [PUBLIC-DISTRIBUTION-PLAN.md](PUBLIC-DISTRIBUTION-PLAN.md) — distribution plan

## Quick start

### 1. Clone and set up

```bash
git clone https://github.com/radektar/malinche.git
cd malinche
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 2. Run locally

```bash
# Menu bar app (recommended)
python -m src.menu_app

# CLI mode
python -m src.main
```

The first-run wizard downloads whisper-cli, ffmpeg, and the chosen Whisper model on launch — no separate setup script.

### 3. Run tests

```bash
pytest tests/ -v
```

## Project structure

```
src/                    application source
├── menu_app.py         # Menu bar entry point
├── main.py             # CLI entry point
├── app_core.py         # Coordinator
├── bootstrap.py        # First-run + legacy migration
├── transcriber.py      # Whisper.cpp orchestration
├── file_monitor.py     # FSEvents
├── state_manager.py    # On-disk state
├── markdown_generator.py
├── vault_index.py      # Multi-device dedup index
├── fingerprint.py      # Audio fingerprinting
├── config/             # Settings, defaults, license, features
├── setup/              # Wizard, dependency manager, downloader
└── ui/                 # Settings window, log viewer, dialogs, theme

tests/                  # Pytest unit tests
tests/integration/      # E2E shell + Python integration scripts (require a recorder)
scripts/                # Asset generators + release helpers
assets/                 # Icons, DMG background, menu bar template PNGs
Docs/                   # Architecture, API, plans, guides
Docs/archive/           # Frozen historical notes (Polish)
Docs/testing-archive/   # Frozen manual test checklists (Polish)
Docs/test-reports/      # Frozen milestone test reports (Polish)
setup_app.py            # py2app entry — produces Malinche.app + DMG
Makefile                # `make release` orchestrates build_release.sh
pyproject.toml          # ruff + pytest + black config
requirements*.txt       # Production / dev dependencies
```

## Development workflow

### Branches

- `main` — production (only released tags merge here)
- `feature/*` / `chore/*` / `refactor/*` — work branches, opened against `main` via PR

There is no `develop` branch — the project uses a trunk-based flow with PRs targeting `main`.

```bash
git checkout main
git pull origin main
git checkout -b feature/short-description
# work + commit
git push -u origin feature/short-description
gh pr create --base main
```

### Commit messages

Use a conventional-commits style prefix when scope helps reviewers. Examples from this repo:

```
v2.0.0-beta.8: UI cleanup, EN localization, settings tabs
chore(repo): clean root, archive test docs, remove dead code, add ruff
refactor(config): rename transrec_migrated → legacy_migrated with backward-compat
docs(root): translate README, QUICKSTART, BACKLOG to English
```

If the commit covers a versioned milestone, end the message with `[tests: pass]` once the suite is green.

### Code quality

```bash
# Lint (ruff is the only linter we run in CI)
ruff check src/

# Auto-fix unused imports / f-string warnings
ruff check --fix src/

# Run all tests (374 unit tests, ~18 minutes; integration tests skipped without a recorder)
pytest tests/ -v

# Coverage report
pytest tests/ --cov=src --cov-report=html
open htmlcov/index.html
```

Configuration lives in `pyproject.toml` (`[tool.ruff]` and `[tool.pytest.ini_options]`).

## Testing strategy

### Unit tests

Each module under `src/` has a corresponding `tests/test_<module>.py`. Notable ones:

- `test_config.py` — configuration validation
- `test_transcriber.py` — transcription logic
- `test_file_monitor.py` — FSEvents handling
- `test_state_manager.py` — state persistence
- `test_bootstrap.py` — first-run + legacy migration
- `test_log_viewer.py` — log parser & filters
- `test_wizard.py` — first-run wizard flow

### Fixtures

Common fixtures live in `tests/conftest.py`. The most important one is **HOME isolation**: at module load, `conftest.py` redirects `Path.home()` to a temp directory (prefix `malinche-test-home-`) so tests never write to the developer's real `~/Library/Application Support/Malinche/`.

```python
@pytest.fixture
def mock_volume(tmp_path):
    """Create mock volume with audio files."""
    volume = tmp_path / "RECORDER"
    volume.mkdir()
    (volume / "recording.mp3").touch()
    return volume
```

### Mocking

```python
from unittest.mock import Mock, patch

@patch("src.transcriber.subprocess.run")
def test_transcribe(mock_run):
    mock_run.return_value.returncode = 0
    # ...
```

For details see **[TESTING-GUIDE.md](TESTING-GUIDE.md)**.

## Staging workflow

For stability, the transcriber stages files locally before processing:

1. **Discovery** — scan the external volume
2. **Staging** — copy to `~/Library/Application Support/Malinche/recordings/`
3. **Transcription** — process the local copy
4. **State update** — only update state when all files succeeded

Benefits:
- Stability — transcription continues even after the volume is unmounted
- Data safety — original files are untouched
- Error recovery — failed files stay in the queue

Test:
```bash
pytest tests/test_transcriber.py::test_stage_audio_file_success -v
```

## Debugging

### Logs

```bash
# Watch application logs
tail -f ~/Library/Application\ Support/Malinche/logs/malinche.log

# Filter for errors
tail -f ~/Library/Application\ Support/Malinche/logs/malinche.log | grep -i error
```

You can also open the native log viewer from the menu bar: **Open logs**. It shows newest-first, supports level filter and live tail.

### Common issues

**FSEvents not working**
```bash
pip list | grep MacFSEvents
ls -la /Volumes
```

**whisper.cpp not found** — open Settings → Maintenance → "Re-download dependencies".

**Import errors** — confirm the virtualenv is activated:
```bash
source venv/bin/activate
pip install -r requirements.txt
```

## Code style

### Python

- Follow PEP 8 (line length 100 in `pyproject.toml` `[tool.ruff]`)
- Use type hints for public functions
- Docstrings: short single-line for non-obvious functions; module docstring at top of file
- No comments narrating WHAT — only WHY when non-obvious

### Logging

Always use the project logger, never `print()`:

```python
from src.logger import logger

logger.info("Processing file %s", path)
logger.error("Failed: %s", error)
```

### Error handling

Validate at boundaries (user input, external APIs). Don't catch generic `Exception` unless you re-raise after logging.

```python
try:
    result = risky_operation()
except SpecificError as exc:
    logger.error("Operation failed: %s", exc)
    return None
```

## Security

- No credentials in code
- API keys via environment variables (`ANTHROPIC_API_KEY`) or the Settings window
- State file lives in `~/Library/Application Support/Malinche/`, never synced to cloud
- whisper.cpp runs locally
- PRO license verification cached locally for 7 days when offline

## Performance notes

- FSEvents is preferred to polling — zero CPU when idle
- Transcription is sequential (one file at a time)
- The state file prevents reprocessing
- Default transcription timeout: 1 hour

## Health checks

```bash
# Is the app running?
pgrep -f menu_app

# Recent activity?
tail -20 ~/Library/Application\ Support/Malinche/logs/malinche.log

# State file?
cat ~/Library/Application\ Support/Malinche/state.json | python -m json.tool
```

## Contributing

1. Fork the repository
2. Create a feature branch off `main`
3. Write tests alongside the change
4. Run `ruff check src/` and `pytest tests/`
5. Open a PR against `main` with a clear description and the test status

### Commit message format

```
<type>(<scope>): <subject>
```

Examples:
```
feat(transcriber): add Metal failure auto-detection
fix(file_monitor): handle FSEvents reordering during mount
docs(api): clarify license cache behavior
```

For larger milestone commits, the legacy `vX.Y.Z-tag: subject [tests: pass]` form is also accepted.

## Getting help

- [ARCHITECTURE.md](ARCHITECTURE.md) — system design
- [API.md](API.md) — module documentation
- [README.md](../README.md) — feature overview
- App logs at `~/Library/Application Support/Malinche/logs/malinche.log`
- Open an issue at <https://github.com/radektar/malinche/issues>

---

> **Related documents:**
> - [README.md](../README.md) — project overview
> - [ARCHITECTURE.md](ARCHITECTURE.md) — system architecture
> - [API.md](API.md) — module API reference
> - [TESTING-GUIDE.md](TESTING-GUIDE.md) — testing guide
> - [PUBLIC-DISTRIBUTION-PLAN.md](PUBLIC-DISTRIBUTION-PLAN.md) — v2.0.0 distribution plan
