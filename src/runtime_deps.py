"""Runtime safeguards for Python dependencies in bundled app."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from src.logger import logger

RUNTIME_DEPS_DIR = (
    Path.home()
    / "Library"
    / "Application Support"
    / "Timshel"
    / "runtime"
    / "python-deps"
)

SAFEGUARDED_PACKAGES = {
    "anthropic": "anthropic==0.75.0",
    # Local recall engine — auto-installed on first use (like whisper.cpp/ffmpeg),
    # NOT a hard requirement, so the base install stays light. Pin sqlite-vec
    # before shipping — it is pre-1.0.
    "fastembed": "fastembed",
    "sqlite_vec": "sqlite-vec",
}


def _ensure_runtime_dir_on_path() -> None:
    """Prepend runtime deps directory to import path once."""
    runtime_path = str(RUNTIME_DEPS_DIR)
    if runtime_path not in sys.path:
        sys.path.insert(0, runtime_path)


def _pip_install(spec: str, target: Path) -> bool:
    """Install package spec into target dir using current Python."""
    target.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--target",
        str(target),
        "--upgrade",
        "--no-cache-dir",
        spec,
    ]
    logger.info("Installing missing dep via pip: %s -> %s", spec, target)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180.0,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as err:
        logger.error("pip install failed for %s: %s", spec, err)
        return False

    if result.returncode != 0:
        logger.error(
            "pip install for %s exited %s; stderr: %s",
            spec,
            result.returncode,
            (result.stderr or "").strip()[:500],
        )
        return False
    return True


def _is_bundled_app() -> bool:
    """True inside the py2app bundle (its bootstrap sets ``sys.frozen``)."""
    return bool(getattr(sys, "frozen", False))


def importable(module_name: str) -> bool:
    """Passive probe: is the module importable (runtime-deps dir included)?

    Never installs and never imports the module body — safe on hot paths
    where ``ensure_importable``'s pip fallback would block on the network.
    """
    _ensure_runtime_dir_on_path()
    import importlib.util

    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):  # pragma: no cover - defensive
        return False


def ensure_importable(module_name: str) -> bool:
    """Ensure module can be imported, installing best-effort if needed."""
    _ensure_runtime_dir_on_path()

    try:
        __import__(module_name)
        return True
    except ImportError:
        pass

    spec = SAFEGUARDED_PACKAGES.get(module_name)
    if not spec:
        logger.warning("No install spec registered for %s", module_name)
        return False

    if _is_bundled_app():
        # The bundled interpreter ships without pip — `python -m pip` can only
        # fail (and used to log an ERROR on every launch). Optional deps stay
        # unavailable in the bundle until they ship inside it.
        logger.debug(
            "Skipping pip auto-install for %s — bundled app has no pip", spec
        )
        return False

    if not _pip_install(spec, RUNTIME_DEPS_DIR):
        return False

    try:
        __import__(module_name)
        logger.info("Runtime safeguard restored %s", module_name)
        return True
    except ImportError as err:
        logger.error("Still cannot import %s after install: %s", module_name, err)
        return False
