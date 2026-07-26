"""Qt-free application layer: owns the current Project, file path, dirty
flag, undo/redo history, and cached read-model projections.

Lives in coconut/application/, not coconut/core/: this
module is allowed to import coconut.storage (for save/load) and
sits between core/ (pure domain) and ui/ (Qt) in the dependency chain â€”
see tests/test_architecture.py for the enforced layering:
core imports nothing from storage/application/ui; storage may import
core; application may import core and storage; ui may only import
application (plus read-model DTOs).

UI emits intent; Application executes intent; domain code (Project,
commands, scheduler, allocation, variance) mutates/derives state; the
resulting ProjectionState is what views render. Nothing here imports
Qt directly, so every workflow is unit-testable without a display.

Command-history ownership lives here, not on Project: Project is a
domain aggregate and has no memory of past commands. apply_command()
below is the only place that pushes onto the undo stack, clears the
redo stack, marks the project dirty, and recomputes projections â€” every
public intent method funnels through it, so those four things can never
drift out of sync with each other.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from coconut.core.allocation import find_over_allocations
from coconut.core.calendar import Calendar
from coconut.core.commands import (
    AddAssignment,
    AddBaseline,
    AddDependency,
    AddResource,
    AddTask,
    Command,
    EditTaskDuration,
    MoveTask,
    RemoveAssignment,
    RemoveDependency,
    RemoveResource,
    RemoveTask,
    SetProjectStart,
    SetTaskColor,
    SetTaskConstraint,
    SetTaskParent,
    SetTaskProgress,
    SetWorkingWeekdays,
)
from coconut.core.exceptions import (
    NothingToRedoError,
    NothingToUndoError,
    ValidationError,
)
from coconut.core.models import (
    Assignment,
    ConstraintType,
    Dependency,
    DependencyType,
    Resource,
    Task,
)
from coconut.core.project import Project
from coconut.core.scheduler import CyclicDependencyError, TaskSchedule, schedule as run_scheduler
from coconut.core.variance import compute_variance
from coconut.core.wbs import (
    SummaryRollup,
    can_indent,
    can_outdent,
    depth_of,
    effective_color_id,
    indent_target_parent,
    outdent_target_parent,
    outline_numbers,
    summary_rollups,
    would_create_cycle,
)
from coconut.application.view_models import (
    AssignableResource,
    AssignmentRow,
    BaselineListItem,
    GanttBar,
    GanttBaselineBar,
    GanttDependencyArrow,
    GanttProjection,
    ProjectionState,
    ResourceRow,
    TaskRow,
    VarianceRow,
)
from coconut.storage.repository import load, save

import re

# MS Project-style predecessor entry, referring to the *row number* shown
# in the WBS table (1-based), e.g. "3", "3FS", "3FS+2", "4SS-1.5" â€” not
# the task's internal id, which the UI never shows.
_PREDECESSOR_TERM_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)*)\s*(FS|SS|FF|SF)?\s*([+-]\s*\d+(?:\.\d+)?)?\s*$", re.IGNORECASE
)


@dataclass(frozen=True)
class PredecessorTerm:
    predecessor_id: int
    type: DependencyType
    lag_days: float


def _format_predecessors(project: Project, task_id: int) -> str:
    outline_by_task_id = outline_numbers(project.tasks)
    terms = []
    for dep in project.dependencies:
        if dep.successor_id != task_id:
            continue
        term = outline_by_task_id[dep.predecessor_id]
        if dep.type != DependencyType.FINISH_TO_START or dep.lag_days:
            term += dep.type.value
        if dep.lag_days:
            term += f"{dep.lag_days:+g}"
        terms.append(term)
    return ", ".join(terms)


def parse_predecessors(project: Project, text: str) -> list[PredecessorTerm]:
    """Parses predecessor text into PredecessorTerms, resolving each entered
    WBS/outline number to the task.id currently displayed with that number.

    Raises ValidationError on malformed terms or a reference that doesn't
    exist, so callers can reject the edit rather than silently dropping it.
    """
    outline_by_task_id = outline_numbers(project.tasks)
    task_id_by_outline = {number: task_id for task_id, number in outline_by_task_id.items()}
    result = []
    for raw_term in text.split(","):
        if not raw_term.strip():
            continue
        match = _PREDECESSOR_TERM_RE.match(raw_term)
        if not match:
            raise ValidationError(f"Invalid predecessor: {raw_term.strip()!r}")
        reference, type_code, lag = match.groups()
        pred_task_id = task_id_by_outline.get(reference)
        if pred_task_id is None and "." not in reference:
            row_number = int(reference)
            if 1 <= row_number <= len(project.tasks):
                pred_task_id = project.task_id_at_position(row_number - 1)
        if pred_task_id is None:
            raise ValidationError(f"No task with WBS number {reference}")
        dep_type = DependencyType(type_code.upper()) if type_code else DependencyType.FINISH_TO_START
        lag_days = float(lag.replace(" ", "")) if lag else 0.0
        result.append(PredecessorTerm(pred_task_id, dep_type, lag_days))
    return result


class Application:
    """Owns application state and orchestrates every workflow. UI code
    should only ever call methods on this class (plus read the
    ProjectionState it returns/exposes) â€” never core.commands,
    core.scheduler, core.allocation, core.variance, or
    storage.repository directly.
    """

    def __init__(self, project: Project | None = None):
        self.project = project or Project(name="Untitled Project", start=date.today())
        self.current_path: str | None = None
        self.is_dirty = False
        self._undo_stack: list[Command] = []
        self._redo_stack: list[Command] = []
        self._selected_baseline_id: int | None = None
        self.projections = self._compute_projections()

    # -- command execution / undo-redo --------------------------------------

    def execute(self, command: Command) -> None:
        """Applies a command, pushes undo history, clears redo, marks
        dirty, and recomputes projections â€” the single funnel every
        intent method in this class goes through, so those effects can
        never happen independently of each other."""
        command.apply(self.project)
        self._undo_stack.append(command)
        self._redo_stack.clear()
        self.is_dirty = True
        self._refresh_projections()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def undo(self) -> None:
        if not self._undo_stack:
            raise NothingToUndoError("No command to undo")
        command = self._undo_stack.pop()
        command.undo(self.project)
        self._redo_stack.append(command)
        self.is_dirty = True
        self._refresh_projections()

    def redo(self) -> None:
        if not self._redo_stack:
            raise NothingToRedoError("No command to redo")
        command = self._redo_stack.pop()
        command.apply(self.project)
        self._undo_stack.append(command)
        self.is_dirty = True
        self._refresh_projections()

    # -- project lifecycle ---------------------------------------------------

    def new_project(self, name: str, start: date) -> None:
        self.project = Project(name=name, start=start)
        self.current_path = None
        self.is_dirty = False
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._selected_baseline_id = None
        self._refresh_projections()

    def open_project(self, path: str) -> None:
        project = load(path)
        self.project = project
        self.current_path = path
        self.is_dirty = False
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._selected_baseline_id = None
        self._refresh_projections()

    def save_project(self, path: str | None = None) -> None:
        target = path or self.current_path
        if target is None:
            raise ValidationError("No file path given and no current path set")
        save(self.project, target)
        self.current_path = target
        self.is_dirty = False

    # -- task intents ---------------------------------------------------------

    def add_task(self, name: str, duration_days: float) -> int:
        task_id = self.project.next_task_id()
        self.execute(AddTask(Task(id=task_id, name=name, duration_days=duration_days)))
        return task_id

    def remove_task(self, task_id: int) -> None:
        self.execute(RemoveTask(task_id))

    def move_task(self, task_id: int, new_index: int) -> None:
        tasks = self.project.tasks
        tasks_by_id = {t.id: t for t in tasks}
        task_depth = depth_of(tasks_by_id, task_id)
        new_parent_id = tasks_by_id[task_id].parent_id
        change_parent = False

        if task_depth > 0:
            new_order = [t.id for t in tasks]
            new_order.remove(task_id)
            new_order.insert(new_index, task_id)
            insertion_index = new_order.index(task_id)
            preceding_ids = new_order[:insertion_index]

            new_parent_id = None
            for preceding_id in reversed(preceding_ids):
                if depth_of(tasks_by_id, preceding_id) < task_depth:
                    new_parent_id = preceding_id
                    break

            change_parent = new_parent_id != tasks_by_id[task_id].parent_id
            if change_parent and would_create_cycle(tasks_by_id, task_id, new_parent_id):
                raise ValidationError(f"Moving task {task_id} would create a WBS cycle")

        self.execute(MoveTask(task_id, new_index, new_parent_id, change_parent))

    def indent_task(self, task_id: int) -> None:
        """Makes task_id a child of its immediate previous sibling.
        Raises ValidationError if it has no preceding sibling (WBS
        legality lives in core/wbs.py, not here or in the UI)."""
        tasks = self.project.tasks
        if not can_indent(tasks, task_id):
            raise ValidationError(f"Task {task_id} has no preceding sibling to indent under")
        new_parent_id = indent_target_parent(tasks, task_id)
        self.execute(SetTaskParent(task_id, new_parent_id))

    def outdent_task(self, task_id: int) -> None:
        """Moves task_id up one level, becoming a sibling of its former
        parent. Raises ValidationError if already at top level."""
        tasks = self.project.tasks
        if not can_outdent(tasks, task_id):
            raise ValidationError(f"Task {task_id} is already at top level")
        new_parent_id = outdent_target_parent(tasks, task_id)
        self.execute(SetTaskParent(task_id, new_parent_id))

    def edit_task_duration(self, task_id: int, duration_days: float) -> None:
        self.execute(EditTaskDuration(task_id, duration_days))

    def edit_task_progress(
        self,
        task_id: int,
        percent: float,
        actual_start: date | None = None,
        actual_finish: date | None = None,
    ) -> None:
        if actual_start is None and actual_finish is None:
            task = self.project.get_task(task_id)
            actual_start = task.actual_start
            actual_finish = task.actual_finish
        self.execute(
            SetTaskProgress(
                task_id,
                percent_complete=percent,
                actual_start=actual_start,
                actual_finish=actual_finish,
            )
        )

    def edit_task_constraint(
        self, task_id: int, constraint_type: ConstraintType, constraint_date: date | None
    ) -> None:
        self.execute(SetTaskConstraint(task_id, constraint_type, constraint_date))

    def edit_task_color(self, task_id: int, color_id: str) -> None:
        """Sets a top-level task's color_id. Only meaningful for a
        top-level task â€” a nested task inherits its ancestor's color for
        display (see core.wbs.effective_color_id) rather than picking its
        own, so callers should only invoke this for a top-level task_id."""
        self.execute(SetTaskColor(task_id, color_id))

    def set_predecessors_from_text(self, task_id: int, text: str) -> None:
        """Replaces task_id's predecessor set from MS Project-style text
        (see parse_predecessors). Raises ValidationError on malformed text,
        a self-reference, or a resulting cyclic graph â€” in the cyclic case
        any commands already applied for this edit are rolled back first,
        so the edit is all-or-nothing.
        """
        new_terms = parse_predecessors(self.project, text)

        new_preds = {(t.predecessor_id, t.type, t.lag_days) for t in new_terms}
        if any(pred_id == task_id for pred_id, _, _ in new_preds):
            raise ValidationError("A task cannot depend on itself")

        existing = [dep for dep in self.project.dependencies if dep.successor_id == task_id]
        existing_keys = {(dep.predecessor_id, dep.type, dep.lag_days) for dep in existing}

        to_remove = [dep for dep in existing if (dep.predecessor_id, dep.type, dep.lag_days) not in new_preds]
        to_add = [
            Dependency(predecessor_id=pred_id, successor_id=task_id, type=dep_type, lag_days=lag)
            for pred_id, dep_type, lag in new_preds
            if (pred_id, dep_type, lag) not in existing_keys
        ]

        undo_depth_before = len(self._undo_stack)
        try:
            for dep in to_remove:
                self.execute(RemoveDependency(dep.predecessor_id, dep.successor_id))
            for dep in to_add:
                self.execute(AddDependency(dep))
        except CyclicDependencyError as exc:
            # execute() itself raised while recomputing projections for a
            # command that *did* apply and get pushed to history (schedule
            # recomputation happens after the push) â€” so on failure there
            # may be one command on the stack beyond undo_depth_before that
            # the loop below wouldn't otherwise know about.
            while len(self._undo_stack) > undo_depth_before:
                self.undo()
            raise ValidationError(str(exc)) from exc

    # -- resource intents -------------------------------------------------

    def add_resource(self, name: str, rate: float, max_units: float) -> int:
        resource_id = self.project.next_resource_id()
        self.execute(AddResource(Resource(id=resource_id, name=name, rate=rate, max_units=max_units)))
        return resource_id

    def remove_resource(self, resource_id: int) -> None:
        self.execute(RemoveResource(resource_id))

    def add_assignment(self, task_id: int, resource_id: int, units: float) -> None:
        self.execute(AddAssignment(Assignment(task_id=task_id, resource_id=resource_id, units=units)))

    def remove_assignment(self, task_id: int, resource_id: int) -> None:
        self.execute(RemoveAssignment(task_id, resource_id))

    # -- project settings / baselines -------------------------------------

    def set_project_settings(self, start: date, working_weekdays: frozenset[int]) -> None:
        if start != self.project.start:
            self.execute(SetProjectStart(start))
        if working_weekdays != self.project.calendar.working_weekdays:
            self.execute(SetWorkingWeekdays(working_weekdays))

    def capture_baseline(self, name: str) -> int:
        baseline_id = self.project.next_baseline_id()
        baseline = self.project.build_baseline_snapshot(baseline_id=baseline_id, name=name)
        self.execute(AddBaseline(baseline))
        return baseline_id

    def select_baseline(self, baseline_id: int | None) -> None:
        """Chooses which baseline the variance/tracking-Gantt projections
        show. Not undoable â€” it's a view selection, not a project edit."""
        self._selected_baseline_id = baseline_id
        self._refresh_projections()

    @property
    def selected_baseline_id(self) -> int | None:
        return self._selected_baseline_id

    # -- projections -----------------------------------------------------

    def _refresh_projections(self) -> None:
        self.projections = self._compute_projections()

    def _compute_projections(self) -> ProjectionState:
        project = self.project
        tasks = project.tasks
        tasks_by_id = {t.id: t for t in tasks}
        summary_ids = {t.parent_id for t in tasks if t.parent_id is not None}

        # The scheduler (core/scheduler.py) schedules executable leaf
        # tasks only; summary tasks (anything with children) are excluded
        # from its input and instead get their start/finish/duration/%
        # complete derived afterward by core.wbs.summary_rollups, per the
        # Phase 7 rule "scheduling stays separate from WBS presentation".
        leaf_tasks = [t for t in tasks if t.id not in summary_ids]
        leaf_ids = {t.id for t in leaf_tasks}
        leaf_dependencies = [
            dep
            for dep in project.dependencies
            if dep.predecessor_id in leaf_ids and dep.successor_id in leaf_ids
        ]
        schedules: dict[int, TaskSchedule] = (
            run_scheduler(leaf_tasks, leaf_dependencies, project.calendar, project.start)
            if leaf_tasks
            else {}
        )
        rollups = summary_rollups(tasks, schedules) if summary_ids else {}

        outline = outline_numbers(tasks)

        task_rows = tuple(
            self._build_task_row(project, tasks, task, row, tasks_by_id, summary_ids, schedules, rollups, outline)
            for row, task in enumerate(tasks)
        )

        over_allocated_ids: set[int] = set()
        if tasks:
            over_allocations = find_over_allocations(project.resources, project.assignments, schedules)
            over_allocated_ids = {oa.resource_id for oa in over_allocations}

        resource_rows = tuple(
            ResourceRow(
                resource_id=resource.id,
                name=resource.name,
                rate=resource.rate,
                max_units=resource.max_units,
                is_over_allocated=resource.id in over_allocated_ids,
            )
            for resource in project.resources
        )

        gantt = self._compute_gantt_projection(schedules, rollups, summary_ids)

        baseline_list = tuple(
            BaselineListItem(baseline_id=b.id, name=b.name) for b in project.baselines
        )

        return ProjectionState(
            project_name=project.name,
            task_rows=task_rows,
            resource_rows=resource_rows,
            gantt=gantt,
            baseline_list=baseline_list,
            can_undo=self.can_undo,
            can_redo=self.can_redo,
            is_dirty=self.is_dirty,
            current_path=self.current_path,
        )

    def _build_task_row(
        self,
        project: Project,
        tasks: list[Task],
        task: Task,
        row: int,
        tasks_by_id: dict[int, Task],
        summary_ids: set[int],
        schedules: dict[int, TaskSchedule],
        rollups: dict[int, SummaryRollup],
        outline: dict[int, str],
    ) -> TaskRow:
        task_is_summary = task.id in summary_ids
        if task_is_summary:
            rollup = rollups[task.id]
            duration_days = rollup.duration_days
            percent_complete = rollup.percent_complete
        else:
            duration_days = task.duration_days
            percent_complete = task.percent_complete

        return TaskRow(
            task_id=task.id,
            row=row,
            name=task.name,
            duration_days=duration_days,
            percent_complete=percent_complete,
            predecessors_text=_format_predecessors(project, task.id),
            constraint_type=task.constraint_type,
            constraint_date=task.constraint_date,
            actual_start=task.actual_start,
            actual_finish=task.actual_finish,
            outline_number=outline[task.id],
            depth=depth_of(tasks_by_id, task.id),
            is_summary=task_is_summary,
            can_indent=can_indent(tasks, task.id),
            can_outdent=can_outdent(tasks, task.id),
            color_id=effective_color_id(tasks_by_id, task.id),
            is_top_level=task.parent_id is None,
        )

    def _compute_gantt_projection(
        self,
        schedules: dict[int, TaskSchedule],
        rollups: dict[int, SummaryRollup],
        summary_ids: set[int],
    ) -> GanttProjection:
        project = self.project
        tasks = project.tasks
        tasks_by_id = {t.id: t for t in tasks}
        row_of_task = {task.id: row for row, task in enumerate(tasks)}

        baseline = None
        if self._selected_baseline_id is not None:
            baseline = project.get_baseline(self._selected_baseline_id)

        if schedules:
            chart_start = min(s.early_start for s in schedules.values())
        else:
            chart_start = project.start
        if baseline is not None and baseline.task_snapshots:
            chart_start = min(chart_start, min(s.start for s in baseline.task_snapshots.values()))

        bars = tuple(
            GanttBar(
                task_id=task.id,
                row=row_of_task[task.id],
                start=schedules[task.id].early_start if task.id in schedules else rollups[task.id].start,
                finish=schedules[task.id].early_finish if task.id in schedules else rollups[task.id].finish,
                is_critical=schedules[task.id].is_critical if task.id in schedules else False,
                color_id=effective_color_id(tasks_by_id, task.id),
                is_top_level=task.parent_id is None,
                is_summary=task.id in summary_ids,
            )
            for task in tasks
        )

        baseline_bars: tuple[GanttBaselineBar, ...] = ()
        if baseline is not None:
            baseline_bars = tuple(
                GanttBaselineBar(
                    task_id=task_id,
                    row=row_of_task[task_id],
                    start=snapshot.start,
                    finish=snapshot.finish,
                )
                for task_id, snapshot in baseline.task_snapshots.items()
                if task_id in row_of_task
            )

        dependency_arrows = tuple(
            GanttDependencyArrow(
                predecessor_id=dep.predecessor_id,
                successor_id=dep.successor_id,
                predecessor_row=row_of_task[dep.predecessor_id],
                successor_row=row_of_task[dep.successor_id],
                predecessor_finish=schedules[dep.predecessor_id].early_finish,
                successor_start=schedules[dep.successor_id].early_start,
            )
            for dep in project.dependencies
            if dep.predecessor_id in schedules and dep.successor_id in schedules
        )

        return GanttProjection(
            chart_start=chart_start,
            bars=bars,
            dependency_arrows=dependency_arrows,
            baseline_bars=baseline_bars,
            row_count=len(tasks),
        )

    def variance_rows(self, baseline_id: int | None) -> list[VarianceRow]:
        if baseline_id is None:
            return []
        baseline = self.project.get_baseline(baseline_id)
        schedules = self.project.compute_schedule()
        variances = compute_variance(baseline, schedules)
        return [
            VarianceRow(
                task_id=v.task_id,
                task_name=self.project.get_task(v.task_id).name,
                baseline_start=v.baseline_start,
                baseline_finish=v.baseline_finish,
                current_start=v.current_start,
                current_finish=v.current_finish,
                start_variance_days=v.start_variance_days,
                finish_variance_days=v.finish_variance_days,
            )
            for v in variances
        ]

    def assignment_rows(self, task_id: int) -> list[AssignmentRow]:
        return [
            AssignmentRow(
                resource_id=a.resource_id,
                resource_name=self.project.get_resource(a.resource_id).name,
                units=a.units,
            )
            for a in self.project.assignments_for_task(task_id)
        ]

    def assignable_resources(self, task_id: int) -> list[AssignableResource]:
        assigned_ids = {a.resource_id for a in self.project.assignments_for_task(task_id)}
        return [
            AssignableResource(resource_id=r.id, name=r.name)
            for r in self.project.resources
            if r.id not in assigned_ids
        ]
