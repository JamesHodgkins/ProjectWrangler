"""Current-vs-baseline variance for progress tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from coconut.core.models import Baseline
from coconut.core.scheduler import TaskSchedule


@dataclass
class TaskVariance:
    task_id: int
    baseline_start: date
    baseline_finish: date
    current_start: date
    current_finish: date

    @property
    def start_variance_days(self) -> int:
        return (self.current_start - self.baseline_start).days

    @property
    def finish_variance_days(self) -> int:
        return (self.current_finish - self.baseline_finish).days


def compute_variance(
    baseline: Baseline, current_schedule: dict[int, TaskSchedule]
) -> list[TaskVariance]:
    variances = []
    for task_id, snapshot in baseline.task_snapshots.items():
        current = current_schedule.get(task_id)
        if current is None:
            continue  # task existed in the baseline but was since removed
        variances.append(
            TaskVariance(
                task_id=task_id,
                baseline_start=snapshot.start,
                baseline_finish=snapshot.finish,
                current_start=current.early_start,
                current_finish=current.early_finish,
            )
        )
    return variances
