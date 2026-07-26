"""WBS hierarchy service: outline numbering, indent/outdent legality,
cycle prevention, and summary-task rollups.

Deliberately a set of plain functions over `list[Task]` (in display
order) rather than a method on Project or a class of its own â€” the
governing rule for Phase 7 is "domain code mutates Project; a WBS
service derives display/rollup facts from it", so this module reads
tasks/schedules and returns derived data, and never mutates anything.
Task identity (task.id) and display order (Project._task_order) are
untouched by anything here; only Task.parent_id encodes hierarchy, and
even that is written by Project.set_task_parent, not by this module.

Keeping this separate from core/scheduler.py preserves "the scheduler
schedules executable leaf tasks; a WBS rollup service derives summary
task dates/duration/% complete afterward" â€” callers must exclude summary
tasks from what they pass to core.scheduler.schedule() and instead call
summary_rollups() with the resulting leaf schedules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from coconut.core.exceptions import ValidationError
from coconut.core.models import Task
from coconut.core.scheduler import TaskSchedule


def is_summary(tasks: list[Task], task_id: int) -> bool:
    return any(t.parent_id == task_id for t in tasks)


def depth_of(tasks_by_id: dict[int, Task], task_id: int) -> int:
    depth = 0
    current = tasks_by_id[task_id]
    seen: set[int] = set()
    while current.parent_id is not None:
        if current.parent_id in seen:
            # A cycle should never survive set_task_parent (validated by
            # would_create_cycle before any caller writes parent_id), but
            # guard rather than infinite-loop if one somehow exists.
            raise ValidationError(f"Cycle detected in WBS hierarchy at task {task_id}")
        seen.add(current.parent_id)
        current = tasks_by_id[current.parent_id]
        depth += 1
    return depth


def would_create_cycle(tasks_by_id: dict[int, Task], task_id: int, new_parent_id: int | None) -> bool:
    """True if setting task_id's parent to new_parent_id would make
    task_id an ancestor of itself (directly or transitively), or would
    parent a task under itself."""
    if new_parent_id is None:
        return False
    if new_parent_id == task_id:
        return True
    current: int | None = new_parent_id
    seen: set[int] = set()
    while current is not None:
        if current == task_id:
            return True
        if current in seen:
            return False  # pre-existing cycle elsewhere; not this operation's problem
        seen.add(current)
        current = tasks_by_id[current].parent_id
    return False


def outline_numbers(tasks: list[Task]) -> dict[int, str]:
    """Returns {task_id: "1.2.3"}-style outline numbers, computed from
    parent_id + the tasks' current display order. Siblings are numbered
    in the order they appear in `tasks` (Project.tasks, i.e. display
    order), independent of task.id."""
    tasks_by_id = {t.id: t for t in tasks}
    children_by_parent: dict[int | None, list[int]] = {}
    for task in tasks:
        children_by_parent.setdefault(task.parent_id, []).append(task.id)

    numbers: dict[int, str] = {}

    def _assign(parent_id: int | None, prefix: str) -> None:
        for index, child_id in enumerate(children_by_parent.get(parent_id, []), start=1):
            number = f"{prefix}{index}" if not prefix else f"{prefix}.{index}"
            numbers[child_id] = number
            _assign(child_id, number)

    _assign(None, "")
    return numbers


def effective_color_id(tasks_by_id: dict[int, Task], task_id: int) -> str:
    """Resolves the color_id a task should display: its own if it's a
    top-level task, or its top-level ancestor's if nested â€” color is only
    ever set on a top-level task (see Task.color_id), so a nested task
    always inherits its ancestor's choice rather than having one of its
    own."""
    current = tasks_by_id[task_id]
    while current.parent_id is not None:
        current = tasks_by_id[current.parent_id]
    return current.color_id


def can_indent(tasks: list[Task], task_id: int) -> bool:
    """A task can indent under its immediate previous sibling, if one
    exists. The first task among its siblings has no one to indent
    under."""
    tasks_by_id = {t.id: t for t in tasks}
    task = tasks_by_id[task_id]
    siblings = [t.id for t in tasks if t.parent_id == task.parent_id]
    return siblings.index(task_id) > 0


def indent_target_parent(tasks: list[Task], task_id: int) -> int:
    """Returns the id of the immediate previous sibling, which becomes
    task_id's new parent. Raises ValidationError if can_indent is False."""
    if not can_indent(tasks, task_id):
        raise ValidationError(f"Task {task_id} has no preceding sibling to indent under")
    task = next(t for t in tasks if t.id == task_id)
    siblings = [t.id for t in tasks if t.parent_id == task.parent_id]
    return siblings[siblings.index(task_id) - 1]


