"""Configuration module for Timshel (backward compatible wrapper)."""

import os
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.config.config import Config

from src.config.settings import UserSettings
from src.config.defaults import defaults


@dataclass
class Config:
    """Backward-compatible configuration wrapper for Timshel.

    This class maintains the old Config interface while using UserSettings
    internally. This allows existing code to continue working while we
    transition to the new configuration system.

    Attributes:
        RECORDER_NAMES: List of possible volume names (from watched_volumes or defaults)
        TRANSCRIBE_DIR: Directory where transcriptions are saved (from output_dir)
        STATE_FILE: JSON file tracking last sync time (legacy)
        LOG_DIR: Directory for application logs
        LOG_FILE: Path to main log file
        WHISPER_MODEL: Whisper model size (from whisper_model)
        WHISPER_LANGUAGE: Language code for transcription (from language)
        WHISPER_DEVICE: Device to use (cpu or auto-detect)
        WHISPER_CPP_PATH: Path to whisper.cpp binary executable
        WHISPER_CPP_MODELS_DIR: Directory containing whisper.cpp models
        TRANSCRIPTION_TIMEOUT: Maximum time allowed for transcription (60 minutes)
        PERIODIC_CHECK_INTERVAL: Fallback check interval (seconds)
        MOUNT_MONITOR_DELAY: Wait time after mount detection (seconds)
        AUDIO_EXTENSIONS: Supported audio file formats
        ENABLE_SUMMARIZATION: Whether to generate summaries using LLM (from enable_ai_summaries)
        LLM_PROVIDER: LLM provider name (claude, openai, ollama)
        LLM_MODEL: Model name for the selected provider
        LLM_API_KEY: API key for LLM provider (from ai_api_key)
        SUMMARY_MAX_WORDS: Maximum words in generated summary
        TITLE_MAX_LENGTH: Maximum length for generated title (characters)
        DELETE_TEMP_TXT: Whether to delete temporary TXT files after MD creation
        LOCAL_RECORDINGS_DIR: Local staging directory for copied recorder files
    """

    # Recorder detection
    RECORDER_NAMES: List[str] = None

    # Directories
    TRANSCRIBE_DIR: Path = None
    LOG_DIR: Path = None
    LOCAL_RECORDINGS_DIR: Path = None  # Local staging area for recorder files
    PROCESS_LOCK_FILE: Path = None  # Lock file preventing overlapping runs

    # Files
    STATE_FILE: Path = None
    LOG_FILE: Path = None
    DIGEST_LOCK_FILE: Path = None  # Lock serialising connection-synthesis digest runs
    CONNECTIONS_STATE_FILE: Path = None  # digest scheduler state (own file)

    # Whisper configuration
    WHISPER_MODEL: str = (
        "small"  # Balanced speed/accuracy: tiny, base, small, medium, large
    )
    WHISPER_LANGUAGE: str = "pl"  # Polish default, can be "en" or None for auto-detect
    WHISPER_DEVICE: str = "cpu"  # Use CPU (whisper.cpp handles Core ML acceleration)
    WHISPER_CPP_PATH: Path = None  # Path to whisper.cpp binary
    WHISPER_CPP_MODELS_DIR: Path = None  # Path to whisper.cpp models directory
    FFMPEG_PATH: Path = None  # Path to ffmpeg binary (Faza 2)

    # Timeouts and intervals (seconds)
    TRANSCRIPTION_TIMEOUT: int = 3600  # 60 minutes (increased from 30)
    PERIODIC_CHECK_INTERVAL: int = 30  # 30 seconds
    MOUNT_MONITOR_DELAY: int = 1  # 1 second

    # Audio formats
    AUDIO_EXTENSIONS: set = None

    # LLM/Summarization configuration
    ENABLE_SUMMARIZATION: bool = True
    LLM_PROVIDER: str = "claude"
    LLM_MODEL: str = "claude-haiku-4-5-20251001"
    LLM_API_KEY: Optional[str] = None
    SUMMARY_MAX_WORDS: int = 200
    TITLE_MAX_LENGTH: int = 60
    DELETE_TEMP_TXT: bool = True

    # Tagging configuration
    ENABLE_LLM_TAGGING: bool = True
    MAX_TAGS_PER_NOTE: int = 6
    MAX_EXISTING_TAGS_IN_PROMPT: int = 150
    MAX_TAGGER_SUMMARY_CHARS: int = 3000
    MAX_TAGGER_TRANSCRIPT_CHARS: int = 1500

    # Personal vocabulary (canonical terms harvested from the vault; grows
    # with use — see src/vocabulary.py). Feeds whisper-cli --prompt and the
    # summarizer's KNOWN TERMS block so proper names survive transcription.
    VOCABULARY_ENABLED: bool = True
    # Feed the glossary to whisper-cli as an initial prompt (separately
    # switchable: it biases *decoding*, the riskier of the two levels).
    WHISPER_GLOSSARY_ENABLED: bool = True
    # Caps: prompt-block terms for the summarizer / chars for whisper's
    # initial prompt (whisper reads ~224 tokens of prompt; ~600 chars of
    # Polish names stays safely under).
    VOCABULARY_MAX_PROMPT_TERMS: int = 60
    VOCABULARY_WHISPER_MAX_CHARS: int = 600
    # A bare capitalised-run entity must appear in at least this many notes
    # before it counts as "confirmed" (wikilinked/curated terms skip this).
    VOCABULARY_MIN_ENTITY_NOTES: int = 2

    # Connection synthesis ("Zestawianie") configuration
    ENABLE_CONNECTION_SYNTHESIS: bool = True
    # Connected LLM for the Insights action handoff (claude | chatgpt).
    # The window's primary CTA reads "Kontynuuj w <active>" (ADR-004).
    LLM_HANDOFF_TOOL: str = "claude"
    # Per-stage model overrides (None -> fall back to LLM_MODEL via model_router).
    LLM_MODEL_SUMMARY: Optional[str] = None
    LLM_MODEL_TAGS: Optional[str] = None
    LLM_MODEL_SYNTHESIS: Optional[str] = None
    LLM_MODEL_JUDGE: Optional[str] = None
    # Results-synthesis: the one LLM in the recall (pull) path — the explicit
    # "synthesize these results" escalation. Independently swappable per the plan.
    LLM_MODEL_RESULTS_SYNTHESIS: Optional[str] = None
    # Verdict pass (magic-insights prototype): verifies proposed connections
    # against fuller note text before the digest is written. Independently
    # swappable so the cascade can run synthesis and verdict on different models.
    LLM_MODEL_VERDICT: Optional[str] = None
    # Candidate-assembly + synthesis budgets (bound the prompt regardless of corpus size).
    MAX_SYNTHESIS_NOTE_CHARS: int = 1200
    MAX_SYNTHESIS_NOTES: int = 25
    MAX_SYNTHESIS_PROMPT_CHARS: int = 30000
    # 4096 (was 2048): the verbose legacy prompt truncated mid tool-call at 2048
    # and returned zero connections. The production prompt is terse and fits, but
    # the headroom keeps a multi-connection digest from ever being cut off.
    SYNTHESIS_MAX_TOKENS: int = (
        8192  # headroom for evidence + fuller directions (ADR-004)
    )
    SYNTHESIS_TIMEOUT: float = 60.0
    # Cross-topic "bridge" notes injected per digest (distance channel): notes far
    # from the recent window in topic but joined by a shared rare token. 0 = pure
    # similarity (legacy). Validated at 4 in the distance experiment.
    SYNTHESIS_BRIDGE_COUNT: int = 4
    # Entity distance-channel (Challenge #3): notes joined to the recent window
    # by a shared named entity (person/project/org) even after topic vocabulary
    # drifts — the channel that catches contradictions BM25/tags miss. 0 = OFF,
    # the production baseline: this channel is UNVALIDATED (that is what H3
    # measures), so it must not silently change every user's digest. The
    # magic-insights prototype turns it on explicitly (magic_digest.py,
    # blind_cascade_test.py); recall_eval.py sweeps it as a variable.
    SYNTHESIS_ENTITY_COUNT: int = 0
    # Dense semantic channel: KNN over the vault's local embedding index (the
    # recall engine — zero API cost). 0 = OFF, production baseline, same rule
    # as the entity channel: unvalidated until H3 passes. Prototype tools turn
    # it on explicitly.
    SYNTHESIS_DENSE_COUNT: int = 0
    # Graph channel: Personalized PageRank over the note-term bridge graph
    # (Swanson ABC / HippoRAG-lite — the LBD mechanism for anti-similar pairs).
    # 0 = OFF (unvalidated until H3). Prototype tools turn it on.
    SYNTHESIS_GRAPH_COUNT: int = 0
    # Stance-flip channel: older notes sharing an anchor with the window but of
    # opposite polarity — contradiction candidates. 0 = OFF (unvalidated).
    SYNTHESIS_STANCE_COUNT: int = 0
    # Digest scheduling: weekly calm container + pattern-triggered escalation.
    CONNECTIONS_DIGEST_INTERVAL_DAYS: int = 7
    CONNECTIONS_PATTERN_TRIGGER_MIN: int = 6
    CONNECTIONS_MIN_GAP_DAYS: int = 2
    # Sub-folder (inside TRANSCRIBE_DIR) where digest notes are written.
    DIGEST_DIR_NAME: str = "Timshel Digests"
    # Hidden per-vault sidecar dir name (metrics/signal/vocabulary/dismissals).
    SIDECAR_DIR_NAME: str = ".timshel"
    # Magic-insights prototype instrumentation. Each digest appends a cost +
    # coverage record to {vault}/.timshel/metrics.jsonl (H1/H4 evidence base).
    # OFF by default: a normal user's daemon should not write a telemetry file
    # (with private note basenames) into their vault. The prototype dogfood
    # (magic_digest.py) turns it on for the measured runs.
    INSIGHT_METRICS_ENABLED: bool = False
    # Verdict pass: verify proposed connections against fuller note text and
    # drop the ones that do not survive. Off = baseline digest, byte-identical.
    VERDICT_ENABLED: bool = False
    # Fuller-text budget per linked note in the verdict prompt.
    VERDICT_MAX_NOTE_CHARS: int = 4000
    # Prototype tester mode: a LABEL only, written into each metrics row so a
    # dogfood run can be told apart from a normal one. It does NOT itself route
    # models, force runs, or toggle metrics — magic_digest.py sets those knobs
    # (LLM_MODEL_*, force=True, VERDICT_ENABLED, INSIGHT_METRICS_ENABLED)
    # explicitly alongside it. Off in normal operation.
    PROTOTYPE_TESTER_MODE: bool = False

    # Markdown template
    MD_TEMPLATE: str = """---
title: "{title}"
date: {date}
recording_date: {recording_date}
source: {source_file}
fingerprint: {fingerprint}
source_volume: {source_volume}
version: {version}
transcribed_on: {hostname}
model: {model}
language: {language}{previous_version_line}{provenance_line}
duration: {duration}
tags: [{tags}]
---

{summary}

## Transkrypcja

{transcript}
"""

    def __post_init__(self):
        """Initialize default values after dataclass initialization.

        This method loads UserSettings and maps values to the old Config interface
        for backward compatibility.

        Note: Migration should be performed explicitly before creating Config instances
        (e.g., in main() or app startup). This ensures deterministic behavior and
        prevents side effects during initialization.
        """
        # Load user settings (migration should have been performed already)
        # This makes Config deterministic and testable
        self._user_settings = UserSettings.load()

        # Map UserSettings to old Config attributes.
        #
        # ``RECORDER_NAMES`` is a legacy field that previously forced detection
        # to a hardcoded list even in "auto" mode - which caused recorders with
        # non-matching volume names to be ignored. Discovery now lives in
        # ``Transcriber.find_recorders`` / ``volume_utils`` and honours the
        # user's ``watch_mode``. This field is kept populated only when the
        # user explicitly selected "specific" mode, so callers that still rely
        # on it have a meaningful whitelist; otherwise it stays empty.
        if self.RECORDER_NAMES is None:
            if (
                self._user_settings.watch_mode == "specific"
                and self._user_settings.watched_volumes
            ):
                self.RECORDER_NAMES = list(self._user_settings.watched_volumes)
            else:
                self.RECORDER_NAMES = []

        if self.TRANSCRIBE_DIR is None:
            # UserSettings stores output_dir as str (JSON), but legacy Config expects Path
            out_dir = self._user_settings.output_dir
            if isinstance(out_dir, Path):
                self.TRANSCRIBE_DIR = out_dir
            else:
                self.TRANSCRIBE_DIR = Path(str(out_dir)).expanduser()

        support_dir = (
            Path.home()
            / "Library"
            / "Application Support"
            / defaults.APP_SUPPORT_DIR_NAME
        )

        if self.LOG_DIR is None:
            self.LOG_DIR = support_dir / "logs"

        if self.STATE_FILE is None:
            self.STATE_FILE = support_dir / "state.json"

        if self.LOG_FILE is None:
            self.LOG_FILE = self.LOG_DIR / "timshel.log"

        if self.LOCAL_RECORDINGS_DIR is None:
            self.LOCAL_RECORDINGS_DIR = support_dir / "recordings"

        if self.PROCESS_LOCK_FILE is None:
            self.PROCESS_LOCK_FILE = support_dir / "runtime" / "transcriber.lock"

        if self.DIGEST_LOCK_FILE is None:
            self.DIGEST_LOCK_FILE = support_dir / "runtime" / "digest.lock"

        if self.CONNECTIONS_STATE_FILE is None:
            self.CONNECTIONS_STATE_FILE = support_dir / "connections_state.json"

        if self.AUDIO_EXTENSIONS is None:
            self.AUDIO_EXTENSIONS = defaults.AUDIO_EXTENSIONS

        # Map whisper settings from UserSettings
        # Always use UserSettings values (they are the source of truth)
        self.WHISPER_MODEL = self._user_settings.whisper_model
        self.WHISPER_LANGUAGE = self._user_settings.language or "pl"

        if self.WHISPER_CPP_PATH is None:
            # Nowa lokalizacja: ~/Library/Application Support/Timshel/bin/
            support_dir = (
            Path.home()
            / "Library"
            / "Application Support"
            / defaults.APP_SUPPORT_DIR_NAME
        )
            new_whisper_path = support_dir / "bin" / "whisper-cli"

            # Sprawdź nową lokalizację (Faza 2)
            if new_whisper_path.exists():
                self.WHISPER_CPP_PATH = new_whisper_path
            else:
                # Fallback do starych lokalizacji (backward compatibility)
                whisper_base = Path.home() / "whisper.cpp"
                if (whisper_base / "build" / "bin" / "whisper-cli").exists():
                    self.WHISPER_CPP_PATH = (
                        whisper_base / "build" / "bin" / "whisper-cli"
                    )
                elif (whisper_base / "build" / "bin" / "main").exists():
                    self.WHISPER_CPP_PATH = whisper_base / "build" / "bin" / "main"
                elif (whisper_base / "main").exists():
                    self.WHISPER_CPP_PATH = whisper_base / "main"
                else:
                    # Default - nowa lokalizacja (będzie pobrana przez downloader)
                    self.WHISPER_CPP_PATH = new_whisper_path

        if self.WHISPER_CPP_MODELS_DIR is None:
            self.WHISPER_CPP_MODELS_DIR = support_dir / "models"

        if self.FFMPEG_PATH is None:
            timshel_ffmpeg_path = support_dir / "bin" / "ffmpeg"
            # Fallback do systemowego ffmpeg (dev environment).
            system_ffmpeg = shutil.which("ffmpeg")
            if system_ffmpeg:
                self.FFMPEG_PATH = Path(system_ffmpeg)
            else:
                # Default - new location (downloaded by DependencyDownloader)
                self.FFMPEG_PATH = timshel_ffmpeg_path

        # Load LLM API key from UserSettings only
        # Environment variables should be migrated to UserSettings via perform_migration_if_needed()
        # This ensures deterministic behavior and prevents runtime ENV reading
        if self.LLM_API_KEY is None:
            if self._user_settings.ai_api_key:
                self.LLM_API_KEY = self._user_settings.ai_api_key
            elif self.LLM_PROVIDER == "ollama":
                # Ollama doesn't require API key, but we can use base URL (default)
                # This is a default value, not reading from ENV
                self.LLM_API_KEY = "http://localhost:11434"

        # Connected LLM for the Insights action handoff (ADR-004).
        self.LLM_HANDOFF_TOOL = (
            getattr(self._user_settings, "ai_handoff_tool", "claude") or "claude"
        )

        # How note/transcript clicks open files: Obsidian deep link by default,
        # but configurable so Timshel doesn't assume Obsidian (see
        # ui/obsidian_link.file_open_argv). "obsidian" | "finder" | "default" |
        # "app:<Name>".
        self.NOTE_OPENER = (
            getattr(self._user_settings, "note_opener", "obsidian") or "obsidian"
        )

        # Local recall engine ("ask your corpus"). Embeddings are local + no API key;
        # provider/model are swappable (no hardcoded provider). Indexing at
        # transcription time is opt-in until the feature ships.
        self.EMBED_PROVIDER = (
            getattr(self._user_settings, "embed_provider", "") or "fastembed"
        )
        self.EMBED_MODEL = (
            getattr(self._user_settings, "embed_model", "")
            or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
        # Recall is on by default (Faza 5): search is 100% local, so indexing the vault
        # in the background is safe and makes the lens "just work". A user who saved the
        # setting keeps their choice; only an absent setting falls back to enabled.
        self.ENABLE_RECALL_INDEX = bool(
            getattr(self._user_settings, "enable_recall_index", True)
        )
        # ONNX thread cap for embeddings. Without it onnxruntime takes ALL
        # cores and oversubscribes against whisper-cli (cores-2): a launch-time
        # backfill coinciding with a recorder batch pegged ~2× the CPU. 0/absent
        # = auto: half the cores, floor 1.
        try:
            raw_embed_threads = int(
                getattr(self._user_settings, "embed_threads", 0) or 0
            )
        except (TypeError, ValueError):
            raw_embed_threads = 0
        self.EMBED_THREADS = (
            raw_embed_threads
            if raw_embed_threads > 0
            else max(1, (os.cpu_count() or 4) // 2)
        )

        # AI summaries run whenever a usable LLM backend is configured: Ollama
        # needs no key; cloud providers need an API key. Key presence is the
        # single control — it matches the Settings copy ("without a key … skips
        # AI summaries"). The enable_ai_summaries user flag is kept in
        # UserSettings for compatibility but no longer gates here; it used to
        # leave summaries stuck off when a key was added via Settings (which
        # never wrote the flag) rather than onboarding.
        if self.LLM_PROVIDER == "ollama":
            enable_summarization = True
        else:
            enable_summarization = bool(self.LLM_API_KEY)

        self.ENABLE_SUMMARIZATION = enable_summarization

        # Tagging requires summarization to be enabled (shared LLM availability).
        if self.ENABLE_LLM_TAGGING and not self.ENABLE_SUMMARIZATION:
            self.ENABLE_LLM_TAGGING = False

    def ensure_directories(self) -> None:
        """Create necessary directories if they don't exist."""
        self.TRANSCRIBE_DIR.mkdir(parents=True, exist_ok=True)
        self.LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.LOCAL_RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        self.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.PROCESS_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)


# Global configuration instance
# This will be initialized after migration in main() or app startup
# For backward compatibility, we create it lazily on first access
_config_instance: Optional[Config] = None


def get_config() -> Config:
    """Get the global Config instance, creating it if necessary.

    Note: In production, migration should be performed before calling this.
    For testing, you can set _config_instance directly.
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance


def reload_config() -> Config:
    """Rebuild the global Config from disk, picking up UserSettings changes.

    The Config singleton caches settings-derived runtime fields
    (``LLM_API_KEY``, ``ENABLE_SUMMARIZATION``, ``ENABLE_LLM_TAGGING``,
    ``TRANSCRIBE_DIR``, whisper settings, …) at construction time and never
    re-reads them. After the user edits and saves settings, call this so the
    live process uses the new values **without a restart** — otherwise a
    changed/fixed API key only takes effect on the next app launch (the cause
    of silent 401s after a key update).

    The fully-built instance is swapped in atomically (single assignment in
    CPython), so a concurrent reader on the daemon thread never observes a
    half-initialised config.
    """
    global _config_instance
    _config_instance = Config()
    # Drop the cached recall engine — it captured the old TRANSCRIBE_DIR and embedder
    # at first use, so a changed vault dir or embedding model would otherwise keep
    # querying the previous index. Lazy import avoids a config↔recall import cycle.
    try:
        from src.connections.recall.seam import reset_engine

        reset_engine()
    except Exception:  # pragma: no cover - recall is optional
        pass
    return _config_instance


# Backward compatibility: expose config as a property-like object
# This allows existing code using `from src.config import config` to continue working
class _ConfigProxy:
    """Proxy for global config instance to maintain backward compatibility."""

    def __getattr__(self, name: str):
        return getattr(get_config(), name)

    def __setattr__(self, name: str, value):
        # Allow setting attributes on the actual config instance
        setattr(get_config(), name, value)

    def ensure_directories(self) -> None:
        """Forward ensure_directories call to config instance."""
        get_config().ensure_directories()


config = _ConfigProxy()
