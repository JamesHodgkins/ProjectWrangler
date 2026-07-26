"""Save/load a Project to/from a .coco SQLite file."""

from __future__ import annotations

import json
import sqlite3
from datetime import date

from coconut.core.calendar import Calendar
from coconut.core.models import (
    Assignment,
    Baseline,
    ConstraintType,
    Dependency,
    DependencyType,
    Resource,
    Task,
    TaskSnapshot,
)
from coconut.core.project import Project
from coconut.storage.migrations import migrate


def save(project: Project, path: str) -> None:
    conn = sqlite3.connect(path)
    try:
        migrate(conn)
        _clear_existing(conn)

        conn.execute(
            """
            INSERT OR REPLACE INTO project
                (id, name, start_date, working_weekdays, non_working_dates)
            VALUES (1, ?, ?, ?, ?)
            """,
            (
                project.name,
                project.start.isoformat(),
                json.dumps(sorted(project.calendar.working_weekdays)),
                json.dumps(sorted(d.isoformat() for d in project.calendar.non_working_dates)),
            ),
        )

        conn.executemany(
            """
            INSERT INTO tasks
                (id, name, duration_days, percent_complete, actual_start, actual_finish, position,
                 constraint_type, constraint_date, parent_id, color_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    t.id,
                    t.name,
                    t.duration_days,
                    t.percent_complete,
                    t.actual_start.isoformat() if t.actual_start else None,
                    t.actual_finish.isoformat() if t.actual_finish else None,
                    position,
                    t.constraint_type.value,
                    t.constraint_date.isoformat() if t.constraint_date else None,
                    t.parent_id,
                    t.color_id,
                )
                for position, t in enumerate(project.tasks)
            ],
        )

        conn.executemany(
            """
            INSERT INTO dependencies
                (predecessor_id, successor_id, type, lag_days)
            VALUES (?, ?, ?, ?)
            """,
            [
                (dep.predecessor_id, dep.successor_id, dep.type.value, dep.lag_days)
                for dep in project.dependencies
            ],
        )

        conn.executemany(
            "INSERT INTO resources (id, name, rate, max_units) VALUES (?, ?, ?, ?)",
            [(r.id, r.name, r.rate, r.max_units) for r in project.resources],
        )

        conn.executemany(
            "INSERT INTO assignments (task_id, resource_id, units) VALUES (?, ?, ?)",
            [(a.task_id, a.resource_id, a.units) for a in project.assignments],
        )

        conn.executemany(
            "INSERT INTO baselines (id, name) VALUES (?, ?)",
            [(b.id, b.name) for b in project.baselines],
        )

        conn.executemany(
            """
            INSERT INTO baseline_task_snapshots
                (baseline_id, task_id, start_date, finish_date, duration_days)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (b.id, snap.task_id, snap.start.isoformat(), snap.finish.isoformat(), snap.duration_days)
                for b in project.baselines
                for snap in b.task_snapshots.values()
            ],
        )

        conn.commit()
    finally:
        conn.close()


def load(path: str) -> Project:
    conn = sqlite3.connect(path)
    try:
        migrate(conn)

        row = conn.execute(
            "SELECT name, start_date, working_weekdays, non_working_dates FROM project WHERE id = 1"
        ).fetchone()
        name, start_date, working_weekdays_json, non_working_dates_json = row

        calendar = Calendar(
            non_working_dates={date.fromisoformat(d) for d in json.loads(non_working_dates_json)},
            working_weekdays=frozenset(json.loads(working_weekdays_json)),
        )
        project = Project(name=name, calendar=calendar, start=date.fromisoformat(start_date))

        for (
            task_id,
            task_name,
            duration_days,
            percent_complete,
            actual_start,
            actual_finish,
            constraint_type,
            constraint_date,
            parent_id,
            color_id,
        ) in conn.execute(
            "SELECT id, name, duration_days, percent_complete, actual_start, actual_finish, "
            "constraint_type, constraint_date, parent_id, color_id FROM tasks ORDER BY position"
        ):
            project.add_task(
                Task(
                    id=task_id,
                    name=task_name,
                    duration_days=duration_days,
                    percent_complete=percent_complete,
                    actual_start=date.fromisoformat(actual_start) if actual_start else None,
                    actual_finish=date.fromisoformat(actual_finish) if actual_finish else None,
                    constraint_type=ConstraintType(constraint_type),
                    constraint_date=date.fromisoformat(constraint_date) if constraint_date else None,
                    parent_id=parent_id,
                    # Older .coco files (or a NULL from before every task
                    # was guaranteed a color) fall back to Task.color_id's
                    # own default ("red", see core.models.Task) Ã¢â‚¬â€ it's a
                    # required str, never None, so omit the kwarg entirely
                    # rather than passing along a stray NULL.
                    **({"color_id": color_id} if color_id is not None else {}),
                )
            )

        for pred_id, succ_id, dep_type, lag_days in conn.execute(
            "SELECT predecessor_id, successor_id, type, lag_days FROM dependencies"
        ):
            project.add_dependency(
                Dependency(
                    predecessor_id=pred_id,
                    successor_id=succ_id,
                    type=DependencyType(dep_type),
                    lag_days=lag_days,
                )
            )

        for res_id, res_name, rate, max_units in conn.execute(
            "SELECT id, name, rate, max_units FROM resources"
        ):
            project.add_resource(Resource(id=res_id, name=res_name, rate=rate, max_units=max_units))

        for task_id, resource_id, units in conn.execute(
            "SELECT task_id, resource_id, units FROM assignments"
        ):
            project.add_assignment(Assignment(task_id=task_id, resource_id=resource_id, units=units))

        snapshots_by_baseline: dict[int, dict[int, TaskSnapshot]] = {}
        for baseline_id, task_id, start_date_str, finish_date_str, duration_days in conn.execute(
            "SELECT baseline_id, task_id, start_date, finish_date, duration_days FROM baseline_task_snapshots"
        ):
            snapshots_by_baseline.setdefault(baseline_id, {})[task_id] = TaskSnapshot(
                task_id=task_id,
                start=date.fromisoformat(start_date_str),
                finish=date.fromisoformat(finish_date_str),
                duration_days=duration_days,
            )

        for baseline_id, baseline_name in conn.execute("SELECT id, name FROM baselines"):
            project.add_baseline(
                Baseline(
                    id=baseline_id,
                    name=baseline_name,
                    task_snapshots=snapshots_by_baseline.get(baseline_id, {}),
                )
            )

        return project
    finally:
        conn.close()


def _clear_existing(conn: sqlite3.Connection) -> None:
    for table in ("assignments", "dependencies", "tasks", "resources", "baseline_task_snapshots", "baselines"):
        conn.execute(f"DELETE FROM {table}")
