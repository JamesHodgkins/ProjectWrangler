from datetime import date

import pytest

from coconut.core.calendar import Calendar
from coconut.core.commands import (
    AddAssignment,
    AddBaseline,
    AddDependency,
    AddResource,
    AddTask,
    MoveTask,
    SetTaskConstraint,
    SetTaskParent,
    SetTaskProgress,
)
from coconut.core.models import Assignment, ConstraintType, Dependency, DependencyType, Resource, Task
from coconut.core.project import Project
from coconut.storage.repository import load, save


@pytest.fixture
def pwproj_path(tmp_path):
    return str(tmp_path / "test.coco")


def test_round_trip_empty_project(pwproj_path):
    project = Project(name="Empty", start=date(2026, 1, 1))
    save(project, pwproj_path)
    loaded = load(pwproj_path)

    assert loaded.name == "Empty"
    assert loaded.start == date(2026, 1, 1)
    assert loaded.tasks == []


def test_round_trip_tasks_and_dependencies(pwproj_path):
    project = Project(name="Sample", start=date(2026, 1, 1))
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=3)))
    project.apply_command(AddTask(Task(id=2, name="B", duration_days=2)))
    project.apply_command(
        AddDependency(
            Dependency(
                predecessor_id=1,
                successor_id=2,
                type=DependencyType.START_TO_START,
                lag_days=1.5,
            )
        )
    )

    save(project, pwproj_path)
    loaded = load(pwproj_path)

    assert {t.id for t in loaded.tasks} == {1, 2}
    assert loaded.get_task(1) == Task(id=1, name="A", duration_days=3)
    dep = loaded.get_dependency(1, 2)
    assert dep.type == DependencyType.START_TO_START
    assert dep.lag_days == 1.5


def test_round_trip_task_color(pwproj_path):
    project = Project(name="Sample", start=date(2026, 1, 1))
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=3, color_id="peach")))
    project.apply_command(AddTask(Task(id=2, name="B", duration_days=2)))

    save(project, pwproj_path)
    loaded = load(pwproj_path)

    assert loaded.get_task(1).color_id == "peach"
    assert loaded.get_task(2).color_id == "red"


def test_round_trip_preserves_task_display_order(pwproj_path):
    project = Project(name="Sample", start=date(2026, 1, 1))
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=1)))
    project.apply_command(AddTask(Task(id=2, name="B", duration_days=1)))
    project.apply_command(AddTask(Task(id=3, name="C", duration_days=1)))
    project.apply_command(MoveTask(task_id=1, new_index=2))  # A, B, C -> B, C, A

    save(project, pwproj_path)
    loaded = load(pwproj_path)

    assert [t.id for t in loaded.tasks] == [2, 3, 1]


def test_round_trip_resources(pwproj_path):
    project = Project(name="Sample", start=date(2026, 1, 1))
    project.apply_command(AddResource(Resource(id=1, name="Alice", rate=50.0, max_units=1.0)))

    save(project, pwproj_path)
    loaded = load(pwproj_path)

    assert loaded.resources == [Resource(id=1, name="Alice", rate=50.0, max_units=1.0)]


def test_round_trip_assignments(pwproj_path):
    project = Project(name="Sample", start=date(2026, 1, 1))
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=1)))
    project.apply_command(AddResource(Resource(id=1, name="Alice")))
    project.apply_command(AddAssignment(Assignment(task_id=1, resource_id=1, units=0.5)))

    save(project, pwproj_path)
    loaded = load(pwproj_path)

    assert loaded.get_assignment(1, 1) == Assignment(task_id=1, resource_id=1, units=0.5)


def test_round_trip_task_progress_fields(pwproj_path):
    project = Project(name="Sample", start=date(2026, 1, 1))
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=3)))
    project.apply_command(
        SetTaskProgress(
            task_id=1,
            percent_complete=40.0,
            actual_start=date(2026, 1, 1),
            actual_finish=None,
        )
    )

    save(project, pwproj_path)
    loaded = load(pwproj_path)

    task = loaded.get_task(1)
    assert task.percent_complete == 40.0
    assert task.actual_start == date(2026, 1, 1)
    assert task.actual_finish is None


def test_round_trip_task_constraint(pwproj_path):
    project = Project(name="Sample", start=date(2026, 1, 1))
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=3)))
    project.apply_command(
        SetTaskConstraint(
            task_id=1,
            new_constraint_type=ConstraintType.FINISH_NO_LATER_THAN,
            new_constraint_date=date(2026, 1, 10),
        )
    )

    save(project, pwproj_path)
    loaded = load(pwproj_path)

    task = loaded.get_task(1)
    assert task.constraint_type == ConstraintType.FINISH_NO_LATER_THAN
    assert task.constraint_date == date(2026, 1, 10)


