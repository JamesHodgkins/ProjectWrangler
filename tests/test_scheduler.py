from datetime import date

import pytest

from coconut.core.calendar import Calendar
from coconut.core.models import ConstraintType, Dependency, DependencyType, Task
from coconut.core.scheduler import (
    CyclicDependencyError,
    critical_path,
    schedule,
)

PROJECT_START = date(2026, 1, 1)


@pytest.fixture
def calendar():
    # Every day is a working day, for simple arithmetic â€” Calendar()'s
    # actual default is Mon-Fri (see test_calendar.py), but these tests
    # exercise scheduling logic, not calendar/weekend semantics.
    return Calendar(working_weekdays=frozenset(range(7)))


def test_single_task_starts_at_project_start(calendar):
    # A 3-day task starting Jan 1 consumes Jan 1, 2, 3 (the start day
    # counts toward the duration) and finishes Jan 3, not Jan 4.
    tasks = [Task(id=1, name="A", duration_days=3)]
    result = schedule(tasks, [], calendar, PROJECT_START)
    sched = result[1]
    assert sched.early_start == PROJECT_START
    assert sched.early_finish == date(2026, 1, 3)
    assert sched.is_critical


def test_two_task_chain_finish_to_start(calendar):
    tasks = [
        Task(id=1, name="A", duration_days=3),
        Task(id=2, name="B", duration_days=2),
    ]
    deps = [Dependency(predecessor_id=1, successor_id=2)]
    result = schedule(tasks, deps, calendar, PROJECT_START)

    # A: Jan 1-3. B (FS, no lag) starts the day after A finishes (Jan 4)
    # and, being 2 days, finishes Jan 5.
    assert result[1].early_finish == date(2026, 1, 3)
    assert result[2].early_start == date(2026, 1, 4)
    assert result[2].early_finish == date(2026, 1, 5)
    assert result[1].is_critical
    assert result[2].is_critical


def test_parallel_paths_produce_float_on_shorter_path():
    # A (5d) -> C (2d); B (2d) -> C (2d). A/C are critical, B has float.
    tasks = [
        Task(id=1, name="A", duration_days=5),
        Task(id=2, name="B", duration_days=2),
        Task(id=3, name="C", duration_days=2),
    ]
    deps = [
        Dependency(predecessor_id=1, successor_id=3),
        Dependency(predecessor_id=2, successor_id=3),
    ]
    result = schedule(tasks, deps, Calendar(working_weekdays=frozenset(range(7))), PROJECT_START)

    assert result[1].is_critical
    assert result[3].is_critical
    assert not result[2].is_critical
    assert result[2].total_float_days == 3


def test_finish_to_start_with_lag(calendar):
    tasks = [
        Task(id=1, name="A", duration_days=2),
        Task(id=2, name="B", duration_days=1),
    ]
    deps = [Dependency(predecessor_id=1, successor_id=2, lag_days=3)]
    result = schedule(tasks, deps, calendar, PROJECT_START)

    # FS lag of 3 working days after the predecessor's finish, plus the
    # usual +1 to move past the finish day itself (see
    # test_two_task_chain_finish_to_start).
    assert result[2].early_start == calendar.add_days(result[1].early_finish, 4)


def test_start_to_start(calendar):
    tasks = [
        Task(id=1, name="A", duration_days=5),
        Task(id=2, name="B", duration_days=2),
    ]
    deps = [Dependency(predecessor_id=1, successor_id=2, type=DependencyType.START_TO_START)]
    result = schedule(tasks, deps, calendar, PROJECT_START)

    assert result[2].early_start == result[1].early_start


def test_finish_to_finish(calendar):
    tasks = [
        Task(id=1, name="A", duration_days=5),
        Task(id=2, name="B", duration_days=2),
    ]
    deps = [Dependency(predecessor_id=1, successor_id=2, type=DependencyType.FINISH_TO_FINISH)]
    result = schedule(tasks, deps, calendar, PROJECT_START)

    assert result[2].early_finish == result[1].early_finish


def test_start_to_finish(calendar):
    tasks = [
        Task(id=1, name="A", duration_days=5),
        Task(id=2, name="B", duration_days=2),
    ]
    deps = [Dependency(predecessor_id=1, successor_id=2, type=DependencyType.START_TO_FINISH)]
    result = schedule(tasks, deps, calendar, PROJECT_START)

    assert result[2].early_finish == result[1].early_start


def test_cyclic_dependency_is_detected(calendar):
    tasks = [
        Task(id=1, name="A", duration_days=1),
        Task(id=2, name="B", duration_days=1),
    ]
    deps = [
        Dependency(predecessor_id=1, successor_id=2),
        Dependency(predecessor_id=2, successor_id=1),
    ]
    with pytest.raises(CyclicDependencyError):
        schedule(tasks, deps, calendar, PROJECT_START)


