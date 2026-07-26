"""Project aggregate: owns tasks/dependencies/resources and exposes a
command-based mutation API.

Kept thin by design: Project coordinates the collections and delegates
scheduling to core/scheduler.py rather than absorbing that logic itself.

Project is a domain aggregate only â€” it enforces entity invariants
(no duplicate ids, dependency/assignment cleanup on removal, display
order) but owns no application workflow: no undo/redo history, no
current file path, no dirty flag, no dialogs, no view refresh
choreography. Those live in application/app.py's Application, which is
also the only thing that should call apply_command in an interactive
(undoable) context â€” see that module for why. Project itself must
never import from coconut.application or coconut.storage
(see tests/test_architecture.py) â€” the dependency only runs the other
way.

Two tiers of mutation are supported:
- Interactive edits (GUI, via Application) go through apply_command;
  Application owns the undo/redo stack built from the same commands
  (core/commands.py).
- Bulk construction (storage/repository.py loading a file, future
  interop readers) uses the add_task/add_dependency/add_resource
  primitives directly â€” there's nothing to undo when building a Project
  from a file, so going through commands would only add undo-stack noise
  to clear afterward.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from coconut.core.calendar import Calendar
from coconut.core.commands import Command
from coconut.core.models import (
    Assignment,
    Baseline,
    ConstraintType,
    Dependency,
    Resource,
    Task,
    TaskSnapshot,
)
from coconut.core.scheduler import TaskSchedule, schedule


class Project:
    def __init__(self, name: str, calendar: Calendar | None = None, start: date | None = None):
        self.name = name
        self.calendar = calendar or Calendar()
        self.start = start or date.today()

        self._tasks: dict[int, Task] = {}
        # Explicit display order of task IDs â€” the WBS row position (and
        # therefore the number shown/typed for predecessors) is this list's
        # index, not task.id. Kept separate from _tasks (a dict, unordered
        # semantically) so reordering never touches task.id or anything
        # that references it (dependencies, assignments, baselines).
        self._task_order: list[int] = []
        self._dependencies: dict[tuple[int, int], Dependency] = {}
        self._resources: dict[int, Resource] = {}
        self._assignments: dict[tuple[int, int], Assignment] = {}
        self._baselines: dict[int, Baseline] = {}

        # Monotonic "highest ID ever issued" counters, not max(existing)+1 â€”
        # so a freed ID (task deleted, then undo tries to re-add it under
        # the same ID) is never handed out to something new in between.
        self._next_task_id = 1
        self._next_resource_id = 1
        self._next_baseline_id = 1

    def next_task_id(self) -> int:
        return self._next_task_id

    def next_resource_id(self) -> int:
        return self._next_resource_id

    def next_baseline_id(self) -> int:
        return self._next_baseline_id

    # -- command-based mutation -------------------------------------------------
    # Applies a single command; does not track history. Undo/redo history is
    # Application's job (application/app.py) â€” Project has no memory of past
    # commands beyond their effect on current state.

    def apply_command(self, command: Command) -> None:
        command.apply(self)

    # -- read access --------------------------------------------------------

    @property
    def tasks(self) -> list[Task]:
        return [self._tasks[task_id] for task_id in self._task_order]

    @property
    def dependencies(self) -> list[Dependency]:
        return list(self._dependencies.values())

    @property
    def resources(self) -> list[Resource]:
        return list(self._resources.values())

    @property
    def assignments(self) -> list[Assignment]:
        return list(self._assignments.values())

    @property
    def baselines(self) -> list[Baseline]:
        return list(self._baselines.values())

    def get_task(self, task_id: int) -> Task:
        return self._tasks[task_id]

    def get_dependency(self, predecessor_id: int, successor_id: int) -> Dependency:
        return self._dependencies[(predecessor_id, successor_id)]

    def get_resource(self, resource_id: int) -> Resource:
        return self._resources[resource_id]

    def get_assignment(self, task_id: int, resource_id: int) -> Assignment:
        return self._assignments[(task_id, resource_id)]

    def get_baseline(self, baseline_id: int) -> Baseline:
        return self._baselines[baseline_id]

    def dependencies_for_task(self, task_id: int) -> list[Dependency]:
        return [
            dep
            for dep in self._dependencies.values()
            if dep.predecessor_id == task_id or dep.successor_id == task_id
        ]

    def assignments_for_task(self, task_id: int) -> list[Assignment]:
        return [a for a in self._assignments.values() if a.task_id == task_id]

    def assignments_for_resource(self, resource_id: int) -> list[Assignment]:
        return [a for a in self._assignments.values() if a.resource_id == resource_id]

    def compute_schedule(self) -> dict[int, TaskSchedule]:
        return schedule(self.tasks, self.dependencies, self.calendar, self.start)

    def build_baseline_snapshot(self, baseline_id: int, name: str) -> Baseline:
        """Builds a Baseline from the current schedule without storing it.

        Callers apply it via AddBaseline (interactive, undoable) or
        add_baseline (bulk load) like any other entity.
        """
        current_schedule = self.compute_schedule()
        snapshots = {
            task.id: TaskSnapshot(
                task_id=task.id,
                start=current_schedule[task.id].early_start,
                finish=current_schedule[task.id].early_finish,
                duration_days=task.duration_days,
            )
            for task in self.tasks
        }
        return Baseline(id=baseline_id, name=name, task_snapshots=snapshots)

    # -- low-level primitives ------------------------------------------------
    # Used by Command objects (interactive edits) and by bulk-construction
    # code such as storage/repository.py (no undo tracking needed there).

    def set_start(self, start: date) -> None:
        self.start = start

    def add_task(self, task: Task) -> None:
        if task.id in self._tasks:
            raise ValueError(f"Task id {task.id} already exists")
        self._tasks[task.id] = task
        self._task_order.append(task.id)
        self._next_task_id = max(self._next_task_id, task.id + 1)

    def remove_task(self, task_id: int) -> None:
        removed_parent_id = self._tasks[task_id].parent_id
        # Re-parent direct children to the removed task's own parent (or to
        # top level) rather than leaving them pointing at a deleted id â€”
        # mirrors MS Project's "delete summary, keep children" behavior.
        # RemoveTask.undo (core/commands.py) restores the removed task and
        # then must restore this parent_id on each child too.
        for child in self.children_of(task_id):
            self.set_task_parent(child.id, removed_parent_id)
        del self._tasks[task_id]
        self._task_order.remove(task_id)
        for key in [k for k in self._dependencies if task_id in k]:
            del self._dependencies[key]
        for key in [k for k in self._assignments if k[0] == task_id]:
            del self._assignments[key]

    def move_task(self, task_id: int, new_index: int) -> None:
        """Moves a task to a new position in display order (0-based).

        Only the display order changes â€” task.id, dependencies, and
        assignments are untouched, so predecessor links (keyed on task.id)
        keep working; only their displayed/typed row number shifts.
        """
        self._task_order.remove(task_id)
        self._task_order.insert(new_index, task_id)

    def task_position(self, task_id: int) -> int:
        """Returns the task's 0-based row position (display order)."""
        return self._task_order.index(task_id)

    def task_id_at_position(self, position: int) -> int:
        return self._task_order[position]

    def set_task_duration(self, task_id: int, duration_days: float) -> None:
        task = self._tasks[task_id]
        self._tasks[task_id] = replace(task, duration_days=duration_days)

    def set_task_parent(self, task_id: int, parent_id: int | None) -> None:
        """Low-level WBS reparent primitive. Does not validate legality
        (cycles, self-parenting) â€” callers (core/wbs.py's indent/outdent
        helpers, via Application) must check that first. Kept a plain
        primitive here, alongside the other set_task_* setters, since
        Project already owns "no duplicate ids" style invariants but not
        higher-level WBS rules."""
        task = self._tasks[task_id]
        self._tasks[task_id] = replace(task, parent_id=parent_id)

    def children_of(self, parent_id: int | None) -> list[Task]:
        """Direct children of parent_id (or top-level tasks if None), in
        display order."""
        return [task for task in self.tasks if task.parent_id == parent_id]

    def set_task_constraint(
        self,
        task_id: int,
        constraint_type: ConstraintType,
        constraint_date: date | None,
    ) -> None:
        task = self._tasks[task_id]
        self._tasks[task_id] = replace(
            task, constraint_type=constraint_type, constraint_date=constraint_date
        )

    def set_task_color(self, task_id: int, color_id: str) -> None:
        task = self._tasks[task_id]
        self._tasks[task_id] = replace(task, color_id=color_id)

    def set_task_progress(
        self,
        task_id: int,
        percent_complete: float,
        actual_start: date | None,
        actual_finish: date | None,
    ) -> None:
        task = self._tasks[task_id]
        self._tasks[task_id] = replace(
            task,
            percent_complete=percent_complete,
            actual_start=actual_start,
            actual_finish=actual_finish,
        )

    def add_dependency(self, dependency: Dependency) -> None:
        key = (dependency.predecessor_id, dependency.successor_id)
        if key in self._dependencies:
            raise ValueError(f"Dependency {key} already exists")
        self._dependencies[key] = dependency

    def remove_dependency(self, predecessor_id: int, successor_id: int) -> None:
        del self._dependencies[(predecessor_id, successor_id)]

    def add_resource(self, resource: Resource) -> None:
        if resource.id in self._resources:
            raise ValueError(f"Resource id {resource.id} already exists")
        self._resources[resource.id] = resource
        self._next_resource_id = max(self._next_resource_id, resource.id + 1)

    def remove_resource(self, resource_id: int) -> None:
        del self._resources[resource_id]
        for key in [k for k in self._assignments if k[1] == resource_id]:
            del self._assignments[key]

    def add_assignment(self, assignment: Assignment) -> None:
        key = (assignment.task_id, assignment.resource_id)
        if key in self._assignments:
            raise ValueError(f"Assignment {key} already exists")
        self._assignments[key] = assignment

    def remove_assignment(self, task_id: int, resource_id: int) -> None:
        del self._assignments[(task_id, resource_id)]

    def add_baseline(self, baseline: Baseline) -> None:
        if baseline.id in self._baselines:
            raise ValueError(f"Baseline id {baseline.id} already exists")
        self._baselines[baseline.id] = baseline
        self._next_baseline_id = max(self._next_baseline_id, baseline.id + 1)

    def remove_baseline(self, baseline_id: int) -> None:
        del self._baselines[baseline_id]
