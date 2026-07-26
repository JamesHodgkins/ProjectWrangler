"""Resource over-allocation detection.

A resource is over-allocated on a given day if the sum of `units` across
all tasks assigned to it that are scheduled to run that day exceeds the
resource's max_units. Uses each task's early_start/early_finish window
from the computed schedule â€” the same dates the Gantt view renders.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from coconut.core.models import Assignment, Resource
from coconut.core.scheduler import TaskSchedule


@dataclass
class OverAllocation:
    resource_id: int
    day: date
    allocated_units: float
    max_units: float


def find_over_allocations(
    resources: list[Resource],
    assignments: list[Assignment],
    schedules: dict[int, TaskSchedule],
) -> list[OverAllocation]:
    assignments_by_resource: dict[int, list[Assignment]] = {r.id: [] for r in resources}
    for assignment in assignments:
        if assignment.resource_id in assignments_by_resource:
            assignments_by_resource[assignment.resource_id].append(assignment)

    results: list[OverAllocation] = []
    for resource in resources:
        daily_units: dict[date, float] = {}
        for assignment in assignments_by_resource[resource.id]:
            sched = schedules.get(assignment.task_id)
            if sched is None:
                continue
            day = sched.early_start
            while day < sched.early_finish:
                daily_units[day] = daily_units.get(day, 0.0) + assignment.units
                day += timedelta(days=1)

        for day, allocated in sorted(daily_units.items()):
            if allocated > resource.max_units:
                results.append(
                    OverAllocation(
                        resource_id=resource.id,
                        day=day,
                        allocated_units=allocated,
                        max_units=resource.max_units,
                    )
                )
    return results


def is_resource_over_allocated(
    resource_id: int,
    resources: list[Resource],
    assignments: list[Assignment],
    schedules: dict[int, TaskSchedule],
) -> bool:
    return any(
        oa.resource_id == resource_id
        for oa in find_over_allocations(resources, assignments, schedules)
    )
