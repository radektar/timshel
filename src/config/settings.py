"""User settings management."""

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from src.config.defaults import defaults

# Serializes load→modify→save cycles across threads (FSEvents monitor,
# periodic checker, UI) — without it two concurrent writers are
# last-save-wins and silently clobber each other's changes.
_SETTINGS_WRITE_LOCK = threading.Lock()


@dataclass
class TrustedVolume:
    """Persistent decision o pojedynczym dysku zewnętrznym.

    Identyfikator (`uuid`) to macOS Volume UUID gdy dostępny,
    a w przypadku braku — kompozyt zaczynający się od ``fallback:``
    (patrz ``src.volume_identity.get_volume_uuid``).
    """

    uuid: str
    name: str
    first_seen: str  # ISO-8601 timestamp pierwszego zatwierdzenia
    decision: str    # "trusted" | "blocked"

    @classmethod
    def from_dict(cls, data: dict) -> "TrustedVolume":
        return cls(
            uuid=str(data.get("uuid", "")),
            name=str(data.get("name", "")),
            first_seen=str(data.get("first_seen", "")),
            decision=str(data.get("decision", "blocked")),
        )

    def to_dict(self) -> dict:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "first_seen": self.first_seen,
            "decision": self.decision,
        }


def _now_iso() -> str:
    """ISO-8601 UTC timestamp (sekundowa precyzja, sufiks Z)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class UserSettings:
    """Ustawienia użytkownika (persystentne w JSON)."""

    # Źródła nagrań
    watch_mode: str = defaults.WATCH_MODE
    watched_volumes: List[str] = field(default_factory=list)
    trusted_volumes: List[TrustedVolume] = field(default_factory=list)
    needs_volume_onboarding: bool = False

    # Ścieżki
    output_dir: Path = field(default_factory=lambda: defaults.DEFAULT_OUTPUT_DIR)

    # Transkrypcja
    language: str = defaults.DEFAULT_LANGUAGE
    whisper_model: str = defaults.DEFAULT_WHISPER_MODEL

    # AI (PRO)
    enable_ai_summaries: bool = defaults.DEFAULT_ENABLE_AI_SUMMARIES
    ai_api_key: Optional[str] = None
    # Connected LLM for the Insights action handoff (claude | chatgpt).
    ai_handoff_tool: str = "claude"

    # How clicking a note/transcript opens it: "obsidian" (deep link, default),
    # "finder" (reveal in Finder), "default" (system .md handler), or
    # "app:<Name>" (e.g. "app:Pile"). Decouples Timshel from assuming Obsidian.
    note_opener: str = "obsidian"

    # Local recall engine — embeddings for "ask your corpus". Local, no API key;
    # provider/model swappable. Recall (local search) is on by default (Faza 5).
    embed_provider: str = "fastembed"
    embed_model: str = ""  # empty -> Config default
    enable_recall_index: bool = True
    # ONNX thread cap for embeddings; 0 = auto (half the cores, floor 1).
    embed_threads: int = 0

    # UI
    show_notifications: bool = defaults.DEFAULT_SHOW_NOTIFICATIONS
    start_at_login: bool = defaults.DEFAULT_START_AT_LOGIN

    # Stan wizarda
    setup_completed: bool = defaults.DEFAULT_SETUP_COMPLETED
    setup_version: str = ""
    setup_stage: str = "welcome"
    index_migrated: bool = False
    legacy_migrated: bool = defaults.DEFAULT_LEGACY_MIGRATED

    # Tester build: turns on the H1 instrumentation (verdict pass, metrics log,
    # entity/dense/graph/stance synthesis channels, Opus synthesis+verdict) for
    # BOTH the scheduled daemon digest and the "Generate digest now" menu action.
    # Baked into a tester DMG (see setup_app.py TESTER_BUILD + bootstrap
    # adoption). Persisted so it survives reload_config(); Config.__post_init__
    # maps it to the runtime knobs.
    tester_mode: bool = False

    def __post_init__(self) -> None:
        """Normalize types after init (e.g., JSON-loaded values)."""
        if isinstance(self.output_dir, str):
            # Path.resolve() may map /tmp → /private/tmp on macOS; tests allow this.
            self.output_dir = Path(self.output_dir).expanduser().resolve()

        # Normalize trusted_volumes (JSON load gives list of dicts).
        if self.trusted_volumes and isinstance(self.trusted_volumes[0], dict):
            self.trusted_volumes = [
                TrustedVolume.from_dict(item) for item in self.trusted_volumes  # type: ignore[arg-type]
            ]

        # Migracja: tryb "auto" został usunięty w v2.0.0-beta.2. Force "manual"
        # i ustaw flagę onboardingu — UI wykryje ją i zaproponuje review
        # podłączonych dysków przy pierwszym starcie po update.
        if self.watch_mode == "auto":
            self.watch_mode = "manual"
            self.needs_volume_onboarding = True

    @classmethod
    def load(cls) -> "UserSettings":
        """Wczytaj ustawienia z pliku JSON."""
        config_path = cls.config_path()
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Backward compat: alpha builds wrote `transrec_migrated`.
                if "transrec_migrated" in data and "legacy_migrated" not in data:
                    data["legacy_migrated"] = data.pop("transrec_migrated")
                else:
                    data.pop("transrec_migrated", None)
                return cls(**data)
            except (json.JSONDecodeError, TypeError):
                pass
        return cls()

    def save(self) -> None:
        """Zapisz ustawienia do pliku JSON."""
        config_path = self.config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def mutate(cls, fn: Callable[["UserSettings"], object]) -> "UserSettings":
        """Atomic load → ``fn(settings)`` → save under the write lock.

        The safe way to persist a change from any thread: a bare
        load-modify-save loses concurrent writes (last save wins). Existing
        load/modify/save call sites elsewhere should migrate to this as they
        are touched. Returns the saved instance.
        """
        with _SETTINGS_WRITE_LOCK:
            settings = cls.load()
            fn(settings)
            settings.save()
            return settings

    def to_dict(self) -> dict:
        """Serialize settings to JSON-friendly dict."""
        return {
            "watch_mode": self.watch_mode,
            "watched_volumes": list(self.watched_volumes),
            "trusted_volumes": [tv.to_dict() for tv in self.trusted_volumes],
            "needs_volume_onboarding": self.needs_volume_onboarding,
            "output_dir": str(self.output_dir),
            "language": self.language,
            "whisper_model": self.whisper_model,
            "enable_ai_summaries": self.enable_ai_summaries,
            "ai_api_key": self.ai_api_key,
            "ai_handoff_tool": self.ai_handoff_tool,
            "note_opener": self.note_opener,
            "embed_provider": self.embed_provider,
            "embed_model": self.embed_model,
            "enable_recall_index": self.enable_recall_index,
            "embed_threads": self.embed_threads,
            "show_notifications": self.show_notifications,
            "start_at_login": self.start_at_login,
            "setup_completed": self.setup_completed,
            "setup_version": self.setup_version,
            "setup_stage": self.setup_stage,
            "index_migrated": self.index_migrated,
            "legacy_migrated": self.legacy_migrated,
            "tester_mode": self.tester_mode,
        }

    def find_trusted_volume(self, uuid: str) -> Optional[TrustedVolume]:
        """Wyszukaj wpis whitelist po UUID. Zwraca None gdy brak."""
        for tv in self.trusted_volumes:
            if tv.uuid == uuid:
                return tv
        return None

    def add_trusted_volume(self, uuid: str, name: str, decision: str) -> TrustedVolume:
        """Doda wpis (lub zaktualizuje nazwę / decyzję istniejącego)."""
        existing = self.find_trusted_volume(uuid)
        if existing is not None:
            existing.name = name
            existing.decision = decision
            return existing
        entry = TrustedVolume(
            uuid=uuid,
            name=name,
            first_seen=_now_iso(),
            decision=decision,
        )
        self.trusted_volumes.append(entry)
        return entry

    @staticmethod
    def config_path() -> Path:
        """Zwróć ścieżkę do pliku konfiguracji."""
        # Compute dynamically so tests can monkeypatch Path.home()
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / defaults.APP_SUPPORT_DIR_NAME
            / "config.json"
        )

    # Backward-compatibility alias used by migration/older code.
    @classmethod
    def _config_path(cls) -> Path:
        """Backward compatible alias for config_path()."""
        return cls.config_path()

    def ensure_directories(self) -> None:
        """Ensure output directory exists."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
