"""Resource sheet: a QTableView over ResourceRow read models.

No per-resource calendar field Ã¢â‚¬â€ resources use the single global
project calendar (see PROJECT_PLAN.md, Out of scope).
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView, QVBoxLayout, QWidget

from coconut.application.view_models import ResourceRow

_COLUMNS = ("Name", "Rate", "Max Units")
_OVER_ALLOCATED_BACKGROUND = QBrush(QColor("#f8d7da"))


class ResourceTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[ResourceRow] = []

    def set_resource_rows(self, rows: list[ResourceRow]) -> None:
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

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.NoItemFlags
        # Editing rate/max_units in place would need an EditResource command
        # (there isn't one yet); for now resources are edited via
        # remove-and-re-add, so cells are read-only rather than silently
        # accepting edits that don't save.
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        if role in (Qt.DisplayRole, Qt.EditRole):
            return (row.name, row.rate, row.max_units)[index.column()]
        if role == Qt.BackgroundRole and row.is_over_allocated:
            return _OVER_ALLOCATED_BACKGROUND
        return None

    def resource_row_at(self, row: int) -> ResourceRow:
        return self._rows[row]


class ResourceView(QWidget):
    resource_selected = Signal(int)
    add_resource_requested = Signal(str, float, float)  # name, rate, max_units
    remove_resource_requested = Signal(int)  # resource_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = ResourceTableModel()

        self.table = QTableView(self)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.selectionModel().currentRowChanged.connect(self._on_row_changed)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.setContentsMargins(0, 0, 0, 0)

    def set_resource_rows(self, rows: list[ResourceRow]) -> None:
        self.model.set_resource_rows(rows)

    def selected_resource_id(self) -> int | None:
        index = self.table.currentIndex()
        if not index.isValid():
            return None
        return self.model.resource_row_at(index.row()).resource_id

    def request_add_resource(self, name: str, rate: float, max_units: float) -> None:
        self.add_resource_requested.emit(name, rate, max_units)

    def request_remove_selected_resource(self) -> None:
        resource_id = self.selected_resource_id()
        if resource_id is None:
            return
        self.remove_resource_requested.emit(resource_id)

    def _on_row_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if current.isValid():
            self.resource_selected.emit(self.model.resource_row_at(current.row()).resource_id)
