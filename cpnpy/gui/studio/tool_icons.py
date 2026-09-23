"""Icons and mouse cursors for the drawing tools.

Each tool gets a picture of what it does -- a pointing hand for *Select*, a
circle for *Place*, a square for *Transition*, an arrow for *Arc* -- on its
button and as the mouse cursor over the canvas, so the active tool is
obvious wherever you look.  Painted in code: the app ships no image files.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from . import style


def _hand(painter: QPainter, size: float, colour: QColor) -> None:
    """A pointing hand (index finger up), drawn in a ``size`` square."""
    s = size / 24.0
    path = QPainterPath()
    # Index finger.
    path.addRoundedRect(QRectF(8.2 * s, 2.0 * s, 3.6 * s, 11.5 * s), 1.8 * s, 1.8 * s)
    # Palm with the folded fingers.
    path.addRoundedRect(QRectF(6.0 * s, 10.0 * s, 12.5 * s, 11.5 * s), 3.2 * s, 3.2 * s)
    # Thumb.
    path.addRoundedRect(QRectF(3.2 * s, 11.6 * s, 4.6 * s, 3.4 * s), 1.6 * s, 1.6 * s)
    painter.setPen(QPen(colour, 1.4 * s))
    painter.setBrush(QColor(255, 255, 255))
    painter.drawPath(path.simplified())
    painter.setPen(QPen(colour, 1.0 * s))
    for x in (11.8, 14.8):                       # knuckle creases
        painter.drawLine(QPointF(x * s, 10.8 * s), QPointF(x * s, 14.0 * s))


def _shape(painter: QPainter, kind: str, size: float, colour: QColor) -> None:
    s = size / 24.0
    pen = QPen(colour, 2.0 * s)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    if kind == "place":
        painter.drawEllipse(QRectF(4 * s, 4 * s, 16 * s, 16 * s))
        painter.setBrush(colour)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(12 * s, 12 * s), 2.4 * s, 2.4 * s)
    elif kind == "transition":
        painter.drawRect(QRectF(5 * s, 4 * s, 14 * s, 16 * s))
    elif kind == "arc":
        painter.drawLine(QPointF(4 * s, 19 * s), QPointF(18 * s, 6 * s))
        head = QPainterPath(QPointF(20 * s, 4 * s))
        head.lineTo(QPointF(12.5 * s, 6.2 * s))
        head.lineTo(QPointF(17.8 * s, 11.5 * s))
        head.closeSubpath()
        painter.setBrush(colour)
        painter.drawPath(head)
    elif kind == "select":
        _hand(painter, size, colour)


def tool_icon(kind: str) -> QIcon:
    """The button icon for a tool (``select``, ``place``, ``transition``, ``arc``)."""
    pixmap = QPixmap(48, 48)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    _shape(painter, kind, 24, QColor(style.tokens().text))
    painter.end()
    return QIcon(pixmap)


def tool_cursor(kind: str) -> QCursor:
    """The canvas cursor for a tool: a crosshair with the tool's shape next to
    it (the plain pointer for Select)."""
    if kind == "select":
        return QCursor(Qt.ArrowCursor)
    pixmap = QPixmap(64, 64)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    black = QColor(20, 20, 20)
    for width, colour in ((3.0, QColor(255, 255, 255)), (1.2, black)):   # outlined cross
        painter.setPen(QPen(colour, width))
        painter.drawLine(QPointF(8, 1), QPointF(8, 15))
        painter.drawLine(QPointF(1, 8), QPointF(15, 8))
    painter.translate(13, 13)
    _shape(painter, kind, 16, QColor(style.tokens().accent))
    painter.end()
    return QCursor(pixmap, 8, 8)
