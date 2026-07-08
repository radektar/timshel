"""Personal vocabulary: the user's confirmed terms, harvested from the vault.

Transcription mangles proper names — Whisper heard "Tech to the Rescue" as
"TekTutoreski" and the summary faithfully cemented the mangled form in the
title, key points and stances. The speaker also drifts between aliases
("TTTR", "Tech to the rescue"). Downstream every variant is a different
entity: BM25, the entity channel and wikilinks cannot join notes that talk
about the same thing under different names.

This module builds a per-user glossary from what the vault already confirms
and feeds it back into the pipeline at two levels:

* **whisper-cli ``--prompt``** — biases decoding toward known spellings, so
  the mangling tends not to happen in the first place;
* **summarizer KNOWN TERMS block** — instructs the model to snap clear
  variants (phonetic manglings, abbreviations) to the canonical form, under
  strict no-invention rules.

Sources, in order of trust:

1. ``{TRANSCRIBE_DIR}/.timshel/vocabulary.json`` — user-curated canonical
   terms with optional aliases. Highest trust, always included first.
2. Wikilink targets ``[[...]]`` in vault notes — explicit references,
   confirmed by use (the summary's "Stances" section keeps adding these).
3. Multi-word capitalised runs that recur across at least
   ``VOCABULARY_MIN_ENTITY_NOTES`` notes — frequency is the confirmation.

Harvesting stops at the ``## Transkrypcja`` / ``## Transcript`` heading of
each note: the raw transcript below it is exactly where the mangled forms
live, and a glossary that learns "TekTutoreski" would defeat its purpose.

The vocabulary GROWS with the vault: every new note's wikilinks widen the
glossary used for the next recording. That flywheel — a personal dictionary
no generic transcriber has — is a core product value, not an implementation
detail.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.config import config
from src.connections.entities import _RUN_RE, _WIKILINK_RE
from src.logger import logger

# Everything below this heading is raw transcript — never harvest from it.
_TRANSCRIPT_HEADING_RE = re.compile(
    r"^##\s+(Transkrypcja|Transcript)\s*$", re.MULTILINE
)

# Terms shorter than this (display form) are dropped as noise.
_MIN_TERM_CHARS = 4


@dataclass
class Term:
    """One canonical vocabulary entry."""

    canonical: str  # display form, original casing ("Tech to the Rescue")
    aliases: List[str] = field(default_factory=list)
    note_count: int = 0  # how many notes reference it (harvested terms)
    curated: bool = False  # came from vocabulary.json
    wikilinked: bool = False  # seen as an explicit [[wikilink]] target


def _alias_file_path() -> Path:
    return Path(config.TRANSCRIBE_DIR) / config.SIDECAR_DIR_NAME / "vocabulary.json"


@dataclass
class VocabularyIndex:
    """Builds and serves the personal glossary. Mirror of :class:`TagIndex`."""

    root_dir: Optional[Path] = None
    _terms: Optional[Dict[str, Term]] = None  # casefold key -> Term

    def __post_init__(self) -> None:
        if self.root_dir is None:
            self.root_dir = Path(config.TRANSCRIBE_DIR)

    # ------------------------------------------------------------------ build

    def build(self, force_refresh: bool = False) -> Dict[str, Term]:
        """Scan the alias file + vault and cache the merged glossary."""
        if self._terms is not None and not force_refresh:
            return self._terms

        self._terms = {}
        self._load_alias_file()
        self._harvest_vault()

        # Drop unconfirmed noise: a bare capitalised run must recur across
        # notes; curated and wikilinked terms are confirmed by definition.
        min_notes = config.VOCABULARY_MIN_ENTITY_NOTES
        self._terms = {
            key: term
            for key, term in self._terms.items()
            if term.curated or term.wikilinked or term.note_count >= min_notes
        }
        return self._terms

    def _load_alias_file(self) -> None:
        """Layer 1: user-curated ``vocabulary.json`` (optional).

        Format: ``{"terms": [{"canonical": "Tech to the Rescue",
        "aliases": ["TTTR", "TekTutoreski"]}, ...]}``.
        """
        path = _alias_file_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("vocabulary.json unreadable (%s) — skipping", exc)
            return
        for entry in data.get("terms", []):
            canonical = str(entry.get("canonical", "")).strip()
            if len(canonical) < _MIN_TERM_CHARS:
                continue
            aliases = [
                str(a).strip() for a in entry.get("aliases", []) if str(a).strip()
            ]
            term = self._terms.setdefault(canonical.casefold(), Term(canonical))
            term.curated = True
            for alias in aliases:
                if alias not in term.aliases:
                    term.aliases.append(alias)

    def _harvest_vault(self) -> None:
        """Layers 2+3: wikilink targets and recurring capitalised runs."""
        root = self.root_dir
        if not root or not root.exists():
            logger.debug("VocabularyIndex root missing: %s", root)
            return
        for md_path in root.rglob("*.md"):
            try:
                text = md_path.read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning("Could not read %s for vocabulary: %s", md_path, exc)
                continue
            self._harvest_note(text)

    def _harvest_note(self, text: str) -> None:
        # Cut at the transcript heading — the raw transcript is where the
        # mangled forms live; learning them would poison the glossary.
        cut = _TRANSCRIPT_HEADING_RE.search(text)
        if cut:
            text = text[: cut.start()]

        seen_here = set()  # count each term once per note

        for raw in _WIKILINK_RE.findall(text):
            display = raw.split("|", 1)[0].strip()
            display = re.sub(r"\s+", " ", display)
            if len(display) < _MIN_TERM_CHARS:
                continue
            key = display.casefold()
            term = self._terms.setdefault(key, Term(display))
            term.wikilinked = True
            if key not in seen_here:
                term.note_count += 1
                seen_here.add(key)

        without_links = _WIKILINK_RE.sub(" ", text)
        for match in _RUN_RE.finditer(without_links):
            candidates = [match.group(0).split()]
            # Same trap as entities.extract_entities: a sentence-initial
            # capital ("Znowu") glues itself onto the real name ("Beta
            # Runda"). Keep the full run AND the without-opener form so the
            # name matches whether or not it opened a sentence elsewhere.
            prefix = without_links[: match.start()].rstrip(" \t")
            sentence_initial = (not prefix) or prefix[-1] in ".!?\n"
            if sentence_initial and len(candidates[0]) >= 3:
                candidates.append(candidates[0][1:])
            for tokens in candidates:
                display = " ".join(tokens)
                if len(display) < _MIN_TERM_CHARS:
                    continue
                key = display.casefold()
                term = self._terms.setdefault(key, Term(display))
                if key not in seen_here:
                    term.note_count += 1
                    seen_here.add(key)

    # ------------------------------------------------------------------ views

    def ranked_terms(self, force_refresh: bool = False) -> List[Term]:
        """Glossary ordered by trust: curated, then wikilinked, then by DF."""
        terms = list(self.build(force_refresh).values())
        terms.sort(
            key=lambda t: (not t.curated, not t.wikilinked, -t.note_count, t.canonical)
        )
        return terms

    def known_terms_block(self) -> str:
        """Prompt-block lines for the summarizer ("" when empty/disabled).

        One line per term: ``- Tech to the Rescue (aliases: TTTR, TekTutoreski)``.
        """
        if not config.VOCABULARY_ENABLED:
            return ""
        lines = []
        for term in self.ranked_terms()[: config.VOCABULARY_MAX_PROMPT_TERMS]:
            if term.aliases:
                lines.append(f"- {term.canonical} (aliases: {', '.join(term.aliases)})")
            else:
                lines.append(f"- {term.canonical}")
        return "\n".join(lines)

    def whisper_prompt(self) -> str:
        """Comma-joined glossary for whisper-cli ``--prompt`` ("" when off).

        Canonical spellings plus short all-caps aliases (an acronym like TTTR
        benefits from decoding bias too). Capped by chars — whisper reads only
        ~224 prompt tokens, and an over-long prompt raises the hallucination
        risk on silent stretches.
        """
        if not (config.VOCABULARY_ENABLED and config.WHISPER_GLOSSARY_ENABLED):
            return ""
        parts: List[str] = []
        seen = set()
        for term in self.ranked_terms():
            candidates = [term.canonical] + [
                a for a in term.aliases if a.isupper() and len(a) <= 6
            ]
            for name in candidates:
                key = name.casefold()
                if key not in seen:
                    parts.append(name)
                    seen.add(key)
        if not parts:
            return ""
        budget = config.VOCABULARY_WHISPER_MAX_CHARS
        out: List[str] = []
        used = 0
        for name in parts:
            cost = len(name) + (2 if out else 0)
            if used + cost > budget:
                break
            out.append(name)
            used += cost
        return ", ".join(out)

    def find_alias_hits(self, text: str) -> List[Tuple[str, str]]:
        """Detect confirmed aliases the MODEL should have canonicalised.

        The model owns canonicalisation (a deterministic code substitution
        would stop the vocabulary from learning new variants). This is the
        JUDGE half: it only *reports* which listed aliases still appear in
        ``text`` — as ``(alias_as_found, canonical)`` pairs — so the caller can
        re-prompt the model with the specific misses named. It never rewrites.

        Caller passes text with quote/transcript sections already excluded
        (those keep aliases verbatim as evidence).
        """
        if not (config.VOCABULARY_ENABLED and text):
            return []
        hits: List[Tuple[str, str]] = []
        for term in self.build().values():
            for alias in term.aliases:
                if not alias or alias.casefold() == term.canonical.casefold():
                    continue
                match = re.search(rf"\b{re.escape(alias)}\b", text, flags=re.I)
                if match:
                    hits.append((match.group(0), term.canonical))
        return hits


def get_vocabulary_index() -> VocabularyIndex:
    """Factory returning VocabularyIndex rooted at the transcripts dir."""
    return VocabularyIndex()
