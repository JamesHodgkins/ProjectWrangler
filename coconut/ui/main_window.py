"""Main window shell: menus, toolbar, and the WBS + Gantt panes wired to
a shared Application instance.

Owns widgets, Qt actions/menus/toolbars, and asks for user input via
dialogs; every actual state change is delegated to Application. This
class must not construct Command objects, call storage.repository,
scheduler/allocation/variance functions, or hold undo/redo history ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â
see application/app.py for where all of that now lives.
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QAction, QBitmap, QImage, QKeySequence, QPainter, QRegion
from PySide6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from coconut.application.app import Application
from coconut.application.view_models import ProjectionState
from coconut.core.exceptions import NothingToRedoError, NothingToUndoError, ValidationError
from coconut.ui.dialogs.assignment_dialog import AssignmentDialog
from coconut.ui.dialogs.new_project_dialog import NewProjectDialog
from coconut.ui.dialogs.settings_dialog import SettingsDialog
from coconut.ui.dialogs.task_color_dialog import TaskColorDialog
from coconut.ui.dialogs.task_constraint_dialog import TaskConstraintDialog
from coconut.ui.gantt_view import GanttView
from coconut.ui import theme
from coconut.ui.icons import icon, swatch_icon
from coconut.ui.resource_view import ResourceView
from coconut.ui.variance_view import VarianceView
from coconut.ui.wbs_view import WbsView

_MENU_CORNER_RADIUS = 8


class RoundedMenu(QMenu):
    """Masks itself to the QSS border-radius so the popup's actual window
    shape is rounded rather than relying on translucency compositing,
    which this Qt build doesn't blend (corners render solid black instead
    of see-through)."""

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # QRegion masks are 1-bit (no antialiasing), so the rounded-rect shape
        # is drawn at 4x scale with antialiasing into an alpha-channel image
        # and downscaled before converting to a mask - this turns the hard
        # staircase edge from masking at native resolution into a smoother
        # curve (the downscale blends edge pixels into a soft alpha gradient
        # that createAlphaMask then dithers into the final 1-bit region).
        scale = 4
        size = self.size() * scale
        image = QImage(size, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(Qt.black)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(
            QRectF(0, 0, size.width(), size.height()),
            _MENU_CORNER_RADIUS * scale,
            _MENU_CORNER_RADIUS * scale,
        )
        painter.end()
        scaled = image.scaled(self.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        bitmap = QBitmap.fromImage(scaled.createAlphaMask())
        self.setMask(QRegion(bitmap))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Coconut")
        self.resize(1200, 750)

        self.app = Application()

        self.wbs_view = WbsView()
        self.gantt_view = GanttView()
        self.resource_view = ResourceView()
        self.variance_view = VarianceView()

        self.wbs_view.add_task_requested.connect(self._on_add_task_requested)
        self.wbs_view.remove_task_requested.connect(self._on_remove_task_requested)
        self.wbs_view.move_task_requested.connect(self._on_move_task_requested)
        self.wbs_view.duration_edit_requested.connect(self._on_duration_edit_requested)
        self.wbs_view.progress_edit_requested.connect(self._on_progress_edit_requested)
        self.wbs_view.predecessors_edit_requested.connect(self._on_predecessors_edit_requested)
        self.wbs_view.indent_task_requested.connect(self._on_indent_task_requested)
        self.wbs_view.outdent_task_requested.connect(self._on_outdent_task_requested)
        self.wbs_view.task_selected.connect(self._on_task_selected)

        self.resource_view.add_resource_requested.connect(self._on_add_resource_requested)
        self.resource_view.remove_resource_requested.connect(self._on_remove_resource_requested)

        self.variance_view.baseline_selected.connect(self._on_variance_baseline_selected)

        top_splitter = QSplitter(self)
        top_splitter.addWidget(self.wbs_view)
        top_splitter.addWidget(self.gantt_view)
        top_splitter.setStretchFactor(1, 1)
        top_splitter.setHandleWidth(1)

        bottom_tabs = QTabWidget(self)
        bottom_tabs.addTab(self.resource_view, "Resources")
        bottom_tabs.addTab(self.variance_view, "Variance")

        main_splitter = QSplitter(Qt.Vertical, self)
        main_splitter.addWidget(top_splitter)
        main_splitter.addWidget(bottom_tabs)
        main_splitter.setStretchFactor(0, 3)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setHandleWidth(1)

        central = QWidget(self)
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(10, 2, 10, 10)
        central_layout.addWidget(main_splitter)
        self.setCentralWidget(central)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()

        self._refresh_all_views()
        self._sync_gantt_row_geometry()

    # -- setup ----------------------------------------------------------

    def _build_actions(self) -> None:
        self.new_action = QAction(icon("new_file"), "&New Project", self)
        self.new_action.setShortcut(QKeySequence.New)
        self.new_action.triggered.connect(self.new_project)

        self.open_action = QAction(icon("open_file"), "&Open...", self)
        self.open_action.setShortcut(QKeySequence.Open)
        self.open_action.triggered.connect(self.open_project)

        self.save_action = QAction(icon("save_file"), "&Save", self)
        self.save_action.setShortcut(QKeySequence.Save)
        self.save_action.triggered.connect(self.save_project)

        self.save_as_action = QAction(icon("save_file_as"), "Save &As...", self)
        self.save_as_action.setShortcut(QKeySequence.SaveAs)
        self.save_as_action.triggered.connect(self.save_project_as)

        self.add_task_action = QAction(icon("new_task"), "Add &Task", self)
        self.add_task_action.triggered.connect(self.add_task)

        self.remove_task_action = QAction(icon("delete_task"), "&Remove Task", self)
        self.remove_task_action.triggered.connect(self.wbs_view.request_remove_selected_task)

        self.move_task_up_action = QAction(icon("move_task_up"), "Move Task &Up", self)
        self.move_task_up_action.setShortcut(QKeySequence("Alt+Up"))
        self.move_task_up_action.triggered.connect(self.wbs_view.request_move_selected_task_up)

        self.move_task_down_action = QAction(icon("move_task_down"), "Move Task &Down", self)
        self.move_task_down_action.setShortcut(QKeySequence("Alt+Down"))
        self.move_task_down_action.triggered.connect(self.wbs_view.request_move_selected_task_down)

        self.indent_task_action = QAction(icon("indent"), "&Indent Task", self)
        self.indent_task_action.setShortcut(QKeySequence("Alt+Right"))
        self.indent_task_action.triggered.connect(self.wbs_view.request_indent_selected_task)

        self.outdent_task_action = QAction(icon("outdent"), "&Outdent Task", self)
        self.outdent_task_action.setShortcut(QKeySequence("Alt+Left"))
        self.outdent_task_action.triggered.connect(self.wbs_view.request_outdent_selected_task)

        self.edit_assignments_action = QAction(icon("edit_assignments"), "Edit &Assignments...", self)
        self.edit_assignments_action.triggered.connect(self.edit_assignments)

        self.edit_constraint_action = QAction(icon("edit_constraint"), "Edit &Constraint...", self)
        self.edit_constraint_action.triggered.connect(self.edit_constraint)

        self.edit_color_action = QAction(swatch_icon(theme.TASK_COLOR_PALETTE[theme.DEFAULT_TASK_COLOR_ID]), "Task &Color...", self)
        self.edit_color_action.triggered.connect(self.edit_task_color)

        self.add_resource_action = QAction(icon("add_resource"), "Add &Resource", self)
        self.add_resource_action.triggered.connect(self.add_resource)

        self.remove_resource_action = QAction(icon("delete_resource"), "R&emove Resource", self)
        self.remove_resource_action.triggered.connect(self.resource_view.request_remove_selected_resource)

        self.capture_baseline_action = QAction(icon("capture_baseline"), "&Capture Baseline...", self)
        self.capture_baseline_action.triggered.connect(self.capture_baseline)

        self.edit_progress_action = QAction(icon("edit_progress"), "Edit &Progress...", self)
        self.edit_progress_action.triggered.connect(self.edit_progress)

        self.project_settings_action = QAction(icon("project_settings"), "&Project Settings...", self)
        self.project_settings_action.triggered.connect(self.edit_project_settings)

        self.undo_action = QAction(icon("undo"), "&Undo", self)
        self.undo_action.setShortcut(QKeySequence.Undo)
        self.undo_action.triggered.connect(self.undo)

        self.redo_action = QAction(icon("redo"), "&Redo", self)
        self.redo_action.setShortcut(QKeySequence.Redo)
        self.redo_action.triggered.connect(self.redo)

    def _build_menus(self) -> None:
        def add_menu(title: str):
            menu = RoundedMenu(title, self)
            self.menuBar().addMenu(menu)
            return menu

        file_menu = add_menu("&File")
        file_menu.addAction(self.new_action)
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.save_action)
        file_menu.addAction(self.save_as_action)
        file_menu.addSeparator()
        file_menu.addAction(self.project_settings_action)

        edit_menu = add_menu("&Edit")
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)

        task_menu = add_menu("&Task")
        task_menu.addAction(self.add_task_action)
        task_menu.addAction(self.remove_task_action)
        task_menu.addAction(self.move_task_up_action)
        task_menu.addAction(self.move_task_down_action)
        task_menu.addAction(self.indent_task_action)
        task_menu.addAction(self.outdent_task_action)
        task_menu.addAction(self.edit_assignments_action)
        task_menu.addAction(self.edit_constraint_action)
        task_menu.addAction(self.edit_color_action)

        resource_menu = add_menu("&Resource")
        resource_menu.addAction(self.add_resource_action)
        resource_menu.addAction(self.remove_resource_action)

        baseline_menu = add_menu("&Baseline")
        baseline_menu.addAction(self.capture_baseline_action)
        baseline_menu.addAction(self.edit_progress_action)

    def _build_toolbar(self) -> None:
        toolbar = self.addToolBar("Main")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        toolbar.setIconSize(QSize(24, 24))
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setFixedHeight(34)
        toolbar.addAction(self.new_action)
        toolbar.addAction(self.open_action)
        toolbar.addAction(self.save_action)
        toolbar.addSeparator()
        toolbar.addAction(self.add_task_action)
        toolbar.addAction(self.remove_task_action)
        toolbar.addAction(self.move_task_up_action)
        toolbar.addAction(self.move_task_down_action)
        toolbar.addAction(self.indent_task_action)
        toolbar.addAction(self.outdent_task_action)
        toolbar.addAction(self.edit_assignments_action)
        toolbar.addAction(self.edit_constraint_action)
        toolbar.addAction(self.edit_color_action)
        toolbar.addSeparator()
        toolbar.addAction(self.add_resource_action)
        toolbar.addAction(self.remove_resource_action)
        toolbar.addSeparator()
        toolbar.addAction(self.capture_baseline_action)
        toolbar.addAction(self.edit_progress_action)
        toolbar.addSeparator()
        toolbar.addAction(self.undo_action)
        toolbar.addAction(self.redo_action)

    # -- view refresh from Application projections --------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_gantt_row_geometry()

    def _sync_gantt_row_geometry(self) -> None:
        # The Gantt's two-tier date header is taller than the WBS table's
        # native single-row header, so height now flows Gantt -> WBS (via
        # set_header_height) rather than the other way around ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â otherwise
        # the two views' task rows would drift out of alignment.
        row_height, _ = self.wbs_view.row_geometry()
        header_height = self.gantt_view.header_height()
        self.wbs_view.set_header_height(header_height)
        self.gantt_view.sync_row_geometry(row_height, header_height)

    def _refresh_all_views(self) -> None:
        """Pushes the current Application projection state to every view.
        The single place all views update from ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â no cascading dataChanged
        connections or ad hoc per-view refresh() calls elsewhere."""
        projections: ProjectionState = self.app.projections
        self.wbs_view.set_task_rows(list(projections.task_rows))
        self.gantt_view.set_calendar(self.app.project.calendar, self.app.project.start)
        self.gantt_view.set_projection(projections.gantt)
        self.resource_view.set_resource_rows(list(projections.resource_rows))
        self.variance_view.set_baseline_list(list(projections.baseline_list))
        self._refresh_variance_rows()
        self.undo_action.setEnabled(projections.can_undo)
        self.redo_action.setEnabled(projections.can_redo)
        title = f"Coconut — {projections.project_name}"
        if projections.is_dirty:
            title += " *"
        self.setWindowTitle(title)
        self._sync_gantt_row_geometry()
        self._update_color_action_icon(self.wbs_view.selected_task_id())

    def _on_task_selected(self, task_id: int) -> None:
        self._update_color_action_icon(task_id)

    def _update_color_action_icon(self, task_id: int | None) -> None:
        """Keeps the toolbar's Task Color button showing the selected
        task's own color (or its top-level ancestor's), falling back to
        the default palette color when nothing is selected."""
        color_id = theme.DEFAULT_TASK_COLOR_ID
        if task_id is not None:
            task_row = next((r for r in self.app.projections.task_rows if r.task_id == task_id), None)
            if task_row is not None:
                color_id = task_row.color_id
        self.edit_color_action.setIcon(swatch_icon(theme.TASK_COLOR_PALETTE[color_id]))

    def _refresh_variance_rows(self) -> None:
        rows = self.app.variance_rows(self.app.selected_baseline_id)
        self.variance_view.set_variance_rows(rows)

    def _show_validation_error(self, title: str, exc: ValidationError) -> None:
        QMessageBox.warning(self, title, str(exc))

    # -- project lifecycle ------------------------------------------------

    def new_project(self) -> None:
        name, start, ok = NewProjectDialog.get_new_project_info(self)
        if not ok or not name:
            return
        self.app.new_project(name=name, start=start)
        self._refresh_all_views()

    def open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Project", filter="Coconut (*.coco)")
        if not path:
            return
        try:
            self.app.open_project(path)
        except Exception as exc:
            QMessageBox.critical(self, "Open Failed", str(exc))
            return
        self._refresh_all_views()

    def save_project(self) -> None:
        if self.app.current_path is None:
            self.save_project_as()
            return
        self.app.save_project()
        self._refresh_all_views()

    def save_project_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save Project", filter="Coconut (*.coco)")
        if not path:
            return
        if not path.endswith(".coco"):
            path += ".coco"
        self.app.save_project(path)
        self._refresh_all_views()

    # -- task editing intents -------------------------------------------------

    def add_task(self) -> None:
        default_name = f"Task {self.app.project.next_task_id()}"
        self.wbs_view.request_add_task(default_name, 1.0)

    def _on_add_task_requested(self, name: str, duration_days: float) -> None:
        task_id = self.app.add_task(name, duration_days)
        self._refresh_all_views()
        self.wbs_view.edit_task_name(task_id)

    def _on_remove_task_requested(self, task_id: int) -> None:
        self.app.remove_task(task_id)
        self._refresh_all_views()

    def _on_move_task_requested(self, task_id: int, new_index: int) -> None:
        self.app.move_task(task_id, new_index)
        self._refresh_all_views()
        self.wbs_view.table.setCurrentIndex(self.wbs_view.model.index(new_index, 0))

    def _on_duration_edit_requested(self, task_id: int, new_duration_days: float) -> None:
        self.app.edit_task_duration(task_id, new_duration_days)
        self._refresh_all_views()

    def _on_progress_edit_requested(self, task_id: int, new_percent: float) -> None:
        self.app.edit_task_progress(task_id, new_percent)
        self._refresh_all_views()

    def _on_predecessors_edit_requested(self, task_id: int, text: str) -> None:
        try:
            self.app.set_predecessors_from_text(task_id, text)
        except ValidationError as exc:
            self._show_validation_error("Invalid Predecessors", exc)
            return
        self._refresh_all_views()

    def _on_indent_task_requested(self, task_id: int) -> None:
        try:
            self.app.indent_task(task_id)
        except ValidationError as exc:
            self._show_validation_error("Cannot Indent Task", exc)
            return
        self._refresh_all_views()

    def _on_outdent_task_requested(self, task_id: int) -> None:
        try:
            self.app.outdent_task(task_id)
        except ValidationError as exc:
            self._show_validation_error("Cannot Outdent Task", exc)
            return
        self._refresh_all_views()

    def edit_assignments(self) -> None:
        task_id = self.wbs_view.selected_task_id()
        if task_id is None:
            QMessageBox.information(self, "Edit Assignments", "Select a task first.")
            return
        task_row = next(r for r in self.app.projections.task_rows if r.task_id == task_id)
        dialog = AssignmentDialog(task_row.name, self)

        def refresh_dialog() -> None:
            dialog.set_assignments(self.app.assignment_rows(task_id))
            dialog.set_assignable_resources(self.app.assignable_resources(task_id))

        def on_add(resource_id: int, units: float) -> None:
            self.app.add_assignment(task_id, resource_id, units)
            self._refresh_all_views()
            refresh_dialog()

        def on_remove(resource_id: int) -> None:
            self.app.remove_assignment(task_id, resource_id)
            self._refresh_all_views()
            refresh_dialog()

        dialog.assignment_add_requested.connect(on_add)
        dialog.assignment_remove_requested.connect(on_remove)
        refresh_dialog()
        dialog.exec()

    def edit_constraint(self) -> None:
        task_id = self.wbs_view.selected_task_id()
        if task_id is None:
            QMessageBox.information(self, "Edit Constraint", "Select a task first.")
            return
        task_row = next(r for r in self.app.projections.task_rows if r.task_id == task_id)
        result, ok = TaskConstraintDialog.get_constraint(
            task_row.name, task_row.constraint_type, task_row.constraint_date, self
        )
        if not ok or result is None:
            return
        if result.constraint_type != task_row.constraint_type or result.constraint_date != task_row.constraint_date:
            self.app.edit_task_constraint(task_id, result.constraint_type, result.constraint_date)
            self._refresh_all_views()

    def edit_task_color(self) -> None:
        task_id = self.wbs_view.selected_task_id()
        if task_id is None:
            QMessageBox.information(self, "Task Color", "Select a task first.")
            return
        task_row = next(r for r in self.app.projections.task_rows if r.task_id == task_id)
        if not task_row.is_top_level:
            QMessageBox.information(
                self, "Task Color", "Only a top-level task can have its own color ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â nested tasks inherit it."
            )
            return
        color_id, ok = TaskColorDialog.get_color(task_row.name, task_row.color_id, self)
        if not ok:
            return
        if color_id != task_row.color_id:
            self.app.edit_task_color(task_id, color_id)
            self._refresh_all_views()

    # -- resource editing intents ---------------------------------------------

    def add_resource(self) -> None:
        name, ok = QInputDialog.getText(self, "Add Resource", "Resource name:")
        if not ok or not name:
            return
        rate, ok = QInputDialog.getDouble(self, "Add Resource", "Rate:", 0.0, 0.0)
        if not ok:
            return
        max_units, ok = QInputDialog.getDouble(self, "Add Resource", "Max units:", 1.0, 0.01)
        if not ok:
            return
        self.resource_view.request_add_resource(name, rate, max_units)

    def _on_add_resource_requested(self, name: str, rate: float, max_units: float) -> None:
        self.app.add_resource(name, rate, max_units)
        self._refresh_all_views()

    def _on_remove_resource_requested(self, resource_id: int) -> None:
        self.app.remove_resource(resource_id)
        self._refresh_all_views()

    def _on_variance_baseline_selected(self, baseline_id) -> None:
        self.app.select_baseline(baseline_id)
        self._refresh_all_views()

    def capture_baseline(self) -> None:
        if not self.app.project.tasks:
            QMessageBox.information(self, "Capture Baseline", "Add at least one task first.")
            return
        name, ok = QInputDialog.getText(self, "Capture Baseline", "Baseline name:")
        if not ok or not name:
            return
        self.app.capture_baseline(name)
        self._refresh_all_views()

    def edit_progress(self) -> None:
        task_id = self.wbs_view.selected_task_id()
        if task_id is None:
            QMessageBox.information(self, "Edit Progress", "Select a task first.")
            return
        task_row = next(r for r in self.app.projections.task_rows if r.task_id == task_id)
        percent, ok = QInputDialog.getDouble(
            self, "Edit Progress", "% complete:", task_row.percent_complete, 0.0, 100.0
        )
        if not ok:
            return
        self.app.edit_task_progress(
            task_id, percent, actual_start=task_row.actual_start, actual_finish=task_row.actual_finish
        )
        self._refresh_all_views()

    def edit_project_settings(self) -> None:
        result, ok = SettingsDialog.get_settings(
            self.app.project.start, self.app.project.calendar.working_weekdays, self
        )
        if not ok or result is None:
            return
        self.app.set_project_settings(start=result.start, working_weekdays=result.working_weekdays)
        self._refresh_all_views()

    def undo(self) -> None:
        try:
            self.app.undo()
        except NothingToUndoError:
            return
        self._refresh_all_views()

    def redo(self) -> None:
        try:
            self.app.redo()
        except NothingToRedoError:
            return
        self._refresh_all_views()
