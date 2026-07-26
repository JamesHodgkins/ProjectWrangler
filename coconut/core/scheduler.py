"""CPM (Critical Path Method) scheduling engine.

Operates on plain Task/Dependency objects (core/models.py) and a Calendar
(core/calendar.py) for all date math â€” no Qt, no SQLite. Supports the
standard FS/SS/FF/SF dependency types with lag/lead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from coconut.core.calendar import Calendar
from coconut.core.exceptions import SchedulingError
from coconut.core.models import ConstraintType, Dependency, DependencyType, Task


class CyclicDependencyError(SchedulingError):
    pass


@dataclass
class TaskSchedule:
    task_id: int
    early_start: date
    early_finish: date
    late_start: date
    late_finish: date

    @property
    def total_float_days(self) -> int:
        return (self.late_start - self.early_start).days

    @property
    def is_critical(self) -> bool:
        return self.total_float_days == 0


def _topological_order(tasks: list[Task], dependencies: list[Dependency]) -> list[int]:
    """Kahn's algorithm; raises CyclicDependencyError if a cycle exists."""
    task_ids = [t.id for t in tasks]
    successors: dict[int, list[int]] = {tid: [] for tid in task_ids}
    in_degree: dict[int, int] = {tid: 0 for tid in task_ids}

    for dep in dependencies:
        successors[dep.predecessor_id].append(dep.successor_id)
        in_degree[dep.successor_id] += 1

    queue = [tid for tid in task_ids if in_degree[tid] == 0]
    order: list[int] = []
    while queue:
        current = queue.pop()
        order.append(current)
        for succ in successors[current]:
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                queue.append(succ)

    if len(order) != len(task_ids):
        raise CyclicDependencyError("Dependency graph contains a cycle")
    return order


def _apply_dependency_forward(
    calendar: Calendar,
    dep: Dependency,
    pred_start: date,
    pred_finish: date,
    succ_duration_days: float,
) -> date:
    """Returns the earliest start for the successor implied by this dependency."""
    if dep.type == DependencyType.FINISH_TO_START:
        # pred_finish is itself a working day fully consumed by the
        # predecessor (see Calendar.finish_date), so the successor starts
        # at least one working day later, plus any lag.
        return calendar.add_days(pred_finish, dep.lag_days + 1)
    elif dep.type == DependencyType.START_TO_START:
        anchor = pred_start
    elif dep.type == DependencyType.FINISH_TO_FINISH:
        finish = calendar.add_days(pred_finish, dep.lag_days)
        return calendar.start_date(finish, succ_duration_days)
    elif dep.type == DependencyType.START_TO_FINISH:
        finish = calendar.add_days(pred_start, dep.lag_days)
        return calendar.start_date(finish, succ_duration_days)
    else:
        raise ValueError(f"Unknown dependency type: {dep.type}")

    return calendar.add_days(anchor, dep.lag_days)


def _apply_dependency_backward(
    calendar: Calendar,
    dep: Dependency,
    succ_start: date,
    succ_finish: date,
    pred_duration_days: float,
) -> date:
    """Returns the latest finish for the predecessor implied by this dependency."""
    if dep.type == DependencyType.FINISH_TO_START:
        # Inverse of the forward FS case: the predecessor must finish at
        # least one working day before the successor's start, plus lag.
        return calendar.add_days(succ_start, -(dep.lag_days + 1))
    elif dep.type == DependencyType.START_TO_START:
        start = calendar.add_days(succ_start, -dep.lag_days)
        return calendar.finish_date(start, pred_duration_days)
    elif dep.type == DependencyType.FINISH_TO_FINISH:
        anchor = succ_finish
        return calendar.add_days(anchor, -dep.lag_days)
    elif dep.type == DependencyType.START_TO_FINISH:
        start = calendar.add_days(succ_finish, -dep.lag_days)
        return calendar.finish_date(start, pred_duration_days)
    else:
        raise ValueError(f"Unknown dependency type: {dep.type}")


def _apply_constraint_forward(calendar: Calendar, task: Task, computed_start: date) -> date:
    """Clamps a forward-pass start date to the task's constraint, if any.

    SNLT/FNLT don't affect the forward pass â€” they only cap how late a task
    may float, which is a backward-pass concern (see
    _apply_constraint_backward).
    """
    ctype = task.constraint_type
    cdate = task.constraint_date
    if ctype in (ConstraintType.AS_SOON_AS_POSSIBLE, ConstraintType.AS_LATE_AS_POSSIBLE):
        return computed_start
    if ctype == ConstraintType.START_NO_EARLIER_THAN:
        return max(computed_start, cdate)
    if ctype == ConstraintType.MUST_START_ON:
        return cdate
    if ctype == ConstraintType.FINISH_NO_EARLIER_THAN:
        if calendar.finish_date(computed_start, task.duration_days) < cdate:
            return calendar.start_date(cdate, task.duration_days)
        return computed_start
    if ctype == ConstraintType.MUST_FINISH_ON:
        return calendar.start_date(cdate, task.duration_days)
    return computed_start


