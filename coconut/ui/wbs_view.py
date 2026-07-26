"""Task outline (WBS) view: a QTableView over TaskRow read models.

Displays projections from Application; setData() emits an edit-request
signal rather than mutating Project or applying commands. MainWindow
wires those signals to Application intent methods and pushes the
resulting projections back down via set_task_rows().
"""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QItemSelectionModel,
    QModelIndex,
    QRect,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QDoubleValidator, QFont, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLineEdit,
    QStyle,
    QStyleOptionHeader,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from coconut.application.view_models import TaskRow
from coconut.ui import theme

_COLUMNS = ("WBS", "Name", "Dur", "%", "Predecessors")
_COLUMN_TOOLTIPS = ("Outline number", "Name", "Duration (days)", "% Complete", "Predecessors")
_INDENT_PER_LEVEL = "    "  # display-only indent; hierarchy rules live in core/wbs.py

# Summary-row read-only cells (duration/%/predecessors, derived rollups â€”
# see TaskRow.is_summary): a muted foreground is enough to read as
# "locked" without a heavier visual treatment like a background tint,
# border, or icon. Lighter than theme._MUTED_TEXT so it's clearly
# distinguishable from normal task-row text at a glance.
_SUMMARY_LOCKED_TEXT = QColor("#9aa1ac")

_TOP_LEVEL_FONT = QFont()
_TOP_LEVEL_FONT.setBold(True)

# Rows no longer get a full-cell background tint for task color â€” instead
# every row gets a thin outline plus a colored bar down its left edge
# (see _RowColorDelegate.paint / _ROW_BORDER_WIDTH), so the color reads
# as a marker rather than washing out the row's text/selection contrast.
# A top-level row's bar is wider than a nested row's, so its color reads
# as the "primary" marker; the ID text margin below is anchored to the
# wider of the two so text still lines up between top-level and nested
# rows regardless of which bar width applies to a given row.
_LEFT_BAR_WIDTH = 8
_NESTED_LEFT_BAR_WIDTH = 4
_ROW_BORDER_WIDTH = 1
_ROW_BORDER_COLOR = QColor("#dde1e6")

# Extra left padding for the ID column's text, beyond the (widest) left
# bar, so the ID number doesn't sit flush against it (see
# _RowColorDelegate.paint).
_ID_COLUMN_TEXT_MARGIN = 6

# Selection tint: a single subtle, neutral grey for every row regardless
# of task color â€” deliberately not derived from the row's accent color
# (that was the previous behavior) so selection reads as a plain "this
# row is selected" cue rather than competing with the left color bar.
_ROW_SELECTED_BACKGROUND = QColor("#efefef")

# Extra height tacked onto the last row of each top-level group (i.e. the
# row immediately before the next top-level task), so nested rows within
# a group sit flush together while distinct groups read as visually
# separate â€” must match GanttView._GROUP_GAP so rows stay aligned between
# the two views (see MainWindow._sync_gantt_row_geometry). The extra
# strip is painted blank by _RowColorDelegate, not as part of the cell.
_GROUP_GAP = 6


def _row_accent_color(color_id: str) -> QColor | None:
    """Left-bar color marker for a row. color_id is always populated â€”
    a nested task's TaskRow.color_id is already its top-level ancestor's
    (see application.view_models.TaskRow.color_id / core.wbs.
    effective_color_id), so nested rows get the same marker color as
    their top-level parent, with no special-casing needed here."""
    hex_value = theme.TASK_COLOR_PALETTE.get(color_id)
    return QColor(hex_value) if hex_value is not None else None


def _is_locked_cell(row: TaskRow, column: int) -> bool:
    """True for a summary row's duration/%/predecessors columns â€” derived
    rollups (core.wbs.summary_rollups), read-only in this view. Shared by
    flags()/data() (to enforce/mute it) and the hover-cursor logic (to
    show "not allowed") so the three stay in agreement."""
    return row.is_summary and column in (2, 3, 4)


