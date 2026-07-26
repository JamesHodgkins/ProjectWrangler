# Coconut

A desktop project-management application in the spirit of Microsoft Project, Primavera P6, and ProjectLibre. Coconut is a WBS/Gantt scheduling tool with critical path analysis, resource management, and baseline tracking, built as a local single-user desktop app.

## Features

- **WBS task table** with inline editing of duration and predecessors (`2FS+1, 3SS-2` syntax, entered by row position)
- **Multi-level WBS hierarchy** — indent/outdent tasks into summary/subtask groupings, with automatic outline numbering and rollup of summary task dates, duration, and % complete
- **CPM scheduling engine** — forward/backward pass, total float, and critical path highlighting, supporting all four standard dependency types (FS, SS, FF, SF) with lag/lead, plus all 8 MS Project constraint types (including cascading ALAP resolution)
- **Gantt chart view** with critical path highlighting and dependency arrows
- **Resource management** — resource sheet, task assignments, and over-allocation detection with visual highlighting
- **Resource leveling** — a greedy, delay-based leveling pass (not yet exposed through the UI)
- **Baselines and progress tracking** — capture a baseline snapshot, track % complete and actual start/finish, and view variance (current vs. baseline) in a dedicated table and tracking Gantt
- **Undo/redo** for all project edits, implemented via a command pattern
- **Light/dark theme** support
- Local project files stored as SQLite (`.coco`), with a versioned, append-only migration system

## Tech Stack

- **Language:** Python 3.14
- **GUI:** [PySide6](https://pypi.org/project/PySide6/) (Qt for Python)
- **Storage:** SQLite via the standard library `sqlite3` module — no ORM
- **Scheduling engine:** plain Python, decoupled from the GUI so it can be unit-tested independently
- **Testing:** [pytest](https://pypi.org/project/pytest/)

The codebase enforces a strict one-directional dependency layering (`core/` → `storage/` / `application/` → `ui/`), checked by an automated architecture test (`tests/test_architecture.py`) that fails the build on a violation. See [PROJECT_PLAN.md](PROJECT_PLAN.md) for the full architecture and phased roadmap.

## Prerequisites

- Python 3.14 (or a compatible 3.x version)
- Windows, macOS, or Linux with a Qt-compatible display environment

## Installation & Setup

```bash
# Clone the repository
git clone <repository-url>
cd Coconut

# Create and activate a virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

Run the application directly with Python:

```bash
python main.py
```

On Windows, `launch.bat` is provided as a convenience script that launches the app using the project's `venv` without requiring manual activation:

```bash
launch.bat
```

Project files are saved with a `.coco` extension (SQLite format).

### Running tests

```bash
pytest
```

## Current Status / Known Limitations

Coconut is under active development. The core scheduling engine, persistence layer, WBS hierarchy, resource assignment, and baseline/variance tracking are functional and covered by an automated test suite (138 tests as of this writing). The following are known gaps:

- **Resource-driven scheduling** is not implemented — task durations are fixed inputs and do not yet recalculate based on assigned units/work (Fixed Duration / Fixed Units / Fixed Work task types are planned).
- **Resource leveling** exists in the engine (`core/leveling.py`) but is not yet wired to any UI action.
- **Per-resource calendars** are not implemented; only a single global calendar is supported.
- **Task splitting and recurring tasks** are not implemented.
- **Only a single active baseline** is supported (no multiple baseline slots).
- **No file-format interoperability** yet — import/export for MS Project (XML/MPP) and Primavera P6 (XER/XML) formats is planned but not started.
- **No reporting/export** (CSV, PDF/image) yet.
- **No concurrency/worker boundary** — scheduling, file I/O, and other potentially expensive operations currently run on the UI thread. This is acceptable at the target scale (projects up to a few thousand tasks) but is a known architectural gap for larger operations like import/export.
- **No packaging/distribution** — the app currently runs from source only; there is no standalone installer or executable.
- Static analysis tooling (`mypy --strict`, import layering enforcement via a dedicated linter) is not yet integrated into a CI pipeline; layering rules are currently enforced only via `tests/test_architecture.py`.

See [PROJECT_PLAN.md](PROJECT_PLAN.md) for the complete phased roadmap, scope decisions, and open risks.

## License

MIT License — see [LICENSE](LICENSE) for the full text.

This project depends on [PySide6](https://pypi.org/project/PySide6/), which is licensed under the LGPLv3 (or a commercial Qt license). PySide6 is used as an unmodified, dynamically-linked dependency; its own license terms apply to that library independently of Coconut's MIT license.
