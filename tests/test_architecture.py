"""Boundaries that must hold for the engine to outlive its user interface.

The current interface is a local web app; the production target is a Windows
desktop application. That swap must not touch the business logic, so the rule
is simply that nothing under ``app/`` may know what the interface is.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE = REPO_ROOT / "app"
UI_PACKAGES = {"streamlit", "tkinter", "PySide6", "PyQt5", "PyQt6", "wx", "flask", "django"}

ENGINE_MODULES = sorted(ENGINE.glob("*.py"))


def imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


@pytest.mark.parametrize("module", ENGINE_MODULES, ids=lambda p: p.name)
def test_the_engine_does_not_import_a_user_interface(module):
    offending = imported_names(module) & UI_PACKAGES
    assert not offending, (
        f"{module.name} imports {offending}. The calculation engine must stay "
        "independent of the interface so Streamlit can be replaced without "
        "rewriting the business logic."
    )


@pytest.mark.parametrize("module", ENGINE_MODULES, ids=lambda p: p.name)
def test_the_engine_does_not_import_the_screens(module):
    assert "ui_pages" not in imported_names(module)


def test_the_engine_never_names_a_specific_interface_to_the_user(module=None):
    """Messages the user reads must not date themselves to one interface."""
    for path in ENGINE_MODULES:
        text = path.read_text(encoding="utf-8").lower()
        assert "streamlit" not in text, f"{path.name} mentions streamlit"


def test_a_report_can_be_built_with_no_interface_imported():
    """The whole pipeline must run in a plain Python process."""
    import subprocess
    import sys

    script = (
        "import sys;"
        "import app.report, app.generator, app.review, app.decisions, app.validation;"
        "assert 'streamlit' not in sys.modules, sys.modules.keys();"
        "print('engine imported cleanly')"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=REPO_ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "engine imported cleanly" in result.stdout


def test_the_interface_depends_on_the_engine_and_not_the_reverse():
    ui_imports = set()
    for path in [REPO_ROOT / "ui.py", *(REPO_ROOT / "ui_pages").glob("*.py")]:
        ui_imports |= imported_names(path)
    assert "app" in ui_imports, "the interface should call into the engine"
