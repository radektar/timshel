"""Version consistency checks for release metadata."""

import ast
from pathlib import Path

from src.ui.constants import APP_VERSION as UI_APP_VERSION


def _read_setup_app_version() -> str:
    setup_path = Path(__file__).resolve().parents[1] / "setup_app.py"
    module = ast.parse(setup_path.read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "APP_VERSION":
                    value = node.value
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        return value.value
    raise AssertionError("APP_VERSION not found in setup_app.py")


def test_app_version_is_synced_between_setup_and_ui() -> None:
    """UI and bundled metadata must expose the same app version."""
    assert _read_setup_app_version() == UI_APP_VERSION


# Docs that state the current version in their header. They drifted ten
# releases behind (beta.8 while the code shipped beta.17) because nothing
# checked them — a tester reading README saw a version that never existed
# on their machine.
_VERSIONED_DOCS = (
    "README.md",
    "CLAUDE.md",
    "Docs/API.md",
    "Docs/ARCHITECTURE.md",
    "Docs/DEVELOPMENT.md",
    "Docs/TESTING-GUIDE.md",
)


def test_docs_headers_state_the_current_version() -> None:
    """Every doc header claiming a version must claim the current one."""
    repo = Path(__file__).resolve().parents[1]
    version = _read_setup_app_version()
    stale = []
    for rel in _VERSIONED_DOCS:
        # The header is in the first few lines; later mentions are history.
        head = "\n".join((repo / rel).read_text(encoding="utf-8").splitlines()[:15])
        if f"v{version}" not in head:
            stale.append(rel)
    assert not stale, f"doc headers not on v{version}: {stale}"
