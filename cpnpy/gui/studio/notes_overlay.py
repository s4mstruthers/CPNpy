"""Notes: scratch paper that floats over whatever page is open.

Learn has its own Notes pane (see :mod:`cpnpy.gui.learn.mode`); this is the
same idea for the rest of the app::

    +--------------------------------------------------------------+
    |  the page: a log, a net, the welcome page …                  |
    |                                                              |
    | +- NOTES ---------------- ⤢  –  +                            |
    | | Work things out here …        |                            |
    | |                               |                            |
    | +-------------------------------+              [− 100% + Fit]|
    +--------------------------------------------------------------+
    | Ready                                             [✎ Notes]  |
    +--------------------------------------------------------------+

* The **✎ Notes** button lives in the status bar (the window puts it there),
  so nothing floats over the page while the notes are folded away.
* Open, it is a card with the notes, in the bottom-left corner of the page
  (the canvases keep their zoom bar in the bottom-right one); **⤢** makes it
  larger and **–** folds it away.  Drag its header to move it out of the
  way, and the grip in its bottom-right corner to resize it.

The window decides where the text is kept (with the folder that is open, or
in the app's settings): :class:`NotesOverlay` only reports edits, a moment
after the last keystroke.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QPlainTextEdit, QToolButton, QVBoxLayout,
    QWidget,
)

from . import style
from .widgets import label

#: How long after the last keystroke the notes are saved (milliseconds).
SAVE_DELAY = 400
#: Space between the overlay and the edges of the page.
MARGIN = 14
#: The card's size, open and enlarged (enlarged: at most this much of the page).
OPEN_SIZE = (380, 300)
EXPANDED_FRACTION = (0.6, 0.75)
#: The smallest the card can be made.
MIN_SIZE = (220, 140)


def _tool(text: str, tooltip: str, slot) -> QToolButton:
    tool = QToolButton()
    tool.setObjectName("notesOverlayButton")
    tool.setText(text)
    tool.setToolTip(tooltip)
    tool.setCursor(Qt.PointingHandCursor)
    tool.setFocusPolicy(Qt.NoFocus)
    tool.clicked.connect(slot)
    return tool


class _Header(QFrame):
    """The card's title row, which also moves the card when dragged."""

    dragged = Signal(QPoint)          # how far, since the last move

    def __init__(self, cursor=Qt.OpenHandCursor) -> None:
        super().__init__()
        self._cursor = cursor
        self.setCursor(cursor)
        self._last: QPoint | None = None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._last = event.globalPosition().toPoint()
            if self._cursor == Qt.OpenHandCursor:
                self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._last is not None:
            now = event.globalPosition().toPoint()
            self.dragged.emit(now - self._last)
            self._last = now
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._last = None
        self.setCursor(self._cursor)
        super().mouseReleaseEvent(event)


class _Grip(_Header):
    """The corner that resizes the card, drawn as a few diagonal strokes."""

    SIZE = 14

    def __init__(self, card: QFrame) -> None:
        super().__init__(Qt.SizeFDiagCursor)
        self.setParent(card)
        self.setObjectName("notesOverlayGrip")
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setToolTip("Drag to resize")
        card.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Resize:
            self.move(watched.width() - self.SIZE - 2, watched.height() - self.SIZE - 2)
            self.raise_()
        return False

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(style.tokens().text_muted), 1.2))
        s = self.SIZE - 3
        for offset in (4, 8):
            painter.drawLine(s, s - offset, s - offset, s)


