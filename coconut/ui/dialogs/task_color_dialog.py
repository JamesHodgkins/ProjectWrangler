"""Modal dialog for picking a top-level task's shading color from the
preset palette (ui.theme.TASK_COLOR_PALETTE).

Every top-level task has a color (no "no color" option â€” see
Task.color_id/ui.theme.DEFAULT_TASK_COLOR_ID), so this always returns a
color_id. It does not mutate Project or apply commands itself.
"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QPushButton,
    QVBoxLayout,
)

from coconut.ui import theme

_SWATCH_SIZE = 32
_SWATCH_COLUMNS = 5


class TaskColorDialog(QDialog):
    def __init__(self, task_name: str, current_color_id: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Task Color â€” {task_name}")
        self._chosen_color_id = current_color_id

        grid = QGridLayout()
        grid.setSpacing(6)
        self._buttons: dict[str, QPushButton] = {}
        for index, (color_id, hex_value) in enumerate(theme.TASK_COLOR_PALETTE.items()):
            button = self._make_swatch_button(QColor(hex_value), color_id)
            grid.addWidget(button, index // _SWATCH_COLUMNS, index % _SWATCH_COLUMNS)

        buttons_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons_box.accepted.connect(self.accept)
        buttons_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(grid)
        layout.addWidget(buttons_box)

        self._update_checked_state()

    def _make_swatch_button(self, color: QColor, color_id: str) -> QPushButton:
        button = QPushButton(self)
        button.setCheckable(True)
        button.setFixedSize(QSize(_SWATCH_SIZE, _SWATCH_SIZE))
        button.setStyleSheet(
            f"QPushButton {{ background: {color.name()}; border: 1px solid #00000030; border-radius: 6px; }}"
            f"QPushButton:checked {{ border: 2px solid #1f2430; }}"
        )
        button.clicked.connect(lambda: self._choose(color_id))
        self._buttons[color_id] = button
        return button

    def _choose(self, color_id: str) -> None:
        self._chosen_color_id = color_id
        self._update_checked_state()

    def _update_checked_state(self) -> None:
        for color_id, button in self._buttons.items():
            button.setChecked(color_id == self._chosen_color_id)

    @property
    def result_value(self) -> str:
        return self._chosen_color_id

    @staticmethod
    def get_color(task_name: str, current_color_id: str, parent=None) -> tuple[str | None, bool]:
        dialog = TaskColorDialog(task_name, current_color_id, parent)
        ok = dialog.exec() == QDialog.Accepted
        return (dialog.result_value, True) if ok else (None, False)
