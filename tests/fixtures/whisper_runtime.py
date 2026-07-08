"""Shared helpers for the L2/L3 scenario tests that drive a *real* whisper.cpp.

The conftest redirects ``$HOME`` to a throw-away dir, so the production config
cannot find the installed whisper binary or models on its own. These helpers
locate the real install (under the developer's true home, discovered via
``pwd`` rather than ``$HOME``), pick an installed model, and assemble a
``Config`` wired to point at them — with ``TRANSCRIBE_DIR`` forced to a test
temp dir so the suite never writes into the user's real vault.

Also here: a diacritic-insensitive word error rate, used to assert
transcription quality against the known sample text without being tripped by
Polish accents (``testów`` vs ``testow``).

See ``Docs/TESTING-E2E-STRATEGY.md`` (layers L2/L3).
"""

from __future__ import annotations

import os
import pwd
import re
import unicodedata
from pathlib import Path
from typing import List, Optional

#: The developer's REAL home — resolved independently of ``$HOME`` so the
#: conftest redirection cannot hide a genuine whisper install from us.
REAL_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)

#: Candidate install roots, most-specific first. The first that holds both a
#: ``bin/whisper-cli`` and at least one ``models/ggml-*.bin`` wins.
_INSTALL_ROOTS = (REAL_HOME / "Library" / "Application Support" / "Timshel",)

#: Model preference order when several are installed: fast-and-good first.
_MODEL_PREFERENCE = ("small", "base", "medium", "tiny", "large")


class WhisperInstall:
    """A located whisper.cpp install: binary + models dir + available models."""

    def __init__(self, binary: Path, models_dir: Path, models: List[str]) -> None:
        self.binary = binary
        self.models_dir = models_dir
        self.models = models

    def pick_model(self) -> str:
        """Return the most preferred installed model name (e.g. ``small``)."""
        for name in _MODEL_PREFERENCE:
            if name in self.models:
                return name
        return self.models[0]


def _models_in(models_dir: Path) -> List[str]:
    """Names of installed ggml models (``ggml-small.bin`` → ``small``)."""
    if not models_dir.is_dir():
        return []
    out = []
    for path in models_dir.glob("ggml-*.bin"):
        name = path.stem[len("ggml-") :]
        # Skip the Core ML encoder sidecars (they are dirs, not .bin models,
        # but guard anyway against ``ggml-small-encoder``-style stems).
        if name.endswith("-encoder"):
            continue
        out.append(name)
    return out


def find_whisper_install() -> Optional[WhisperInstall]:
    """Locate a usable whisper.cpp install, or ``None`` if none is present.

    'Usable' means: an executable ``whisper-cli`` and at least one ggml model.
    """
    for root in _INSTALL_ROOTS:
        binary = root / "bin" / "whisper-cli"
        models_dir = root / "models"
        if not (binary.exists() and os.access(binary, os.X_OK)):
            continue
        models = _models_in(models_dir)
        if not models:
            continue
        return WhisperInstall(binary, models_dir, models)
    return None


def find_ffmpeg() -> Optional[Path]:
    """Path to a usable ffmpeg, or ``None``."""
    import shutil

    found = shutil.which("ffmpeg")
    return Path(found) if found else None


def make_e2e_config(
    transcribe_dir: Path, language: Optional[str], model: Optional[str] = None
):
    """Build a ``Config`` wired to the real whisper install.

    ``transcribe_dir`` MUST be a test temp dir — it is where whisper writes its
    TXT and where Markdown notes land. ``language`` is the whisper ``-l`` code
    (``"en"``, ``"pl"``, or ``None`` for auto-detect). Raises ``RuntimeError``
    if no install is found; callers should guard with :data:`requires_whisper`.
    """
    from src.config.config import Config

    install = find_whisper_install()
    if install is None:
        raise RuntimeError("no whisper.cpp install found; guard with requires_whisper")
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise RuntimeError("ffmpeg not found; guard with requires_whisper")

    cfg = Config()
    cfg.WHISPER_CPP_PATH = install.binary
    cfg.WHISPER_CPP_MODELS_DIR = install.models_dir
    cfg.WHISPER_MODEL = model or install.pick_model()
    cfg.WHISPER_LANGUAGE = language
    cfg.FFMPEG_PATH = ffmpeg
    cfg.TRANSCRIBE_DIR = Path(transcribe_dir)
    cfg.TRANSCRIBE_DIR.mkdir(parents=True, exist_ok=True)
    return cfg


# --------------------------------------------------------------------------- #
# Quality metric.
# --------------------------------------------------------------------------- #


def _normalize(text: str) -> List[str]:
    """Lowercase, strip accents and punctuation, split into words.

    Accent stripping makes the metric robust to whisper emitting correct
    diacritics where the reference text avoided them (and vice versa).
    """
    decomposed = unicodedata.normalize("NFKD", text.lower())
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.findall(r"\w+", ascii_only)


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Word error rate (Levenshtein over words) ∈ [0, 1+].

    0.0 is a perfect match. Returns 1.0 for an empty hypothesis against a
    non-empty reference. Diacritic- and punctuation-insensitive.
    """
    ref = _normalize(reference)
    hyp = _normalize(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    # Classic edit-distance DP over word lists.
    prev = list(range(len(hyp) + 1))
    for i, r_word in enumerate(ref, start=1):
        curr = [i]
        for j, h_word in enumerate(hyp, start=1):
            cost = 0 if r_word == h_word else 1
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[len(hyp)] / len(ref)
