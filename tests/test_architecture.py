"""Guards the core/ <-> storage/ <-> application/ <-> ui/ dependency chain.

Target dependency rule:
- core/ imports no coconut.storage, no coconut.application,
  no coconut.ui, no PySide6, no sqlite3. It is the pure domain
  layer: models, scheduler, calendar, allocation, variance, leveling,
  commands, the Project aggregate, and the domain exception hierarchy.
- storage/ may import core/, but not coconut.ui or
  coconut.application. It only knows how to persist/load a
  Project; it must not know Application exists.
- application/ may import core/ and storage/, but not PySide6 or
  coconut.ui. This is where Application (core/app.py's former
  home) and the read-model projections live â€” it is still Qt-free, just
  no longer part of the domain layer.
- ui/ may import coconut.application (the Application facade and
  its read-model DTOs) but must not import core.commands,
  storage.repository, core.scheduler, core.allocation, core.variance, or
  core.leveling directly â€” those are exactly the modules Application
  exists to stand in front of.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE_DIR = ROOT / "coconut" / "core"
STORAGE_DIR = ROOT / "coconut" / "storage"
APPLICATION_DIR = ROOT / "coconut" / "application"
UI_DIR = ROOT / "coconut" / "ui"

FORBIDDEN_CORE_IMPORT_PREFIXES = (
    "PySide6",
    "sqlite3",
    "coconut.storage",
    "coconut.application",
    "coconut.ui",
)
FORBIDDEN_STORAGE_IMPORT_PREFIXES = (
    "PySide6",
    "coconut.application",
    "coconut.ui",
)
FORBIDDEN_APPLICATION_IMPORT_PREFIXES = (
    "PySide6",
    "coconut.ui",
)
FORBIDDEN_UI_IMPORT_PREFIXES = (
    "coconut.core.commands",
    "coconut.storage.repository",
    "coconut.core.scheduler",
    "coconut.core.allocation",
    "coconut.core.variance",
    "coconut.core.leveling",
)


def _imported_module_names(source_path: Path) -> set[str]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _violations(directory: Path, forbidden_prefixes: tuple[str, ...]) -> list[str]:
    violations = []
    for py_file in directory.rglob("*.py"):
        for module_name in _imported_module_names(py_file):
            if module_name.startswith(forbidden_prefixes):
                violations.append(f"{py_file.relative_to(ROOT)}: imports {module_name}")
    return violations


def test_core_does_not_import_qt_sqlite_storage_application_or_ui():
    violations = _violations(CORE_DIR, FORBIDDEN_CORE_IMPORT_PREFIXES)
    assert not violations, (
        "core/ must stay a pure, storage-free, UI-free domain layer:\n" + "\n".join(violations)
    )


def test_storage_does_not_import_application_or_ui():
    violations = _violations(STORAGE_DIR, FORBIDDEN_STORAGE_IMPORT_PREFIXES)
    assert not violations, (
        "storage/ may depend on core/ but not application/ or ui/:\n" + "\n".join(violations)
    )


def test_application_does_not_import_qt_or_ui():
    violations = _violations(APPLICATION_DIR, FORBIDDEN_APPLICATION_IMPORT_PREFIXES)
    assert not violations, (
        "application/ may depend on core/ and storage/ but not Qt or ui/:\n" + "\n".join(violations)
    )


def test_ui_does_not_bypass_application_facade():
    violations = _violations(UI_DIR, FORBIDDEN_UI_IMPORT_PREFIXES)
    assert not violations, (
        "ui/ must go through application.app.Application, not commands/repository/"
        "scheduler/allocation/variance/leveling directly:\n" + "\n".join(violations)
    )