class NotesOverlay(QObject):
    """The notes card, floating over ``host`` (see the module docstring)."""

    #: The text, a moment after it was edited (see :meth:`flush`).
    edited = Signal(str)
    #: The card was opened or folded away (the ✎ Notes button follows it).
    open_changed = Signal(bool)

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self.host = host
        self.expanded = False
        #: Where the card was dragged to (its top-left corner); None: the corner.
        self._moved_to: QPoint | None = None
        #: The size the card was resized to with its grip; None: the usual size.
        self._resized_to: tuple[int, int] | None = None

        self.card = QFrame(host)
        self.card.setObjectName("notesOverlay")
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 70))
        self.card.setGraphicsEffect(shadow)
        column = QVBoxLayout(self.card)
        column.setContentsMargins(12, 6, 8, 12)
        column.setSpacing(4)
        header = _Header()
        header.dragged.connect(self._drag)
        row = QHBoxLayout(header)
        row.setContentsMargins(4, 0, 0, 0)
        row.setSpacing(2)
        row.addWidget(label("NOTES", "taskCaption"))
        row.addStretch(1)
        self.expand_button = _tool("⤢", "Larger", lambda: self.set_expanded(not self.expanded))
        row.addWidget(self.expand_button)
        row.addWidget(_tool("–", "Fold the notes away (they are kept)",
                            lambda: self.set_open(False)))
        column.addWidget(header)
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("notesEdit")
        self.editor.setPlaceholderText("Jot things down while you work: markings, firing "
                                       "sequences, traces to try, questions…")
        column.addWidget(self.editor, 1)
        grip = _Grip(self.card)
        grip.dragged.connect(self._resize)
        self.grip = grip
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SAVE_DELAY)
        self._timer.timeout.connect(self.flush)
        self.editor.textChanged.connect(self._timer.start)
        self.card.hide()

        # Follow the page's size, and stay above pages added later.
        host.installEventFilter(self)
        self._place()

    # -- the text ---------------------------------------------------------------------
    def text(self) -> str:
        return self.editor.toPlainText()

    def set_text(self, text: str) -> None:
        """Show other notes (another folder's): not an edit, so nothing is saved."""
        self.flush()
        self.editor.blockSignals(True)
        self.editor.setPlainText(text)
        self.editor.blockSignals(False)
        self._timer.stop()

    def flush(self) -> None:
        """Report an edit not reported yet (before switching folders, or quitting)."""
        if self._timer.isActive() or self.sender() is self._timer:
            self._timer.stop()
            self.edited.emit(self.text())

    # -- open, folded, enlarged ---------------------------------------------------------------
    @property
    def is_open(self) -> bool:
        return not self.card.isHidden()

    def set_open(self, show: bool) -> None:
        if show == self.is_open:
            if show:
                self.editor.setFocus()
            return
        self.card.setVisible(show)
        self._place()
        if show:
            self.editor.setFocus()
        else:
            self.flush()
        self.open_changed.emit(show)

    def set_expanded(self, expanded: bool) -> None:
        self.expanded = expanded
        self._resized_to = None               # ⤢ / ⤡ go back to a standard size
        self.expand_button.setText("⤡" if expanded else "⤢")
        self.expand_button.setToolTip("Smaller" if expanded else "Larger")
        self._place()

    # -- where it goes ---------------------------------------------------------------------------
    def _card_size(self) -> tuple[int, int]:
        width, height = self.host.width() - 2 * MARGIN, self.host.height() - 2 * MARGIN
        if self._resized_to is not None:
            wanted = self._resized_to
        elif self.expanded:
            wanted = (max(OPEN_SIZE[0], int(self.host.width() * EXPANDED_FRACTION[0])),
                      max(OPEN_SIZE[1], int(self.host.height() * EXPANDED_FRACTION[1])))
        else:
            wanted = OPEN_SIZE
        return max(MIN_SIZE[0], min(wanted[0], width)), max(MIN_SIZE[1], min(wanted[1], height))

    def _place(self) -> None:
        host = self.host.rect()
        if not self.is_open:
            return
        width, height = self._card_size()
        if self._moved_to is None:
            corner = QPoint(MARGIN, host.height() - height - MARGIN)
        else:
            corner = self._moved_to
        self.card.setGeometry(self._inside(QRect(corner.x(), corner.y(), width, height)))
        self.card.raise_()

    def _inside(self, rect: QRect) -> QRect:
        """``rect`` moved (not resized) so that it stays on the page."""
        host = self.host.rect()
        x = min(max(rect.x(), 0), max(0, host.width() - rect.width()))
        y = min(max(rect.y(), 0), max(0, host.height() - rect.height()))
        return QRect(x, y, rect.width(), rect.height())

    def _drag(self, delta: QPoint) -> None:
        rect = self._inside(self.card.geometry().translated(delta))
        self._moved_to = rect.topLeft()
        self.card.setGeometry(rect)

    def _resize(self, delta: QPoint) -> None:
        """The grip in the bottom-right corner: the top-left corner stays put."""
        rect = self.card.geometry()
        host = self.host.rect()
        width = min(max(MIN_SIZE[0], rect.width() + delta.x()), host.width() - rect.x())
        height = min(max(MIN_SIZE[1], rect.height() + delta.y()), host.height() - rect.y())
        self._resized_to = (width, height)
        self._moved_to = rect.topLeft()
        self.card.setGeometry(rect.x(), rect.y(), width, height)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self.host and event.type() in (QEvent.Resize, QEvent.ChildAdded):
            QTimer.singleShot(0, self._place)
        return False


__all__ = ["NotesOverlay"]
