# System Architecture

> **Version:** v2.0.0-beta.18 (development)
>
> **Related documents:**
> - [README.md](../README.md) — project overview
> - [API.md](API.md) — module API reference
> - [DEVELOPMENT.md](DEVELOPMENT.md) — developer guide
> - [PUBLIC-DISTRIBUTION-PLAN.md](PUBLIC-DISTRIBUTION-PLAN.md) — distribution plan

## Overview

Malinche is a system that automatically transcribes audio files from any external volume (USB recorder, SD card, thumbdrive).

```
┌─────────────────────────────────────────────────────────────────┐
│                        macOS System                              │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  Menu Bar App (src/menu_app.py)                            │ │
│  │  - rumps-based native macOS interface                      │ │
│  │  - Status display & user actions                           │ │
│  └───────────────────┬────────────────────────────────────────┘ │
│                      │                                           │
│  ┌───────────────────┴────────────────────────────────────────┐ │
│  │  App Core (src/app_core.py)                                │ │
│  │  - Thread-safe state management                            │ │
│  │  - Orchestrates monitoring & transcription                 │ │
│  └───────────────────┬────────────────────────────────────────┘ │
│                      │                                           │
│  ┌───────────────────┴────────────────────────────────────────┐ │
│  │  FSEvents Monitor (src/file_monitor.py)                    │ │
│  │  - Watches /Volumes for mount events                       │ │
│  │  - Detects ANY external volume with audio files            │ │
│  └───────────────────┬────────────────────────────────────────┘ │
│                      │ (onChange callback)                       │
│  ┌───────────────────┴────────────────────────────────────────┐ │
│  │  Transcriber Engine (src/transcriber.py)                   │ │
│  │  - Scans for new audio files                               │ │
│  │  - Stages files locally before processing                  │ │
│  │  - Manages transcription queue                             │ │
│  └───────────────────┬────────────────────────────────────────┘ │
│                      │                                           │
│  ┌───────────────────┴────────────────────────────────────────┐ │
│  │  whisper.cpp Engine                                        │ │
│  │  - Native binary with Core ML acceleration                 │ │
│  │  - Runs as subprocess with timeout protection              │ │
│  └───────────────────┬────────────────────────────────────────┘ │
│                      │                                           │
│  ┌───────────────────┴────────────────────────────────────────┐ │
│  │  Markdown Generator (src/markdown_generator.py)            │ │
│  │  - Creates .md files with YAML frontmatter                 │ │
│  │  - Formats transcription output                            │ │
│  └───────────────────┬────────────────────────────────────────┘ │
│                      │                                           │
│                      ▼                                           │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  Output: TRANSCRIBE_DIR (configurable)                     │ │
│  │  - YYYY-MM-DD_Title.md files                               │ │
│  │  - Ready for Obsidian / other markdown editors             │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  State Management (src/state_manager.py)                   │ │
│  │  - ~/Library/Application Support/Malinche/state.json       │ │
│  │  - Tracks processed files per volume                       │ │
│  │  - Prevents duplicate transcriptions                       │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  Logging                                                   │ │
│  │  ~/Library/Application Support/Malinche/logs/malinche.log  │ │
│  │  - Rotating handler (5×5 MB)                               │ │
│  │  - All events logged with timestamps                       │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Component breakdown

### 1. Menu Bar App (`src/menu_app.py`)

**Responsibility:** macOS menu bar UI.

```python
MenuBarApp (rumps.App)
├── title              # Status icon
├── menu               # Dropdown items
├── status_item()      # Current status display
├── open_logs()        # Open native log viewer window
├── retranscribe_*()   # Submenu for re-running transcription
├── settings()         # Open settings window
└── quit()             # Clean shutdown
```

**Tech:** `rumps` (Python wrapper around AppKit `NSStatusBar`).

### 2. App Core (`src/app_core.py`)

**Responsibility:** Coordinate all components.

```python
MalincheCore
├── state: AppState           # Thread-safe state container
├── transcriber: Transcriber  # Transcription engine
├── monitor: FileMonitor      # FSEvents monitor
├── start()                   # Start all components
├── stop()                    # Clean shutdown
└── get_status()              # Current status for UI
```

**AppState values:**
- `IDLE` — waiting for a volume
- `SCANNING` — scanning files on a volume
- `TRANSCRIBING` — transcription in progress
- `ERROR` — error state

### 3. FSEvents Monitor (`src/file_monitor.py`)

**Responsibility:** Detect external volume mounts.

```python
FileMonitor
├── start()                      # Begin monitoring /Volumes
├── stop()                       # Stop monitoring
├── on_change()                  # Callback on volume change
└── _should_process_volume()     # Check if volume has audio
```

**Mechanism (v2.0.0):**
- Watches `/Volumes` via FSEvents
- Detects ANY new external volume
- Checks whether it contains audio files
- Waits 2 seconds for full mount
- Triggers callback when audio is found

**Ignored:**
- `.Spotlight-V100`, `.fseventsd`, `.Trashes`
- Internal system volumes

### 4. Transcriber Engine (`src/transcriber.py`)

**Responsibility:** Run the full transcription workflow.

```python
Transcriber
├── find_audio_files()        # Scan volume for audio
├── _stage_audio_file()       # Copy to local staging
├── transcribe_file()         # Run whisper.cpp
├── process_volume()          # Main workflow
└── on_status_change          # Callback for UI updates
```

**Staging workflow:**
1. Copy file from external volume to `~/Library/Application Support/Malinche/recordings/`
2. Transcribe the local copy (so the volume can be unplugged safely)
3. Generate markdown output
4. Update state

### 5. Markdown Generator (`src/markdown_generator.py`)

**Responsibility:** Produce `.md` files.

```python
MarkdownGenerator
├── generate()                # Create markdown file
├── _format_frontmatter()     # YAML frontmatter
└── _format_content()         # Transcription content
```

**Output format:**
```markdown
---
source: recording.mp3
date: 2026-05-05
duration: 5:32
tags: []
---

