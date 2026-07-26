"""Modal dialog for editing a single task's resource assignments.

Live-editing (add/remove while open) rather than a single OK/Cancel
result, so unlike the other dialogs this one emits intent signals as the
user acts and is re-populated by the caller from fresh Application
projections after each â€” it does not call Application or mutate Project
itself.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from coconut.application.view_models import AssignableResource, AssignmentRow
from coconut.ui.icons import icon


class AssignmentDialog(QDialog):
    assignment_add_requested = Signal(int, float)  # resource_id, units
    assignment_remove_requested = Signal(int)  # resource_id

    def __init__(self, task_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Assignments â€” {task_name}")

        self.list_widget = QListWidget(self)

        self.resource_combo = QComboBox(self)
        self.units_spin = QDoubleSpinBox(self)
        self.units_spin.setRange(0.01, 100.0)
        self.units_spin.setValue(1.0)
        self.units_spin.setSingleStep(0.1)

        add_button = QPushButton(icon("placeholder"), "", self)
        add_button.setToolTip("Add")
        add_button.setFixedSize(32, 32)
        add_button.setIconSize(QSize(26, 26))
        add_button.setStyleSheet("padding: 3px;")
        add_button.clicked.connect(self._emit_add)
        remove_button = QPushButton(icon("placeholder"), "", self)
        remove_button.setToolTip("Remove Selected")
        remove_button.setFixedSize(32, 32)
        remove_button.setIconSize(QSize(26, 26))
        remove_button.setStyleSheet("padding: 3px;")
        remove_button.clicked.connect(self._emit_remove)

        add_row = QHBoxLayout()
        add_row.addWidget(self.resource_combo)
        add_row.addWidget(self.units_spin)
        add_row.addWidget(add_button)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(self.list_widget)
        layout.addLayout(add_row)
        layout.addWidget(remove_button)
        layout.addWidget(buttons)

    def set_assignments(self, assignments: list[AssignmentRow]) -> None:
        self.list_widget.clear()
        for assignment in assignments:
            item = QListWidgetItem(f"{assignment.resource_name} â€” {assignment.units} units")
            item.setData(1, assignment.resource_id)
            self.list_widget.addItem(item)

    def set_assignable_resources(self, resources: list[AssignableResource]) -> None:
        self.resource_combo.clear()
        for resource in resources:
            self.resource_combo.addItem(resource.name, resource.resource_id)

    def _emit_add(self) -> None:
        if self.resource_combo.count() == 0:
            return
        resource_id = self.resource_combo.currentData()
        self.assignment_add_requested.emit(resource_id, self.units_spin.value())

    def _emit_remove(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        self.assignment_remove_requested.emit(item.data(1))
