"""Tests for the WBS hierarchy service (core/wbs.py): outline numbering,
indent/outdent legality, cycle prevention, and summary rollups.

These operate on plain Task lists (in display order), independent of
Project/Application, mirroring how core/wbs.py itself has no dependency
on either.
"""

from datetime import date

import pytest

from coconut.core.exceptions import ValidationError
from coconut.core.models import Task
from coconut.core.scheduler import TaskSchedule
from coconut.core.wbs import (
    can_indent,
    can_outdent,
    depth_of,
    effective_color_id,
    indent_target_parent,
    is_summary,
    outdent_target_parent,
    outline_numbers,
    summary_rollups,
    would_create_cycle,
)


def _task(
    task_id: int,
    name: str,
    parent_id: int | None = None,
    duration: float = 1,
    percent: float = 0.0,
    color_id: str = "red",
) -> Task:
    return Task(
        id=task_id,
        name=name,
        duration_days=duration,
        parent_id=parent_id,
        percent_complete=percent,
        color_id=color_id,
    )


def test_outline_numbers_flat():
    tasks = [_task(1, "A"), _task(2, "B"), _task(3, "C")]
    numbers = outline_numbers(tasks)
    assert numbers == {1: "1", 2: "2", 3: "3"}


def test_outline_numbers_nested():
    tasks = [
        _task(1, "Phase 1"),
        _task(2, "Task A", parent_id=1),
        _task(3, "Task B", parent_id=1),
        _task(4, "Phase 2"),
        _task(5, "Task C", parent_id=4),
    ]
    numbers = outline_numbers(tasks)
    assert numbers == {1: "1", 2: "1.1", 3: "1.2", 4: "2", 5: "2.1"}


def test_outline_numbers_multi_level():
    tasks = [
        _task(1, "Phase 1"),
        _task(2, "Sub", parent_id=1),
        _task(3, "Leaf", parent_id=2),
    ]
    numbers = outline_numbers(tasks)
    assert numbers == {1: "1", 2: "1.1", 3: "1.1.1"}


def test_outline_numbers_follow_display_order_not_id():
    # id 2 appears before id 1 in display order -> numbered 1, 2 accordingly.
    tasks = [_task(2, "B"), _task(1, "A")]
    numbers = outline_numbers(tasks)
    assert numbers == {2: "1", 1: "2"}


def test_is_summary():
    tasks = [_task(1, "Parent"), _task(2, "Child", parent_id=1)]
    assert is_summary(tasks, 1) is True
    assert is_summary(tasks, 2) is False


def test_depth_of():
    tasks = [_task(1, "A"), _task(2, "B", parent_id=1), _task(3, "C", parent_id=2)]
    tasks_by_id = {t.id: t for t in tasks}
    assert depth_of(tasks_by_id, 1) == 0
    assert depth_of(tasks_by_id, 2) == 1
    assert depth_of(tasks_by_id, 3) == 2


def test_can_indent_first_sibling_cannot_indent():
    tasks = [_task(1, "A"), _task(2, "B")]
    assert can_indent(tasks, 1) is False
    assert can_indent(tasks, 2) is True


def test_indent_target_parent_is_previous_sibling():
    tasks = [_task(1, "A"), _task(2, "B")]
    assert indent_target_parent(tasks, 2) == 1


def test_indent_target_parent_raises_when_no_previous_sibling():
    tasks = [_task(1, "A"), _task(2, "B")]
    with pytest.raises(ValidationError):
        indent_target_parent(tasks, 1)


def test_can_outdent_requires_parent():
    tasks = [_task(1, "A"), _task(2, "B", parent_id=1)]
    assert can_outdent(tasks, 1) is False
    assert can_outdent(tasks, 2) is True


def test_outdent_target_parent_is_grandparent():
    tasks = [_task(1, "A"), _task(2, "B", parent_id=1), _task(3, "C", parent_id=2)]
    assert outdent_target_parent(tasks, 3) == 1
    assert outdent_target_parent(tasks, 2) is None


