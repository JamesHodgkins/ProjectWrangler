"""Gantt chart: renders a GanttProjection against a timeline.

Reads the pre-computed bars/arrows/baseline-bars Application provides
(core/view_models.GanttProjection) â€” no scheduling happens here. Also
needs the project's calendar (for weekend shading) and start date
(fallback chart origin when there are no tasks yet); those are plain
Qt-free value objects, not scheduling calls, so passing them in doesn't
reintroduce the coupling this view used to have to Project.compute_schedule().
Rendering only â€” no editing happens here, so it doesn't need Command
objects or Application intent methods.
"""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QGraphicsPathItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
)

from coconut.core.calendar import Calendar
from coconut.application.view_models import GanttProjection
from coconut.ui import theme

_ROW_HEIGHT = 28
_BAR_MARGIN = 4

# Extra vertical space inserted above every top-level task's row (other
# than the very first row), so nested rows under the same top-level task
# sit flush against each other while distinct groups read as visually
# separate â€” must match WbsView._GROUP_GAP so rows stay aligned between
# the two views (see GanttView.sync_row_geometry()).
_GROUP_GAP = 6

_MIN_DAY_WIDTH = 1.0
_MAX_DAY_WIDTH = 90.0
_DEFAULT_DAY_WIDTH = 36.0
_ZOOM_STEP_FACTOR = 1.2

# Minimum horizontal breathing room, in pixels, around a label's text
# before its column is considered "too crowded" and granularity switches
# to the next coarser level.
_LABEL_PADDING = 8

# How many zoom-out steps "early" the granularity switch fires, checked
# against the label-width threshold â€” e.g. 2 means switching as soon as
# two more scroll notches would be too cramped, not just one. Tune this
# single constant rather than special-casing individual transitions.
_GRANULARITY_LOOKAHEAD_STEPS = 2

_CRITICAL_COLOR = QColor(theme.CRITICAL)
_NORMAL_COLOR = QColor(theme.ACCENT)
_ARROW_COLOR = QColor(theme.ARROW)
_BASELINE_COLOR = QColor(theme.BASELINE)
_BASELINE_BAR_HEIGHT = 6
_TODAY_MARKER_WIDTH = 2

# Outline color for non-critical task bars â€” a fixed dark neutral rather
# than a shade of the bar's own palette color, so every bar's border
# reads consistently regardless of task color.
_BAR_OUTLINE_COLOR = QColor("#222222")
# Outline thickness â€” a uniform hairline for every bar, top-level,
# nested, or critical.
_BAR_OUTLINE_WIDTH = 1

# A summary task (has children â€” see GanttBar.is_summary) renders as an
# MS-Project-style "caliper"/bracket marker instead of a filled bar: a
# thick horizontal spine spanning its full duration, with a short
# triangular tick pointing down at each end. A top-level task with no
# children still renders as a normal bar (see GanttView._bar_colors).
_SUMMARY_SPINE_HEIGHT = 4
_SUMMARY_TICK_WIDTH = 8
_SUMMARY_TICK_HEIGHT = 7
_SUMMARY_COLOR = QColor("#404040")

# Fixed horizontal "step out" distance for orthogonal dependency-arrow
# routing (see _draw_dependency_arrow) â€” always exit a bar's right edge
# and enter the next bar's left edge horizontally, connected by straight
# horizontal/vertical segments only, never a diagonal.
_ARROW_ELBOW = 10

_MONTH_NAMES = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


