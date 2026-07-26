"""Tests for the Project domain aggregate.

Project has no undo/redo history of its own (see application/app.py) â€” these
tests apply commands via project.apply_command() and, where a command's
inverse is exercised, call command.undo(project) directly rather than
project.undo(). Undo/redo *stack* behavior (history, redo-clearing,
rollback-on-failure) is Application's responsibility and is covered in
tests/test_app.py instead.
"""

from datetime import date

import pytest

from coconut.core.commands import (
    AddAssignment,
    AddBaseline,
    AddDependency,
    AddResource,
    AddTask,
    EditTaskDuration,
    MoveTask,
    RemoveAssignment,
    RemoveBaseline,
    RemoveDependency,
    RemoveResource,
    RemoveTask,
    SetProjectStart,
    SetTaskColor,
    SetTaskConstraint,
    SetTaskParent,
    SetTaskProgress,
)
from coconut.core.models import Assignment, ConstraintType, Dependency, Resource, Task
from coconut.core.project import Project

PROJECT_START = date(2026, 1, 1)


@pytest.fixture
def project():
    return Project(name="Test Project", start=PROJECT_START)


def test_add_task_via_command(project):
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=3)))
    assert [t.id for t in project.tasks] == [1]


def test_undo_add_task(project):
    command = AddTask(Task(id=1, name="A", duration_days=3))
    project.apply_command(command)
    command.undo(project)
    assert project.tasks == []


def test_remove_task_undo_restores_task_and_dependencies(project):
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=3)))
    project.apply_command(AddTask(Task(id=2, name="B", duration_days=2)))
    project.apply_command(AddDependency(Dependency(predecessor_id=1, successor_id=2)))

    remove = RemoveTask(task_id=1)
    project.apply_command(remove)
    assert project.get_task(2) is not None
    assert project.dependencies_for_task(2) == []

    remove.undo(project)
    assert project.get_task(1).name == "A"
    assert len(project.dependencies_for_task(1)) == 1


def test_move_task_changes_display_order_not_ids(project):
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=1)))
    project.apply_command(AddTask(Task(id=2, name="B", duration_days=1)))
    project.apply_command(AddTask(Task(id=3, name="C", duration_days=1)))

    project.apply_command(MoveTask(task_id=1, new_index=2))

    assert [t.id for t in project.tasks] == [2, 3, 1]
    assert project.task_position(1) == 2
    assert project.task_id_at_position(0) == 2


def test_undo_move_task_restores_order(project):
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=1)))
    project.apply_command(AddTask(Task(id=2, name="B", duration_days=1)))
    move = MoveTask(task_id=1, new_index=1)
    project.apply_command(move)

    move.undo(project)
    assert [t.id for t in project.tasks] == [1, 2]


def test_move_task_does_not_affect_dependencies(project):
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=1)))
    project.apply_command(AddTask(Task(id=2, name="B", duration_days=1)))
    project.apply_command(AddDependency(Dependency(predecessor_id=1, successor_id=2)))

    project.apply_command(MoveTask(task_id=1, new_index=1))

    dep = project.get_dependency(1, 2)
    assert dep.predecessor_id == 1 and dep.successor_id == 2


def test_remove_task_undo_restores_original_position(project):
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=1)))
    project.apply_command(AddTask(Task(id=2, name="B", duration_days=1)))
    project.apply_command(AddTask(Task(id=3, name="C", duration_days=1)))

    remove = RemoveTask(task_id=2)
    project.apply_command(remove)
    assert [t.id for t in project.tasks] == [1, 3]

    remove.undo(project)
    assert [t.id for t in project.tasks] == [1, 2, 3]


def test_edit_task_duration_and_undo(project):
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=3)))
    edit = EditTaskDuration(task_id=1, new_duration_days=5)
    project.apply_command(edit)
    assert project.get_task(1).duration_days == 5

    edit.undo(project)
    assert project.get_task(1).duration_days == 3


def test_add_and_remove_dependency(project):
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=1)))
    project.apply_command(AddTask(Task(id=2, name="B", duration_days=1)))
    dep = Dependency(predecessor_id=1, successor_id=2)
    project.apply_command(AddDependency(dep))
    assert project.get_dependency(1, 2) == dep

    remove_dep = RemoveDependency(predecessor_id=1, successor_id=2)
    project.apply_command(remove_dep)
    with pytest.raises(KeyError):
        project.get_dependency(1, 2)

    remove_dep.undo(project)
    assert project.get_dependency(1, 2) == dep


def test_add_resource(project):
    project.apply_command(AddResource(Resource(id=1, name="Alice")))
    assert [r.id for r in project.resources] == [1]


def test_remove_resource_undo_restores_resource_and_assignments(project):
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=1)))
    project.apply_command(AddResource(Resource(id=1, name="Alice")))
    project.apply_command(AddAssignment(Assignment(task_id=1, resource_id=1)))

    remove = RemoveResource(resource_id=1)
    project.apply_command(remove)
    assert project.resources == []
    assert project.assignments_for_task(1) == []

    remove.undo(project)
    assert project.get_resource(1).name == "Alice"
    assert len(project.assignments_for_task(1)) == 1


def test_add_and_remove_assignment(project):
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=1)))
    project.apply_command(AddResource(Resource(id=1, name="Alice")))
    assignment = Assignment(task_id=1, resource_id=1, units=0.5)
    project.apply_command(AddAssignment(assignment))
    assert project.get_assignment(1, 1) == assignment

    remove = RemoveAssignment(task_id=1, resource_id=1)
    project.apply_command(remove)
    with pytest.raises(KeyError):
        project.get_assignment(1, 1)

    remove.undo(project)
    assert project.get_assignment(1, 1) == assignment


