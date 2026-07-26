"""Loads toolbar/button icons from Coconut/assets/icons by name,
falling back to placeholder.svg when a given name has no matching asset.

Icons are rasterized via QSvgRenderer rather than handed to QIcon(path)
directly: this Qt installation's imageformats/qsvg plugin isn't picked up
by QImageReader, so QIcon(path) silently returns a null icon for SVGs even
though QtSvg itself works fine."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"
_PLACEHOLDER = _ICON_DIR / "placeholder.svg"
_SIZES = (16, 24, 32, 48)


def icon(name: str) -> QIcon:
    path = _ICON_DIR / f"{name}.svg"
    if not path.exists():
        path = _PLACEHOLDER

    renderer = QSvgRenderer(str(path))
    result = QIcon()
    for size in _SIZES:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        result.addPixmap(pixmap)
    return result


def swatch_icon(hex_value: str) -> QIcon:
    """Builds a toolbar icon that's just a solid rounded swatch of the
    given color, so the "task color" toolbar button can show the current/
    selected task's color instead of a fixed pictogram."""
    color = QColor(hex_value)
    result = QIcon()
    for size in _SIZES:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        inset = max(1, size // 8)
        painter.setPen(QColor(0, 0, 0, 48))
        painter.setBrush(color)
        radius = size * 0.2
        painter.drawRoundedRect(QRectF(inset, inset, size - 2 * inset, size - 2 * inset), radius, radius)
        painter.end()
        result.addPixmap(pixmap)
    return result