def _apply_constraint_backward(calendar: Calendar, task: Task, computed_finish: date) -> date:
    """Clamps a backward-pass finish date to the task's constraint, if any.

    SNET/FNET don't affect the backward pass â€” they only push out the
    earliest a task may start, which is a forward-pass concern (see
    _apply_constraint_forward).
    """
    ctype = task.constraint_type
    cdate = task.constraint_date
    if ctype in (ConstraintType.AS_SOON_AS_POSSIBLE, ConstraintType.AS_LATE_AS_POSSIBLE):
        return computed_finish
    if ctype == ConstraintType.FINISH_NO_LATER_THAN:
        return min(computed_finish, cdate)
    if ctype == ConstraintType.MUST_FINISH_ON:
        return cdate
    if ctype == ConstraintType.START_NO_LATER_THAN:
        return min(computed_finish, calendar.finish_date(cdate, task.duration_days))
    if ctype == ConstraintType.MUST_START_ON:
        return calendar.finish_date(cdate, task.duration_days)
    return computed_finish


def schedule(
    tasks: list[Task],
    dependencies: list[Dependency],
    calendar: Calendar,
    project_start: date,
) -> dict[int, TaskSchedule]:
    """Runs forward and backward passes, returning a TaskSchedule per task id."""
    tasks_by_id = {t.id: t for t in tasks}
    order = _topological_order(tasks, dependencies)

    predecessors: dict[int, list[Dependency]] = {tid: [] for tid in tasks_by_id}
    successors: dict[int, list[Dependency]] = {tid: [] for tid in tasks_by_id}
    for dep in dependencies:
        predecessors[dep.successor_id].append(dep)
        successors[dep.predecessor_id].append(dep)

    early_start: dict[int, date] = {}
    early_finish: dict[int, date] = {}

    for tid in order:
        task = tasks_by_id[tid]
        preds = predecessors[tid]
        if not preds:
            start = project_start
        else:
            candidate_starts = [
                _apply_dependency_forward(
                    calendar,
                    dep,
                    early_start[dep.predecessor_id],
                    early_finish[dep.predecessor_id],
                    task.duration_days,
                )
                for dep in preds
            ]
            start = max(candidate_starts)
        start = _apply_constraint_forward(calendar, task, start)
        early_start[tid] = start
        early_finish[tid] = calendar.finish_date(start, task.duration_days)

    project_finish = max(early_finish.values()) if early_finish else project_start

    late_start: dict[int, date] = {}
    late_finish: dict[int, date] = {}

    for tid in reversed(order):
        task = tasks_by_id[tid]
        succs = successors[tid]
        if not succs:
            finish = project_finish
        else:
            candidate_finishes = [
                _apply_dependency_backward(
                    calendar,
                    dep,
                    late_start[dep.successor_id],
                    late_finish[dep.successor_id],
                    task.duration_days,
                )
                for dep in succs
            ]
            finish = min(candidate_finishes)
        finish = _apply_constraint_backward(calendar, task, finish)
        late_finish[tid] = finish
        late_start[tid] = calendar.start_date(finish, task.duration_days)

    # Third pass: re-derive the *effective* (displayed/scheduled) start and
    # finish dates. Identical to the forward pass above except that ALAP
    # tasks are re-anchored to their late_start (computed above from the
    # backward pass) instead of their dependency-driven early_start â€” so an
    # ALAP task, and anything chained after it via a dependency, is pushed
    # out to the latest date that doesn't slip the project, rather than
    # sitting at its earliest possible date.
    effective_start: dict[int, date] = {}
    effective_finish: dict[int, date] = {}

    for tid in order:
        task = tasks_by_id[tid]
        preds = predecessors[tid]
        if not preds:
            start = project_start
        else:
            candidate_starts = [
                _apply_dependency_forward(
                    calendar,
                    dep,
                    effective_start[dep.predecessor_id],
                    effective_finish[dep.predecessor_id],
                    task.duration_days,
                )
                for dep in preds
            ]
            start = max(candidate_starts)
        start = _apply_constraint_forward(calendar, task, start)
        if task.constraint_type == ConstraintType.AS_LATE_AS_POSSIBLE:
            start = late_start[tid]
        effective_start[tid] = start
        effective_finish[tid] = calendar.finish_date(start, task.duration_days)

    return {
        tid: TaskSchedule(
            task_id=tid,
            early_start=effective_start[tid],
            early_finish=effective_finish[tid],
            late_start=late_start[tid],
            late_finish=late_finish[tid],
        )
        for tid in tasks_by_id
    }


def critical_path(schedules: dict[int, TaskSchedule]) -> list[int]:
    return [tid for tid, sched in schedules.items() if sched.is_critical]
