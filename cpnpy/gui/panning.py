"""Panning a canvas by dragging with the middle mouse button.

Two things made middle-drag panning unreliable before this mixin:

* Qt's ``QGraphicsView.ScrollHandDrag`` only starts on a *left*-button
  press, so switching to it on a middle press mostly did nothing, and could
  leave the view stuck in hand-drag mode for the next left drag.
* The scene is sized to fit the net, so with the whole net in view there was
  nothing to scroll: panning only worked once you had zoomed in.

This mixin pans by moving the scroll bars itself, whatever the drag mode, the
tool or the item under the pointer, and never hands the middle button to the
scene.  When a drag goes past the edge of the drawing, the view's scrollable
area grows to follow it; zooming to fit (:meth:`reset_pan_area`) shrinks it
back.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt


class MiddleButtonPan:
    """Mix into a ``QGraphicsView`` subclass (before it in the bases)."""

    _pan_last = None            # the pointer position while a middle drag is on
    _pan_cursor = None          # the (tool's) cursor to put back afterwards
    _pan_following = False      # following the scene's own rect (see _scene_grew)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MiddleButton:
            self._pan_last = event.position()
            self._pan_cursor = self.viewport().cursor()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._pan_last is not None:
            if not event.buttons() & Qt.MiddleButton:      # released outside the window
                self._end_pan()
            else:
                delta = event.position() - self._pan_last
                self._pan_last = event.position()
                self.pan_by(round(delta.x()), round(delta.y()))
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MiddleButton and self._pan_last is not None:
            self._end_pan()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _end_pan(self) -> None:
        self._pan_last = None
        self.viewport().setCursor(self._pan_cursor)

    def pan_by(self, dx: int, dy: int) -> None:
        """Move the drawing ``dx``, ``dy`` pixels with the pointer."""
        # Panning is taking charge of the view, like zooming by hand: resizing
        # the window (or scroll bars appearing) must not re-fit it.
        self.auto_fit = False
        horizontal, vertical = self.horizontalScrollBar(), self.verticalScrollBar()
        x, y = horizontal.value() - dx, vertical.value() - dy
        if not (horizontal.minimum() <= x <= horizontal.maximum()
                and vertical.minimum() <= y <= vertical.maximum()):
            self._grow_pan_area()
            x, y = horizontal.value() - dx, vertical.value() - dy
        horizontal.setValue(x)
        vertical.setValue(y)

    def _grow_pan_area(self) -> None:
        """Make room for a viewport's worth of panning in every direction."""
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        room = visible.adjusted(-visible.width(), -visible.height(),
                                visible.width(), visible.height())
        self.setSceneRect(self.sceneRect().united(room))
        # Growing the area (and the scroll bars that may appear) must not
        # move the drawing: put the top-left corner back where it was.
        drift = self.mapFromScene(visible.topLeft())
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + drift.x())
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + drift.y())
        if not self._pan_following and self.scene() is not None:
            # The view no longer follows the scene's rect by itself: keep
            # anything drawn later (outside the grown area) reachable.
            self.scene().sceneRectChanged.connect(self._scene_grew)
            self._pan_following = True

    def _scene_grew(self, rect: QRectF) -> None:
        if self._pan_following and not self.sceneRect().contains(rect):
            self.setSceneRect(self.sceneRect().united(rect))

    def reset_pan_area(self) -> None:
        """Back to scrolling over just the drawing (call when zooming to fit)."""
        if self._pan_following:
            self.scene().sceneRectChanged.disconnect(self._scene_grew)
            self._pan_following = False
        self.setSceneRect(QRectF())         # a null rect: follow the scene's again