def test_round_trip_default_constraint_is_asap(pwproj_path):
    project = Project(name="Sample", start=date(2026, 1, 1))
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=3)))

    save(project, pwproj_path)
    loaded = load(pwproj_path)

    task = loaded.get_task(1)
    assert task.constraint_type == ConstraintType.AS_SOON_AS_POSSIBLE
    assert task.constraint_date is None


def test_round_trip_baseline(pwproj_path):
    project = Project(name="Sample", start=date(2026, 1, 1))
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=3)))
    baseline = project.build_baseline_snapshot(baseline_id=1, name="Baseline 1")
    project.apply_command(AddBaseline(baseline))

    save(project, pwproj_path)
    loaded = load(pwproj_path)

    loaded_baseline = loaded.get_baseline(1)
    assert loaded_baseline.name == "Baseline 1"
    assert loaded_baseline.task_snapshots[1].duration_days == 3
    assert loaded_baseline.task_snapshots[1].start == baseline.task_snapshots[1].start


def test_round_trip_preserves_calendar(pwproj_path):
    calendar = Calendar(
        non_working_dates={date(2026, 1, 1), date(2026, 12, 25)},
        working_weekdays=frozenset({0, 1, 2, 3, 4}),
    )
    project = Project(name="Sample", calendar=calendar, start=date(2026, 1, 1))

    save(project, pwproj_path)
    loaded = load(pwproj_path)

    assert loaded.calendar.working_weekdays == frozenset({0, 1, 2, 3, 4})
    assert loaded.calendar.non_working_dates == {date(2026, 1, 1), date(2026, 12, 25)}


def test_save_overwrites_previous_state(pwproj_path):
    project = Project(name="First", start=date(2026, 1, 1))
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=1)))
    save(project, pwproj_path)

    project2 = Project(name="Second", start=date(2026, 2, 1))
    project2.apply_command(AddTask(Task(id=5, name="Z", duration_days=2)))
    save(project2, pwproj_path)

    loaded = load(pwproj_path)
    assert loaded.name == "Second"
    assert [t.id for t in loaded.tasks] == [5]


def test_computed_schedule_matches_after_round_trip(pwproj_path):
    project = Project(name="Sample", start=date(2026, 1, 1))
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=3)))
    project.apply_command(AddTask(Task(id=2, name="B", duration_days=2)))
    project.apply_command(AddDependency(Dependency(predecessor_id=1, successor_id=2)))

    save(project, pwproj_path)
    loaded = load(pwproj_path)

    original_schedule = project.compute_schedule()
    loaded_schedule = loaded.compute_schedule()
    assert original_schedule[2].early_start == loaded_schedule[2].early_start


def test_round_trip_task_hierarchy(pwproj_path):
    project = Project(name="Sample", start=date(2026, 1, 1))
    project.apply_command(AddTask(Task(id=1, name="Parent", duration_days=1)))
    project.apply_command(AddTask(Task(id=2, name="Child", duration_days=1)))
    project.apply_command(SetTaskParent(task_id=2, new_parent_id=1))

    save(project, pwproj_path)
    loaded = load(pwproj_path)

    assert loaded.get_task(1).parent_id is None
    assert loaded.get_task(2).parent_id == 1
    assert [c.id for c in loaded.children_of(1)] == [2]


def test_round_trip_flat_project_has_no_parents(pwproj_path):
    project = Project(name="Sample", start=date(2026, 1, 1))
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=1)))
    project.apply_command(AddTask(Task(id=2, name="B", duration_days=1)))

    save(project, pwproj_path)
    loaded = load(pwproj_path)

    assert all(t.parent_id is None for t in loaded.tasks)


def test_older_schema_migrates_tasks_to_flat_hierarchy(pwproj_path):
    """A .coco created before the parent_id column existed (schema
    version 4) must migrate cleanly to a flat hierarchy (all parent_id
    None), not fail to load or default to some other value."""
    import sqlite3

    from coconut.storage.migrations import MIGRATIONS

    conn = sqlite3.connect(pwproj_path)
    try:
        for script in MIGRATIONS[:4]:
            conn.executescript(script)
        conn.execute("INSERT INTO schema_version (version) VALUES (1)")
        conn.execute("UPDATE schema_version SET version = 4")
        conn.execute(
            "INSERT INTO project (id, name, start_date, working_weekdays, non_working_dates) "
            "VALUES (1, 'Legacy', '2026-01-01', '[0,1,2,3,4]', '[]')"
        )
        conn.execute(
            "INSERT INTO tasks (id, name, duration_days, position, constraint_type) "
            "VALUES (1, 'A', 3, 0, 'ASAP')"
        )
        conn.commit()
    finally:
        conn.close()

    loaded = load(pwproj_path)
    assert loaded.get_task(1).parent_id is None
