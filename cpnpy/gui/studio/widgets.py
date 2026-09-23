"""Small reusable widgets: cards, stat tiles, segmented controls, chips.

These are deliberately plain ``QWidget`` subclasses styled through object
names (``#card``, ``#statValue`` ...) so that every look-and-feel decision
stays in :mod:`style`.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QSizePolicy, QStyle, QStyledItemDelegate,
    QVBoxLayout, QWidget,
)

from .. import theme
from . import style


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------
def shortcut_text(keys: str) -> str:
    """A shortcut as this computer writes it: ``"Ctrl+S"`` is shown as ⌘S on
    a Mac and as Ctrl+S on Windows and Linux (Qt swaps Ctrl and ⌘ for the
    actual key presses in the same way)."""
    from PySide6.QtGui import QKeySequence
    return QKeySequence(keys).toString(QKeySequence.NativeText)


def modifier_text(name: str) -> str:
    """A modifier key's name as this computer writes it: ``"Ctrl"`` is ⌘ on a
    Mac, ``"Alt"`` is ⌥, ``"Shift"`` is ⇧; unchanged elsewhere."""
    import sys
    if sys.platform != "darwin":
        return name
    return {"Ctrl": "⌘", "Alt": "⌥", "Shift": "⇧", "Meta": "⌃"}.get(name, name)


def hbox(*widgets, spacing: int = 8, margins=(0, 0, 0, 0), stretch_last=False) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setSpacing(spacing)
    layout.setContentsMargins(*margins)
    for widget in widgets:
        if widget is None:
            layout.addStretch(1)
        elif isinstance(widget, int):
            layout.addSpacing(widget)
        elif isinstance(widget, QWidget):
            layout.addWidget(widget)
        else:
            layout.addLayout(widget)
    if stretch_last:
        layout.addStretch(1)
    return layout


def vbox(*widgets, spacing: int = 8, margins=(0, 0, 0, 0)) -> QVBoxLayout:
    layout = QVBoxLayout()
    layout.setSpacing(spacing)
    layout.setContentsMargins(*margins)
    for widget in widgets:
        if widget is None:
            layout.addStretch(1)
        elif isinstance(widget, int):
            layout.addSpacing(widget)
        elif isinstance(widget, QWidget):
            layout.addWidget(widget)
        else:
            layout.addLayout(widget)
    return layout


def label(text: str = "", name: str | None = None, wrap: bool = False,
          selectable: bool = False) -> QLabel:
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    if wrap:
        # Wrapped labels must be allowed to grow vertically, otherwise some
        # layouts give them their one-line height and the text is clipped.
        widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    if selectable:
        widget.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return widget


def button(text: str, slot=None, kind: str | None = None, tooltip: str | None = None) -> QPushButton:
    widget = QPushButton(text)
    if kind:
        widget.setObjectName(kind)
    if slot is not None:
        widget.clicked.connect(slot)
    if tooltip:
        widget.setToolTip(tooltip)
    widget.setCursor(Qt.PointingHandCursor)
    return widget


class Card(QFrame):
    """A rounded surface with an optional title row."""

    def __init__(self, title: str | None = None, caption: str | None = None,
                 padding: int = 16, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding - 2, padding, padding)
        self.body.setSpacing(10)
        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        if title:
            self.title_label = label(title, "cardTitle")
            self.header.addWidget(self.title_label)
        self.header.addStretch(1)
        if title or caption:
            self.body.addLayout(self.header)
        if caption:
            self.caption_label = label(caption, "cardCaption", wrap=True)
            self.body.addWidget(self.caption_label)
        #: Items before this index are chrome (title, caption); see clear().
        self.fixed_count = self.body.count()

    def clear(self) -> None:
        """Remove all content, keeping the title and caption."""
        while self.body.count() > self.fixed_count:
            item = self.body.takeAt(self.body.count() - 1)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
            elif item.layout():
                _delete_layout(item.layout())

    def add(self, item, stretch: int = 0):
        if isinstance(item, QWidget):
            self.body.addWidget(item, stretch)
        else:
            self.body.addLayout(item, stretch)
        return item


def _delete_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout():
            _delete_layout(item.layout())


class StatTile(QFrame):
    """label · value · sub-line, the standard figure tile."""

    def __init__(self, caption: str, value: str = "–", sub: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 12)
        layout.setSpacing(2)
        self.caption = label(caption, "statLabel")
        self.value = label(value, "statValue")
        self.sub = label(sub, "statSub", wrap=True)
        self.value.setWordWrap(True)
        layout.addWidget(self.caption)
        layout.addWidget(self.value)
        layout.addWidget(self.sub)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set(self, value: str, sub: str = "") -> None:
        self.value.setText(value)
        self.sub.setText(sub)


class SegmentedControl(QFrame):
    """A row of mutually exclusive pill buttons (like NSSegmentedControl)."""

    changed = Signal(int)

    def __init__(self, labels: list[str], parent=None, compact: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("segmented")
        # Compact: tighter padding and a smaller font, for narrow panels.
        self.setProperty("compact", compact)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: list[QPushButton] = []
        for index, text in enumerate(labels):
            item = QPushButton(text)
            item.setCheckable(True)
            item.setCursor(Qt.PointingHandCursor)
            self.group.addButton(item, index)
            layout.addWidget(item)
            self.buttons.append(item)
        if self.buttons:
            self.buttons[0].setChecked(True)
        self.group.idClicked.connect(self.changed.emit)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def index(self) -> int:
        return self.group.checkedId()

    def set_index(self, index: int) -> None:
        if 0 <= index < len(self.buttons):
            self.buttons[index].setChecked(True)
            self.changed.emit(index)


class Verdict(QWidget):
    """Icon + property name + explanation, coloured by status.

    The icon glyph and the word carry the meaning; colour only reinforces it.
    """

    def __init__(self, name: str, status: str, detail: str, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(10)
        badge = _StatusBadge(status)
        layout.addWidget(badge, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(1)
        title = label(name)
        title.setStyleSheet("font-weight: 600;")
        text.addWidget(title)
        if detail:
            text.addWidget(label(detail, "muted", wrap=True, selectable=True))
        layout.addLayout(text, 1)


class _StatusBadge(QWidget):
    def __init__(self, status: str) -> None:
        super().__init__()
        self.status = status
        self.setFixedSize(20, 20)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        colour = QColor(style.STATUS.get(self.status, style.tokens().text_muted))
        painter.setPen(Qt.NoPen)
        painter.setBrush(colour)
        painter.drawEllipse(QRectF(1, 1, 18, 18))
        painter.setPen(QColor("#ffffff") if self.status != "warning" else QColor("#0b0b0b"))
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(12)
        painter.setFont(font)
        painter.drawText(QRectF(0, 0, 20, 20), Qt.AlignCenter,
                         style.STATUS_ICON.get(self.status, "?"))


def status_for(value: bool | None) -> str:
    return "unknown" if value is None else ("good" if value else "critical")


def fitness_status(value: float) -> str:
    """Traffic-light bands for a quality value in [0, 1]."""
    if value >= 0.95:
        return "good"
    if value >= 0.8:
        return "warning"
    return "critical"


# ---------------------------------------------------------------------------
# Activity chips
# ---------------------------------------------------------------------------
def paint_chips(painter: QPainter, rect: QRectF, sequence: list[tuple[str, str, str | None]],
                font, max_chip: float = 150.0) -> float:
    """Paint ``(text, fill, outline)`` chips left to right inside ``rect``.

    Returns the x coordinate after the last chip.  Chips that do not fit are
    replaced by a ``+n`` counter, so a long variant never overflows its row.
    """
    metrics = QFontMetricsF(font)
    painter.setFont(font)
    x = rect.left()
    height = min(rect.height(), metrics.height() + 8)
    y = rect.center().y() - height / 2
    for index, (text, fill, outline) in enumerate(sequence):
        shown = metrics.elidedText(text, Qt.ElideRight, max_chip - 16)
        width = metrics.horizontalAdvance(shown) + 16
        remaining = len(sequence) - index
        if x + width > rect.right() - (34 if remaining > 1 else 0):
            more = f"+{remaining}"
            painter.setPen(QColor(style.tokens().text_muted))
            painter.drawText(QRectF(x + 2, y, 40, height), Qt.AlignVCenter | Qt.AlignLeft, more)
            return x + 40
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, width, height), height / 2, height / 2)
        painter.setPen(QPen(QColor(outline), 1.5) if outline else Qt.NoPen)
        painter.setBrush(QColor(fill))
        painter.drawPath(path)
        painter.setPen(QColor(style.text_on(fill)))
        painter.drawText(QRectF(x, y, width, height), Qt.AlignCenter, shown)
        x += width + 4
    return x


class SequenceDelegate(QStyledItemDelegate):
    """Draws a list/table cell's ``Qt.UserRole`` value as activity chips.

    The role holds ``list[(text, fill, outline)]``.
    """

    def paint(self, painter: QPainter, option, index) -> None:
        sequence = index.data(Qt.UserRole)
        if not sequence:
            super().paint(painter, option, index)
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor(style.tokens().accent_soft))
        font = option.font
        font.setPointSizeF(max(font.pointSizeF() - 1, 9))
        paint_chips(painter, QRectF(option.rect).adjusted(6, 3, -6, -3), sequence, font)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        base = super().sizeHint(option, index)
        return QSize(base.width(), max(base.height(), 30))


class BarDelegate(QStyledItemDelegate):
    """Draws a number with a thin horizontal bar (``Qt.UserRole`` = fraction)."""

    def __init__(self, colour_role: int | None = None, parent=None) -> None:
        super().__init__(parent)
        self.colour_role = colour_role

    def paint(self, painter: QPainter, option, index) -> None:
        fraction = index.data(Qt.UserRole)
        if fraction is None:
            super().paint(painter, option, index)
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor(style.tokens().accent_soft))
        rect = QRectF(option.rect).adjusted(8, 0, -8, 0)
        text = str(index.data(Qt.DisplayRole) or "")
        metrics = QFontMetricsF(option.font)
        text_width = 64.0
        bar_rect = QRectF(rect.left() + text_width + 6, rect.center().y() - 4,
                          max(rect.width() - text_width - 6, 10) * float(fraction), 8)
        colour = index.data(self.colour_role) if self.colour_role else None
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(colour or style.categorical(0)))
        if bar_rect.width() > 0.5:
            painter.drawRoundedRect(bar_rect, 3, 3)
        painter.setPen(QColor(style.tokens().text))
        painter.drawText(QRectF(rect.left(), rect.top(), text_width, rect.height()),
                         Qt.AlignVCenter | Qt.AlignRight, metrics.elidedText(
                             text, Qt.ElideRight, text_width))
        painter.restore()


class ColourDot(QWidget):
    """A small filled circle: the identity mark beside a legend label."""

    def __init__(self, colour: str, size: int = 10) -> None:
        super().__init__()
        self.colour = colour
        self.setFixedSize(size, size)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self.colour))
        painter.drawEllipse(self.rect().adjusted(0, 0, -1, -1))


def is_dark() -> bool:
    return theme.is_dark()


class ElidedLabel(QLabel):
    """A one-line label that shortens itself with "…" instead of forcing width.

    A normal QLabel insists on being as wide as its text, which is how a long
    file name in a header can push the whole window wider than the screen.
    This one reports a tiny minimum width and elides when squeezed; the full
    text is always available as a tooltip.
    """

    def __init__(self, text: str = "", name: str | None = None) -> None:
        super().__init__(text)
        if name:
            self.setObjectName(name)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(40)
        self.setToolTip(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt naming
        super().setText(text)
        self.setToolTip(text)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.setFont(self.font())
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, rect.width())
        painter.drawText(rect, int(self.alignment() | Qt.AlignVCenter), text)


class PageHeader(QWidget):
    """Large title, muted subtitle, and a right-aligned row of actions."""

    def __init__(self, title: str = "", subtitle: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("pageHeader")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 10)
        layout.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = ElidedLabel(title, "pageTitle")
        self.subtitle = ElidedLabel(subtitle, "pageSubtitle")
        text.addWidget(self.title)
        text.addWidget(self.subtitle)
        layout.addLayout(text, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        layout.addLayout(self.actions)

    def set_text(self, title: str, subtitle: str) -> None:
        self.title.setText(title)
        self.subtitle.setText(subtitle)


def scroll(widget: QWidget, horizontal: bool = False) -> "QScrollArea":
    """Wrap ``widget`` in a frameless scroll area.

    With ``horizontal=False`` the content always matches the viewport width
    (only vertical scrolling).  With ``True`` the content may also scroll
    sideways when the viewport is narrower than its minimum width -- used
    around whole pages so that the *window* can always be made smaller.
    """
    from PySide6.QtWidgets import QScrollArea
    area = QScrollArea()
    area.setWidgetResizable(True)
    if not horizontal:
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setFrameShape(QFrame.NoFrame)
    area.setWidget(widget)
    return area


class LegendSwatch(QWidget):
    """A small painted key: a colour ramp, a line (thin/thick/dashed), or a dot."""

    def __init__(self, kind: str, colour: str | None = None, width: float = 1.5) -> None:
        super().__init__()
        self.kind, self.colour, self.line_width = kind, colour, width
        self.setFixedSize(46 if kind in ("ramp", "widths") else 30, 16)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = style.tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        colour = QColor(self.colour or t.text_secondary)
        if self.kind == "ramp":
            steps = 6
            w = self.width() / steps
            for i in range(steps):
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(style.sequential(0.1 + 0.8 * i / (steps - 1))))
                painter.drawRoundedRect(QRectF(i * w, 3, w - 1, 10), 2, 2)
        elif self.kind == "widths":
            for i, width in enumerate((1.0, 2.5, 4.5)):
                pen = QPen(colour, width)
                pen.setCapStyle(Qt.RoundCap)
                painter.setPen(pen)
                x = 4 + i * 14
                painter.drawLine(QPointF(x, 12), QPointF(x + 8, 4))
        elif self.kind == "dot":
            painter.setPen(Qt.NoPen)
            painter.setBrush(colour)
            painter.drawEllipse(QRectF(9, 2, 12, 12))
        else:
            pen = QPen(colour, self.line_width, Qt.DashLine if self.kind == "dashed" else Qt.SolidLine)
            pen.setCapStyle(Qt.FlatCap)
            painter.setPen(pen)
            painter.drawLine(QPointF(2, 8), QPointF(28, 8))


class FlowLayout(QLayout):
    """Lays widgets out left to right and wraps onto new lines when needed.

    Used for toolbars and legends, so a narrow window wraps them instead of
    forcing the whole page wider than the screen.
    """

    def __init__(self, parent=None, spacing: int = 8, line_spacing: int = 6) -> None:
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self._line_spacing = line_spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _arrange(self, rect: QRect, apply: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, line_height = area.x(), area.y(), 0
        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            hint = item.sizeHint()
            if x + hint.width() > area.right() + 1 and line_height > 0:
                x = area.x()
                y += line_height + self._line_spacing
                line_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


def flow(*widgets, spacing: int = 8) -> QWidget:
    """A widget holding ``widgets`` in a :class:`FlowLayout` (ints = extra gaps)."""
    host = QWidget()
    layout = FlowLayout(host, spacing=spacing)
    for widget in widgets:
        if isinstance(widget, int):
            spacer = QWidget()
            spacer.setFixedSize(max(widget - spacing, 0), 1)
            layout.addWidget(spacer)
        elif widget is not None:
            layout.addWidget(widget)
    host.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
    return host


class Legend(QWidget):
    """A wrapped row of (swatch, explanation) pairs under a chart or graph."""

    def __init__(self) -> None:
        super().__init__()
        self.layout_ = FlowLayout(self, spacing=16, line_spacing=4)
        self.layout_.setContentsMargins(0, 2, 0, 0)

    def set_items(self, items: list[tuple["LegendSwatch", str]]) -> None:
        while self.layout_.count():
            entry = self.layout_.takeAt(0)
            if entry.widget():
                entry.widget().hide()            # gone now, not at the next event loop
                entry.widget().deleteLater()
        for swatch, text in items:
            pair = QWidget()
            row = QHBoxLayout(pair)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            row.addWidget(swatch)
            row.addWidget(label(text, "muted"))
            self.layout_.addWidget(pair)
        self.layout_.invalidate()
        self.updateGeometry()


def short_names(names: list[str]) -> list[str]:
    """Distinct abbreviations for column headers: the initials of each word
    (``check credit`` -> ``cc``), numbered where two would clash; names of up
    to three characters stay as they are."""
    result = []
    for name in names:
        words = name.replace("_", " ").split()
        result.append(name if len(name) <= 3 else "".join(w[0] for w in words).lower()
                      or name[:3])
    for index, value in enumerate(result):
        clashes = [i for i, other in enumerate(result) if other == value]
        if len(clashes) > 1:
            for number, i in enumerate(clashes, 1):
                result[i] = f"{value}{number}"
    return result


def footprint_table(fp, compact: bool = False) -> "QTableWidget":
    """A footprint matrix (row activity vs column activity: → ← ‖ #) as a
    table, tinted by relation.  Used for logs and for models alike.

    ``compact`` (narrow panels): columns are headed by short names, with the
    full name in the header's tooltip."""
    from PySide6.QtWidgets import QAbstractItemView, QTableWidget, QTableWidgetItem
    from ...mining.footprint import CAUSAL, INVERSE, PARALLEL
    activities = fp.activities
    table = QTableWidget(len(activities), len(activities))
    headers = short_names(activities) if compact else activities
    table.setHorizontalHeaderLabels(headers)
    if compact:
        for index, name in enumerate(activities):
            table.horizontalHeaderItem(index).setToolTip(name)
    table.setVerticalHeaderLabels(activities)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionMode(QAbstractItemView.NoSelection)
    table.horizontalHeader().setDefaultSectionSize(
        40 if compact else max(52, min(140, 900 // max(len(activities), 1))))
    table.verticalHeader().setDefaultSectionSize(30 if compact else 34)
    table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
    t = style.tokens()
    tint = {CAUSAL: style.qc(style.categorical(0), 0.16),
            INVERSE: style.qc(style.categorical(0), 0.08),
            PARALLEL: style.qc(style.categorical(1), 0.18)}
    big = theme.ui_font(13 if compact else 15)
    for i, a in enumerate(activities):
        for j, b in enumerate(activities):
            relation = fp.relation(a, b)
            cell = QTableWidgetItem(relation)
            cell.setTextAlignment(Qt.AlignCenter)
            cell.setFont(big)
            cell.setToolTip({"→": f"{a} → {b}: causality ({a} > {b}, never {b} > {a})",
                             "←": f"{a} ← {b}: inverse causality",
                             "‖": f"{a} ‖ {b}: parallel (both orders occur)",
                             "#": f"{a} # {b}: never directly follow each other"}[relation])
            if relation in tint:
                cell.setBackground(tint[relation])
            else:
                cell.setForeground(QColor(t.text_muted))
            table.setItem(i, j, cell)
    return table
