"""Basic resource leveling: a single greedy delay-based pass.

For each over-allocated resource, tasks assigned to it are considered in
schedule order (early_start, then task id for determinism); whichever
task would otherwise start second on a conflicting day is delayed to
start right after the first one finishes. This is intentionally simple â€”
priority schemes, task splitting, and multi-pass leveling are out of
scope (see PROJECT_PLAN.md).

Returns a list of AddDependency-shaped delay constraints as plain
(task_id, delay_until) pairs rather than mutating the Project directly,
so the caller decides how to apply them (e.g. as FS dependencies with
lag, or direct start-date overrides) once constraint types exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from coconut.core.calendar import Calendar
from coconut.core.models import Assignment, Dependency, DependencyType, Resource, Task
from coconut.core.scheduler import TaskSchedule, schedule


@dataclass
class LevelingDelay:
    task_id: int
    delayed_after_task_id: int


def level_resources(
    tasks: list[Task],
    dependencies: list[Dependency],
    resources: list[Resource],
    assignments: list[Assignment],
    calendar: Calendar,
    project_start: date,
) -> list[LevelingDelay]:
    """Returns extra finish-to-start links that resolve over-allocation.

    Does not mutate any input; the caller applies the returned delays
    (e.g. via AddDependency commands) if it accepts them.
    """
    current_dependencies = list(dependencies)
    delays: list[LevelingDelay] = []

    assignments_by_resource: dict[int, list[Assignment]] = {r.id: [] for r in resources}
    for assignment in assignments:
        if assignment.resource_id in assignments_by_resource:
            assignments_by_resource[assignment.resource_id].append(assignment)

    for resource in resources:
        resource_assignments = assignments_by_resource[resource.id]
        if len(resource_assignments) < 2:
            continue

        sched = schedule(tasks, current_dependencies, calendar, project_start)
        ordered_task_ids = sorted(
            (a.task_id for a in resource_assignments),
            key=lambda tid: (sched[tid].early_start, tid),
        )

        total_units = 0.0
        units_by_task = {a.task_id: a.units for a in resource_assignments}
        previous_task_id: int | None = None

        for task_id in ordered_task_ids:
            total_units += units_by_task[task_id]
            if total_units > resource.max_units and previous_task_id is not None:
                current_dependencies.append(
                    Dependency(
                        predecessor_id=previous_task_id,
                        successor_id=task_id,
                        type=DependencyType.FINISH_TO_START,
                    )
                )
                delays.append(LevelingDelay(task_id=task_id, delayed_after_task_id=previous_task_id))
                total_units = units_by_task[task_id]
                sched = schedule(tasks, current_dependencies, calendar, project_start)
            previous_task_id = task_id

    return delays
