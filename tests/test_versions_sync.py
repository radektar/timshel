"""Version consistency checks for release metadata."""

import ast
import re
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
    "Docs/FULL_DISK_ACCESS_SETUP.md",
)

# Whole version tokens only. A substring check would pass `v2.0.0` against a
# header still saying `v2.0.0-beta.18` — going blind at the GA bump, the one
# release it most needs to catch.
# The pre-release suffix must not swallow sentence punctuation: a greedy
# `[0-9A-Za-z.]+` turns "v2.0.0-beta.18." into a token with a trailing dot.
_VERSION_TOKEN = re.compile(r"v\d+\.\d+\.\d+(?:-[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)?")

# The line that states what the doc describes ("> **Version:** …" /
# "- Current version: …"). Checking a whole 15-line head is not enough:
# README and CLAUDE also name the GA target on that same line ("→ v2.0.0 (in
# preparation)"), so at the GA bump the target token would satisfy an
# any-token check while the stated version stayed on beta.18.
_VERSION_LINE = re.compile(r"^\W*(?:\*\*)?(?:Current version|Version)(?:\*\*)?:", re.I)


def _stated_version(head_lines: list[str]) -> str | None:
    """First version token on the doc's version line — what it claims to be."""
    for line in head_lines:
        if _VERSION_LINE.match(line.strip()):
            match = _VERSION_TOKEN.search(line)
            return match.group(0) if match else None
    return None


def test_docs_headers_state_the_current_version() -> None:
    """Every doc header claiming a version must claim the current one."""
    repo = Path(__file__).resolve().parents[1]
    version = _read_setup_app_version()
    stale = {}
    for rel in _VERSIONED_DOCS:
        # The header is in the first few lines; later mentions are history.
        head = (repo / rel).read_text(encoding="utf-8").splitlines()[:15]
        stated = _stated_version(head)
        if stated != f"v{version}":
            stale[rel] = stated or "<no version line>"
    assert not stale, f"doc headers not on v{version}: {stale}"
