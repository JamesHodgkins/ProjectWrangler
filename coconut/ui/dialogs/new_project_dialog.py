"""Modal dialog for creating a new project: name plus start date.

Unlike the other dialogs in this package, there's no Project yet to mutate,
so this exposes a static get() helper (QInputDialog-style) that returns the
entered values rather than applying a command.
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QLineEdit


class NewProjectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Project")

        self.name_edit = QLineEdit(self)
        self.name_edit.setText("Untitled Project")
        self.name_edit.selectAll()

        self.start_date_edit = QDateEdit(self)
        self.start_date_edit.setCalendarPopup(True)
        today = date.today()
        self.start_date_edit.setDate(QDate(today.year, today.month, today.day))

        form = QFormLayout(self)
        form.addRow("Project name:", self.name_edit)
        form.addRow("Start date:", self.start_date_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    @property
    def project_name(self) -> str:
        return self.name_edit.text()

    @property
    def start_date(self) -> date:
        qdate = self.start_date_edit.date()
        return date(qdate.year(), qdate.month(), qdate.day())

    @staticmethod
    def get_new_project_info(parent=None) -> tuple[str, date, bool]:
        dialog = NewProjectDialog(parent)
        ok = dialog.exec() == QDialog.Accepted
        return dialog.project_name, dialog.start_date, ok
