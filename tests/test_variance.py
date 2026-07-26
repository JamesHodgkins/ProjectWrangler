from datetime import date

from coconut.core.commands import AddTask, EditTaskDuration, RemoveTask
from coconut.core.models import Task
from coconut.core.project import Project
from coconut.core.variance import compute_variance

PROJECT_START = date(2026, 1, 1)


def test_no_variance_when_schedule_unchanged():
    project = Project(name="Sample", start=PROJECT_START)
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=3)))
    baseline = project.build_baseline_snapshot(baseline_id=1, name="Baseline 1")

    variances = compute_variance(baseline, project.compute_schedule())
    assert len(variances) == 1
    assert variances[0].start_variance_days == 0
    assert variances[0].finish_variance_days == 0


def test_variance_reflects_duration_change():
    project = Project(name="Sample", start=PROJECT_START)
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=3)))
    baseline = project.build_baseline_snapshot(baseline_id=1, name="Baseline 1")

    project.apply_command(EditTaskDuration(task_id=1, new_duration_days=6))
    variances = compute_variance(baseline, project.compute_schedule())

    assert variances[0].start_variance_days == 0
    assert variances[0].finish_variance_days == 3


def test_variance_skips_tasks_removed_since_baseline():
    project = Project(name="Sample", start=PROJECT_START)
    project.apply_command(AddTask(Task(id=1, name="A", duration_days=3)))
    project.apply_command(AddTask(Task(id=2, name="B", duration_days=2)))
    baseline = project.build_baseline_snapshot(baseline_id=1, name="Baseline 1")

    project.apply_command(RemoveTask(task_id=2))
    variances = compute_variance(baseline, project.compute_schedule())

    assert {v.task_id for v in variances} == {1}
