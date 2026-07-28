"""Guards for bootstrap call ordering in entry points."""

from __future__ import annotations

import ast
from pathlib import Path


def _parse_module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _is_bootstrap_import(node: ast.stmt) -> bool:
    if not isinstance(node, ast.ImportFrom):
        return False
    if node.module != "src.bootstrap":
        return False
    return any(alias.name == "ensure_ready" for alias in node.names)


def _is_ensure_ready_call(node: ast.stmt) -> bool:
    if not isinstance(node, ast.Expr):
        return False
    if not isinstance(node.value, ast.Call):
        return False
    return (
        isinstance(node.value.func, ast.Name) and node.value.func.id == "ensure_ready"
    )


def _is_forbidden_import(node: ast.stmt) -> bool:
    if isinstance(node, ast.ImportFrom):
        mod = node.module or ""
        return mod.startswith("src.config") or mod.startswith("src.logger")
    if isinstance(node, ast.Import):
        return any(
            alias.name.startswith("src.config") or alias.name.startswith("src.logger")
            for alias in node.names
        )
    return False


def _assert_bootstrap_order(module_path: Path) -> None:
    parsed = _parse_module(module_path)
    bootstrap_index = None
    call_index = None

    for idx, stmt in enumerate(parsed.body):
        if _is_bootstrap_import(stmt) and bootstrap_index is None:
            bootstrap_index = idx
        if _is_ensure_ready_call(stmt) and call_index is None:
            call_index = idx

    assert bootstrap_index is not None, f"{module_path} must import ensure_ready"
    assert call_index is not None, f"{module_path} must call ensure_ready()"
    assert (
        call_index > bootstrap_index
    ), f"{module_path} must call ensure_ready after import"

    for idx, stmt in enumerate(parsed.body):
        if _is_forbidden_import(stmt):
            assert (
                idx > call_index
            ), f"{module_path} imports config/logger before ensure_ready()"


def test_main_calls_bootstrap_before_config_imports():
    """`src/main.py` must call bootstrap before config/logger imports."""
    _assert_bootstrap_order(Path("src/main.py"))


def test_menu_app_calls_bootstrap_before_config_imports():
    """`src/menu_app.py` must call bootstrap before config/logger imports."""
    _assert_bootstrap_order(Path("src/menu_app.py"))
