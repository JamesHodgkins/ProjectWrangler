import pytest

from coconut.core.models import (
    Assignment,
    Dependency,
    DependencyType,
    Resource,
    Task,
)


def test_task_construction():
    task = Task(id=1, name="Design", duration_days=5)
    assert task.name == "Design"
    assert task.duration_days == 5


def test_task_rejects_empty_name():
    with pytest.raises(ValueError):
        Task(id=1, name="", duration_days=5)


def test_task_rejects_negative_duration():
    with pytest.raises(ValueError):
        Task(id=1, name="Design", duration_days=-1)


def test_dependency_defaults_to_finish_to_start():
    dep = Dependency(predecessor_id=1, successor_id=2)
    assert dep.type == DependencyType.FINISH_TO_START
    assert dep.lag_days == 0.0


def test_dependency_rejects_self_reference():
    with pytest.raises(ValueError):
        Dependency(predecessor_id=1, successor_id=1)


def test_resource_rejects_empty_name():
    with pytest.raises(ValueError):
        Resource(id=1, name="", rate=10.0)


def test_resource_rejects_non_positive_max_units():
    with pytest.raises(ValueError):
        Resource(id=1, name="Alice", max_units=0)


def test_assignment_rejects_non_positive_units():
    with pytest.raises(ValueError):
        Assignment(task_id=1, resource_id=1, units=0)