class _TwoRowHeaderView(QHeaderView):
    """Horizontal header that paints as two stacked rows: a single blank
    cell spanning the full width on top, and the usual per-column labels
    in the bottom row.

    Mirrors the Gantt view's two-tier date header (see GanttView's
    top/bottom header bands in drawBackground()) so both panes present the
    same header "shape" even though the WBS side has nothing to put in the
    top row yet â€” and like the Gantt's month band, the top row doesn't
    follow the bottom row's column boundaries.
    """

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self._top_row_height = 0

    def set_top_row_height(self, height: int) -> None:
        self._top_row_height = height
        self.updateGeometry()

    def paintSection(self, painter, rect: QRect, logicalIndex: int) -> None:
        # Only paint each section's usual label into the bottom row here;
        # the blank top row is painted once, spanning the full header
        # width as a single cell, in paintEvent() below â€” not per-section,
        # since it shouldn't follow the bottom row's column boundaries.
        bottom_rect = QRect(
            rect.left(), rect.top() + self._top_row_height, rect.width(), rect.height() - self._top_row_height
        )
        painter.save()
        painter.setClipRect(bottom_rect)
        super().paintSection(painter, bottom_rect, logicalIndex)
        painter.restore()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._top_row_height <= 0:
            return
        top_rect = QRect(0, 0, self.viewport().width(), self._top_row_height)
        painter = QPainter(self.viewport())
        option = QStyleOptionHeader()
        self.initStyleOption(option)
        option.rect = top_rect
        option.text = ""
        option.icon = QIcon()
        option.position = QStyleOptionHeader.OnlyOneSection
        self.style().drawControl(QStyle.CE_Header, option, painter, self)


class _RowColorDelegate(QStyledItemDelegate):
    """Overrides the default selection highlight for every task row â€” not
    just colored ones â€” with a darker/more-saturated tint of that row's
    own accent color (or neutral grey for an uncolored row), so the WBS
    table's selection state never mixes in the app's unrelated default
    accent color (see _ROW_SELECTED_BACKGROUND). Also paints a thin
    outline around every cell and, in the first column, a thicker
    colored bar down the left edge in place of the old full-row
    background tint (see _row_accent_color) â€” for every row, top-level
    or nested."""

    def paint(self, painter, option, index: QModelIndex) -> None:
        model = index.model()
        row: TaskRow = model.task_row_at(index.row())
        is_selected = bool(option.state & QStyle.State_Selected)

        # A group-end row is taller than the rest (see _GROUP_GAP /
        # WbsView.set_task_rows) so a gap opens up before the next
        # top-level task; that extra strip at the bottom is left blank
        # here rather than treated as part of the cell â€” the outline and
        # color bar below are confined to the base row height.
        full_rect = QRectF(option.rect)
        cell_rect = full_rect
        if model.is_group_end(index.row()):
            cell_rect = QRectF(full_rect.left(), full_rect.top(), full_rect.width(), full_rect.height() - _GROUP_GAP)

        opt = QStyleOptionViewItem(option)
        opt.rect = cell_rect.toRect()
        if index.column() == 0:
            # Push the ID text's rect right, past the left color bar, so
            # it isn't flush against it.
            opt.rect = opt.rect.adjusted(_LEFT_BAR_WIDTH + _ID_COLUMN_TEXT_MARGIN, 0, 0, 0)

        if is_selected:
            # Paint our own flat grey background, then delegate the rest
            # of the cell (text, icons) with State_Selected cleared so
            # the base style doesn't also paint its own default-colored
            # highlight over ours.
            painter.save()
            painter.fillRect(cell_rect, _ROW_SELECTED_BACKGROUND)
            painter.restore()

            opt.state = opt.state & ~QStyle.State_Selected
            super().paint(painter, opt, index)
        else:
            super().paint(painter, opt, index)

        # Only the outer edges of a top-level group get a border â€” the top
        # edge on its first (top-level) row, the bottom edge on its last
        # (group-end) row. Rows within the same group share a boundary
        # with no line drawn there at all, so nested rows read as flush
        # rather than each getting its own fully-boxed cell (which would
        # double up adjacent top/bottom borders into what reads as a
        # visible gap).
        painter.save()
        pen = QPen(_ROW_BORDER_COLOR)
        pen.setWidth(_ROW_BORDER_WIDTH)
        painter.setPen(pen)
        border_rect = cell_rect.adjusted(0, 0, -1, -1)
        painter.drawLine(border_rect.topLeft(), border_rect.bottomLeft())
        painter.drawLine(border_rect.topRight(), border_rect.bottomRight())
        if row.is_top_level:
            painter.drawLine(border_rect.topLeft(), border_rect.topRight())
        if model.is_group_end(index.row()):
            painter.drawLine(border_rect.bottomLeft(), border_rect.bottomRight())
        painter.restore()

        accent = _row_accent_color(row.color_id)
        if accent is not None and index.column() == 0:
            bar_rect = QRectF(cell_rect)
            bar_rect.setWidth(_LEFT_BAR_WIDTH if row.is_top_level else _NESTED_LEFT_BAR_WIDTH)
            painter.save()
            painter.fillRect(bar_rect, accent)
            painter.restore()


