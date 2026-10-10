"""Motion: the few short transitions that make the window read as one flow.

Nothing here changes what a widget does; it only smooths how it appears.

* :func:`lift` -- a veil in the page's colour over a widget that lifts in
  about 180 ms, for a change that replaces what the widget shows (a space
  switch, the side panel appearing, Canvas ↔ Summary).
* :func:`fade_in` -- a popup window fading in (the + Add box picker).
* A box on the canvas pulses once when it finishes (see
  :meth:`~openprocess.gui.flow.canvas.BoxItem.set_status`).

Set the environment variable ``OPENPROCESS_NO_MOTION=1`` to turn it all off
(for screenshots, slow machines, or motion sensitivity); :data:`enabled` can
also be switched at run time.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from . import style

#: Whether transitions play at all.
enabled = os.environ.get("OPENPROCESS_NO_MOTION", "") != "1"
LIFT_MS = 180
FADE_MS = 120


class Veil(QWidget):
    """A sheet in the page's colour over its parent, whose opacity animates."""

    def __init__(self, parent: QWidget, colour: QColor) -> None:
        super().__init__(parent)
        self._opacity = 1.0
        self.colour = colour
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.animation: QPropertyAnimation | None = None

    def get_opacity(self) -> float:
        return self._opacity

    def set_opacity(self, value: float) -> None:
        self._opacity = max(0.0, min(1.0, float(value)))
        self.update()

    opacity = Property(float, get_opacity, set_opacity)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        colour = QColor(self.colour)
        colour.setAlphaF(self._opacity)
        painter.fillRect(self.rect(), colour)
        painter.end()


def lift(widget: QWidget | None, duration: int = LIFT_MS) -> Veil | None:
    """Cover ``widget`` with a veil that lifts: what it now shows settles in.
    Returns the veil (None when motion is off or the widget is not showing)."""
    if not enabled or widget is None or not widget.isVisible():
        return None
    veil = Veil(widget, QColor(style.tokens().page))
    veil.setGeometry(widget.rect())
    veil.show()
    veil.raise_()
    animation = QPropertyAnimation(veil, b"opacity", veil)
    animation.setDuration(duration)
    animation.setStartValue(1.0)
    animation.setEndValue(0.0)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    animation.finished.connect(veil.deleteLater)
    veil.animation = animation
    animation.start()
    return veil


def fade_in(window: QWidget, duration: int = FADE_MS) -> QPropertyAnimation | None:
    """A top-level window (a popup) fades in as it shows."""
    if not enabled or not window.isWindow():
        return None
    window.setWindowOpacity(0.0)
    animation = QPropertyAnimation(window, b"windowOpacity", window)
    animation.setDuration(duration)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    animation.start()
    return animation


__all__ = ["enabled", "lift", "fade_in", "Veil"]
