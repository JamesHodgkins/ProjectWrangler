"""Immutable read models (projections) consumed by the UI layer.

Frozen dataclasses only â€” these carry no behavior beyond simple derived
properties, and nothing here may be mutated by a view. Application
(application/app.py) rebuilds them after every accepted command; Qt
models and widgets read them and never touch Project, the scheduler,
allocation, or variance modules directly.

Lives in application/, not core/: these are projections shaped for the
UI's needs (row/position, pre-resolved names, pre-computed Gantt
geometry inputs), not domain concepts core/ itself has any use for.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from coconut.core.models import ConstraintType, DependencyType


@dataclass(frozen=True)
class TaskRow:
    """One row of the WBS task table, at its current display position.

    duration_days/percent_complete are derived rollups (core.wbs.summary_
    rollups), not editable task fields, when is_summary is True â€” the UI
    must treat those two (and, transitively, predecessors on a summary
    row) as read-only rather than routing edits to Application the way it
    does for a leaf row's own fields.
    """

    task_id: int
    row: int
    name: str
    duration_days: float
    percent_complete: float
    predecessors_text: str
    constraint_type: ConstraintType
    constraint_date: date | None
    actual_start: date | None
    actual_finish: date | None
    outline_number: str
    depth: int
    is_summary: bool
    can_indent: bool
    can_outdent: bool
    # The task's own color_id if it's top-level, else its top-level
    # ancestor's (core.wbs.effective_color_id) â€” always what should be
    # *displayed*, never necessarily what's stored on this task's own
    # Task.color_id.
    color_id: str
    is_top_level: bool


@dataclass(frozen=True)
class ResourceRow:
    resource_id: int
    name: str
    rate: float
    max_units: float
    is_over_allocated: bool


@dataclass(frozen=True)
class GanttBar:
    task_id: int
    row: int
    start: date
    finish: date
    is_critical: bool
    color_id: str
    is_top_level: bool
    # True for a summary task (one with children) â€” such a task renders
    # as a bracket/caliper shape instead of a bar (see
    # GanttView._draw_summary_marker), regardless of is_top_level: a
    # top-level task with no children still renders as a normal bar.
    is_summary: bool


@dataclass(frozen=True)
class GanttBaselineBar:
    task_id: int
    row: int
    start: date
    finish: date


@dataclass(frozen=True)
class GanttDependencyArrow:
    predecessor_id: int
    successor_id: int
    predecessor_row: int
    successor_row: int
    predecessor_finish: date
    successor_start: date


@dataclass(frozen=True)
class GanttProjection:
    """Everything the Gantt view needs to paint a frame, pre-computed by
    Application so the view does no scheduling of its own."""

    chart_start: date
    bars: tuple[GanttBar, ...]
    dependency_arrows: tuple[GanttDependencyArrow, ...]
    baseline_bars: tuple[GanttBaselineBar, ...]
    row_count: int


@dataclass(frozen=True)
class VarianceRow:
    task_id: int
    task_name: str
    baseline_start: date
    baseline_finish: date
    current_start: date
    current_finish: date
    start_variance_days: int
    finish_variance_days: int


@dataclass(frozen=True)
class BaselineListItem:
    baseline_id: int
    name: str


@dataclass(frozen=True)
class AssignmentRow:
    resource_id: int
    resource_name: str
    units: float


@dataclass(frozen=True)
class AssignableResource:
    """A resource not yet assigned to the task the assignment dialog is
    currently editing."""

    resource_id: int
    name: str


@dataclass(frozen=True)
class ProjectionState:
    """The full set of projections Application recomputes after every
    accepted command. Views read the slice they need from here."""

    project_name: str
    task_rows: tuple[TaskRow, ...]
    resource_rows: tuple[ResourceRow, ...]
    gantt: GanttProjection
    baseline_list: tuple[BaselineListItem, ...]
    can_undo: bool
    can_redo: bool
    is_dirty: bool
    current_path: str | None
