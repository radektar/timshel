"""Session-wide test fixtures for Malinche.

This file serves two critical purposes:

1. **HOME isolation (module-level).** Before *any* test module imports
   ``src.logger`` or ``src.config``, this file redirects ``$HOME`` to a
   per-session temp directory. ``Path.home()`` returns that fake directory, so
   the lazily-initialised ``Config`` writes its ``STATE_FILE``,
   ``PROCESS_LOCK_FILE`` and ``LOG_FILE`` into a throw-away location instead of
   the developer's real ``~``.

2. **Regression guard (session fixture).** An autouse, session-scoped fixture
   snapshots the mtimes of the user-state artifacts that tests previously
   corrupted (``~/.olympus_transcriber_state.json``,
   ``~/.olympus_transcriber/transcriber.lock``,
   ``~/Library/Logs/olympus_transcriber.log``) and asserts at session teardown
   that they are unchanged. A regression that makes the test suite pollute the
   developer's HOME again will fail the build instead of silently corrupting
   the running Malinche instance.
"""

from __future__ import annotations

import os
import pwd
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Optional

import pytest

# --------------------------------------------------------------------------- #
# Module-level HOME redirection (runs BEFORE any test module is imported).
# --------------------------------------------------------------------------- #

# Resolve the REAL user home via getpwuid so we can always compare against it
# regardless of any subsequent $HOME changes.
_REAL_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)

# Fake HOME used for the whole session.
_FAKE_HOME = Path(tempfile.mkdtemp(prefix="malinche-test-home-"))
(_FAKE_HOME / "Library" / "Logs").mkdir(parents=True, exist_ok=True)
(_FAKE_HOME / "Library" / "Application Support" / "Malinche").mkdir(
    parents=True, exist_ok=True
)
(_FAKE_HOME / ".olympus_transcriber").mkdir(parents=True, exist_ok=True)

# Reassigning HOME here — at conftest module load time — guarantees that every
# subsequent ``Path.home()`` call (including the one inside
# ``Config.__post_init__``) resolves to the fake directory.
os.environ["HOME"] = str(_FAKE_HOME)

# Paths that production code writes to in ``_REAL_HOME``. If any of these get
# touched during the test session, the developer environment is being
# corrupted and we must fail loudly.
_USER_HOME_PROTECTED_PATHS = (
    _REAL_HOME / ".olympus_transcriber_state.json",
    _REAL_HOME / ".olympus_transcriber" / "transcriber.lock",
    _REAL_HOME / "Library" / "Logs" / "olympus_transcriber.log",
)


def _snapshot(paths) -> Dict[Path, Optional[float]]:
    """Capture current mtime (or None if missing) for every path."""
    snapshot: Dict[Path, Optional[float]] = {}
    for path in paths:
        try:
            snapshot[path] = path.stat().st_mtime
        except FileNotFoundError:
            snapshot[path] = None
    return snapshot


# --------------------------------------------------------------------------- #
# Fixtures.
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def fake_home() -> Path:
    """Expose the session-wide fake HOME for tests that need it explicitly."""
    return _FAKE_HOME


@pytest.fixture(scope="session", autouse=True)
def _assert_real_home_untouched():
    """Fail the test run if any protected path under the real HOME changes.

    Rationale: in v2.0.0-alpha.2 we discovered that pytest runs were
    overwriting the live state file / log of the installed Malinche instance,
    which looked like the application had stopped detecting the recorder.
    This guard makes that failure mode impossible to merge unnoticed.
    """
    before = _snapshot(_USER_HOME_PROTECTED_PATHS)
    yield
    after = _snapshot(_USER_HOME_PROTECTED_PATHS)

    mutated = [
        path for path in _USER_HOME_PROTECTED_PATHS if before[path] != after[path]
    ]

    if mutated:
        details = "\n".join(
            f"  - {path}: mtime {before[path]!r} -> {after[path]!r}" for path in mutated
        )
        pytest.fail(
            "Test run mutated real user HOME artifacts. "
            "Tests must never write to ~/.olympus_* or the production log.\n"
            f"{details}",
            pytrace=False,
        )


