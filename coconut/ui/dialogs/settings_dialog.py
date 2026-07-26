"""Modal dialog for editing project-level settings: the project start date
that unconstrained (ASAP) tasks schedule against, and which weekdays count
as working days for scheduling and Gantt weekend shading.

Returns the edited values; it does not mutate Project or call Application
itself — the caller decides whether/how to apply them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QVBoxLayout,
)

_WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass(frozen=True)
class ProjectSettingsResult:
    start: date
    working_weekdays: frozenset[int]


class SettingsDialog(QDialog):
    def __init__(self, start: date, working_weekdays: frozenset[int], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Project Settings")

        layout = QVBoxLayout(self)

        start_form = QFormLayout()
        self.start_date_edit = QDateEdit(self)
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDate(QDate(start.year, start.month, start.day))
        start_form.addRow("Project start date:", self.start_date_edit)
        layout.addLayout(start_form)

        weekdays_group = QGroupBox("Working Days", self)
        weekdays_layout = QVBoxLayout(weekdays_group)
        self.weekday_checks: list[QCheckBox] = []
        for weekday, name in enumerate(_WEEKDAY_NAMES):
            checkbox = QCheckBox(name, self)
            checkbox.setChecked(weekday in working_weekdays)
            self.weekday_checks.append(checkbox)
            weekdays_layout.addWidget(checkbox)
        layout.addWidget(weekdays_group)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def result_value(self) -> ProjectSettingsResult:
        qdate = self.start_date_edit.date()
        new_start = date(qdate.year(), qdate.month(), qdate.day())
        new_working_weekdays = frozenset(
            weekday for weekday, checkbox in enumerate(self.weekday_checks) if checkbox.isChecked()
        )
        return ProjectSettingsResult(start=new_start, working_weekdays=new_working_weekdays)

    @staticmethod
    def get_settings(
        start: date, working_weekdays: frozenset[int], parent=None
    ) -> tuple[ProjectSettingsResult | None, bool]:
        dialog = SettingsDialog(start, working_weekdays, parent)
        ok = dialog.exec() == QDialog.Accepted
        return (dialog.result_value, ok) if ok else (None, ok)