class GanttView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._projection: GanttProjection | None = None
        self._calendar = Calendar()
        self._fallback_chart_start = date.today()
        self.row_height = _ROW_HEIGHT
        self.top_offset = 0
        self.day_width = _DEFAULT_DAY_WIDTH
        # Row index -> y-offset (from rows_top), accounting for the group
        # gap inserted above each top-level task's row. Rebuilt in
        # refresh() from the projection's bars; see _row_y().
        self._row_offsets: list[float] = []
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._month_band_height = self._header_band_height()
        self.refresh()

    def _header_band_height(self) -> int:
        """Height of a single header band (month/year strip, or the
        granularity-detail strip below it), from font metrics so it scales
        with the view's font like _granularity()'s thresholds do."""
        metrics = QFontMetrics(self.font())
        return metrics.height() + _LABEL_PADDING

    def header_height(self) -> int:
        """Total height of the two-tier date header (month/year band plus
        the granularity-detail band beneath it). Queried by MainWindow to
        size the WBS table's native header to match, so task rows stay
        aligned between the two views â€” see sync_row_geometry().
        """
        return self._header_band_height() * 2

    def wheelEvent(self, event) -> None:
        if not event.modifiers() & Qt.ControlModifier:
            super().wheelEvent(event)
            return
        factor = _ZOOM_STEP_FACTOR if event.angleDelta().y() > 0 else 1 / _ZOOM_STEP_FACTOR
        self.day_width = min(_MAX_DAY_WIDTH, max(_MIN_DAY_WIDTH, self.day_width * factor))
        self.refresh()
        event.accept()

    def _compute_row_offsets(self, bars, row_count: int) -> list[float]:
        """Row index -> y-offset from rows_top, in ascending row order.

        Each row is row_height tall, plus _GROUP_GAP inserted above every
        top-level task's row (other than row 0) so nested rows within the
        same group sit flush together while distinct top-level groups get
        a visible gap â€” mirrors WbsView's per-row-height gap so the two
        views' rows line up. Has row_count + 1 entries; the last is the
        total rows height (used for chart_bottom).
        """
        is_top_level_by_row = {bar.row: bar.is_top_level for bar in bars}
        offsets = [0.0] * (row_count + 1)
        y = 0.0
        for row in range(row_count):
            if row > 0 and is_top_level_by_row.get(row, False):
                y += _GROUP_GAP
            offsets[row] = y
            y += self.row_height
        offsets[row_count] = y
        return offsets

    def _row_y(self, row: int) -> float:
        return self._rows_top + self._row_offsets[row]

    def sync_row_geometry(self, row_height: int, top_offset: int) -> None:
        """Aligns Gantt rows with an external table's row height/header height.

        Called by MainWindow with the WBS QTableView's actual metrics so
        rows in both views line up regardless of platform/style-dependent
        default row heights.
        """
        self.row_height = row_height
        self.top_offset = top_offset
        self.refresh()

    def set_calendar(self, calendar: Calendar, fallback_chart_start: date) -> None:
        """Sets the calendar used for weekend shading and the chart-start
        fallback used when the projection has no bars (no tasks yet)."""
        self._calendar = calendar
        self._fallback_chart_start = fallback_chart_start
        self.refresh()

    def set_projection(self, projection: GanttProjection) -> None:
        self._projection = projection
        self.refresh()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # The grid/header must fill at least the viewport (see refresh()),
        # so widening or heightening the window needs a re-draw, not just
        # scroll-area re-layout.
        self.refresh()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == event.Type.PaletteChange:
            # Grid/header colors are derived from the palette (_theme_colors),
            # so a live light/dark theme switch needs a re-draw.
            self.refresh()

    def _theme_colors(self) -> dict[str, QColor]:
        """Derives grid/header colors from the widget's own palette so the
        Gantt view follows the app's light/dark theme instead of using
        colors that were only ever tuned for a light background."""
        palette = self.palette()
        group = palette.currentColorGroup()
        window_text = palette.color(group, QPalette.ColorRole.WindowText)
        base = palette.color(group, QPalette.ColorRole.Base)
        mid = palette.color(group, QPalette.ColorRole.Mid)
        is_dark = base.lightness() < 128

        return {
            "header_background": mid.lighter(115) if is_dark else mid.lighter(160),
            "header_text": window_text,
            # Derived from `base` rather than `mid` â€” on some styles/themes
            # (including this app's own theme.py) `mid` is a very pale
            # border color, which made `mid.lighter(120)` push it even
            # closer to white and left gridlines invisible against the
            # white chart background. A small darker shift off the row
            # background itself is guaranteed to show up regardless of
            # what `mid` happens to resolve to.
            "gridline": mid.darker(115) if is_dark else base.darker(110),
            "month_gridline": mid.darker(140) if is_dark else base.darker(125),
            "weekend": base.darker(114) if is_dark else base.darker(107),
            # A warm accent distinct from gridline/weekend so "today" reads
            # as its own semantic marker rather than a gridline.
            "today_marker": QColor(theme.TODAY_MARKER),
        }

    def refresh(self) -> None:
        self.scene.clear()
        self._colors = self._theme_colors()
        projection = self._projection

        bars = projection.bars if projection else ()
        baseline_bars = projection.baseline_bars if projection else ()
        dependency_arrows = projection.dependency_arrows if projection else ()
        row_count = projection.row_count if projection else 0

        if projection is not None and (bars or baseline_bars):
            chart_start = projection.chart_start
        else:
            chart_start = self._fallback_chart_start

        if bars:
            total_days = max(self._days_from(chart_start, bar.finish) for bar in bars)
        else:
            total_days = 0
        if baseline_bars:
            total_days = max(
                total_days, max(self._days_from(chart_start, bar.finish) for bar in baseline_bars)
            )
        chart_day_count = int(total_days) + 2  # pad one day so the last bar isn't flush with the edge

        # top_offset is sized by MainWindow from our own header_height()
        # (two stacked bands: month/year, then granularity detail) and then
        # pushed onto the WBS table's native header to match, so task rows
        # in both views start at the same y â€” see sync_row_geometry().
        rows_top = self.top_offset
        self._row_offsets = self._compute_row_offsets(bars, row_count)
        chart_bottom = rows_top + (
            self._row_offsets[row_count] if row_count else 0
        )

        # Consumed by drawBackground() so the grid/header paint directly
        # over the visible rect rather than being limited to scene items â€”
        # see setSceneRect below for why that matters.
        self._chart_start = chart_start
        self._rows_top = rows_top
        self._chart_bottom = chart_bottom
        self._month_band_height = self._header_band_height()

        baseline_bar_by_task = {bar.task_id: bar for bar in baseline_bars}

        for bar in bars:
            y = self._row_y(bar.row)

            baseline_bar = baseline_bar_by_task.get(bar.task_id)
            if baseline_bar is not None:
                self._draw_baseline_bar(baseline_bar, y, chart_start)

            x = self._days_from(chart_start, bar.start) * self.day_width
            width = max(self._days_from(bar.start, self._exclusive_end(bar.finish)) * self.day_width, 2)

            if bar.is_summary:
                self._draw_summary_marker(x, y, width)
            else:
                rect_item = QGraphicsRectItem(QRectF(x, y + _BAR_MARGIN, width, self.row_height - 2 * _BAR_MARGIN))
                fill, outline, outline_width = self._bar_colors(bar)
                rect_item.setBrush(QBrush(fill))
                rect_item.setPen(QPen(outline, outline_width))
                self.scene.addItem(rect_item)

        for arrow in dependency_arrows:
            self._draw_dependency_arrow(arrow, chart_start)

        # Sized to actual content only (tasks/dates), never inflated to
        # "at least the viewport" â€” that created a feedback loop with
        # QGraphicsView's AsNeeded scrollbars (viewport shrinks for a
        # scrollbar, which changes what "fits", which can re-trigger it).
        # The grid itself still visually fills the pane via drawBackground(),
        # which paints in viewport coordinates and isn't part of the
        # scrollable scene rect. A real scrollbar now only appears once a
        # project's date range or task count actually exceeds the viewport.
        padding = 20 if row_count else 0
        self.scene.setSceneRect(
            0,
            0,
            chart_day_count * self.day_width + padding,
            chart_bottom + padding,
        )

        # drawBackground() paints the grid from day_width/colors/etc, but
        # the view's default MinimalViewportUpdate only repaints regions
        # where scene items reported a change â€” it doesn't know the
        # background depends on state that just changed here (zoom level,
        # theme, project). Without forcing a full repaint, e.g. zooming out
        # (which shrinks the scene) leaves stale grid pixels painted at the
        # previous zoom level outside the new, smaller scene bounds.
        self.viewport().update()

    def _granularity(self) -> str:
        """Chooses grid/header detail from the current zoom level.

        Switches to a coarser level once _GRANULARITY_LOOKAHEAD_STEPS more
        zoom-out steps would no longer fit that level's widest realistic
        label (plus padding) in the space that level's column actually
        occupies â€” a day label gets one day-column, a month label gets
        ~28 (the shortest month, so it's never too optimistic). Looking
        ahead rather than checking only the current day_width means the
        switch happens comfortably before labels would actually crowd, not
        right as they start to. Measured with the view's actual font
        rather than a guessed pixel threshold that may not match the real
        text/font at all.
        """
        metrics = QFontMetrics(self.font())
        # The month/year band (top header row) always has a full month's
        # width to render into regardless of granularity, so it never needs
        # a crowding check here â€” only the bottom, granularity-detail band's
        # thresholds matter. In "day" granularity the bottom band now only
        # labels week starts ("13 Jul"), not every day, so it's checked
        # against the week-boundary label width rather than a bare day
        # number.
        week_boundary_label_width = metrics.horizontalAdvance("31 Aug") + _LABEL_PADDING
        month_label_width = metrics.horizontalAdvance("Aug 2026") + _LABEL_PADDING
        lookahead_day_width = self.day_width / (_ZOOM_STEP_FACTOR**_GRANULARITY_LOOKAHEAD_STEPS)

        if lookahead_day_width * 28 < month_label_width:
            return "month"
        if lookahead_day_width * 7 < week_boundary_label_width:
            return "week"
        return "day"

    def drawBackground(self, painter, rect) -> None:
        """Paints the two-tier date header, weekend shading, gridlines, and
        the "today" marker directly in the view, covering the full visible
        rect rather than being limited to scene items.

        This is what lets the grid visually fill the pane even with few or
        no tasks, without inflating setSceneRect to do it â€” which would
        fight QGraphicsView's AsNeeded scrollbars (see the comment in
        refresh() where the scene rect is set from content size only).
        Header and rows share the same scene-coordinate space as the task
        bars (y=0..top_offset is the header band, y>=top_offset is rows),
        so this intentionally does NOT pin the header to the viewport â€”
        it scrolls with the chart like the rest of the grid, consistent
        with how bars are positioned in refresh().

        The header is two stacked bands: a month/year band on top (always
        shown, full month width, every granularity) and a granularity-detail
        band below it (day/week labels, thinned per _granularity()). The
        today marker paints last so nothing can obscure it.
        """
        super().drawBackground(painter, rect)
        if not hasattr(self, "_chart_start"):
            return

        chart_start = self._chart_start
        rows_top = self._rows_top
        rows_bottom = max(self._chart_bottom, rect.bottom())
        month_band_bottom = rect.top() + self._month_band_height

        first_day_offset = max(0, int(rect.left() / self.day_width))
        last_day_offset = int(rect.right() / self.day_width) + 1
        granularity = self._granularity()

        if rows_top > rect.top():
            header_rect = QRectF(rect.left(), rect.top(), rect.width(), rows_top - rect.top())
            painter.fillRect(header_rect, self._colors["header_background"])

        for day_offset in range(first_day_offset, last_day_offset):
            day = chart_start + timedelta(days=day_offset)
            x = day_offset * self.day_width
            if not self._calendar.is_working_day(day):
                painter.fillRect(
                    QRectF(x, rows_top, self.day_width, rows_bottom - rows_top), self._colors["weekend"]
                )
            # At "month" granularity, day_width is tiny enough that a
            # gridline every day would render as near-solid ink, so the body
            # only draws week/month-boundary lines there; day/week
            # granularity keeps a line every day, with week boundaries
            # promoted to the "major" color so weeks still read clearly.
            if granularity != "month":
                self._paint_gridline(painter, x, rows_top, rows_bottom, major=(day.day == 1 or day.weekday() == 0))
            elif day.day == 1 or day.weekday() == 0:
                self._paint_gridline(painter, x, rows_top, rows_bottom, major=(day.day == 1))

        if granularity != "month":
            # Bottom band: in "day" granularity this now only labels week
            # starts (not every day), so it shares the same boundary logic
            # as "week" granularity â€” just restricted to the bottom band.
            detail_granularity = "week" if granularity == "day" else granularity
            boundary_offsets = self._boundary_day_offsets(
                chart_start, first_day_offset, last_day_offset, detail_granularity
            )
            for i, day_offset in enumerate(boundary_offsets):
                day = chart_start + timedelta(days=day_offset)
                x = day_offset * self.day_width
                self._paint_gridline(painter, x, month_band_bottom, rows_top, major=True)

                next_offset = boundary_offsets[i + 1] if i + 1 < len(boundary_offsets) else last_day_offset
                segment_width = (next_offset - day_offset) * self.day_width
                text = f"{day.day} {_MONTH_NAMES[day.month - 1]}"
                self._paint_header_label(painter, text, x, segment_width, month_band_bottom, rows_top)

        # Top band: month/year, always shown, independent of granularity.
        month_boundary_offsets = self._boundary_day_offsets(chart_start, first_day_offset, last_day_offset, "month")
        for i, day_offset in enumerate(month_boundary_offsets):
            day = chart_start + timedelta(days=day_offset)
            x = day_offset * self.day_width
            self._paint_gridline(painter, x, rect.top(), month_band_bottom, major=True)

            next_offset = month_boundary_offsets[i + 1] if i + 1 < len(month_boundary_offsets) else last_day_offset
            segment_width = (next_offset - day_offset) * self.day_width
            text = f"{_MONTH_NAMES[day.month - 1]} {day.year}"
            self._paint_header_label(painter, text, x, segment_width, rect.top(), month_band_bottom)

        if rows_top > rect.top():
            painter.setPen(QPen(self._colors["month_gridline"]))
            painter.drawLine(QLineF(rect.left(), month_band_bottom, rect.right(), month_band_bottom))
            painter.drawLine(QLineF(rect.left(), rows_top, rect.right(), rows_top))

        self._paint_today_marker(painter, chart_start, rows_top, rows_bottom)

    def _paint_header_label(self, painter, text: str, x: float, width: float, top: float, bottom: float) -> None:
        painter.setPen(QPen(self._colors["header_text"]))
        label_rect = QRectF(x + _LABEL_PADDING / 2, top, width - _LABEL_PADDING / 2, bottom - top)
        painter.drawText(label_rect, Qt.AlignVCenter | Qt.AlignLeft, text)

    def _paint_today_marker(self, painter, chart_start: date, rows_top: float, rows_bottom: float) -> None:
        today_x = self._days_from(chart_start, date.today()) * self.day_width
        pen = QPen(self._colors["today_marker"], _TODAY_MARKER_WIDTH)
        painter.setPen(pen)
        painter.drawLine(QLineF(today_x, rows_top, today_x, rows_bottom))

    def _boundary_day_offsets(self, chart_start: date, first_offset: int, last_offset: int, granularity: str) -> list[int]:
        """Day offsets (from chart_start) where a week or month boundary falls, within [first_offset, last_offset)."""
        offsets = []
        for day_offset in range(first_offset, last_offset):
            day = chart_start + timedelta(days=day_offset)
            is_boundary = day.weekday() == 0 if granularity == "week" else day.day == 1
            if is_boundary or day_offset == first_offset:
                offsets.append(day_offset)
        return offsets

    def _paint_gridline(self, painter, x: float, top: float, bottom: float, major: bool) -> None:
        color = self._colors["month_gridline"] if major else self._colors["gridline"]
        painter.setPen(QPen(color))
        painter.drawLine(QLineF(x, top, x, bottom))

    def _draw_summary_marker(self, x: float, y: float, width: float) -> None:
        """Draws an MS-Project-style "caliper" for a summary task: a thick
        horizontal spine spanning [x, x+width] near the row's top, with a
        downward-pointing triangular tick at each end â€” reads as a
        bracket around the group's date range rather than a task bar
        with a literal duration.
        """
        spine_top = y + _BAR_MARGIN
        spine = QGraphicsRectItem(QRectF(x, spine_top, width, _SUMMARY_SPINE_HEIGHT))
        spine.setBrush(QBrush(_SUMMARY_COLOR))
        spine.setPen(QPen(Qt.NoPen))
        self.scene.addItem(spine)

        tick_bottom = spine_top + _SUMMARY_SPINE_HEIGHT + _SUMMARY_TICK_HEIGHT
        for tick_x in (x, x + width):
            tick = QPolygonF([
                QPointF(tick_x - _SUMMARY_TICK_WIDTH / 2, spine_top),
                QPointF(tick_x + _SUMMARY_TICK_WIDTH / 2, spine_top),
                QPointF(tick_x, tick_bottom),
            ])
            tick_item = QGraphicsPolygonItem(tick)
            tick_item.setBrush(QBrush(_SUMMARY_COLOR))
            tick_item.setPen(QPen(Qt.NoPen))
            self.scene.addItem(tick_item)

    def _bar_colors(self, bar) -> tuple[QColor, QColor, int]:
        """Returns (fill, outline, outline_width) for a task bar (never
        called for a summary task â€” see _draw_summary_marker).

        Critical-path status always wins over task shading, filling the
        whole bar red â€” losing the critical-path cue would be a
        regression for the feature this view exists for. Otherwise every
        bar (top-level or nested) is filled with its own effective
        palette color (its own color if top-level, else its top-level
        ancestor's â€” see core.wbs.effective_color_id) and outlined with
        the same fixed dark neutral and hairline width, so every bar's
        border reads consistently regardless of task color.
        """
        if bar.is_critical:
            return _CRITICAL_COLOR, _CRITICAL_COLOR.darker(150), _BAR_OUTLINE_WIDTH
        palette_hex = theme.TASK_COLOR_PALETTE.get(bar.color_id)
        color = QColor(palette_hex) if palette_hex is not None else _NORMAL_COLOR
        return color, _BAR_OUTLINE_COLOR, _BAR_OUTLINE_WIDTH

    def _draw_baseline_bar(self, baseline_bar, row_y: float, chart_start: date) -> None:
        x = self._days_from(chart_start, baseline_bar.start) * self.day_width
        width = max(
            self._days_from(baseline_bar.start, self._exclusive_end(baseline_bar.finish)) * self.day_width, 2
        )
        bar_y = row_y + self.row_height - _BASELINE_BAR_HEIGHT - 1
        bar = QGraphicsRectItem(QRectF(x, bar_y, width, _BASELINE_BAR_HEIGHT))
        bar.setBrush(QBrush(_BASELINE_COLOR))
        bar.setPen(QPen(_BASELINE_COLOR.darker(150)))
        self.scene.addItem(bar)

    def _draw_dependency_arrow(self, arrow, chart_start: date) -> None:
        start_x = self._days_from(chart_start, self._exclusive_end(arrow.predecessor_finish)) * self.day_width
        start_y = self._row_y(arrow.predecessor_row) + self.row_height / 2
        end_x = self._days_from(chart_start, arrow.successor_start) * self.day_width
        end_y = self._row_y(arrow.successor_row) + self.row_height / 2

        points = _route_orthogonal(start_x, start_y, end_x, end_y, _ARROW_ELBOW)

        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        path_item = self.scene.addPath(path, QPen(_ARROW_COLOR, 1.5))
        path_item.setBrush(QBrush())

        arrow_size = 5
        tip = points[-1]
        arrowhead = QPolygonF(
            [
                tip,
                QPointF(tip.x() - arrow_size, tip.y() - arrow_size),
                QPointF(tip.x() - arrow_size, tip.y() + arrow_size),
            ]
        )
        head = QGraphicsPolygonItem(arrowhead)
        head.setBrush(QBrush(_ARROW_COLOR))
        head.setPen(QPen(_ARROW_COLOR))
        self.scene.addItem(head)

    @staticmethod
    def _days_from(start: date, end: date) -> float:
        return (end - start) / timedelta(days=1)

    @staticmethod
    def _exclusive_end(finish: date) -> date:
        """Converts a schedule's inclusive finish date (the last working
        day the task actually occupies, per Calendar.finish_date) into an
        exclusive end boundary for bar-width/arrow-position math, which
        wants "one day past the last occupied day" the same way a range
        slice does.
        """
        return finish + timedelta(days=1)


