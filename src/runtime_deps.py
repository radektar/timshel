"""Runtime safeguards for Python dependencies in bundled app."""

from __future__ import annotations

import subprocess
import sys
from importlib import metadata as _importlib_metadata
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
    # NOT a hard requirement, so the base install stays light. Both are pre-1.0,
    # so they are pinned to the versions the suite runs against
    # (requirements-dev.txt carries the same pins).
    "fastembed": "fastembed==0.8.0",
    "sqlite_vec": "sqlite-vec==0.1.9",
}

# Modules already loaded at a drifted version — warned about once per process,
# because the callers construct stores and providers repeatedly and this log
# is the one a tester is asked to read.
_DRIFT_WARNED: set[str] = set()


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


def _runtime_dir_version(dist_name: str) -> str | None:
    """Version of ``dist_name`` as installed in RUNTIME_DEPS_DIR, if any.

    Scoped to that directory on purpose: a bare ``metadata.version`` resolves
    against the whole sys.path and would report a dev venv's copy.
    """
    try:
        dists = _importlib_metadata.distributions(path=[str(RUNTIME_DEPS_DIR)])
        for dist in dists:
            name = dist.metadata["Name"] or ""
            if name.replace("_", "-").lower() == dist_name.replace("_", "-").lower():
                return dist.version
    except OSError:  # pragma: no cover - unreadable runtime dir
        return None
    return None


def _repin_if_drifted(module_name: str, spec: str) -> None:
    """Reinstall an auto-installed dep that drifted off its ``==`` pin.

    Called BEFORE the module is imported — that is the only safe moment.
    Re-installing over a live import would swap the native extension under
    the running Python wrapper (a 0.1.6 sqlite-vec wrapper calling a 0.1.9
    ``vec0`` — the very skew the pin exists to prevent), so once something is
    in ``sys.modules`` this backs off to a warning instead.
    """
    if "==" not in spec:
        return
    dist_name, pinned = spec.split("==", 1)
    installed = _runtime_dir_version(dist_name)
    if installed is None or installed == pinned:
        return  # not ours to manage, or already at the pin

    if module_name in sys.modules:
        if module_name not in _DRIFT_WARNED:
            _DRIFT_WARNED.add(module_name)
            logger.warning(
                "%s is loaded at %s, pinned at %s — restart the app to re-pin",
                module_name,
                installed,
                pinned,
            )
        return

    logger.info(
        "Re-pinning %s: %s installed, %s pinned", module_name, installed, pinned
    )
    _pip_install(spec, RUNTIME_DEPS_DIR)


def ensure_importable(module_name: str) -> bool:
    """Ensure module can be imported, installing best-effort if needed."""
    _ensure_runtime_dir_on_path()

    spec = SAFEGUARDED_PACKAGES.get(module_name)

    # Repair a pre-pin auto-install while nothing of it is loaded yet.
    if spec and not _is_bundled_app():
        _repin_if_drifted(module_name, spec)

    try:
        __import__(module_name)
    except ImportError:
        pass
    else:
        return True

    if not spec:
        logger.warning("No install spec registered for %s", module_name)
        return False

    if _is_bundled_app():
        # The bundled interpreter ships without pip — `python -m pip` can only
        # fail (and used to log an ERROR on every launch). Optional deps stay
        # unavailable in the bundle until they ship inside it.
        logger.debug("Skipping pip auto-install for %s — bundled app has no pip", spec)
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