def test_remove_task_also_removes_its_assignments(project):
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=1)))
    project.apply_command(AddResource(Resource(id=1, name="Alice")))
    project.apply_command(AddAssignment(Assignment(task_id=1, resource_id=1)))

    project.apply_command(RemoveTask(task_id=1))
    assert project.assignments == []


def test_set_task_progress_and_undo(project):
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=5)))
    progress = SetTaskProgress(task_id=1, percent_complete=50.0, actual_start=PROJECT_START, actual_finish=None)
    project.apply_command(progress)
    task = project.get_task(1)
    assert task.percent_complete == 50.0
    assert task.actual_start == PROJECT_START

    progress.undo(project)
    task = project.get_task(1)
    assert task.percent_complete == 0.0
    assert task.actual_start is None


def test_edit_task_duration_preserves_progress_fields(project):
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=5)))
    project.apply_command(
        SetTaskProgress(task_id=1, percent_complete=25.0, actual_start=PROJECT_START, actual_finish=None)
    )
    project.apply_command(EditTaskDuration(task_id=1, new_duration_days=8))

    task = project.get_task(1)
    assert task.duration_days == 8
    assert task.percent_complete == 25.0
    assert task.actual_start == PROJECT_START


def test_set_task_constraint_and_undo(project):
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=5)))
    constraint = SetTaskConstraint(
        task_id=1, new_constraint_type=ConstraintType.MUST_START_ON, new_constraint_date=PROJECT_START
    )
    project.apply_command(constraint)
    task = project.get_task(1)
    assert task.constraint_type == ConstraintType.MUST_START_ON
    assert task.constraint_date == PROJECT_START

    constraint.undo(project)
    task = project.get_task(1)
    assert task.constraint_type == ConstraintType.AS_SOON_AS_POSSIBLE
    assert task.constraint_date is None


def test_set_task_color_and_undo(project):
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=5)))
    color = SetTaskColor(task_id=1, new_color_id="peach")
    project.apply_command(color)
    assert project.get_task(1).color_id == "peach"

    color.undo(project)
    assert project.get_task(1).color_id == "red"


def test_set_project_start_and_undo(project):
    new_start = date(2026, 2, 1)
    set_start = SetProjectStart(new_start)
    project.apply_command(set_start)
    assert project.start == new_start

    set_start.undo(project)
    assert project.start == PROJECT_START


def test_set_project_start_cascades_unconstrained_tasks(project):
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=3)))
    new_start = date(2026, 2, 1)
    project.apply_command(SetProjectStart(new_start))

    schedule = project.compute_schedule()
    assert schedule[1].early_start == new_start


def test_add_and_remove_baseline(project):
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=3)))
    baseline = project.build_baseline_snapshot(baseline_id=1, name="Baseline 1")
    project.apply_command(AddBaseline(baseline))

    assert project.get_baseline(1).name == "Baseline 1"
    assert 1 in project.get_baseline(1).task_snapshots

    remove = RemoveBaseline(baseline_id=1)
    project.apply_command(remove)
    with pytest.raises(KeyError):
        project.get_baseline(1)

    remove.undo(project)
    assert project.get_baseline(1).name == "Baseline 1"


def test_compute_schedule_reflects_current_tasks(project):
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=3)))
    project.apply_command(AddTask(Task(id=2, name="B", duration_days=2)))
    project.apply_command(AddDependency(Dependency(predecessor_id=1, successor_id=2)))

    result = project.compute_schedule()
    # FS with zero lag: successor starts the working day after the
    # predecessor's finish (which is itself the predecessor's last worked
    # day), not on the same day.
    assert result[2].early_start == project.calendar.add_days(result[1].early_finish, 1)
    assert result[1].is_critical and result[2].is_critical


def test_set_task_parent_and_undo(project):
    project.apply_command(AddTask(Task(id=1, name="Parent", duration_days=1)))
    project.apply_command(AddTask(Task(id=2, name="Child", duration_days=1)))

    set_parent = SetTaskParent(task_id=2, new_parent_id=1)
    project.apply_command(set_parent)
    assert project.get_task(2).parent_id == 1
    assert [c.id for c in project.children_of(1)] == [2]

    set_parent.undo(project)
    assert project.get_task(2).parent_id is None


def test_remove_task_reparents_children_to_removed_tasks_parent(project):
    project.apply_command(AddTask(Task(id=1, name="Grandparent", duration_days=1)))
    project.apply_command(AddTask(Task(id=2, name="Parent", duration_days=1)))
    project.apply_command(AddTask(Task(id=3, name="Child", duration_days=1)))
    project.apply_command(SetTaskParent(task_id=2, new_parent_id=1))
    project.apply_command(SetTaskParent(task_id=3, new_parent_id=2))

    project.apply_command(RemoveTask(task_id=2))

    # Child (3) is re-parented to Grandparent (1), the removed task's own parent.
    assert project.get_task(3).parent_id == 1


def test_remove_task_undo_restores_childrens_parent(project):
    project.apply_command(AddTask(Task(id=1, name="Parent", duration_days=1)))
    project.apply_command(AddTask(Task(id=2, name="Child", duration_days=1)))
    project.apply_command(SetTaskParent(task_id=2, new_parent_id=1))

    remove = RemoveTask(task_id=1)
    project.apply_command(remove)
    assert project.get_task(2).parent_id is None

    remove.undo(project)
    assert project.get_task(2).parent_id == 1
