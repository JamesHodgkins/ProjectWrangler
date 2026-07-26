from datetime import date

from coconut.core.allocation import find_over_allocations
from coconut.core.calendar import Calendar
from coconut.core.leveling import level_resources
from coconut.core.models import Assignment, Dependency, Resource, Task
from coconut.core.scheduler import schedule

PROJECT_START = date(2026, 1, 1)


def test_no_delays_needed_within_capacity():
    tasks = [Task(id=1, name="A", duration_days=3)]
    resources = [Resource(id=1, name="Alice", max_units=1.0)]
    assignments = [Assignment(task_id=1, resource_id=1, units=1.0)]

    delays = level_resources(tasks, [], resources, assignments, Calendar(), PROJECT_START)
    assert delays == []


def test_leveling_resolves_over_allocation():
    tasks = [
        Task(id=1, name="A", duration_days=3),
        Task(id=2, name="B", duration_days=3),
    ]
    resources = [Resource(id=1, name="Alice", max_units=1.0)]
    assignments = [
        Assignment(task_id=1, resource_id=1, units=1.0),
        Assignment(task_id=2, resource_id=1, units=1.0),
    ]

    delays = level_resources(tasks, [], resources, assignments, Calendar(), PROJECT_START)
    assert len(delays) == 1
    assert delays[0].task_id == 2
    assert delays[0].delayed_after_task_id == 1

    # Applying the delay as an FS dependency should clear the over-allocation.
    new_deps = [
        Dependency(predecessor_id=d.delayed_after_task_id, successor_id=d.task_id) for d in delays
    ]
    sched = schedule(tasks, new_deps, Calendar(), PROJECT_START)
    assert find_over_allocations(resources, assignments, sched) == []


def test_leveling_does_not_touch_resource_with_single_assignment():
    tasks = [
        Task(id=1, name="A", duration_days=3),
        Task(id=2, name="B", duration_days=3),
    ]
    resources = [
        Resource(id=1, name="Alice", max_units=1.0),
        Resource(id=2, name="Bob", max_units=1.0),
    ]
    assignments = [
        Assignment(task_id=1, resource_id=1, units=1.0),
        Assignment(task_id=2, resource_id=2, units=1.0),
    ]

    delays = level_resources(tasks, [], resources, assignments, Calendar(), PROJECT_START)
    assert delays == []
