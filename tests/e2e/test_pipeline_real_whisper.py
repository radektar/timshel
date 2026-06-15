"""L2 scenario tests: the real audio → whisper.cpp → Markdown pipeline.

These run the *actual* whisper.cpp binary on generated speech samples — no
mocks on the transcription boundary — but keep Claude out of the loop (the
summarizer/tagger are disabled, so post-processing takes the offline fallback
path). That isolates exactly the layer the unit suite cannot reach: does audio
of every supported format decode, transcribe, and land as a valid note?

Requires a real whisper install (binary + at least one model), ffmpeg, and the
macOS ``say`` voices. All are skipped cleanly when absent, so this file is inert
on a CI box without them. See ``Docs/TESTING-E2E-STRATEGY.md`` (layer L2).

Marked ``e2e`` and ``slow``; run with ``make test-pipeline`` or
``pytest -m e2e tests/e2e/test_pipeline_real_whisper.py``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.markdown_frontmatter import read_frontmatter
from tests.fixtures import whisper_runtime as wr
from tests.fixtures.audio_factory import DEFAULT_TEXTS, AudioFactory, say_available

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

#: Generous so the test is about "did transcription basically work", not about
#: chasing whisper accuracy. Clean ``small``-model runs measure ~0.1; a format
#: that fails to decode collapses to ~1.0, which this catches with wide margin.
MAX_WER = 0.35

#: Every advertised format must transcribe. The pipeline now normalises each
#: input to 16 kHz mono WAV via ffmpeg before whisper (``_convert_to_wav``), so
#: whisper-cli's decoder limitations no longer matter. This list was the
#: regression guard for finding F1 (m4a/wma/aac silently failed); the fix
#: landed, so all 7 formats are required to pass. See
#: ``Docs/TESTING-E2E-STRATEGY.md`` §F1.
SUPPORTED_FORMATS = [".wav", ".mp3", ".m4a", ".wma", ".flac", ".aac", ".ogg"]

_FORMAT_PARAMS = [pytest.param(ext, id=ext) for ext in SUPPORTED_FORMATS]

requires_runtime = pytest.mark.skipif(
    wr.find_whisper_install() is None
    or wr.find_ffmpeg() is None
    or not say_available(),
    reason="requires a real whisper install, ffmpeg, and macOS `say`",
)


# --------------------------------------------------------------------------- #
# Fixtures.
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def factory() -> AudioFactory:
    """Shared sample factory (default cache → reused across the module/runs)."""
    return AudioFactory()


def _build_transcriber(cfg):
    """Construct a Transcriber on *cfg* with AI disabled (offline fallback).

    Nulling ``summarizer``/``tagger`` makes ``_postprocess_transcript`` skip
    every Claude call and use the fallback summary — this is what keeps L2 from
    silently becoming a (paid, non-deterministic) L3 run.
    """
    from src.transcriber import Transcriber

    with patch("src.transcriber.logger"):
        transcriber = Transcriber(config=cfg)
    transcriber.summarizer = None
    transcriber.tagger = None
    return transcriber


def _whisper_text(
    factory: AudioFactory, audio: Path, lang_code: str, tmp_path: Path
) -> str:
    """Run real whisper on *audio* and return the raw transcript text."""
    cfg = wr.make_e2e_config(tmp_path, language=lang_code, model="small")
    transcriber = _build_transcriber(cfg)
    txt_path = transcriber._run_macwhisper(audio)
    assert txt_path is not None, f"whisper produced no output for {audio.name}"
    return Path(txt_path).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Per-format transcription (the format matrix).
# --------------------------------------------------------------------------- #


@requires_runtime
@pytest.mark.parametrize("ext", _FORMAT_PARAMS)
def test_real_whisper_transcribes_each_format(factory, ext, tmp_path):
    """Every supported format transcribes to the expected text.

    Inputs are normalised to 16 kHz mono WAV before whisper, so m4a/wma/aac
    (which whisper-cli cannot decode directly) work too — this is the guard for
    finding F1.
    """
    audio = factory.make(lang="en_US", ext=ext)
    text = _whisper_text(factory, audio, "en", tmp_path)
    assert text.strip(), f"{ext}: transcript was empty"
    wer = wr.word_error_rate(DEFAULT_TEXTS["en_US"], text)
    assert wer <= MAX_WER, f"{ext}: WER {wer:.3f} exceeds {MAX_WER} (hyp={text!r})"


# --------------------------------------------------------------------------- #
# Multilingual transcription.
# --------------------------------------------------------------------------- #


@requires_runtime
@pytest.mark.parametrize(
    "lang_code,voice_lang",
    [("en", "en_US"), ("pl", "pl_PL"), ("de", "de_DE")],
)
def test_real_whisper_matches_language(factory, lang_code, voice_lang, tmp_path):
    """Transcribing with the matching language code yields the spoken text."""
    from tests.fixtures.audio_factory import resolve_voice

    if resolve_voice(voice_lang) is None:
        pytest.skip(f"no `say` voice for {voice_lang}")

    audio = factory.make(lang=voice_lang, ext=".wav")
    text = _whisper_text(factory, audio, lang_code, tmp_path)
    wer = wr.word_error_rate(DEFAULT_TEXTS[voice_lang], text)
    assert wer <= MAX_WER, f"{lang_code}: WER {wer:.3f} (hyp={text!r})"


# --------------------------------------------------------------------------- #
# Full pipeline → Markdown note.
# --------------------------------------------------------------------------- #


@requires_runtime
def test_full_pipeline_writes_valid_markdown(factory, tmp_path):
    """End-to-end: audio in → a Markdown note with correct frontmatter out."""
    audio = factory.make(lang="en_US", ext=".wav")
    cfg = wr.make_e2e_config(tmp_path, language="en", model="small")
    transcriber = _build_transcriber(cfg)

    assert transcriber.transcribe_file(audio) is True

    notes = list(Path(cfg.TRANSCRIBE_DIR).glob("*.md"))
    assert len(notes) == 1, f"expected exactly one note, got {notes}"
    note = notes[0]

    fm = read_frontmatter(note)
    assert fm.get("language") == "en", f"frontmatter language wrong: {fm}"
    assert fm.get("model") == "small", f"frontmatter model wrong: {fm}"

    body = note.read_text(encoding="utf-8").lower()
    # The transcript must be embedded in the note (not just frontmatter).
    assert "recording" in body, "transcript text missing from the note body"


# --------------------------------------------------------------------------- #
# Edge cases (historical regressions).
# --------------------------------------------------------------------------- #


@requires_runtime
def test_corrupted_audio_fails_without_crash(factory, tmp_path):
    """alpha.16: an unreadable file must fail cleanly, not raise or loop."""
    corrupt = factory.corrupted(ext=".mp3")
    cfg = wr.make_e2e_config(tmp_path, language="en", model="small")
    transcriber = _build_transcriber(cfg)

    assert transcriber.transcribe_file(corrupt) is False
    assert not list(Path(cfg.TRANSCRIBE_DIR).glob("*.md"))


@requires_runtime
def test_silence_is_handled_gracefully(factory, tmp_path):
    """Silence must not crash the pipeline and still yields exactly one note.

    Note we deliberately do NOT assert an empty/placeholder transcript: whisper
    routinely hallucinates a short token (e.g. ``you``) on pure silence, so the
    transcript may be non-empty. The contract under test is graceful handling —
    one note, no exception — not the hallucination's content.
    """
    silent = factory.silence(duration=2.0, ext=".wav")
    cfg = wr.make_e2e_config(tmp_path, language="en", model="small")
    transcriber = _build_transcriber(cfg)

    result = transcriber.transcribe_file(silent)
    assert result is True
    notes = list(Path(cfg.TRANSCRIBE_DIR).glob("*.md"))
    assert len(notes) == 1, f"expected one note for silence, got {notes}"
