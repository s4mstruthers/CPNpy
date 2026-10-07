"""An endless canvas: pan anywhere, zoom about the pointer.

Earlier versions sized the scrollable area to the drawing.  With the whole
net in view there was then nothing to scroll: two-finger scrolling did
nothing, zooming could not keep the point under the pointer still (the view
re-centred the drawing instead), and to start a new part of the net beside
the old one you first had to zoom in.  Middle-drag panning grew the area on
the fly, but only that one gesture did.

This mixin gives the view a very large scene rect and no scroll bars, so the
canvas behaves like a sheet of paper that goes on in every direction:

* two-finger scroll (or the mouse wheel; Shift + wheel goes sideways) pans,
  whatever is in view;
* dragging with the middle button, or with the left button while Space is
  held, pans too -- whatever the tool or the item under the pointer;
* ⌘/Ctrl + scroll and trackpad pinch zoom about the pointer
  (:meth:`CanvasPanning.zoom_about`).

Zooming to fit just frames the drawing; nothing has to be reset.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QGraphicsView

#: Half the side of the canvas, in scene units: far more than any net needs,
#: small enough that the scroll range fits in an int at the largest zoom.
EXTENT = 50_000.0


class CanvasPanning:
    """Mix into a ``QGraphicsView`` subclass (before it in the bases) and call
    :meth:`init_canvas` at the end of ``__init__``."""

    _pan_last = None            # the pointer position while a pan drag is on
    _pan_cursor = None          # the (tool's) cursor to put back afterwards
    _space_held = False         # Space is down: a left drag pans
    _space_cursor = None

    def init_canvas(self) -> None:
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSceneRect(QRectF(-EXTENT, -EXTENT, 2 * EXTENT, 2 * EXTENT))
        # The anchor for zooming needs to know where the pointer is.
        self.viewport().setMouseTracking(True)

    # -- dragging -------------------------------------------------------------------
    def _starts_pan(self, event) -> bool:
        return event.button() == Qt.MiddleButton or (
            event.button() == Qt.LeftButton and self._space_held)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._starts_pan(event):
            self._pan_last = event.position()
            self._pan_button = event.button()
            if self._pan_cursor is None:
                self._pan_cursor = self.viewport().cursor()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._pan_last is not None:
            if not event.buttons() & self._pan_button:     # released outside the window
                self._end_pan()
            else:
                delta = event.position() - self._pan_last
                self._pan_last = event.position()
                self.pan_by(round(delta.x()), round(delta.y()))
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._pan_last is not None and event.button() == self._pan_button:
            self._end_pan()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _end_pan(self) -> None:
        self._pan_last = None
        if self._space_held:
            self.viewport().setCursor(Qt.OpenHandCursor)
        else:
            self._restore_cursor()

    def _restore_cursor(self) -> None:
        if self._pan_cursor is not None:
            self.viewport().setCursor(self._pan_cursor)
            self._pan_cursor = None

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Space and not event.isAutoRepeat() \
                and event.modifiers() == Qt.NoModifier:
            self._space_held = True
            if self._pan_cursor is None:
                self._pan_cursor = self.viewport().cursor()
            self.viewport().setCursor(Qt.OpenHandCursor)
            event.accept()
            return
        if event.key() == Qt.Key_Space:
            event.accept()                  # auto-repeat while held
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_held = False
            if self._pan_last is None:
                self._restore_cursor()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        if self._space_held:                # Space released somewhere else
            self._space_held = False
            if self._pan_last is None:
                self._restore_cursor()
        super().focusOutEvent(event)

    # -- moving the view ----------------------------------------------------------------
    def pan_by(self, dx: int, dy: int) -> None:
        """Move the drawing ``dx``, ``dy`` pixels (with the pointer)."""
        # Panning is taking charge of the view, like zooming by hand: resizing
        # the window must not re-fit it.
        self.auto_fit = False
        horizontal, vertical = self.horizontalScrollBar(), self.verticalScrollBar()
        horizontal.setValue(horizontal.value() - dx)
        vertical.setValue(vertical.value() - dy)

    def wheel_pan(self, event) -> None:
        """Scroll: pan by the trackpad's pixels, or a step per wheel notch."""
        pixels = event.pixelDelta()
        if not pixels.isNull():
            dx, dy = pixels.x(), pixels.y()
        else:
            angle = event.angleDelta()
            dx, dy = angle.x() / 3, angle.y() / 3          # 40 px per notch
            if event.modifiers() & Qt.ShiftModifier and not dx:
                dx, dy = dy, 0                             # Shift + wheel: sideways
        self.pan_by(round(dx), round(dy))
        event.accept()

    def zoom_about(self, ratio: float, point: QPointF | None = None) -> None:
        """Scale by ``ratio`` keeping the scene point under ``point`` (viewport
        coordinates; the pointer, else the centre) where it is on screen."""
        if point is None:
            pointer = self.viewport().mapFromGlobal(QCursor.pos())
            point = QPointF(pointer if self.viewport().rect().contains(pointer)
                            else self.viewport().rect().center())
        anchor = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        before = self.mapToScene(point.toPoint())
        self.scale(ratio, ratio)
        after = self.mapFromScene(before)
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value()
                                            + after.x() - round(point.x()))
        self.verticalScrollBar().setValue(self.verticalScrollBar().value()
                                          + after.y() - round(point.y()))
        self.setTransformationAnchor(anchor)

    # Older names, kept for callers outside this module.
    def reset_pan_area(self) -> None:
        """Nothing to reset: the canvas is endless."""

    def hold_still(self) -> None:
        """The drawing never moves by itself on an endless canvas."""


#: The previous name of the mixin.
MiddleButtonPan = CanvasPanning
