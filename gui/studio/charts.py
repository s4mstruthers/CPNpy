"""Small painted charts used on the overview page.

Only one form is needed so far: a column chart (case-length distribution).
It follows the data-visualisation mark specs: columns at most 24 px wide,
4 px rounded tops anchored to a single baseline, a 2 px surface gap between
neighbours, hairline recessive axis, text in text colours (never in the data
colour), and a hover tooltip per column.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from . import style


class ColumnChart(QWidget):
    def __init__(self, x_title: str = "", y_title: str = "", parent=None) -> None:
        super().__init__(parent)
        self.values: list[tuple[str, float]] = []
        self.x_title, self.y_title = x_title, y_title
        self.setMinimumHeight(180)
        self.setMouseTracking(True)
        self._bars: list[tuple[QRectF, str, float]] = []

    def set_values(self, values: list[tuple[str, float]]) -> None:
        self.values = values
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = style.tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        font = painter.font()
        font.setPointSizeF(10)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        self._bars = []
        if not self.values:
            painter.setPen(QColor(t.text_muted))
            painter.drawText(self.rect(), Qt.AlignCenter, "No data")
            return
        top_value = max(v for _, v in self.values) or 1
        left, bottom, top, right = 40.0, 30.0, 12.0, 8.0
        plot = QRectF(left, top, self.width() - left - right, self.height() - top - bottom)

        # recessive gridlines at nice values
        step = _nice(top_value / 3)
        value = 0.0
        while value <= top_value * 1.001:
            y = plot.bottom() - value / top_value * plot.height()
            painter.setPen(QPen(QColor(t.grid if value else t.axis), 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(QColor(t.text_muted))
            painter.drawText(QRectF(0, y - 8, left - 6, 16), Qt.AlignRight | Qt.AlignVCenter,
                             f"{int(value):,}")
            value += step

        slot = plot.width() / len(self.values)
        width = min(24.0, max(slot - 2, 1.0))           # cap: let the rest be air
        label_every = max(1, int(len(self.values) / max(plot.width() / 28, 1)))
        for index, (name, value) in enumerate(self.values):
            height = value / top_value * plot.height()
            x = plot.left() + index * slot + (slot - width) / 2
            bar = QRectF(x, plot.bottom() - height, width, height)
            self._bars.append((QRectF(plot.left() + index * slot, plot.top(), slot, plot.height()),
                               name, value))
            if height > 0.5:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(style.categorical(0)))
                painter.drawPath(_rounded_top(bar, min(4.0, width / 2, height)))
            if index % label_every == 0:
                painter.setPen(QColor(t.text_muted))
                w = metrics.horizontalAdvance(name) + 6
                painter.drawText(QRectF(x + width / 2 - w / 2, plot.bottom() + 4, w, 14),
                                 Qt.AlignCenter, name)
        if self.x_title:
            painter.setPen(QColor(t.text_muted))
            painter.drawText(QRectF(plot.left(), self.height() - 14, plot.width(), 14),
                             Qt.AlignCenter, self.x_title)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        for rect, name, value in self._bars:
            if rect.contains(event.position()):
                QToolTip.showText(event.globalPosition().toPoint(),
                                  f"{self.x_title} {name}: <b>{int(value):,}</b> {self.y_title}", self)
                return
        QToolTip.hideText()


def _rounded_top(rect: QRectF, radius: float) -> QPainterPath:
    """A column with rounded data-end and a square baseline."""
    path = QPainterPath()
    path.moveTo(rect.bottomLeft())
    path.lineTo(rect.left(), rect.top() + radius)
    path.quadTo(rect.topLeft(), QPointF(rect.left() + radius, rect.top()))
    path.lineTo(rect.right() - radius, rect.top())
    path.quadTo(rect.topRight(), QPointF(rect.right(), rect.top() + radius))
    path.lineTo(rect.bottomRight())
    path.closeSubpath()
    return path


def _nice(raw: float) -> float:
    import math
    if raw <= 0:
        return 1
    exponent = math.floor(math.log10(raw))
    for multiple in (1, 2, 5, 10):
        if multiple * 10 ** exponent >= raw:
            return max(1, multiple * 10 ** exponent)
    return 10 ** (exponent + 1)