def pytest_sessionfinish(session, exitstatus):
    """Clean up the session-wide fake HOME tempdir."""
    shutil.rmtree(_FAKE_HOME, ignore_errors=True)


@pytest.fixture(autouse=True)
def _no_onboarding_modal(monkeypatch):
    """Never open the real onboarding modal in tests (it would block).

    Forcing it to return ``None`` makes the wizard fall back to its
    ``rumps.alert`` path, which the wizard tests already mock.
    """
    try:
        monkeypatch.setattr(
            "src.setup.onboarding_window.show_onboarding_screen",
            lambda **_kwargs: None,
        )
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _recall_index_off_by_default(monkeypatch):
    """Recall ships enabled (Faza 5), but that would make the transcription seam try to
    index — and load the embedding model — inside unrelated tests. Isolate the suite:
    default the flag off. Recall's own tests drive the engine directly and never read it,
    so they are unaffected; a test that wants the seam can re-enable it explicitly.
    """
    try:
        from src.config.config import config as cfg

        monkeypatch.setattr(cfg, "ENABLE_RECALL_INDEX", False, raising=False)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _clear_volume_session():
    """Reset the process-wide 'Once' registry around every test.

    ``src.volume_session`` is module-global state shared by FileMonitor and
    volume_utils; without this an 'Once' approval in one test would leak into
    the next (e.g. silently making an 'unknown' disk look trusted).
    """
    from src import volume_session

    volume_session.clear()
    yield
    volume_session.clear()


@pytest.fixture(autouse=True)
def _clear_prompts_in_flight():
    """Reset the per-UUID prompt guard around every test.

    ``file_monitor._PROMPTS_IN_FLIGHT`` is module-global; a test that leaves a
    UUID in flight would silently suppress prompts in later tests.
    """
    from src import file_monitor

    file_monitor._PROMPTS_IN_FLIGHT.clear()
    yield
    file_monitor._PROMPTS_IN_FLIGHT.clear()


# --------------------------------------------------------------------------- #
# Audio sample fixtures (L2/L3 scenario tests).
#
# Backed by ``tests/fixtures/audio_factory.py``. The factory caches under the OS
# temp dir — NOT under HOME — so it never trips the guard above. Every fixture
# skips cleanly when ``say``/``ffmpeg`` are unavailable, so the unit suite (L1)
# stays green on a box without them. See ``Docs/TESTING-E2E-STRATEGY.md``.
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def audio_factory():
    """Session-wide :class:`AudioFactory`. Skips if `say`/`ffmpeg` are absent."""
    from tests.fixtures.audio_factory import AudioFactory

    factory = AudioFactory()
    if not factory.available:
        pytest.skip("audio fixtures require macOS `say` and `ffmpeg`")
    return factory


@pytest.fixture(scope="session")
def sample_pl(audio_factory):
    """A Polish spoken-word WAV (16 kHz mono)."""
    return audio_factory.make(lang="pl_PL", ext=".wav")


@pytest.fixture(scope="session")
def sample_en(audio_factory):
    """An English spoken-word WAV (16 kHz mono)."""
    return audio_factory.make(lang="en_US", ext=".wav")


@pytest.fixture(scope="session")
def samples_all_formats(audio_factory):
    """The same English utterance in every ``AUDIO_EXTENSIONS`` format."""
    return audio_factory.all_formats(lang="en_US")


@pytest.fixture(scope="session")
def corrupted_audio(audio_factory):
    """A file with audio magic bytes followed by garbage (alpha.16 case)."""
    return audio_factory.corrupted(ext=".mp3")


@pytest.fixture(scope="session")
def silence_audio(audio_factory):
    """A valid but silent 2s clip (empty-transcript path)."""
    return audio_factory.silence(duration=2.0, ext=".wav")