class _NarrowNumericDelegate(_RowColorDelegate):
    """Plain validated QLineEdit editor instead of Qt's default
    QDoubleSpinBox, whose up/down arrows don't fit the Dur/% columns'
    narrow, content-sized width."""

    def __init__(self, minimum: float, maximum: float, decimals: int, parent=None):
        super().__init__(parent)
        self._minimum = minimum
        self._maximum = maximum
        self._decimals = decimals

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        validator = QDoubleValidator(self._minimum, self._maximum, self._decimals, editor)
        validator.setNotation(QDoubleValidator.StandardNotation)
        editor.setValidator(validator)
        return editor

    def setEditorData(self, editor: QLineEdit, index: QModelIndex) -> None:
        value = index.model().data(index, Qt.EditRole)
        editor.setText(f"{value:g}")

    def setModelData(self, editor: QLineEdit, model, index: QModelIndex) -> None:
        model.setData(index, editor.text(), Qt.EditRole)


class TaskTableModel(QAbstractTableModel):
    """Displays TaskRow projections. Never touches Project/Application â€”
    setData() only emits an edit-request signal for MainWindow to route
    to Application; the model's own state doesn't change until the
    caller pushes a fresh set_task_rows() after the intent is applied.
    """

    duration_edit_requested = Signal(int, float)  # task_id, new_duration_days
    progress_edit_requested = Signal(int, float)  # task_id, new_percent
    predecessors_edit_requested = Signal(int, str)  # task_id, text

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[TaskRow] = []

    def set_task_rows(self, rows: list[TaskRow]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation != Qt.Horizontal:
            return None
        if role == Qt.DisplayRole:
            return _COLUMNS[section]
        if role == Qt.ToolTipRole:
            return _COLUMN_TOOLTIPS[section]
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.NoItemFlags
        row = self._rows[index.row()]
        if index.column() == 0:
            return Qt.ItemIsEnabled | Qt.ItemIsSelectable
        # Summary rows derive duration/%/predecessors from their children
        # (core.wbs.summary_rollups) and are read-only for those columns â€”
        # this is display-only enforcement of a fact Application/TaskRow
        # already computed; the view adds no hierarchy rules of its own.
        if _is_locked_cell(row, index.column()):
            return Qt.ItemIsEnabled | Qt.ItemIsSelectable
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        locked = _is_locked_cell(row, index.column())
        if role == Qt.ForegroundRole:
            return _SUMMARY_LOCKED_TEXT if locked else None
        if role == Qt.FontRole:
            return _TOP_LEVEL_FONT if row.depth == 0 else None
        if role not in (Qt.DisplayRole, Qt.EditRole):
            return None
        if index.column() == 0:
            return row.outline_number
        if index.column() == 1:
            if role == Qt.EditRole:
                return row.name
            return f"{_INDENT_PER_LEVEL * row.depth}{row.name}"
        if index.column() == 2:
            return row.duration_days
        if index.column() == 3:
            return row.percent_complete
        return row.predecessors_text

    def setData(self, index: QModelIndex, value, role=Qt.EditRole) -> bool:
        if not index.isValid() or role != Qt.EditRole:
            return False
        row = self._rows[index.row()]

        if index.column() == 2:
            try:
                new_duration = float(value)
            except (TypeError, ValueError):
                return False
            self.duration_edit_requested.emit(row.task_id, new_duration)
            return True

        if index.column() == 3:
            try:
                new_percent = float(value)
            except (TypeError, ValueError):
                return False
            if not 0.0 <= new_percent <= 100.0:
                return False
            self.progress_edit_requested.emit(row.task_id, new_percent)
            return True

        if index.column() == 4:
            self.predecessors_edit_requested.emit(row.task_id, str(value))
            return True

        return False

    def task_row_at(self, row: int) -> TaskRow:
        return self._rows[row]

    def is_group_end(self, row: int) -> bool:
        """True if `row` is the last row of its top-level group â€” the row
        immediately before the next top-level task, or the table's last
        row. Used to add a trailing gap between groups (see _GROUP_GAP)."""
        next_row = row + 1
        return next_row >= len(self._rows) or self._rows[next_row].is_top_level


class WbsView(QWidget):
    task_selected = Signal(int)
    add_task_requested = Signal(str, float)  # name, duration_days
    remove_task_requested = Signal(int)  # task_id
    move_task_requested = Signal(int, int)  # task_id, new_index
    duration_edit_requested = Signal(int, float)
    progress_edit_requested = Signal(int, float)
    predecessors_edit_requested = Signal(int, str)
    indent_task_requested = Signal(int)  # task_id
    outdent_task_requested = Signal(int)  # task_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = TaskTableModel()
        self.model.duration_edit_requested.connect(self.duration_edit_requested)
        self.model.progress_edit_requested.connect(self.progress_edit_requested)
        self.model.predecessors_edit_requested.connect(self.predecessors_edit_requested)

        self.table = QTableView(self)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setHorizontalHeader(_TwoRowHeaderView(self.table))
        self.table.setItemDelegate(_RowColorDelegate(self.table))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setMinimumSectionSize(30)
        header.resizeSection(0, 60)
        self.table.setItemDelegateForColumn(2, _NarrowNumericDelegate(0.0, 9999.0, 2, self.table))
        self.table.setItemDelegateForColumn(3, _NarrowNumericDelegate(0.0, 100.0, 1, self.table))
        # Interactive with a fixed width sized for the widest possible
        # value ("9999.00" / "100.0"), not ResizeToContents â€” that sizes to
        # whatever's currently displayed (e.g. "0.0"), which is too narrow
        # once the editor is showing a longer typed value.
        metrics = self.table.fontMetrics()
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.resizeSection(2, metrics.horizontalAdvance("9999.00") + 16)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        header.resizeSection(3, metrics.horizontalAdvance("100.0") + 16)
        header.setSectionResizeMode(4, QHeaderView.Interactive)
        header.resizeSection(4, 100)
        self.setMinimumWidth(450)
        self.table.selectionModel().currentRowChanged.connect(self._on_row_changed)

        # Locked cells (summary-row Dur/%/Predecessors, read-only rollups â€”
        # see TaskRow.is_summary) aren't editable, so hovering them shows a
        # "not allowed" cursor rather than the default arrow/I-beam, as an
        # extra cue beyond the muted text color (_SUMMARY_LOCKED_TEXT).
        self.table.setMouseTracking(True)
        self.table.viewport().setMouseTracking(True)
        self.table.viewport().installEventFilter(self)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.setContentsMargins(0, 0, 0, 0)

    def row_geometry(self) -> tuple[int, int]:
        """Returns (row_height, header_height) so other views (Gantt) can
        align their rows with this table's actual, style-dependent metrics."""
        row_height = self.table.verticalHeader().defaultSectionSize()
        header_height = self.table.horizontalHeader().height()
        return row_height, header_height

    def set_header_height(self, height: int) -> None:
        """Forces this table's header to a specific total height, split
        evenly into the two stacked rows _TwoRowHeaderView paints, so it
        matches the Gantt view's taller two-tier date header (see
        GanttView.header_height() and MainWindow._sync_gantt_row_geometry).
        """
        header = self.table.horizontalHeader()
        header.setMinimumHeight(height)
        header.setMaximumHeight(height)
        header.set_top_row_height(height // 2)

    def set_task_rows(self, rows: list[TaskRow]) -> None:
        # beginResetModel/endResetModel (inside model.set_task_rows) drops
        # Qt's selection state outright, so every edit/command that flows
        # through _refresh_all_views would otherwise deselect the current
        # task â€” restore it by task_id since row indices can shift.
        selected_id = self.selected_task_id()
        self.model.set_task_rows(rows)
        self._apply_row_heights()
        if selected_id is not None:
            self._restore_selection(selected_id)

    def _restore_selection(self, task_id: int) -> None:
        for row in range(self.model.rowCount()):
            if self.model.task_row_at(row).task_id == task_id:
                index = self.model.index(row, 0)
                self.table.setCurrentIndex(index)
                self.table.selectionModel().select(
                    index,
                    QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
                )
                break

    def _apply_row_heights(self) -> None:
        """Adds _GROUP_GAP to each top-level group's last row, so nested
        rows sit flush together while distinct groups get a visible gap â€”
        must stay in sync with GanttView._compute_row_offsets(), which
        mirrors this same per-group gap for the Gantt side."""
        base_height = self.table.verticalHeader().defaultSectionSize()
        vertical_header = self.table.verticalHeader()
        for row in range(self.model.rowCount()):
            height = base_height + _GROUP_GAP if self.model.is_group_end(row) else base_height
            vertical_header.resizeSection(row, height)

    def selected_task_id(self) -> int | None:
        index = self.table.currentIndex()
        if not index.isValid():
            return None
        return self.model.task_row_at(index.row()).task_id

    def request_add_task(self, name: str, duration_days: float) -> None:
        self.add_task_requested.emit(name, duration_days)

    def edit_task_name(self, task_id: int) -> None:
        """Selects the given task's row and opens its Name cell for editing."""
        for row in range(self.model.rowCount()):
            if self.model.task_row_at(row).task_id == task_id:
                index = self.model.index(row, 1)
                self.table.setCurrentIndex(index)
                self.table.edit(index)
                return

    def request_remove_selected_task(self) -> None:
        task_id = self.selected_task_id()
        if task_id is None:
            return
        self.remove_task_requested.emit(task_id)

    def request_indent_selected_task(self) -> None:
        task_id = self.selected_task_id()
        if task_id is None:
            return
        self.indent_task_requested.emit(task_id)

    def request_outdent_selected_task(self) -> None:
        task_id = self.selected_task_id()
        if task_id is None:
            return
        self.outdent_task_requested.emit(task_id)

    def request_move_selected_task_up(self) -> None:
        self._request_move_selected_task(-1)

    def request_move_selected_task_down(self) -> None:
        self._request_move_selected_task(1)

    def _request_move_selected_task(self, delta: int) -> None:
        index = self.table.currentIndex()
        if not index.isValid():
            return
        row = index.row()
        new_row = row + delta
        if not 0 <= new_row < self.model.rowCount():
            return
        task_id = self.model.task_row_at(row).task_id
        self.move_task_requested.emit(task_id, new_row)

    def _on_row_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if current.isValid():
            self.task_selected.emit(self.model.task_row_at(current.row()).task_id)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.table.viewport() and event.type() in (QEvent.MouseMove, QEvent.Leave):
            self._update_cursor_for_position(event.position().toPoint() if event.type() == QEvent.MouseMove else None)
        return super().eventFilter(watched, event)

    def _update_cursor_for_position(self, pos) -> None:
        index = self.table.indexAt(pos) if pos is not None else QModelIndex()
        locked = index.isValid() and _is_locked_cell(self.model.task_row_at(index.row()), index.column())
        cursor = Qt.ForbiddenCursor if locked else Qt.ArrowCursor
        self.table.viewport().setCursor(cursor)
