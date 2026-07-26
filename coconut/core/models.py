"""Plain data model for tasks, dependencies, and resources.

No Qt or SQLite types here — see tests/test_architecture.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class DependencyType(Enum):
    FINISH_TO_START = "FS"
    START_TO_START = "SS"
    FINISH_TO_FINISH = "FF"
    START_TO_FINISH = "SF"


class ConstraintType(Enum):
    AS_SOON_AS_POSSIBLE = "ASAP"
    AS_LATE_AS_POSSIBLE = "ALAP"
    START_NO_EARLIER_THAN = "SNET"
    START_NO_LATER_THAN = "SNLT"
    FINISH_NO_EARLIER_THAN = "FNET"
    FINISH_NO_LATER_THAN = "FNLT"
    MUST_START_ON = "MSO"
    MUST_FINISH_ON = "MFO"


# Constraint types that don't pin the task to a specific calendar date —
# ASAP/ALAP are driven purely by dependencies/float, so constraint_date
# must be absent for these and required for all others.
_FLEXIBLE_CONSTRAINTS = (ConstraintType.AS_SOON_AS_POSSIBLE, ConstraintType.AS_LATE_AS_POSSIBLE)


@dataclass
class Task:
    id: int
    name: str
    duration_days: float
    percent_complete: float = 0.0
    actual_start: date | None = None
    actual_finish: date | None = None
    constraint_type: ConstraintType = ConstraintType.AS_SOON_AS_POSSIBLE
    constraint_date: date | None = None
    # WBS hierarchy: the parent task's id, or None for a top-level task.
    # Deliberately just an id reference on Task rather than a separate
    # tree/node structure — task identity (this id) must stay independent
    # of display order (Project._task_order) and of whether a task is a
    # summary (has children) or a leaf; parent_id is the one fact needed to
    # derive both, via core/wbs.py, without duplicating task state anywhere
    # else. Cycle prevention, indent/outdent legality, outline numbering,
    # and summary rollups all live in core/wbs.py, not here or in Project.
    parent_id: int | None = None
    # Key into ui.theme.TASK_COLOR_PALETTE — every task has one (default
    # "red", matching ui.theme.DEFAULT_TASK_COLOR_ID; kept as a literal
    # here rather than importing ui.theme, which core/ must stay free of —
    # see tests/test_architecture.py). Only meaningful on a top-level task
    # (parent_id is None): a child inherits its top-level ancestor's
    # color_id for display (see core/wbs.effective_color_id) rather than
    # carrying its own.
    color_id: str = "red"

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Task name must not be empty")
        if self.duration_days < 0:
            raise ValueError("Task duration_days must not be negative")
        if not 0.0 <= self.percent_complete <= 100.0:
            raise ValueError("Task percent_complete must be between 0 and 100")
        if self.constraint_type in _FLEXIBLE_CONSTRAINTS:
            if self.constraint_date is not None:
                raise ValueError(f"{self.constraint_type.value} constraint must not have a constraint_date")
        elif self.constraint_date is None:
            raise ValueError(f"{self.constraint_type.value} constraint requires a constraint_date")


@dataclass
class Dependency:
    predecessor_id: int
    successor_id: int
    type: DependencyType = DependencyType.FINISH_TO_START
    lag_days: float = 0.0

    def __post_init__(self) -> None:
        if self.predecessor_id == self.successor_id:
            raise ValueError("A task cannot depend on itself")


@dataclass
class Resource:
    id: int
    name: str
    rate: float = 0.0
    max_units: float = 1.0

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Resource name must not be empty")
        if self.max_units <= 0:
            raise ValueError("Resource max_units must be positive")


@dataclass
class Assignment:
    task_id: int
    resource_id: int
    units: float = 1.0

    def __post_init__(self) -> None:
        if self.units <= 0:
            raise ValueError("Assignment units must be positive")


@dataclass
class Baseline:
    id: int
    name: str
    task_snapshots: dict[int, "TaskSnapshot"] = field(default_factory=dict)


@dataclass
class TaskSnapshot:
    task_id: int
    start: date
    finish: date
    duration_days: float