def test_start_no_earlier_than_pushes_start_later_than_asap(calendar):
    # No predecessor, so the ASAP start would be project_start (Jan 1);
    # SNET should push it out to the constraint date instead.
    tasks = [
        Task(
            id=1,
            name="A",
            duration_days=3,
            constraint_type=ConstraintType.START_NO_EARLIER_THAN,
            constraint_date=date(2026, 1, 6),
        )
    ]
    result = schedule(tasks, [], calendar, PROJECT_START)
    assert result[1].early_start == date(2026, 1, 6)
    assert result[1].early_finish == date(2026, 1, 8)


def test_must_start_on_overrides_dependency_even_when_conflicting(calendar):
    # B is forced to start Jan 2 by MSO even though its FS predecessor A
    # doesn't finish until Jan 3 â€” a real constraint conflict, which
    # should surface as the hard date winning (matching MS Project), not
    # an error.
    tasks = [
        Task(id=1, name="A", duration_days=3),
        Task(
            id=2,
            name="B",
            duration_days=2,
            constraint_type=ConstraintType.MUST_START_ON,
            constraint_date=date(2026, 1, 2),
        ),
    ]
    deps = [Dependency(predecessor_id=1, successor_id=2)]
    result = schedule(tasks, deps, calendar, PROJECT_START)
    assert result[2].early_start == date(2026, 1, 2)


def test_start_no_later_than_caps_late_start_and_removes_float(calendar):
    # C is a long, unconstrained parallel task that pushes the project
    # finish out to Jan 7, giving B (which finishes well before that)
    # slack. An SNLT constraint on B should cap its late_start back down,
    # eliminating that float.
    tasks = [
        Task(id=1, name="A", duration_days=3),
        Task(
            id=2,
            name="B",
            duration_days=2,
            constraint_type=ConstraintType.START_NO_LATER_THAN,
            constraint_date=date(2026, 1, 4),
        ),
        Task(id=3, name="C", duration_days=7),
    ]
    deps = [Dependency(predecessor_id=1, successor_id=2)]
    result = schedule(tasks, deps, calendar, PROJECT_START)

    assert result[2].early_start == date(2026, 1, 4)
    assert result[2].late_start == date(2026, 1, 4)
    assert result[2].total_float_days == 0


def test_finish_no_later_than_can_produce_negative_float(calendar):
    # An unconstrained 7-day task normally has zero float (it's a leaf
    # with no successors, so its late_finish == project_finish ==
    # early_finish). An FNLT constraint earlier than its own early_finish
    # forces late_finish backward, producing negative float â€” the
    # standard signal of a constraint conflict.
    tasks = [
        Task(
            id=1,
            name="A",
            duration_days=7,
            constraint_type=ConstraintType.FINISH_NO_LATER_THAN,
            constraint_date=date(2026, 1, 5),
        )
    ]
    result = schedule(tasks, [], calendar, PROJECT_START)
    assert result[1].early_finish == date(2026, 1, 7)
    assert result[1].late_finish == date(2026, 1, 5)
    assert result[1].total_float_days < 0


def test_alap_cascades_to_successor(calendar):
    # C is a long, unconstrained parallel task that pushes the project
    # finish out to Jan 10, giving the A->B chain slack. A is ALAP, so it
    # should be pinned to its late_start (not its early/ASAP start), and
    # B (FS successor of A) should be pushed out to match, not left at
    # its old ASAP position.
    tasks = [
        Task(id=1, name="A", duration_days=3, constraint_type=ConstraintType.AS_LATE_AS_POSSIBLE),
        Task(id=2, name="B", duration_days=2),
        Task(id=3, name="C", duration_days=10),
    ]
    deps = [Dependency(predecessor_id=1, successor_id=2)]
    result = schedule(tasks, deps, calendar, PROJECT_START)

    assert result[1].total_float_days == 0
    assert result[1].early_start == result[1].late_start
    # ASAP would have put A at Jan 1 and B at Jan 4 â€” ALAP should push
    # both later, with B still starting the day after A finishes.
    assert result[1].early_start > PROJECT_START
    assert result[2].early_start == calendar.add_days(result[1].early_finish, 1)


def test_critical_path_helper_returns_only_zero_float_tasks():
    tasks = [
        Task(id=1, name="A", duration_days=5),
        Task(id=2, name="B", duration_days=2),
        Task(id=3, name="C", duration_days=2),
    ]
    deps = [
        Dependency(predecessor_id=1, successor_id=3),
        Dependency(predecessor_id=2, successor_id=3),
    ]
    result = schedule(tasks, deps, Calendar(working_weekdays=frozenset(range(7))), PROJECT_START)
    assert set(critical_path(result)) == {1, 3}
