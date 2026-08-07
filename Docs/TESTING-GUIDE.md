# Testing Guide

> **Version:** v2.0.0-beta.18 (development)
>
> **Related documents:**
> - [README.md](../README.md) — project overview
> - [DEVELOPMENT.md](DEVELOPMENT.md) — developer guide
> - [API.md](API.md) — module API reference
> - [PUBLIC-DISTRIBUTION-PLAN.md](PUBLIC-DISTRIBUTION-PLAN.md) — testing strategy per phase

Comprehensive guide for testing Malinche.

## Test types

| Type | Tooling | When to run |
|---|---|---|
| **Unit tests** | pytest | Every commit |
| **Integration tests** | pytest + fixtures | Before merging to main |
| **E2E tests** | Manual / shell scripts in `tests/integration/` | Before a release |
| **Beta testing** | External users via DMG distribution | Before a public release |

The full unit suite (~374 tests) takes ~18 minutes locally. Integration tests require a connected recorder/SD card and are skipped in headless CI.

## Setup

```bash
cd ~/CODEing/malinche
source venv/bin/activate
pip install -r requirements-dev.txt
```

## Running tests

```bash
# All unit tests
pytest tests/ -v

# Specific file
pytest tests/test_config.py -v

# Specific function
pytest tests/test_transcriber.py::test_find_recorder_found -v

# With coverage
pytest tests/ --cov=src --cov-report=html
open htmlcov/index.html

# Exclude integration tests (default for headless)
pytest tests/ --ignore=tests/integration -v
```

## Module-level test files

| Module | Test file |
|---|---|
| `src/config/config.py` | `tests/test_config.py` |
| `src/config/settings.py` | indirectly via `tests/test_bootstrap.py` |
| `src/config/license.py` | `tests/test_license.py` |
| `src/config/features.py` | `tests/test_features.py` |
| `src/transcriber.py` | `tests/test_transcriber.py` (+ postprocess, finalize, etc.) |
| `src/file_monitor.py` | `tests/test_file_monitor.py` |
| `src/state_manager.py` | `tests/test_state_manager.py` |
| `src/markdown_generator.py` | `tests/test_markdown_generator.py` |
| `src/menu_app.py` | `tests/test_menu_app*.py` |
| `src/setup/wizard.py` | `tests/test_wizard.py` |
| `src/setup/downloader.py` | `tests/test_downloader.py` |
| `src/bootstrap.py` | `tests/test_bootstrap.py` |
| `src/vault_index.py` | `tests/test_vault_index*.py` |
| `src/fingerprint.py` | `tests/test_fingerprint.py` |
| `src/ui/log_viewer.py` | `tests/test_log_viewer.py` |
| `src/ui/dialogs.py` | `tests/test_ui_dialogs.py` |

## Fixtures

The most important fixture lives in `tests/conftest.py` and runs at module load time:

- **HOME isolation** — `Path.home()` is redirected to a temp directory (prefix `malinche-test-home-`). All tests get a fake `~` so they never write to the developer's real `~/Library/Application Support/Malinche/`.
- **State guard** — a session-scoped autouse fixture asserts that legacy paths (`~/.olympus_transcriber_state.json`, `~/Library/Logs/olympus_transcriber.log`, etc.) are unchanged at session teardown.

Common per-test fixtures:

```python
@pytest.fixture
def mock_volume(tmp_path):
    """Create a mock external volume with audio files."""
    volume = tmp_path / "RECORDER"
    volume.mkdir()
    (volume / "recording.mp3").touch()
    return volume
```

## Mocking patterns

```python
from unittest.mock import Mock, patch

@patch("src.transcriber.subprocess.run")
def test_transcribe_calls_whisper(mock_run):
    mock_run.return_value.returncode = 0
    transcriber.transcribe_file(audio_file)
    mock_run.assert_called_once()
```

For `LicenseManager` interactions:

```python
@patch("src.config.license.license_manager.get_current_tier")
def test_pro_feature(mock_tier):
    mock_tier.return_value = FeatureTier.PRO
    # PRO-only path
```

## Integration tests

Live in `tests/integration/`. These are **not** part of the standard `pytest` run by default and require a connected recorder or SD card.

| Script | What it tests |
|---|---|
| `test_staging_e2e.sh` | Full E2E: connect recorder → wait → transcribe → verify markdown in vault |
| `test_staging_e2e_wait.sh` | Same, but waits for the recorder to be plugged in |
| `test_m2_no_internet.sh` | Verifies offline behavior (no internet) |
| `test_download_automated.py` | Automates the dependency download flow on a clean install |
| `test_m5_corrupted_file.py` | Detects and recovers from a corrupted whisper-cli binary |

Run with:
```bash
bash tests/integration/test_staging_e2e_wait.sh
python tests/integration/test_download_automated.py
```

## Manual test scenarios

For manual smoke testing before a release:

1. **Fresh install:** wipe `~/Library/Application Support/Malinche/`, mount the latest DMG, drag-and-drop into `/Applications`, run the wizard end to end.
2. **Recorder detection:** plug in an Olympus LS-P1 (or equivalent) and confirm the menu bar status switches to "Scanning recorder…" then "Processing: …".
3. **Markdown output:** verify that transcripts land in the configured output folder, with valid YAML frontmatter and the "Transcript" section.
4. **Settings:** open Settings → switch model to `medium`, change the output folder, save, restart, confirm changes persist.
5. **Log viewer:** open from the menu bar, confirm newest-first order, level filter, search, and live tail.
6. **PRO gate:** confirm that AI summaries don't run without an API key, and run with a valid Anthropic key.
7. **Reset memory:** verify that "Reset memory" lets you pick 7d / 30d / custom and re-scans accordingly.
8. **Quit cleanly:** confirm the menu bar item disappears, no zombie process (`pgrep -f menu_app`), no stuck lock file.

Detailed historical manual checklists live in [Docs/testing-archive/](testing-archive/).

## Linting

```bash
# Ruff is the only linter we run in CI
ruff check src/

# Auto-fix unused imports / f-string warnings (idempotent)
ruff check --fix src/
```

Configuration is in `pyproject.toml` `[tool.ruff]`.

## Pre-release checklist

Before tagging a release:

- [ ] `pytest tests/ -q` — all tests pass (374+, no failures)
- [ ] `ruff check src/` — no warnings
- [ ] `make release` — DMG builds cleanly
- [ ] Manual smoke test (see above) on a fresh user account
- [ ] CHANGELOG.md has an entry for the new version
- [ ] `APP_VERSION` consistent across `src/ui/constants.py` and `setup_app.py` (`tests/test_versions_sync.py` enforces this)

---

> **Related documents:**
> - [README.md](../README.md) — project overview
> - [DEVELOPMENT.md](DEVELOPMENT.md) — developer guide
> - [API.md](API.md) — module API reference
> - [PUBLIC-DISTRIBUTION-PLAN.md](PUBLIC-DISTRIBUTION-PLAN.md) — testing strategy per phase
