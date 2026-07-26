"""Variance view: current vs. baseline dates/duration for a chosen baseline.

Displays VarianceRow/BaselineListItem projections from Application;
baseline selection is emitted as intent, not applied directly.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtWidgets import QComboBox, QHeaderView, QTableView, QVBoxLayout, QWidget

from coconut.application.view_models import BaselineListItem, VarianceRow

_COLUMNS = ("Task", "Baseline Start", "Baseline Finish", "Current Start", "Current Finish", "Start Var (d)", "Finish Var (d)")


class VarianceTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[VarianceRow] = []

    def set_variance_rows(self, rows: list[VarianceRow]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        return _COLUMNS[section]

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        variance = self._rows[index.row()]
        values = (
            variance.task_name,
            variance.baseline_start.isoformat(),
            variance.baseline_finish.isoformat(),
            variance.current_start.isoformat(),
            variance.current_finish.isoformat(),
            variance.start_variance_days,
            variance.finish_variance_days,
        )
        return values[index.column()]


class VarianceView(QWidget):
    baseline_selected = Signal(object)  # baseline_id: int | None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = VarianceTableModel()

        self.baseline_combo = QComboBox(self)
        self.baseline_combo.currentIndexChanged.connect(self._on_baseline_selected)

        self.table = QTableView(self)
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)

        layout = QVBoxLayout(self)
        layout.addWidget(self.baseline_combo)
        layout.addWidget(self.table)
        layout.setContentsMargins(0, 0, 0, 0)

    def set_baseline_list(self, items: list[BaselineListItem]) -> None:
        self.baseline_combo.blockSignals(True)
        self.baseline_combo.clear()
        for item in items:
            self.baseline_combo.addItem(item.name, item.baseline_id)
        self.baseline_combo.blockSignals(False)

    def set_variance_rows(self, rows: list[VarianceRow]) -> None:
        self.model.set_variance_rows(rows)

    def _on_baseline_selected(self, combo_index: int) -> None:
        baseline_id = self.baseline_combo.itemData(combo_index) if combo_index >= 0 else None
        self.baseline_selected.emit(baseline_id)