def can_outdent(tasks: list[Task], task_id: int) -> bool:
    """A task can outdent only if it currently has a parent."""
    tasks_by_id = {t.id: t for t in tasks}
    return tasks_by_id[task_id].parent_id is not None


def outdent_target_parent(tasks: list[Task], task_id: int) -> int | None:
    """Returns the id of the new parent after outdenting (the current
    parent's own parent), or None if outdenting to top level. Raises
    ValidationError if can_outdent is False."""
    if not can_outdent(tasks, task_id):
        raise ValidationError(f"Task {task_id} is already at top level")
    tasks_by_id = {t.id: t for t in tasks}
    current_parent = tasks_by_id[tasks_by_id[task_id].parent_id]
    return current_parent.parent_id


@dataclass(frozen=True)
class SummaryRollup:
    task_id: int
    start: date
    finish: date
    duration_days: float
    percent_complete: float


def summary_rollups(tasks: list[Task], leaf_schedules: dict[int, TaskSchedule]) -> dict[int, SummaryRollup]:
    """Derives start/finish/duration/% complete for every summary task
    (a task with at least one child) from its descendant leaf tasks'
    schedules, bottom-up. leaf_schedules must contain a TaskSchedule for
    every non-summary task (i.e. the scheduler was run over leaves only)
    keyed by task_id; summary task ids must not appear in it.

    Duration is measured in calendar working days spanned (finish - start
    + 1 in calendar-day terms is a scheduler concern); here it's simply
    the day count implied by the rolled-up start/finish, consistent with
    how a leaf task's own duration_days already relates to its schedule.
    % complete is a duration-weighted average of descendant leaves so a
    long unfinished leaf under a mostly-finished summary still moves the
    number appropriately.
    """
    tasks_by_id = {t.id: t for t in tasks}
    children_by_parent: dict[int, list[int]] = {}
    for task in tasks:
        if task.parent_id is not None:
            children_by_parent.setdefault(task.parent_id, []).append(task.id)

    rollups: dict[int, SummaryRollup] = {}

    def _rollup(task_id: int) -> tuple[date, date, float, float]:
        """Returns (start, finish, weighted_percent_numerator, total_weight)
        for the leaf-descendant set of task_id, computing summary rollups
        bottom-up via memoization in `rollups`."""
        child_ids = children_by_parent.get(task_id, [])
        if not child_ids:
            sched = leaf_schedules[task_id]
            task = tasks_by_id[task_id]
            weight = task.duration_days
            return sched.early_start, sched.early_finish, task.percent_complete * weight, weight

        starts: list[date] = []
        finishes: list[date] = []
        weighted_percent = 0.0
        total_weight = 0.0
        for child_id in child_ids:
            if child_id in children_by_parent:
                start, finish, child_percent_num, child_weight = _rollup(child_id)
            else:
                sched = leaf_schedules[child_id]
                start, finish = sched.early_start, sched.early_finish
                child_task = tasks_by_id[child_id]
                child_weight = child_task.duration_days
                child_percent_num = child_task.percent_complete * child_weight
            starts.append(start)
            finishes.append(finish)
            weighted_percent += child_percent_num
            total_weight += child_weight

        start = min(starts)
        finish = max(finishes)
        duration_days = (finish - start).days + 1
        percent_complete = weighted_percent / total_weight if total_weight else 0.0
        rollups[task_id] = SummaryRollup(
            task_id=task_id,
            start=start,
            finish=finish,
            duration_days=duration_days,
            percent_complete=percent_complete,
        )
        return start, finish, weighted_percent, total_weight

    for parent_id in children_by_parent:
        if parent_id not in rollups:
            _rollup(parent_id)

    return rollups
