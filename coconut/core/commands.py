"""Invertible commands for mutating a Project.

One class per mutation type (not a single Command with a type enum) so
each command's apply/undo logic stays small and undo/redo (Phase 7) is a
simple stack of these rather than a dispatch table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from datetime import date

from coconut.core.models import Assignment, Baseline, ConstraintType, Dependency, Resource, Task

if TYPE_CHECKING:
    from coconut.core.project import Project


class Command(Protocol):
    def apply(self, project: "Project") -> None: ...
    def undo(self, project: "Project") -> None: ...


@dataclass
class AddTask:
    task: Task

    def apply(self, project: "Project") -> None:
        project.add_task(self.task)

    def undo(self, project: "Project") -> None:
        project.remove_task(self.task.id)


@dataclass
class RemoveTask:
    task_id: int
    _removed_task: Task | None = None
    _removed_position: int | None = None
    _removed_dependencies: list[Dependency] | None = None
    _removed_assignments: list[Assignment] | None = None
    _child_ids: list[int] | None = None

    def apply(self, project: "Project") -> None:
        self._removed_task = project.get_task(self.task_id)
        self._removed_position = project.task_position(self.task_id)
        self._removed_dependencies = project.dependencies_for_task(self.task_id)
        self._removed_assignments = project.assignments_for_task(self.task_id)
        # remove_task re-parents direct children to the removed task's own
        # parent; record which children so undo can point them back at
        # this task once it's restored (see Project.remove_task).
        self._child_ids = [child.id for child in project.children_of(self.task_id)]
        project.remove_task(self.task_id)

    def undo(self, project: "Project") -> None:
        assert self._removed_task is not None
        assert self._removed_position is not None
        project.add_task(self._removed_task)
        project.move_task(self._removed_task.id, self._removed_position)
        for dep in self._removed_dependencies or []:
            project.add_dependency(dep)
        for assignment in self._removed_assignments or []:
            project.add_assignment(assignment)
        for child_id in self._child_ids or []:
            project.set_task_parent(child_id, self._removed_task.id)


@dataclass
class MoveTask:
    task_id: int
    new_index: int
    new_parent_id: int | None = None
    change_parent: bool = False
    _previous_index: int | None = None
    _previous_parent_id: int | None = None

    def apply(self, project: "Project") -> None:
        self._previous_index = project.task_position(self.task_id)
        self._previous_parent_id = project.get_task(self.task_id).parent_id
        project.move_task(self.task_id, self.new_index)
        if self.change_parent:
            project.set_task_parent(self.task_id, self.new_parent_id)

    def undo(self, project: "Project") -> None:
        assert self._previous_index is not None
        if self.change_parent:
            project.set_task_parent(self.task_id, self._previous_parent_id)
        project.move_task(self.task_id, self._previous_index)


@dataclass
class EditTaskDuration:
    task_id: int
    new_duration_days: float
    _previous_duration_days: float | None = None

    def apply(self, project: "Project") -> None:
        task = project.get_task(self.task_id)
        self._previous_duration_days = task.duration_days
        project.set_task_duration(self.task_id, self.new_duration_days)

    def undo(self, project: "Project") -> None:
        assert self._previous_duration_days is not None
        project.set_task_duration(self.task_id, self._previous_duration_days)


@dataclass
class SetTaskProgress:
    task_id: int
    percent_complete: float
    actual_start: date | None = None
    actual_finish: date | None = None
    _previous: Task | None = None

    def apply(self, project: "Project") -> None:
        self._previous = project.get_task(self.task_id)
        project.set_task_progress(
            self.task_id, self.percent_complete, self.actual_start, self.actual_finish
        )

    def undo(self, project: "Project") -> None:
        assert self._previous is not None
        project.set_task_progress(
            self.task_id,
            self._previous.percent_complete,
            self._previous.actual_start,
            self._previous.actual_finish,
        )


@dataclass
class SetTaskConstraint:
    task_id: int
    new_constraint_type: ConstraintType
    new_constraint_date: date | None = None
    _previous_constraint_type: ConstraintType | None = None
    _previous_constraint_date: date | None = None

    def apply(self, project: "Project") -> None:
        task = project.get_task(self.task_id)
        self._previous_constraint_type = task.constraint_type
        self._previous_constraint_date = task.constraint_date
        project.set_task_constraint(self.task_id, self.new_constraint_type, self.new_constraint_date)

    def undo(self, project: "Project") -> None:
        assert self._previous_constraint_type is not None
        project.set_task_constraint(self.task_id, self._previous_constraint_type, self._previous_constraint_date)


@dataclass
class SetTaskColor:
    task_id: int
    new_color_id: str
    _previous_color_id: str | None = None
    _had_previous: bool = False

    def apply(self, project: "Project") -> None:
        self._previous_color_id = project.get_task(self.task_id).color_id
        self._had_previous = True
        project.set_task_color(self.task_id, self.new_color_id)

    def undo(self, project: "Project") -> None:
        assert self._had_previous
        project.set_task_color(self.task_id, self._previous_color_id)


@dataclass
class SetTaskParent:
    """Reparents a task for indent/outdent. Legality (no cycles, valid
    indent target) is checked by Application before this command is
    constructed (see core/wbs.py) â€” this command only applies the
    already-validated new parent_id and remembers the previous one for
    undo."""

    task_id: int
    new_parent_id: int | None
    _previous_parent_id: int | None = None
    _had_previous: bool = False

    def apply(self, project: "Project") -> None:
        self._previous_parent_id = project.get_task(self.task_id).parent_id
        self._had_previous = True
        project.set_task_parent(self.task_id, self.new_parent_id)

    def undo(self, project: "Project") -> None:
        assert self._had_previous
        project.set_task_parent(self.task_id, self._previous_parent_id)


@dataclass
class AddDependency:
    dependency: Dependency

    def apply(self, project: "Project") -> None:
        project.add_dependency(self.dependency)

    def undo(self, project: "Project") -> None:
        project.remove_dependency(self.dependency.predecessor_id, self.dependency.successor_id)


@dataclass
class RemoveDependency:
    predecessor_id: int
    successor_id: int
    _removed_dependency: Dependency | None = None

    def apply(self, project: "Project") -> None:
        self._removed_dependency = project.get_dependency(self.predecessor_id, self.successor_id)
        project.remove_dependency(self.predecessor_id, self.successor_id)

    def undo(self, project: "Project") -> None:
        assert self._removed_dependency is not None
        project.add_dependency(self._removed_dependency)


@dataclass
class AddResource:
    resource: Resource

    def apply(self, project: "Project") -> None:
        project.add_resource(self.resource)

    def undo(self, project: "Project") -> None:
        project.remove_resource(self.resource.id)


@dataclass
class RemoveResource:
    resource_id: int
    _removed_resource: Resource | None = None
    _removed_assignments: list[Assignment] | None = None

    def apply(self, project: "Project") -> None:
        self._removed_resource = project.get_resource(self.resource_id)
        self._removed_assignments = project.assignments_for_resource(self.resource_id)
        project.remove_resource(self.resource_id)

    def undo(self, project: "Project") -> None:
        assert self._removed_resource is not None
        project.add_resource(self._removed_resource)
        for assignment in self._removed_assignments or []:
            project.add_assignment(assignment)


@dataclass
class AddAssignment:
    assignment: Assignment

    def apply(self, project: "Project") -> None:
        project.add_assignment(self.assignment)

    def undo(self, project: "Project") -> None:
        project.remove_assignment(self.assignment.task_id, self.assignment.resource_id)


@dataclass
class RemoveAssignment:
    task_id: int
    resource_id: int
    _removed_assignment: Assignment | None = None

    def apply(self, project: "Project") -> None:
        self._removed_assignment = project.get_assignment(self.task_id, self.resource_id)
        project.remove_assignment(self.task_id, self.resource_id)

    def undo(self, project: "Project") -> None:
        assert self._removed_assignment is not None
        project.add_assignment(self._removed_assignment)


@dataclass
class SetProjectStart:
    new_start: date
    _previous_start: date | None = None

    def apply(self, project: "Project") -> None:
        self._previous_start = project.start
        project.set_start(self.new_start)

    def undo(self, project: "Project") -> None:
        assert self._previous_start is not None
        project.set_start(self._previous_start)


@dataclass
class SetWorkingWeekdays:
    new_working_weekdays: frozenset[int]
    _previous_working_weekdays: frozenset[int] | None = None

    def apply(self, project: "Project") -> None:
        self._previous_working_weekdays = project.calendar.working_weekdays
        project.calendar.working_weekdays = self.new_working_weekdays

    def undo(self, project: "Project") -> None:
        assert self._previous_working_weekdays is not None
        project.calendar.working_weekdays = self._previous_working_weekdays


@dataclass
class AddBaseline:
    baseline: Baseline

    def apply(self, project: "Project") -> None:
        project.add_baseline(self.baseline)

    def undo(self, project: "Project") -> None:
        project.remove_baseline(self.baseline.id)


@dataclass
class RemoveBaseline:
    baseline_id: int
    _removed_baseline: Baseline | None = None

    def apply(self, project: "Project") -> None:
        self._removed_baseline = project.get_baseline(self.baseline_id)
        project.remove_baseline(self.baseline_id)

    def undo(self, project: "Project") -> None:
        assert self._removed_baseline is not None
        project.add_baseline(self._removed_baseline)
