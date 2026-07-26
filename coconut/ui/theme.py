"""Application-wide look and feel: a flat, modern light theme with a black
accent, applied once at startup via apply_theme(QApplication).

Centralizing this here (Fusion style + QPalette + QSS) means every widget
built from stock Qt controls picks up a consistent, non-native appearance
without each view needing its own styling code. Views that paint
themselves directly (GanttView) still read individual colors from here so
bar colors stay in sync with the rest of the UI.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

# Single source of truth for the accent + semantic colors used both in the
# QSS below and by GanttView's hand-painted bars/markers.
ACCENT = "#222222"
ACCENT_HOVER = "#111111"
ACCENT_TINT = "#d9d9d9"
ACCENT_TINT_TEXT = "#1a1a1a"
CRITICAL = "#dc4c4c"
ARROW = "#9aa1ac"
BASELINE = "#b7bdc7"
TODAY_MARKER = "#f59e0b"

# Preset task-shading palette, keyed by a stable id (persisted on
# Task.color_id) rather than list position, so saved projects don't shift
# colors if entries are reordered/added later. Every top-level task has a
# color (Task.color_id defaults to DEFAULT_TASK_COLOR_ID, "red" — there's
# no "no color" option); a nested task doesn't pick its own, it displays
# its top-level ancestor's (see core.wbs.effective_color_id). Saturated
# enough to read as bold rather than pastel, while staying light enough
# that dark text (_TEXT / _SUMMARY_LOCKED_TEXT) on top stays legible.
TASK_COLOR_PALETTE: dict[str, str] = {
    "red": "#e88a8a",
    "peach": "#eaa877",
    "sand": "#e8c46a",
    "lime": "#a9d97a",
    "mint": "#7dd9ae",
    "teal": "#6fd6d1",
    "sky": "#7cb8e8",
    "periwinkle": "#8f8fe0",
    "lavender": "#b98fe0",
    "mauve": "#e07fb0",
}

# The color every new top-level task starts with (Task.color_id's
# dataclass default) — must be a key of TASK_COLOR_PALETTE.
DEFAULT_TASK_COLOR_ID = "red"

_BACKGROUND = "#f5f6f8"
_SURFACE = "#ffffff"
_BORDER = "#dde1e6"
_BORDER_STRONG = "#c9ced6"
_TEXT = "#1f2430"
_MUTED_TEXT = "#6b7280"

_STYLESHEET = f"""
QMainWindow, QDialog {{
    background: {_BACKGROUND};
    color: {_TEXT};
}}
QMainWindow::separator {{
    background: transparent;
    width: 0px;
    height: 0px;
    border: none;
}}

QWidget {{
    color: {_TEXT};
}}

QToolBar {{
    background: {_BACKGROUND};
    border: none;
    padding: 1px 4px;
    spacing: 1px;
}}
QToolBar::separator {{
    background: {_BORDER};
    width: 1px;
    margin: 3px 4px;
}}
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 5px;
    padding: 1px;
}}
QToolButton:hover {{
    background: #eef2f3;
    border-color: {_BORDER};
}}
QToolButton:pressed {{
    background: {ACCENT_TINT};
}}
QToolButton:disabled {{
    color: #b3b8c2;
}}

QMenuBar {{
    background: {_BACKGROUND};
    border-bottom: 1px solid {_BORDER};
    padding: 2px 4px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 5px 10px;
    border-radius: 5px;
}}
QMenuBar::item:selected {{
    background: #eef2f3;
}}
QMenu {{
    background: {_SURFACE};
    border: 1px solid {_BORDER};
    border-radius: 8px;
    padding: 4px;
    icon-size: 16px;
}}
QMenu::item {{
    padding: 6px 24px 6px 8px;
    border-radius: 5px;
}}
QMenu::icon {{
    padding-left: 8px;
}}
QMenu::item:selected {{
    background: {ACCENT};
    color: #ffffff;
}}
QMenu::separator {{
    height: 1px;
    background: {_BORDER};
    margin: 4px 6px;
}}

QSplitter::handle {{
    background: {_BORDER};
}}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}

QTableView, QGraphicsView {{
    background: {_SURFACE};
    alternate-background-color: #f8f9fb;
    gridline-color: #edeff2;
    border: 1px solid {_BORDER};
    border-radius: 6px;
    selection-background-color: {ACCENT_TINT};
    selection-color: {ACCENT_TINT_TEXT};
}}
QTableView::item {{
    padding: 2px 6px;
}}
QHeaderView::section {{
    background: #f5f6f8;
    color: {_MUTED_TEXT};
    border: none;
    border-bottom: 1px solid {_BORDER};
    border-right: 1px solid #edeff2;
    padding: 6px 8px;
    font-weight: 600;
}}

QTabWidget::pane {{
    border: 1px solid {_BORDER};
    border-radius: 6px;
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    padding: 7px 16px;
    color: {_MUTED_TEXT};
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{
    color: {ACCENT};
    border-bottom: 2px solid {ACCENT};
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{
    color: {_TEXT};
}}

QPushButton {{
    background: {_SURFACE};
    border: 1px solid {_BORDER_STRONG};
    border-radius: 6px;
    padding: 6px 14px;
}}
QPushButton:hover {{
    background: #f1f4f4;
    border-color: {ACCENT};
}}
QPushButton:pressed {{
    background: {ACCENT_TINT};
}}
QPushButton:default {{
    background: {ACCENT};
    color: #ffffff;
    border-color: {ACCENT};
}}
QPushButton:default:hover {{
    background: {ACCENT_HOVER};
}}

QLineEdit, QComboBox, QAbstractSpinBox {{
    background: {_SURFACE};
    border: 1px solid {_BORDER_STRONG};
    border-radius: 6px;
    padding: 4px 8px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus {{
    border-color: {ACCENT};
}}

QCheckBox {{ spacing: 8px; }}

QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {_BORDER_STRONG};
    border-radius: 5px;
    min-height: 24px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{ background: #a9afb9; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
}}
QScrollBar::handle:horizontal {{
    background: {_BORDER_STRONG};
    border-radius: 5px;
    min-width: 24px;
    margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{ background: #a9afb9; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QStatusBar {{
    background: {_BACKGROUND};
    border-top: 1px solid {_BORDER};
}}
"""


def _build_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(_BACKGROUND))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(_TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(_SURFACE))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#f8f9fb"))
    palette.setColor(QPalette.ColorRole.Text, QColor(_TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(_SURFACE))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(_TEXT))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(_SURFACE))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(_TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Mid, QColor(_BORDER))
    palette.setColor(QPalette.ColorRole.Dark, QColor(_BORDER_STRONG))
    palette.setColor(QPalette.ColorRole.Light, QColor(_SURFACE))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(_MUTED_TEXT))
    disabled_text = QColor("#b3b8c2")
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled_text)
    return palette


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setPalette(_build_palette())
    app.setFont(QFont("Segoe UI", 9))
    app.setStyleSheet(_STYLESHEET)