def test_outdent_target_parent_raises_when_top_level():
    tasks = [_task(1, "A")]
    with pytest.raises(ValidationError):
        outdent_target_parent(tasks, 1)


def test_would_create_cycle_direct_self_parent():
    tasks_by_id = {1: _task(1, "A")}
    assert would_create_cycle(tasks_by_id, 1, 1) is True


def test_would_create_cycle_transitive():
    tasks = [_task(1, "A"), _task(2, "B", parent_id=1), _task(3, "C", parent_id=2)]
    tasks_by_id = {t.id: t for t in tasks}
    # Making 1 a child of 3 (its own descendant) would create a cycle.
    assert would_create_cycle(tasks_by_id, 1, 3) is True


def test_would_create_cycle_false_for_valid_reparent():
    tasks = [_task(1, "A"), _task(2, "B"), _task(3, "C", parent_id=1)]
    tasks_by_id = {t.id: t for t in tasks}
    assert would_create_cycle(tasks_by_id, 3, 2) is False


def test_would_create_cycle_none_parent_is_always_safe():
    tasks_by_id = {1: _task(1, "A")}
    assert would_create_cycle(tasks_by_id, 1, None) is False


def test_effective_color_id_top_level_task_uses_own_color():
    tasks_by_id = {1: _task(1, "A", color_id="peach")}
    assert effective_color_id(tasks_by_id, 1) == "peach"


def test_effective_color_id_child_inherits_top_level_ancestor():
    tasks = [_task(1, "A", color_id="peach"), _task(2, "B", parent_id=1), _task(3, "C", parent_id=2)]
    tasks_by_id = {t.id: t for t in tasks}
    assert effective_color_id(tasks_by_id, 2) == "peach"
    assert effective_color_id(tasks_by_id, 3) == "peach"


def test_effective_color_id_defaults_to_red_when_unassigned():
    tasks = [_task(1, "A"), _task(2, "B", parent_id=1)]
    tasks_by_id = {t.id: t for t in tasks}
    assert effective_color_id(tasks_by_id, 2) == "red"


def _schedule(task_id: int, start: date, finish: date) -> TaskSchedule:
    return TaskSchedule(task_id=task_id, early_start=start, early_finish=finish, late_start=start, late_finish=finish)


def test_summary_rollup_single_level():
    tasks = [
        _task(1, "Parent"),
        _task(2, "Child A", parent_id=1, duration=3, percent=100.0),
        _task(3, "Child B", parent_id=1, duration=2, percent=0.0),
    ]
    leaf_schedules = {
        2: _schedule(2, date(2026, 1, 1), date(2026, 1, 3)),
        3: _schedule(3, date(2026, 1, 4), date(2026, 1, 5)),
    }
    rollups = summary_rollups(tasks, leaf_schedules)
    parent = rollups[1]
    assert parent.start == date(2026, 1, 1)
    assert parent.finish == date(2026, 1, 5)
    assert parent.duration_days == 5
    # Weighted by duration: (100*3 + 0*2) / 5 = 60
    assert parent.percent_complete == pytest.approx(60.0)


def test_summary_rollup_nested():
    tasks = [
        _task(1, "Top"),
        _task(2, "Mid", parent_id=1),
        _task(3, "Leaf A", parent_id=2, duration=2, percent=50.0),
        _task(4, "Leaf B", parent_id=2, duration=2, percent=50.0),
    ]
    leaf_schedules = {
        3: _schedule(3, date(2026, 1, 1), date(2026, 1, 2)),
        4: _schedule(4, date(2026, 1, 3), date(2026, 1, 4)),
    }
    rollups = summary_rollups(tasks, leaf_schedules)
    assert rollups[2].start == date(2026, 1, 1)
    assert rollups[2].finish == date(2026, 1, 4)
    assert rollups[1].start == date(2026, 1, 1)
    assert rollups[1].finish == date(2026, 1, 4)
    assert rollups[1].percent_complete == pytest.approx(50.0)
