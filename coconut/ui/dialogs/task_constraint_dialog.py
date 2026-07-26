"""Modal dialog for editing a single task's date constraint (MS Project-
style: ASAP/ALAP plus the six hard/soft date-bound constraint types).

Returns the edited constraint; it does not mutate Project or apply
commands itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout

from coconut.core.models import ConstraintType

_LABELS = {
    ConstraintType.AS_SOON_AS_POSSIBLE: "As Soon As Possible",
    ConstraintType.AS_LATE_AS_POSSIBLE: "As Late As Possible",
    ConstraintType.START_NO_EARLIER_THAN: "Start No Earlier Than",
    ConstraintType.START_NO_LATER_THAN: "Start No Later Than",
    ConstraintType.FINISH_NO_EARLIER_THAN: "Finish No Earlier Than",
    ConstraintType.FINISH_NO_LATER_THAN: "Finish No Later Than",
    ConstraintType.MUST_START_ON: "Must Start On",
    ConstraintType.MUST_FINISH_ON: "Must Finish On",
}

_FLEXIBLE = (ConstraintType.AS_SOON_AS_POSSIBLE, ConstraintType.AS_LATE_AS_POSSIBLE)


@dataclass(frozen=True)
class TaskConstraintResult:
    constraint_type: ConstraintType
    constraint_date: date | None


class TaskConstraintDialog(QDialog):
    def __init__(
        self, task_name: str, constraint_type: ConstraintType, constraint_date: date | None, parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Constraint â€” {task_name}")

        self.type_combo = QComboBox(self)
        for ctype, label in _LABELS.items():
            self.type_combo.addItem(label, ctype)
        self.type_combo.setCurrentIndex(self.type_combo.findData(constraint_type))
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)

        self.date_edit = QDateEdit(self)
        self.date_edit.setCalendarPopup(True)
        initial_date = constraint_date or date.today()
        self.date_edit.setDate(QDate(initial_date.year, initial_date.month, initial_date.day))

        form = QFormLayout()
        form.addRow("Type:", self.type_combo)
        form.addRow("Date:", self.date_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QFormLayout(self)
        layout.addRow(form)
        layout.addRow(buttons)

        self._on_type_changed()

    def _on_type_changed(self) -> None:
        self.date_edit.setEnabled(self.type_combo.currentData() not in _FLEXIBLE)

    @property
    def result_value(self) -> TaskConstraintResult:
        constraint_type: ConstraintType = self.type_combo.currentData()
        if constraint_type in _FLEXIBLE:
            constraint_date = None
        else:
            qdate = self.date_edit.date()
            constraint_date = date(qdate.year(), qdate.month(), qdate.day())
        return TaskConstraintResult(constraint_type=constraint_type, constraint_date=constraint_date)

    @staticmethod
    def get_constraint(
        task_name: str, constraint_type: ConstraintType, constraint_date: date | None, parent=None
    ) -> tuple[TaskConstraintResult | None, bool]:
        dialog = TaskConstraintDialog(task_name, constraint_type, constraint_date, parent)
        ok = dialog.exec() == QDialog.Accepted
        return (dialog.result_value, ok) if ok else (None, ok)