# Transcript

[content here]
```

### 6. State Manager (`src/state_manager.py`)

Persists processed-file state per volume.

### 6.1. Multi-device Vault Index (`src/vault_index.py`, `src/fingerprint.py`)

- Audio fingerprint (`sha256`) computed from: first 1 MB + size + datetime metadata
- Central index inside the vault: `<TRANSCRIBE_DIR>/.malinche/index.json`
- `VaultIndex` uses `fcntl.flock` + atomic write (`.tmp` → `os.replace`)
- Markdown frontmatter includes fingerprint, model, language, version, hostname
- FREE: deduplicate by fingerprint (skip)
- PRO: re-transcription creates versioned files (`.v2.md`, `.v3.md`)

### 7. License Manager (`src/config/license.py`)

**Responsibility:** License verification and PRO feature access.

```python
LicenseManager
├── get_current_tier()        # FREE / PRO / PRO_ORG
├── get_features()            # Returns FeatureFlags
├── activate_license()        # Activate license key
└── get_usage_limits()        # Minute limits (PRO Individual)
```

---

## v2.0.0 architecture changes

### Universal volume detection

**Before (v1.x):**
```python
RECORDER_NAMES = ["LS-P1", "OLYMPUS"]
if volume_name in RECORDER_NAMES:
    process()
```

**After (v2.0.0):**
```python
def _should_process_volume(volume_path: Path) -> bool:
    if _is_internal_volume(volume_path):
        return False
    return _has_audio_files(volume_path)
```

### Feature flags (Freemium)

**Structure:**
```python
from src.config.features import FeatureTier, FeatureFlags

# Tiers: FREE, PRO (Individual), PRO_ORG (Organization)
# Flags: ai_summaries, ai_smart_tags, speaker_diarization, domain_lexicon, knowledge_base
```

**Usage:**
```python
from src.config.license import license_manager

features = license_manager.get_features()
if features.ai_summaries:
    # PRO-only path
