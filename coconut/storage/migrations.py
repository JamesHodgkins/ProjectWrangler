"""Versioned schema migrations for .coco SQLite files.

Each migration is a plain SQL script applied once, in order, tracked via
the schema_version table. New schema changes append a new entry here
rather than editing existing ones, so existing .coco files upgrade
in place instead of breaking.
"""

from __future__ import annotations

import sqlite3

MIGRATIONS: list[str] = [
    # version 1
    """
    CREATE TABLE schema_version (
        version INTEGER NOT NULL
    );

    CREATE TABLE project (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        name TEXT NOT NULL,
        start_date TEXT NOT NULL,
        working_weekdays TEXT NOT NULL,
        non_working_dates TEXT NOT NULL
    );

    CREATE TABLE tasks (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        duration_days REAL NOT NULL
    );

    CREATE TABLE dependencies (
        predecessor_id INTEGER NOT NULL REFERENCES tasks(id),
        successor_id INTEGER NOT NULL REFERENCES tasks(id),
        type TEXT NOT NULL,
        lag_days REAL NOT NULL,
        PRIMARY KEY (predecessor_id, successor_id)
    );

    CREATE TABLE resources (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        rate REAL NOT NULL,
        max_units REAL NOT NULL
    );

    CREATE TABLE assignments (
        task_id INTEGER NOT NULL REFERENCES tasks(id),
        resource_id INTEGER NOT NULL REFERENCES resources(id),
        units REAL NOT NULL,
        PRIMARY KEY (task_id, resource_id)
    );

    CREATE TABLE baselines (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL
    );

    CREATE TABLE baseline_task_snapshots (
        baseline_id INTEGER NOT NULL REFERENCES baselines(id),
        task_id INTEGER NOT NULL,
        start_date TEXT NOT NULL,
        finish_date TEXT NOT NULL,
        duration_days REAL NOT NULL,
        PRIMARY KEY (baseline_id, task_id)
    );
    """,
    # version 2: progress tracking (Phase 5)
    """
    ALTER TABLE tasks ADD COLUMN percent_complete REAL NOT NULL DEFAULT 0.0;
    ALTER TABLE tasks ADD COLUMN actual_start TEXT;
    ALTER TABLE tasks ADD COLUMN actual_finish TEXT;
    """,
    # version 3: explicit WBS display order, independent of task.id.
    # Existing rows are backfilled in id order â€” the closest approximation
    # of prior behavior, since insertion order wasn't previously persisted.
    """
    ALTER TABLE tasks ADD COLUMN position INTEGER;
    UPDATE tasks SET position = (
        SELECT COUNT(*) FROM tasks AS earlier WHERE earlier.id <= tasks.id
    ) - 1;
    """,
    # version 4: date constraints (ASAP/ALAP/SNET/SNLT/FNET/FNLT/MSO/MFO).
    """
    ALTER TABLE tasks ADD COLUMN constraint_type TEXT NOT NULL DEFAULT 'ASAP';
    ALTER TABLE tasks ADD COLUMN constraint_date TEXT;
    """,
    # version 5: WBS hierarchy (Phase 7) â€” parent linkage. NULL means
    # top-level, so existing rows migrate to a flat hierarchy with no
    # parents with no data migration needed beyond the new column
    # defaulting to NULL. Sibling/display order is still the existing
    # `position` column (version 3) â€” hierarchy nests within that same
    # flat ordering rather than needing a second order column.
    """
    ALTER TABLE tasks ADD COLUMN parent_id INTEGER REFERENCES tasks(id);
    """,
    # version 6: task color shading â€” a preset palette key (see
    # ui.theme.TASK_COLOR_PALETTE), meaningful only on top-level tasks.
    # Every task has one (Task.color_id is a required str, not NULL) â€”
    # existing rows load as NULL here and repository.load() falls back to
    # the default color for those, so no SQL backfill is needed.
    """
    ALTER TABLE tasks ADD COLUMN color_id TEXT;
    """,
]


def current_version(conn: sqlite3.Connection) -> int:
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchall()
    if not tables:
        return 0
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    return row[0] if row else 0


def migrate(conn: sqlite3.Connection) -> None:
    version = current_version(conn)
    for next_version, script in enumerate(MIGRATIONS[version:], start=version + 1):
        conn.executescript(script)
        if next_version == 1:
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (next_version,))
        else:
            conn.execute("UPDATE schema_version SET version = ?", (next_version,))
    conn.commit()