def _route_orthogonal(start_x: float, start_y: float, end_x: float, end_y: float, elbow: float) -> list[QPointF]:
    """Routes a dependency arrow as horizontal/vertical segments only â€”
    never diagonal â€” always leaving the predecessor moving right and
    always arriving at the successor moving right, matching the standard
    MS Project/Primavera Gantt convention.

    Two cases:
    - Same row: a single straight horizontal segment.
    - Different rows, with room to spare (out_x <= in_x): a simple
      3-segment route â€” out from the predecessor, one vertical bridge,
      into the successor.
    - Different rows, not enough room (the successor starts at or before
      where the predecessor's bridge would land, e.g. an SS link or a
      task reordered behind its predecessor): a 5-segment detour that
      steps out past both bars before dropping to the successor's row,
      so the line never has to run backward through either bar.
    """
    if start_y == end_y:
        return [QPointF(start_x, start_y), QPointF(end_x, end_y)]

    out_x = start_x + elbow
    in_x = end_x - elbow

    if out_x <= in_x:
        return [
            QPointF(start_x, start_y),
            QPointF(out_x, start_y),
            QPointF(out_x, end_y),
            QPointF(end_x, end_y),
        ]

    bridge_x = max(out_x, end_x + elbow)
    return [
        QPointF(start_x, start_y),
        QPointF(bridge_x, start_y),
        QPointF(bridge_x, end_y),
        QPointF(in_x, end_y),
        QPointF(end_x, end_y),
    ]