```

### PRO features architecture (v2.1.0+)

The Malinche client integrates with a backend service for features that require large AI models (Claude) and license/usage management.

1. **PRO Individual (subscription):** AI summaries, AI tags, diarization (with monthly minute limits).
2. **PRO Organization (subscription):** Shared speaker database, domain lexicon, knowledge base.

```
┌─────────────────────────────────────────────────────────────────┐
│                     PRO Features (v2.1.0)                        │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  License Manager (src/config/license.py)                   │ │
│  │  - Verify license against backend                          │ │
│  │  - Cache locally (7 days offline)                          │ │
│  │  - Feature gate checking                                   │ │
│  └───────────────────┬────────────────────────────────────────┘ │
│                      │                                           │
│  ┌───────────────────┴────────────────────────────────────────┐ │
│  │  Summarizer (src/summarizer.py)                            │ │
│  │  - Generate AI summaries via backend API                   │ │
│  │  - Feature flag: ai_summaries                              │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  Tagger (src/tagger.py)                                    │ │
│  │  - Auto-generate tags via backend API                      │ │
│  │  - Feature flag: ai_smart_tags                             │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  malinche-backend (private repo)                 │
│                                                                  │
│  FastAPI Server                                                  │
│  ├── POST /api/v1/summarize      # AI summaries                  │
│  ├── POST /api/v1/tags           # Auto-tagging                  │
│  ├── POST /api/v1/license/verify # License check                 │
│  └── POST /api/v1/license/activate # Activation                  │
└─────────────────────────────────────────────────────────────────┘
```

## Configuration (`src/config/config.py`)

Central configuration. Environment variables are honored only during legacy migration.

```python
@dataclass
class Config:
    # Paths
    TRANSCRIBE_DIR: Path          # Output directory
    LOCAL_RECORDINGS_DIR: Path    # Staging directory
    STATE_FILE: Path              # State persistence
    LOG_FILE: Path                # Log file

    # whisper.cpp
    WHISPER_CPP_PATH: Path        # Binary path
    WHISPER_CPP_MODELS_DIR: Path  # Models directory
    WHISPER_MODEL: str            # Model size (tiny/base/small/medium/large)
    WHISPER_LANGUAGE: str         # Transcription language

    # Timeouts
    TRANSCRIPTION_TIMEOUT: int    # Max transcription time (seconds)
    MOUNT_MONITOR_DELAY: int      # Wait after mount (seconds)

    # Audio
    AUDIO_EXTENSIONS: set         # Supported formats
```

**Notes:**
- Migration runs once during app startup (in `src/bootstrap.py`)
- `Config` performs no side effects on initialization
- `Transcriber` uses dependency injection for config (testability)

For details see **[API.md](API.md)**.

## Error handling

### Graceful degradation

1. **whisper.cpp not found** → first-run wizard downloads it
2. **Transcription timeout** → log error, skip the file, continue
3. **Corrupted state file** → reset to 7 days ago
4. **FSEvents fails** → fall back to periodic checking
5. **Invalid PRO license** → continue with FREE features only

### Retry strategy

- Each volume mount = a new attempt for non-transcribed files
- `last_sync` is updated only when ALL files succeed
- Failed files remain in the queue for the next sync

## Performance

### Resource usage
- **RAM:** ~50–100 MB (idle) + whisper.cpp (~500 MB–2 GB during transcription)
- **CPU:** minimal at idle, ~80–100% during transcription
- **Disk:** staging + output (temporary + permanent)

### Optimizations
- FSEvents = zero polling overhead
- Core ML acceleration on Apple Silicon
- Sequential processing (one file at a time)
- State file prevents reprocessing

## Security

- No credentials in code
- API keys via environment variables only
- Local state file (no cloud sync in FREE)
- whisper.cpp runs locally (no cloud)
- License verification cached locally (7 days offline)

---

> **Related documents:**
> - [README.md](../README.md) — project overview
> - [API.md](API.md) — module API reference
> - [DEVELOPMENT.md](DEVELOPMENT.md) — developer guide
> - [PUBLIC-DISTRIBUTION-PLAN.md](PUBLIC-DISTRIBUTION-PLAN.md) — v2.0.0 distribution plan
