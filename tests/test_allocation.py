from datetime import date

from coconut.core.allocation import find_over_allocations, is_resource_over_allocated
from coconut.core.calendar import Calendar
from coconut.core.models import Assignment, Resource, Task
from coconut.core.scheduler import schedule

PROJECT_START = date(2026, 1, 1)


def test_no_over_allocation_within_capacity():
    tasks = [Task(id=1, name="A", duration_days=3)]
    resources = [Resource(id=1, name="Alice", max_units=1.0)]
    assignments = [Assignment(task_id=1, resource_id=1, units=1.0)]

    sched = schedule(tasks, [], Calendar(), PROJECT_START)
    assert find_over_allocations(resources, assignments, sched) == []
    assert not is_resource_over_allocated(1, resources, assignments, sched)


def test_over_allocation_detected_when_units_exceed_capacity():
    tasks = [
        Task(id=1, name="A", duration_days=3),
        Task(id=2, name="B", duration_days=3),
    ]
    resources = [Resource(id=1, name="Alice", max_units=1.0)]
    assignments = [
        Assignment(task_id=1, resource_id=1, units=0.75),
        Assignment(task_id=2, resource_id=1, units=0.75),
    ]

    sched = schedule(tasks, [], Calendar(), PROJECT_START)
    over_allocations = find_over_allocations(resources, assignments, sched)

    assert over_allocations
    assert all(oa.resource_id == 1 for oa in over_allocations)
    assert all(oa.allocated_units == 1.5 for oa in over_allocations)
    assert is_resource_over_allocated(1, resources, assignments, sched)


def test_non_overlapping_tasks_do_not_over_allocate():
    tasks = [
        Task(id=1, name="A", duration_days=2),
        Task(id=2, name="B", duration_days=2),
    ]
    resources = [Resource(id=1, name="Alice", max_units=1.0)]
    assignments = [
        Assignment(task_id=1, resource_id=1, units=1.0),
        Assignment(task_id=2, resource_id=1, units=1.0),
    ]
    # Force sequential scheduling via a dependency so tasks don't overlap.
    from coconut.core.models import Dependency

    sched = schedule(tasks, [Dependency(predecessor_id=1, successor_id=2)], Calendar(), PROJECT_START)
    assert find_over_allocations(resources, assignments, sched) == []
