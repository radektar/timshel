# API Documentation

> **Version:** v2.0.0-beta.18 (development)
>
> **Related documents:**
> - [README.md](../README.md) — project overview
> - [ARCHITECTURE.md](ARCHITECTURE.md) — system architecture
> - [DEVELOPMENT.md](DEVELOPMENT.md) — developer guide

Complete API reference for Malinche modules.

## Table of Contents

- [config.py](#configpy) — configuration
- [features.py](#featurespy) — feature flags (FREE/PRO/PRO_ORG)
- [license.py](#licensepy) — license management
- [logger.py](#loggerpy) — logging
- [file_monitor.py](#file_monitorpy) — FSEvents monitoring
- [transcriber.py](#transcriberpy) — transcription engine
- [markdown_generator.py](#markdown_generatorpy) — markdown generator
- [state_manager.py](#state_managerpy) — state management
- [menu_app.py](#menu_apppy) — menu bar app
- [app_core.py](#app_corepy) — core logic
- [summarizer.py](#summarizerpy) — AI summaries (PRO)
- [tagger.py](#taggerpy) — auto-tagging (PRO)
- [fingerprint.py](#fingerprintpy) — audio fingerprinting
- [vault_index.py](#vault_indexpy) — vault dedup index

---

## config.py (src/config/config.py)

Configuration management module.

**Note:** Module has been refactored - file is now located at `src/config/config.py` for better organization. Import remains unchanged: `from src.config import config`.

### Class: `Config`

Central configuration dataclass with all application settings.

#### Attributes

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `TRANSCRIBE_DIR` | `Path` | `~/Documents/Transcriptions` | Output directory for transcriptions |
| `LOCAL_RECORDINGS_DIR` | `Path` | `~/Library/Application Support/Malinche/recordings` | Staging directory for audio files |
| `LOG_DIR` | `Path` | `~/Library/Application Support/Malinche/logs` | Directory for log files |
| `STATE_FILE` | `Path` | `~/Library/Application Support/Malinche/state.json` | State file path |
| `LOG_FILE` | `Path` | `~/Library/Application Support/Malinche/logs/malinche.log` | Main log file path (rotating, 5×5 MB) |
| `WHISPER_CPP_PATH` | `Path` | `~/Library/Application Support/Malinche/bin/whisper-cli` | Path to whisper.cpp binary |
| `WHISPER_CPP_MODELS_DIR` | `Path` | `~/Library/Application Support/Malinche/models` | Models directory |
| `WHISPER_MODEL` | `str` | `"small"` | Model size (tiny/base/small/medium/large) |
| `WHISPER_LANGUAGE` | `str` | `"pl"` | Transcription language |
| `TRANSCRIPTION_TIMEOUT` | `int` | `3600` | Max transcription time (seconds) |
| `PERIODIC_CHECK_INTERVAL` | `int` | `30` | Fallback check interval (seconds) |
| `MOUNT_MONITOR_DELAY` | `int` | `2` | Wait after mount detection (seconds) |
| `AUDIO_EXTENSIONS` | `set` | `{".mp3", ".wav", ".m4a", ".ogg"}` | Supported audio formats |

#### Environment Variables

| Variable | Config Field | Description |
|----------|--------------|-------------|
| `MALINCHE_TRANSCRIBE_DIR` | `TRANSCRIBE_DIR` | Override output directory |
| `OLYMPUS_TRANSCRIBE_DIR` | `TRANSCRIBE_DIR` | Legacy alias for `MALINCHE_TRANSCRIBE_DIR` (still honored during migration) |
| `WHISPER_CPP_PATH` | `WHISPER_CPP_PATH` | Override whisper.cpp path |
| `ANTHROPIC_API_KEY` | — | API key for AI summaries (PRO) |

#### Methods

##### `ensure_directories() -> None`

Creates necessary directories if they don't exist.

```python
from src.config import config

config.ensure_directories()
```

### Global Instance

```python
from src.config import config

# Access configuration
print(config.TRANSCRIBE_DIR)
print(config.WHISPER_MODEL)
```

---

## features.py (src/config/features.py)

Module defining feature flags and subscription tiers.

### Enum: `FeatureTier`

| Value | Description |
|-------|-------------|
| `FREE` | Basic local transcription |
| `PRO` | Individual subscription (AI features + Diarization) |
| `PRO_ORG` | Organization subscription (Knowledge Base features) |

### Class: `FeatureFlags`

Immutable dataclass holding all available feature flags.

#### Methods

##### `for_tier(tier: FeatureTier) -> FeatureFlags` (static)

Returns flags enabled for specific tier.

##### `can_use(feature: str) -> bool`

Checks if specific feature is enabled.

---

## license.py (src/config/license.py)

License management and usage limits.

### Global singleton: `license_manager`

#### Methods

##### `get_current_tier() -> FeatureTier`

Returns active license tier (cached).

##### `get_features() -> FeatureFlags`

Returns flags for current tier.

##### `get_usage_limits() -> dict`

Returns monthly minute limits for current tier.

##### `activate_license(key: str) -> (bool, str)`

Attempts to activate license key via API.

---

## logger.py

Centralized logging configuration.

### Function: `setup_logger`

```python
def setup_logger(
    name: str = "transrec",
    level: int = logging.INFO,
    log_to_file: bool = True,
    log_to_console: bool = True,
) -> logging.Logger
```

Setup and return configured logger instance.

### Global Instance

```python
from src.logger import logger

logger.info("Application started")
logger.debug("Debug information")
logger.warning("Warning message")
logger.error("Error occurred")
```

---

## file_monitor.py

File system monitoring using FSEvents.

### Class: `FileMonitor`

Monitors `/Volumes` for external volume mount events.

#### Constructor

```python
def __init__(self, callback: Callable[[], None])
```

**Parameters:**
- `callback`: Function to call when audio-containing volume is detected

#### Methods

##### `start() -> None`

Start monitoring `/Volumes` for mount events.

```python
from src.file_monitor import FileMonitor

def on_volume_detected():
    print("Audio volume found!")

monitor = FileMonitor(callback=on_volume_detected)
monitor.start()
```

##### `stop() -> None`

Stop monitoring and clean up resources.

##### `_should_process_volume(volume_path: Path) -> bool` (v2.0.0)

Check if volume should be processed (has audio files, is external).

```python
# Internal logic
def _should_process_volume(self, volume_path: Path) -> bool:
    if self._is_internal_volume(volume_path):
        return False
    return self._has_audio_files(volume_path)
```

---

## transcriber.py

Core transcription engine.

### Dedup + versioning (v2)

- `compute_fingerprint(audio_file)` determines cross-device identity.
- `VaultIndex.lookup(fingerprint)` controls skip/retranscribe behavior.
- FREE tier: known fingerprint => skip.
- PRO tier: known fingerprint => create new version markdown (`.v2.md`, `.v3.md`).

---

## fingerprint.py

### Function: `compute_fingerprint(audio_file: Path) -> str`

Returns deterministic identifier:
- first 1MB bytes
- full file size
- recording datetime metadata (fallback mtime)

Format: `sha256:<hex>`.

---

## vault_index.py

### Class: `VaultIndex`

Main methods:
- `load()`
- `lookup(fingerprint)`
- `add(fingerprint, entry)`
- `add_version(fingerprint, version_info)`

Storage:
- `<TRANSCRIBE_DIR>/.malinche/index.json`
- `<TRANSCRIBE_DIR>/.malinche/index.lock`

### Class: `Transcriber`

Handles volume detection, file scanning, and transcription.

#### Constructor

```python
def __init__(self, on_status_change: Optional[Callable] = None)
```

**Parameters:**
- `on_status_change`: Optional callback for status updates (for UI)

#### Methods

##### `find_audio_files(volume_path: Path, since: datetime) -> List[Path]`

Find new audio files modified after given datetime.

```python
from datetime import datetime, timedelta
from pathlib import Path

volume = Path("/Volumes/RECORDER")
since = datetime.now() - timedelta(days=1)
files = transcriber.find_audio_files(volume, since)
```

##### `_stage_audio_file(audio_file: Path) -> Optional[Path]`

Copy audio file to local staging directory.

```python
staged_path = transcriber._stage_audio_file(audio_file)
if staged_path:
    # Process staged file
    pass
```

##### `transcribe_file(audio_file: Path) -> bool`

Transcribe a single audio file using whisper.cpp.

```python
success = transcriber.transcribe_file(staged_file)
```

##### `process_volume(volume_path: Path) -> None`

Main workflow: scan volume, stage files, transcribe.

```python
transcriber.process_volume(Path("/Volumes/RECORDER"))
```

---

## markdown_generator.py

Markdown file generator with YAML frontmatter.

### Class: `MarkdownGenerator`

#### Methods

##### `generate(transcription: str, metadata: dict) -> str`

Generate markdown content from transcription.

```python
from src.markdown_generator import MarkdownGenerator

generator = MarkdownGenerator()
content = generator.generate(
    transcription="Text content...",
    metadata={
        "source": "recording.mp3",
        "date": "2025-01-15",
        "duration": "5:32",
        "tags": ["meeting", "notes"]
    }
)
```

**Output:**
```markdown
---
source: recording.mp3
date: 2025-01-15
duration: 5:32
tags:
  - meeting
  - notes
---

# Transcript

Text content...
```

---

## state_manager.py

State persistence management.

### Class: `StateManager`

#### Methods

##### `get_last_sync_time(volume_name: str) -> datetime`

Get timestamp of last synchronization for volume.

```python
from src.state_manager import StateManager

state = StateManager()
last_sync = state.get_last_sync_time("LS-P1")
```

##### `save_sync_time(volume_name: str) -> None`

Save current time as last sync timestamp.

##### `reset_state(volume_name: str, since: Optional[datetime] = None) -> None`

Reset state for volume (optionally to specific date).

```python
from datetime import datetime

state.reset_state("LS-P1", since=datetime(2025, 1, 1))
```

##### `get_processed_files(volume_name: str) -> List[str]`

Get list of already processed files for volume.

---

## menu_app.py

macOS menu bar application.

### Class: `MalincheMenuApp`

rumps-based menu bar application.

#### Constructor

```python
def __init__(self)
```

Creates menu bar app with:
- Status indicator
- Open logs action
- Reset memory action
- Settings action
- Quit action

#### Usage

```bash
python -m src.menu_app
```

---

## app_core.py

Core application logic.

### Class: `AppState`

Thread-safe state container.

```python
class AppState(Enum):
    IDLE = "idle"
    SCANNING = "scanning"
    TRANSCRIBING = "transcribing"
    ERROR = "error"
```

### Class: `MalincheTranscriber`

Main application coordinator.

#### Methods

##### `start() -> None`

Start the transcriber daemon.

```python
from src.app_core import MalincheTranscriber

app = MalincheTranscriber()
app.start()
```

##### `stop() -> None`

Stop the daemon and cleanup.

##### `get_status() -> dict`

Get current status for UI.

```python
status = app.get_status()
# {
#     "state": "idle",
#     "current_file": None,
#     "processed_count": 5,
#     "error": None
# }
```

---

## summarizer.py (src/summarizer.py)

AI-powered summaries (PRO feature).

### Function: `get_summarizer() -> Optional[BaseSummarizer]`

Factory function returning summarizer instance. 
**PRO Check:** Returns `None` if license doesn't support `ai_summaries`.

---

## tagger.py (src/tagger.py)

Auto-tagging system (PRO feature).

### Function: `get_tagger() -> Optional[BaseTagger]`

Factory function returning tagger instance.
**PRO Check:** Returns `None` if license doesn't support `ai_smart_tags`.

---

## Usage Examples

### Basic Transcription

```python
from src.transcriber import Transcriber
from pathlib import Path

transcriber = Transcriber()
transcriber.process_volume(Path("/Volumes/RECORDER"))
```

### Custom Configuration

```python
from src.config import config
from pathlib import Path

# Override paths
config.TRANSCRIBE_DIR = Path.home() / "My Transcriptions"
config.WHISPER_MODEL = "medium"

config.ensure_directories()
```

### With Status Callbacks

```python
from src.transcriber import Transcriber

def on_status(state, current_file=None):
    print(f"Status: {state}, File: {current_file}")

transcriber = Transcriber(on_status_change=on_status)
transcriber.process_volume(volume_path)
```

---

## Type Hints Reference

```python
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Callable, Dict
from enum import Enum

# Common types
PathLike = Path
Callback = Callable[[], None]
StatusCallback = Callable[[str, Optional[str]], None]
AudioFiles = List[Path]
TimeStamp = datetime
```

---

## Constants

```python
# Timeouts
DEFAULT_TIMEOUT = 3600        # 1 hour
DEFAULT_CHECK_INTERVAL = 30   # 30 seconds
DEFAULT_MOUNT_DELAY = 2       # 2 seconds

# Audio formats
SUPPORTED_FORMATS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}

# State
OFFLINE_LICENSE_CACHE_DAYS = 7
```

---

## Error Handling

All modules use comprehensive error handling:

```python
try:
    result = operation()
except SpecificError as e:
    logger.error(f"Specific error: {e}")
    # Handle specifically
except Exception as e:
    logger.error(f"Unexpected error: {e}", exc_info=True)
    # Handle generally
```

## Threading Safety

- `AppState` uses thread-safe operations
- `StateManager` uses file locking
- All UI callbacks are thread-safe
- Daemon threads for background operations

---

> **Related documents:**
> - [README.md](../README.md) — project overview
> - [ARCHITECTURE.md](ARCHITECTURE.md) — system architecture
> - [DEVELOPMENT.md](DEVELOPMENT.md) — developer guide
> - [PUBLIC-DISTRIBUTION-PLAN.md](PUBLIC-DISTRIBUTION-PLAN.md) — v2.0.0 distribution plan
