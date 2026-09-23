"""Qt graphics items that draw the net on the canvas.

Coordinate systems
------------------
CPN Tools files place the origin at the centre of the page with **y increasing
upwards**.  Qt's scene has y increasing *downwards*.  The whole GUI therefore
uses one rule, applied in exactly two functions here (:func:`to_scene` /
:func:`to_model`): flip the sign of y at the boundary.  Everywhere else in the
GUI, coordinates are scene coordinates.

Item structure
--------------
Each net element is one top-level item with its labels as *child* items, so
moving a place moves its annotations with it for free.  Labels are plain text
items rather than editable ones: editing happens in the properties panel, which
keeps this module free of input handling.

Where the annotations go, and why
---------------------------------
A place carries up to four pieces of text, and none of them may collide --
neither with each other nor with the annotations of the *next* place along::

          ③ 1`ph(1)++1`ph(3)     <- current marking, centred ABOVE
             ( Think )  PH       <- colour set, to the RIGHT
          1`ph(1)++1`ph(2)…      <- initial marking, centred BELOW

The three long annotations are stacked vertically and each is **centred on the
place**, which is what keeps neighbouring nodes apart: a label capped at ~130 px
and centred extends only ~65 px either side, so two places 250 units apart can
never overprint one another.  Putting the live marking and the declared initial
marking on the same horizontal line -- the obvious first arrangement -- fails
badly here, because those two strings are usually similar in length and content
and end up sitting side by side across the whole diagram.

Long annotations are shortened with an ellipsis and carry the full text in a
tooltip; nothing is lost, because the complete marking is always listed in the
simulation panel.

Arc inscriptions sit at **35 % along the arc**, not at the midpoint.  Two arcs
running between the same neighbourhood in opposite directions have their
midpoints in nearly the same place, so midpoint labels overlap; measuring from
each arc's own source separates them.

Colours come from :mod:`cpnpy.gui.theme`, so everything here follows the system
light/dark appearance.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath,
    QPainterPathStroker, QPen, QPolygonF,
)
from PySide6.QtWidgets import (
    QGraphicsItem, QGraphicsPathItem, QGraphicsSimpleTextItem, QStyle,
)

from . import theme

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..model.net import Arc, Place, Transition


# ---------------------------------------------------------------------------
# Coordinate conversion
# ---------------------------------------------------------------------------
def to_scene(x: float, y: float) -> QPointF:
    """Model coordinates -> scene coordinates (flip y)."""
    return QPointF(x, -y)


def to_model(point: QPointF) -> tuple[float, float]:
    """Scene coordinates -> model coordinates (flip y back)."""
    return point.x(), -point.y()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
#: Longest annotation we will draw before shortening it, in scene units.
#: A marking such as ``1`ph(1)++1`ph(2)++1`ph(3)`` is wider than the gap
#: between two nodes, so drawn in full it runs straight over its neighbour.
#: The full text is always available in the tooltip and in the simulation
#: panel, so shortening on the canvas loses nothing.
MAX_ANNOTATION_WIDTH = 132.0
#: Inscriptions placed by the modeller (positions from a ``.cpn`` file) were
#: laid out for their full text, so they may be much longer before shortening.
MAX_AUTHORED_WIDTH = 340.0


class _Annotation(QGraphicsSimpleTextItem):
    """Text on the canvas, optionally on a soft backdrop of the canvas colour.

    Inscriptions often sit on top of arcs or grid dots; a translucent
    backdrop keeps them legible without boxing them in.
    """

    PAD = 2.0

    def __init__(self, parent: QGraphicsItem, backdrop: bool) -> None:
        super().__init__("", parent)
        self.backdrop = backdrop
        #: Called with the label's new centre (parent coordinates) after the
        #: user dragged it; ``None`` = the label cannot be dragged.
        self.on_dragged = None
        self._drag_from: QPointF | None = None

    # -- dragging (edit mode only) ------------------------------------------------
    def _draggable(self) -> bool:
        scene = self.scene()
        return (self.on_dragged is not None and bool(self.text())
                and getattr(scene, "editable", False) and getattr(scene, "tool", "") == "select")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton or not self._draggable():
            event.ignore()                       # let the node underneath handle it
            return
        event.accept()
        owner = self.parentItem()
        if owner is not None and owner.flags() & QGraphicsItem.ItemIsSelectable \
                and not owner.isSelected():
            if not event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier):
                self.scene().clearSelection()
            owner.setSelected(True)
        self._drag_from = event.scenePos() - self.pos()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_from is None:
            return
        self.setPos(event.scenePos() - self._drag_from)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_from is None:
            return
        self._drag_from = None
        centre = self.pos() + super().boundingRect().center()
        self.on_dragged(centre)

    def hoverEnterEvent(self, event) -> None:  # noqa: N802
        self.setCursor(Qt.OpenHandCursor if self._draggable() else Qt.ArrowCursor)

    def boundingRect(self) -> QRectF:  # noqa: N802
        rect = super().boundingRect()
        return rect.adjusted(-self.PAD, -1, self.PAD, 1) if self.backdrop else rect

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: N802
        if self.backdrop and self.text():
            colour = QColor(theme.palette().canvas)
            colour.setAlphaF(0.86)
            painter.setPen(Qt.NoPen)
            painter.setBrush(colour)
            painter.drawRoundedRect(self.boundingRect(), 3, 3)
        super().paint(painter, option, widget)


class _MarkingBox(QGraphicsSimpleTextItem):
    """The current marking of a place, in a pale green box with a shadow --
    how CPN Tools and CPN IDE show it next to the token count."""

    PAD_X, PAD_Y = 5.0, 2.0

    def boundingRect(self) -> QRectF:  # noqa: N802
        return super().boundingRect().adjusted(-self.PAD_X, -self.PAD_Y,
                                               self.PAD_X + 1.5, self.PAD_Y + 1.5)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: N802
        box = super().boundingRect().adjusted(-self.PAD_X, -self.PAD_Y,
                                              self.PAD_X, self.PAD_Y)
        dark = theme.is_dark()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 60))
        painter.drawRoundedRect(box.translated(1.5, 1.5), 3, 3)
        painter.setBrush(QColor("#1F4D24" if dark else "#C9F5C4"))
        painter.setPen(QPen(QColor("#3C8C44" if dark else "#7CCB76"), 0.8))
        painter.drawRoundedRect(box, 3, 3)
        super().paint(painter, option, widget)


class _CountBubble(QGraphicsPathItem):
    """The green token count.  Clicking it shows or hides the marking box,
    as in CPN Tools and CPN IDE."""

    def __init__(self, parent: "PlaceItem") -> None:
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptedMouseButtons(Qt.LeftButton)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        event.accept()                      # not a drag of the place
        self.parentItem().toggle_marking()


def _label(parent: QGraphicsItem, colour: QColor, font: QFont,
           backdrop: bool = True) -> QGraphicsSimpleTextItem:
    item = _Annotation(parent, backdrop)
    item.setBrush(QBrush(colour))
    item.setFont(font)
    return item


def _draggable_label(item: _Annotation, node: "_NodeItem", key: str) -> None:
    """Let the user drag a node's inscription; its spot is kept in the model
    (as an offset from the node's centre, in model units -- the ``.cpn`` way)."""
    def dragged(centre: QPointF) -> None:
        offsets = node.graphics().label_offsets
        offsets[key] = (centre.x(), -centre.y())
        node.refresh()

    item.on_dragged = dragged
    item.setAcceptHoverEvents(True)


def _snap(value: float, step: float) -> float:
    return round(value / step) * step if step > 0 else value


def _place_at_offset(item: QGraphicsSimpleTextItem, offsets: dict, key: str) -> bool:
    """Centre ``item`` where the model file put it (an offset in model units).

    Returns False when the file gave no position, so the caller can fall back
    to the automatic placement.
    """
    offset = offsets.get(key)
    if offset is None:
        return False
    bounds = item.boundingRect()
    # Model y points up, scene y points down.
    item.setPos(offset[0] - bounds.width() / 2, -offset[1] - bounds.height() / 2)
    return True


def _set_elided(item: QGraphicsSimpleTextItem, text: str,
                max_width: float = MAX_ANNOTATION_WIDTH) -> None:
    """Set an annotation, shortening it with an ellipsis if it is too wide.

    The untruncated string goes into the tooltip, so hovering always shows the
    real inscription.
    """
    metrics = QFontMetricsF(item.font())
    if metrics.horizontalAdvance(text) > max_width:
        item.setText(metrics.elidedText(text, Qt.ElideRight, max_width))
        item.setToolTip(text)
    else:
        item.setText(text)
        item.setToolTip("")


class _NodeItem(QGraphicsPathItem):
    """Shared behaviour for places and transitions.

    Both are rounded shapes with a name inside, both are movable, and both
    write their position back to the model as they move.  Factoring that out
    keeps the two concrete classes to just their own drawing and labels.

    Selection is drawn by us, not by Qt: the default is a dashed marching-ants
    rectangle, which looks dated and obscures the annotations.  We strip the
    selected state before delegating to the base paint and draw an accent ring
    instead.
    """

    def __init__(self, rect: QRectF) -> None:
        super().__init__()
        self._rect = rect
        #: Draw a soft accent halo (the transition that fired last).
        self.halo = False
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setZValue(10)

    def rect(self) -> QRectF:
        """The node's bounding shape, used by :class:`ArcItem` for clipping."""
        return self._rect

    def _build_path(self) -> QPainterPath:
        """The outline for the current :attr:`_rect`.  Supplied by subclasses."""
        raise NotImplementedError

    def _grow_to_fit(self, content_width: float, padding: float) -> bool:
        """Widen the node so its name fits, and report whether it changed.

        A node narrower than its own label looks broken, and CPN Tools sizes
        nodes to their names too.  The new width is written back to the model,
        so it survives a save and the diagram opens the same way next time.
        """
        needed = content_width + padding
        if needed <= self._rect.width() + 0.5:
            return False
        height = self._rect.height()
        self._rect = QRectF(-needed / 2, -height / 2, needed, height)
        self.setPath(self._build_path())
        return True

    def boundingRect(self) -> QRectF:  # noqa: N802
        # Room for the halo and the selection ring outside the outline.
        return super().boundingRect().adjusted(-6, -6, 6, 6)

    def set_halo(self, on: bool) -> None:
        if on != self.halo:
            self.halo = on
            self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: N802
        selected = bool(option.state & QStyle.State_Selected)
        option.state &= ~QStyle.State_Selected
        if self.halo:
            colour = QColor(theme.palette().accent)
            colour.setAlphaF(0.30)
            painter.setPen(QPen(colour, 8.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(self.path())
        super().paint(painter, option, widget)
        if selected:
            palette = theme.palette()
            pen = QPen(palette.accent, 2.0)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(self.path())

    def graphics(self):
        """The model's graphics record for this node."""
        raise NotImplementedError

    def refresh(self) -> None:
        raise NotImplementedError

    def itemChange(self, change, value):  # noqa: N802 - Qt naming
        # "Snap to grid": a dragged node's centre lands on the dot grid.
        if change == QGraphicsItem.ItemPositionChange:
            step = getattr(self.scene(), "snap_step", 0)
            if step:
                return QPointF(_snap(value.x(), step), _snap(value.y(), step))
        return super().itemChange(change, value)

    def _notify_arcs(self) -> None:
        """Ask every arc touching this node to recompute its route."""
        scene = self.scene()
        if scene is None:
            return
        identifier = getattr(self, "model_id", None)
        for item in scene.items():
            if isinstance(item, ArcItem) and item.touches(identifier):
                item.reroute()


# ---------------------------------------------------------------------------
# Places
# ---------------------------------------------------------------------------
class PlaceItem(_NodeItem):
    """An ellipse with its name inside and four annotations around it."""

    def __init__(self, place: "Place") -> None:
        width = place.graphics.width or 76.0
        height = place.graphics.height or 48.0
        super().__init__(QRectF(-width / 2, -height / 2, width, height))
        self.place = place
        self.model_id = place.id

        self.setPath(self._build_path())

        palette = theme.palette()
        self.setBrush(QBrush(palette.surface))
        self.setPen(QPen(palette.border_strong, 1.6))

        self.name_label = _label(self, palette.text, theme.ui_font(12, QFont.DemiBold), False)
        type_font = theme.ui_font(10)
        type_font.setItalic(True)
        self.type_label = _label(self, palette.text_muted, type_font)
        self.initial_label = _label(self, palette.inscription, theme.mono_font(10))
        _draggable_label(self.type_label, self, "type")
        _draggable_label(self.initial_label, self, "initmark")

        # The live marking, as in CPN Tools: a green token count at the
        # place's right-hand edge, and next to it the tokens themselves in a
        # pale green box that clicking the count shows or hides.
        self.count_pill = _CountBubble(self)
        self.count_pill.setPen(QPen(Qt.NoPen))
        self.count_pill.setBrush(QBrush(palette.success))
        self.count_label = _label(self.count_pill, QColor("#FFFFFF"),
                                  theme.ui_font(10, QFont.Bold), False)
        self.marking_label = _MarkingBox(self)
        self.marking_label.setFont(theme.mono_font(10))
        self.marking_label.setBrush(QBrush(QColor("#D7F5D7" if theme.is_dark() else "#113311")))
        self.marking_label.setZValue(2)
        self._marking_state = (0, "", None)
        self.set_marking(0, "")

        self.setPos(to_scene(place.graphics.x, place.graphics.y))
        self.refresh()

    # -- presentation --------------------------------------------------------
    def graphics(self):
        return self.place.graphics

    def _build_path(self) -> QPainterPath:
        path = QPainterPath()
        path.addEllipse(self._rect)
        return path

    def refresh(self) -> None:
        """Re-read the model object and lay the annotations out."""
        self.name_label.setText(self.place.name)
        bounds = self.name_label.boundingRect()

        # An ellipse only offers about 70 % of its width at the text's height,
        # so the name needs proportionally more room here than in a rectangle.
        if self._grow_to_fit(bounds.width() / 0.70, 12.0):
            self.place.graphics.width = self._rect.width()
        rect = self._rect

        self.name_label.setPos(-bounds.width() / 2, -bounds.height() / 2)

        # Inscriptions go where the model file put them; otherwise at CPN
        # Tools' default spots: colour set below right, initial marking above
        # right.
        offsets = self.place.graphics.label_offsets
        self.type_label.setText(self.place.colour_set_name)
        if not _place_at_offset(self.type_label, offsets, "type"):
            self.type_label.setPos(rect.right() - 4, rect.bottom() - 4)

        _set_elided(self.initial_label, self.place.initial_marking_text,
                    MAX_AUTHORED_WIDTH if "initmark" in offsets else MAX_ANNOTATION_WIDTH)
        if not _place_at_offset(self.initial_label, offsets, "initmark"):
            initial_bounds = self.initial_label.boundingRect()
            self.initial_label.setPos(rect.right() - 4, rect.top() - initial_bounds.height() + 4)

    def set_marking(self, count: int, text: str, show_values: bool | None = None) -> None:
        """Show the simulator's current contents at the place.

        ``count`` goes in the green bubble at the place's right-hand edge;
        ``text`` (the multiset) in the box beside it, which is shown or
        hidden per place -- the model file's own setting at first, then by
        clicking the bubble -- unless ``show_values`` forces all on or off.
        The tooltip always has the full marking.  An empty place shows
        nothing.
        """
        self._marking_state = (count, text, show_values)
        visible = count > 0
        self.count_pill.setVisible(visible)
        if show_values is None:
            show_values = not self.place.graphics.marking_hidden
        self.marking_label.setVisible(visible and show_values)
        tip = "" if not visible else f"{self.place.name}: {count} token(s)\n" + (
            text if len(text) < 1500 else text[:1500] + " …")
        self.setToolTip(tip)
        self.count_pill.setToolTip(tip + ("\n\nClick to show or hide the tokens" if tip else ""))
        if not visible:
            return

        self.count_label.setText(str(count))
        label_bounds = self.count_label.boundingRect()
        pill_height = 16.0
        pill_width = max(pill_height, label_bounds.width() + 9)
        pill = QPainterPath()
        pill.addRoundedRect(QRectF(0, 0, pill_width, pill_height),
                            pill_height / 2, pill_height / 2)
        self.count_pill.setPath(pill)
        self.count_label.setPos((pill_width - label_bounds.width()) / 2,
                                (pill_height - label_bounds.height()) / 2)

        # CPN Tools' convention (as CPN IDE reads it): the count's corner is
        # at the place's right edge, level with its centre, moved by the
        # file's "token" offset; the marking box is to the right of the count,
        # moved by the "marking" offset.  Offsets from a file that would put
        # them far away are ignored.
        tx, ty = self.place.graphics.label_offsets.get("token", (0.0, 0.0))
        if abs(tx) > 60 or abs(ty) > 60:
            tx = ty = 0.0
        left, top = self._rect.right() + tx - 4, -ty - pill_height / 2
        self.count_pill.setPos(left, top)

        _set_elided(self.marking_label, text, 260.0)
        mx, my = self.place.graphics.label_offsets.get("marking", (0.0, 0.0))
        if abs(mx) > 120 or abs(my) > 120:
            mx = my = 0.0
        box_left = max(left + pill_width + 6, left + pill_width + 6 + mx)
        text_bounds = self.marking_label.boundingRect()
        self.marking_label.setPos(box_left + _MarkingBox.PAD_X,
                                  top - my + (pill_height - text_bounds.height()) / 2
                                  + _MarkingBox.PAD_Y)

    def toggle_marking(self) -> None:
        """Clicking the count: show or hide this place's tokens."""
        self.place.graphics.marking_hidden = self.marking_label.isVisible()
        count, text, _forced = self._marking_state
        self.set_marking(count, text, None)

    def set_error(self, has_error: bool) -> None:
        palette = theme.palette()
        self.setPen(QPen(palette.danger if has_error else palette.border_strong, 1.6))

    def itemChange(self, change, value):  # noqa: N802 - Qt naming
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.place.graphics.x, self.place.graphics.y = to_model(self.pos())
            self._notify_arcs()
        return super().itemChange(change, value)


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------
class TransitionItem(_NodeItem):
    """A rounded rectangle with name, guard and time labels, plus the enabling cue."""

    def __init__(self, transition: "Transition") -> None:
        width = transition.graphics.width or 82.0
        height = transition.graphics.height or 48.0
        super().__init__(QRectF(-width / 2, -height / 2, width, height))
        self.transition = transition
        self.model_id = transition.id
        self.enabled_count = 0
        self._has_error = False

        self.setPath(self._build_path())

        palette = theme.palette()
        self.name_label = _label(self, palette.text, theme.ui_font(12, QFont.DemiBold), False)
        self.guard_label = _label(self, palette.inscription, theme.mono_font(10))
        self.time_label = _label(self, palette.inscription, theme.mono_font(10))
        _draggable_label(self.guard_label, self, "cond")
        _draggable_label(self.time_label, self, "time")

        # The binding count sits in its own pill, mirroring the place's marking
        # pill so the two read as the same kind of information.
        self.count_pill = QGraphicsPathItem(self)
        self.count_pill.setPen(QPen(Qt.NoPen))
        self.count_pill.setBrush(QBrush(palette.success))
        self.count_label = _label(self.count_pill, QColor("#FFFFFF"),
                                  theme.ui_font(10, QFont.Bold), False)
        self.count_pill.setVisible(False)

        self.setPos(to_scene(transition.graphics.x, transition.graphics.y))
        self.refresh()
        self.set_enabled_count(0)

    def graphics(self):
        return self.transition.graphics

    def _build_path(self) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(self._rect, theme.RADIUS, theme.RADIUS)
        return path

    def refresh(self) -> None:
        palette = theme.palette()

        self.name_label.setText(self.transition.name)
        bounds = self.name_label.boundingRect()
        if self._grow_to_fit(bounds.width(), 26.0):
            self.transition.graphics.width = self._rect.width()
        rect = self._rect

        self.name_label.setPos(-bounds.width() / 2, -bounds.height() / 2)

        # Guards are conventionally shown in square brackets, to the left.
        offsets = self.transition.graphics.label_offsets
        guard = self.transition.guard_text.strip()
        if guard and not guard.startswith("["):
            guard = f"[{guard}]"
        _set_elided(self.guard_label, guard, MAX_AUTHORED_WIDTH if "cond" in offsets else 200)
        if not _place_at_offset(self.guard_label, offsets, "cond"):
            # CPN Tools' default spot: above, to the left.
            bounds = self.guard_label.boundingRect()
            self.guard_label.setPos(rect.left() - 5 - bounds.width() + 8,
                                    rect.top() - bounds.height() + 2)

        # The file may store "@+5" or just "5"; show it once as "@+5".
        delay = self.transition.time_text.strip()
        if delay.startswith("@+"):
            delay = delay[2:].strip()
        _set_elided(self.time_label, f"@+{delay}" if delay else "",
                    MAX_AUTHORED_WIDTH if "time" in offsets else 200)
        if not _place_at_offset(self.time_label, offsets, "time"):
            # Above, to the right.
            bounds = self.time_label.boundingRect()
            self.time_label.setPos(rect.right() - 3, rect.top() - bounds.height() + 2)

    def set_enabled_count(self, count: int) -> None:
        """Colour the transition according to how many bindings are enabled."""
        self.enabled_count = count
        palette = theme.palette()

        if self._has_error:
            self.setBrush(QBrush(palette.surface))
            self.setPen(QPen(palette.danger, 1.8))
        elif count:
            self.setBrush(QBrush(palette.success_soft))
            self.setPen(QPen(palette.success, 2.2))
        else:
            self.setBrush(QBrush(palette.surface))
            # A substitution transition gets a heavier border, as in CPN Tools,
            # because it stands for a whole subpage rather than an event.
            self.setPen(QPen(palette.border_strong,
                             3.0 if self.transition.is_substitution else 1.6))

        # Only show the pill when there is a genuine choice to make.
        self.count_pill.setVisible(count > 1)
        if count > 1:
            self.count_label.setText(str(count))
            bounds = self.count_label.boundingRect()
            width = max(18.0, bounds.width() + 10)
            height = 16.0
            pill = QPainterPath()
            pill.addRoundedRect(QRectF(0, 0, width, height), height / 2, height / 2)
            self.count_pill.setPath(pill)
            self.count_label.setPos((width - bounds.width()) / 2,
                                    (height - bounds.height()) / 2)
            self.count_pill.setPos(self._rect.right() - width / 2,
                                   self._rect.bottom() - height / 2 - 1)

    def set_error(self, has_error: bool) -> None:
        self._has_error = has_error
        self.set_enabled_count(self.enabled_count)

    def itemChange(self, change, value):  # noqa: N802 - Qt naming
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.transition.graphics.x, self.transition.graphics.y = to_model(self.pos())
            self._notify_arcs()
        return super().itemChange(change, value)


# ---------------------------------------------------------------------------
# Arcs
# ---------------------------------------------------------------------------
class _BendHandle(QGraphicsPathItem):
    """A round handle on a selected arc.

    A *bend* handle (filled) sits on a bendpoint: drag it to move the bend,
    double-click it to remove the bend.  An *add* handle (hollow, smaller)
    sits halfway along a segment: dragging it creates a new bend there.
    Handles keep the same size on screen at every zoom level.
    """

    def __init__(self, arc_item: "ArcItem", is_bend: bool) -> None:
        super().__init__(arc_item)
        self.arc_item = arc_item
        self.is_bend = is_bend
        #: Bend: its index in ``arc.bendpoints``; add handle: the index a new
        #: bend gets.
        self.index = 0
        self._dragging: int | None = None
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setCursor(Qt.SizeAllCursor if is_bend else Qt.CrossCursor)
        radius = 4.5 if is_bend else 3.6
        path = QPainterPath()
        path.addEllipse(QPointF(0, 0), radius, radius)
        self.setPath(path)
        accent = theme.palette().accent
        if is_bend:
            self.setBrush(QBrush(accent))
            self.setPen(QPen(QColor("#FFFFFF"), 1.4))
        else:
            self.setBrush(QBrush(theme.palette().canvas))
            self.setPen(QPen(accent, 1.4))
        self.setToolTip("Drag to move this bend · double-click to remove it" if is_bend else
                        "Drag to add a bend here")

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addEllipse(QPointF(0, 0), 8, 8)     # easy to grab
        return path

    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(-8, -8, 16, 16)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            event.ignore()
            return
        event.accept()
        if self.is_bend:
            self._dragging = self.index
        else:
            self._dragging = self.arc_item.insert_bend(self.index, event.scenePos())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._dragging is not None:
            self.arc_item.move_bend(self._dragging, event.scenePos())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._dragging = None

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self.is_bend:
            event.accept()
            self.arc_item.remove_bend(self.index)

class ArcItem(QGraphicsPathItem):
    """A directed arc with an arrowhead and an inscription label.

    Three routing features, each fixing a way that a naive straight line
    between two centres goes wrong:

    **Endpoint clipping.**  The line stops at the boundary of each shape, so
    the arrowhead lands on the edge of the transition rather than at its centre.

    **Bendpoints.**  ``.cpn`` files store polyline bendpoints, and real models
    use them heavily to route around nodes.  Ignoring them would make an
    imported model look nothing like it does in CPN Tools, so the path follows
    them when present.

    **Parallel arcs.**  Two arcs between the *same* place and transition -- a
    consume-and-return pair, say -- would otherwise be drawn exactly on top of
    each other.  When the scene reports that an arc has siblings, it is
    shifted sideways (``bow``) so both are visible, as in CPN IDE.
    """

    ARROW_LENGTH = 10.0
    ARROW_HALF_WIDTH = 4.2
    #: Where along the arc the inscription sits.  Not 0.5: see the module
    #: docstring -- opposing arcs would collide at the midpoint.
    LABEL_POSITION = 0.35

    def __init__(self, arc: "Arc", place_item: PlaceItem,
                 transition_item: TransitionItem, bow: float = 0.0) -> None:
        super().__init__()
        self.arc = arc
        self.place_item = place_item
        self.transition_item = transition_item
        self.bow = bow

        palette = theme.palette()
        self.setPen(QPen(palette.border_strong, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        self.setBrush(QBrush(palette.border_strong))
        self.setZValue(5)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)

        self.inscription_label = _label(self, palette.inscription, theme.mono_font(10))
        self.inscription_label.on_dragged = self._inscription_dragged
        self.inscription_label.setAcceptHoverEvents(True)
        #: Where the modeller put the inscription, relative to the midpoint
        #: of the two nodes (so it follows them when they move).
        self._label_offset: QPointF | None = None
        absolute = arc.graphics.label_offsets.get("annot")
        if absolute is not None and arc.graphics.label_offsets:
            self._label_offset = to_scene(*absolute) - self._node_midpoint()
        #: While nodes are being dragged: (transition position, place
        #: position, bendpoints) at the start of the drag, so the bends can
        #: follow the nodes (see :meth:`_follow_nodes`).
        self.drag_origin: tuple[QPointF, QPointF, list[QPointF]] | None = None
        self._bend_handles: list[_BendHandle] = []
        self._add_handles: list[_BendHandle] = []
        #: Halfway points of the drawn segments, transition end first.
        self._segment_middles: list[QPointF] = []
        self.reroute()

    def _node_midpoint(self) -> QPointF:
        return (self.place_item.pos() + self.transition_item.pos()) / 2

    def touches(self, element_id: str | None) -> bool:
        return element_id is not None and element_id in (
            self.arc.place_id, self.arc.transition_id
        )

    # -- geometry ------------------------------------------------------------
    #: A bendpoint within this distance (horizontally or vertically) of a
    #: node's centre makes the arc leave the node straight across or straight
    #: down -- CPN Tools' tidy right-angled arcs.
    SNAP = 20.0

    def reroute(self) -> None:
        """Recompute the path, the arrowhead(s) and the label position.

        The rules are those of CPN Tools and CPN IDE:

        * an input arc runs place -> transition, every other one (output
          and double-headed) transition -> place;
        * bendpoints are stored from the transition end to the place end,
          and are joined by straight segments;
        * a first or last bendpoint roughly level with (or above) its node
          pulls the end of the arc level with it, so it leaves the node at a
          right angle instead of heading for the exact centre;
        * arcs between the same place and transition without bendpoints are
          drawn side by side as parallel lines.
        """
        if self.arc.is_input and not self.arc.is_output:
            start_item, end_item = self.place_item, self.transition_item
        else:
            start_item, end_item = self.transition_item, self.place_item

        self._follow_nodes()
        stored = [to_scene(x, y) for x, y in self.arc.bendpoints]   # transition -> place
        ordered = stored if start_item is self.transition_item else stored[::-1]

        if ordered:
            start = self._crop(start_item, self._anchor(start_item, ordered[0]), ordered[0])
            end = self._crop(end_item, self._anchor(end_item, ordered[-1]), ordered[-1])
        else:
            # Parallel arcs: shift both ends sideways by the same amount.
            # The side is measured in one fixed direction (place ->
            # transition), so an input and an output arc between the same
            # nodes go to opposite sides instead of on top of each other.
            chord = self.transition_item.pos() - self.place_item.pos()
            length = math.hypot(chord.x(), chord.y()) or 1.0
            shift = QPointF(-chord.y() / length, chord.x() / length) * self.bow
            a, b = start_item.pos() + shift, end_item.pos() + shift
            start = self._crop(start_item, a, b)
            end = self._crop(end_item, b, a)

        path = QPainterPath(start)
        chain = [start, *ordered, end]
        middles = []
        if ordered and self.arc.graphics.smooth:
            # A curve through the bendpoints (Catmull-Rom as cubic Béziers):
            # routes computed by Graphviz are curves, not corners.
            for i in range(len(chain) - 1):
                p0 = chain[i - 1] if i > 0 else chain[i]
                p1, p2 = chain[i], chain[i + 1]
                p3 = chain[i + 2] if i + 2 < len(chain) else p2
                c1, c2 = p1 + (p2 - p0) / 6, p2 - (p3 - p1) / 6
                path.cubicTo(c1, c2, p2)
                middles.append((p1 + c1 * 3 + c2 * 3 + p2) / 8)   # the curve at t = ½
        else:
            for point in chain[1:]:
                path.lineTo(point)
            middles = [(a + b) / 2 for a, b in zip(chain, chain[1:])]
        # Handles are indexed from the transition end, like the bendpoints.
        self._segment_middles = middles if start_item is self.transition_item else middles[::-1]

        # The line is stroked and the arrowheads are filled, so they live in
        # separate paths.  (One combined, filled path would also fill the area
        # enclosed by a bent line -- the "black triangles" bug.)
        self.line_path = QPainterPath(path)
        arrows = QPainterPath()
        self._append_arrowhead(arrows, self._tangent_source(path, 0.97), end)
        if self.arc.orientation == "BOTHDIR":
            self._append_arrowhead(arrows, self._tangent_source(path, 0.03), start)
        self.arrow_path = arrows
        combined = QPainterPath(path)
        combined.addPath(arrows)
        self.setPath(combined)

        self._place_label(path)
        self.sync_handles()

    # -- editing the route ----------------------------------------------------
    def _follow_nodes(self) -> None:
        """While nodes are dragged, carry the bends along.

        Each bend moves by a blend of the two nodes' displacements, weighted
        by how far along the arc it lies: moving both ends moves the whole
        route; moving one end stretches it, with the bends near the other
        end staying put.  (CPN Tools leaves bends where they are, which is
        what makes a laid-out arc feel pinned down.)
        """
        if self.drag_origin is None:
            return
        t0, p0, bends = self.drag_origin
        dt = self.transition_item.pos() - t0
        dp = self.place_item.pos() - p0
        if not bends or (dt.manhattanLength() < 1e-6 and dp.manhattanLength() < 1e-6):
            return
        axis = p0 - t0
        length2 = axis.x() ** 2 + axis.y() ** 2
        moved = []
        for bend in bends:
            if length2 < 1e-6:
                share = 0.5
            else:
                along = bend - t0
                share = (along.x() * axis.x() + along.y() * axis.y()) / length2
                share = max(0.0, min(1.0, share))
            moved.append(to_model(bend + dt * (1 - share) + dp * share))
        self.arc.bendpoints = moved

    def _handles_wanted(self) -> bool:
        scene = self.scene()
        return (self.isSelected() and getattr(scene, "editable", False)
                and getattr(scene, "tool", "") == "select")

    def sync_handles(self) -> None:
        """Show handles on the bends and halfway along each segment (only
        while this arc is selected in edit mode)."""
        wanted = self._handles_wanted()
        bends = [to_scene(x, y) for x, y in self.arc.bendpoints] if wanted else []
        middles = self._segment_middles if wanted else []
        for handles, points, is_bend in ((self._bend_handles, bends, True),
                                         (self._add_handles, middles, False)):
            while len(handles) < len(points):
                handles.append(_BendHandle(self, is_bend))
            for index, handle in enumerate(handles):
                if index < len(points):
                    handle.index = index
                    handle.setPos(points[index])
                    handle.setVisible(True)
                else:
                    handle.setVisible(False)
        self.setZValue(11 if wanted else 5)     # handles above the nodes

    def _scene_snap(self, point: QPointF) -> QPointF:
        step = getattr(self.scene(), "snap_step", 0)
        return QPointF(_snap(point.x(), step), _snap(point.y(), step))

    def insert_bend(self, index: int, point: QPointF) -> int:
        """Add a bend at ``index`` (0 = next to the transition); returns its index."""
        index = max(0, min(index, len(self.arc.bendpoints)))
        self.arc.bendpoints.insert(index, to_model(self._scene_snap(point)))
        self.reroute()
        return index

    def move_bend(self, index: int, point: QPointF) -> None:
        if 0 <= index < len(self.arc.bendpoints):
            self.arc.bendpoints[index] = to_model(self._scene_snap(point))
            self.reroute()

    def remove_bend(self, index: int) -> None:
        if 0 <= index < len(self.arc.bendpoints):
            scene = self.scene()
            if scene is not None and hasattr(scene, "about_to_change"):
                scene.about_to_change.emit()
            del self.arc.bendpoints[index]
            self.reroute()
            if scene is not None and hasattr(scene, "moved"):
                scene.moved.emit()

    def add_bend_near(self, point: QPointF) -> int:
        """Add a bend at ``point`` in the segment closest to it (right-click menu)."""
        chain = ([self.transition_item.pos()]
                 + [to_scene(x, y) for x, y in self.arc.bendpoints]
                 + [self.place_item.pos()])
        best, best_distance = 0, math.inf
        for index, (a, b) in enumerate(zip(chain, chain[1:])):
            d = b - a
            length2 = d.x() ** 2 + d.y() ** 2 or 1.0
            share = max(0.0, min(1.0, ((point - a).x() * d.x() + (point - a).y() * d.y())
                                 / length2))
            gap = point - (a + d * share)
            distance = math.hypot(gap.x(), gap.y())
            if distance < best_distance:
                best, best_distance = index, distance
        return self.insert_bend(best, point)

    def straighten(self) -> None:
        self.arc.bendpoints = []
        self.reroute()

    def reset_label(self) -> None:
        self._label_offset = None
        self.arc.graphics.label_offsets.pop("annot", None)
        self.reroute()

    def _inscription_dragged(self, centre: QPointF) -> None:
        self._label_offset = centre - self._node_midpoint()
        self.reroute()

    def itemChange(self, change, value):  # noqa: N802 - Qt naming
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self.sync_handles()
        return super().itemChange(change, value)

    @staticmethod
    def _tangent_source(path: QPainterPath, percent: float) -> QPointF:
        """A point just short of an end, giving the direction to point the head."""
        return path.pointAtPercent(max(0.0, min(1.0, percent)))

    def _place_label(self, path: QPainterPath) -> None:
        """Put the inscription a third of the way along, clear of the line."""
        _set_elided(self.inscription_label, self.arc.expression_text,
                    MAX_AUTHORED_WIDTH if self._label_offset is not None
                    else MAX_ANNOTATION_WIDTH)
        if not self.arc.expression_text:
            return
        if self._label_offset is not None:
            centre = self._node_midpoint() + self._label_offset
            bounds = self.inscription_label.boundingRect()
            self.inscription_label.setPos(centre.x() - bounds.width() / 2,
                                          centre.y() - bounds.height() / 2)
            # Keep the model in step, so saving writes where it is drawn.
            self.arc.graphics.label_offsets["annot"] = to_model(centre)
            return

        anchor = path.pointAtPercent(self.LABEL_POSITION)
        angle = math.radians(path.angleAtPercent(self.LABEL_POSITION))
        # Qt reports the angle counter-clockwise from the x axis in a
        # y-down scene, hence the negated sine.
        tangent = QPointF(math.cos(angle), -math.sin(angle))
        normal = QPointF(-tangent.y(), tangent.x())

        bounds = self.inscription_label.boundingRect()
        if abs(self.bow) > 0.01 and not self.arc.bendpoints:
            # One of a pair of parallel arcs: write on its own side, so the
            # two inscriptions of a pair end up on opposite sides.
            chord = self.transition_item.pos() - self.place_item.pos()
            length = math.hypot(chord.x(), chord.y()) or 1.0
            side = QPointF(-chord.y() / length, chord.x() / length) * math.copysign(1, self.bow)
            # Far enough that the text box clears the line, whatever the angle.
            reach = 6.0 + abs(side.x()) * bounds.width() / 2 + abs(side.y()) * bounds.height() / 2
            offset = side * reach
        else:
            # Offset to whichever side of the line points "up" on screen, so
            # the text never sits on top of the arc.
            offset = normal * (12.0 if normal.y() < 0 else -12.0)
        self.inscription_label.setPos(
            anchor.x() + offset.x() - bounds.width() / 2,
            anchor.y() + offset.y() - bounds.height() / 2,
        )

    def _anchor(self, item: _NodeItem, towards: QPointF) -> QPointF:
        """Where inside ``item`` the arc starts: its centre, moved level with
        (or in line with) the neighbouring bendpoint when that is close, as
        long as the point stays inside the node."""
        centre = item.pos()
        rect = item.rect()
        x, y = centre.x(), centre.y()
        if abs(towards.y() - y) < self.SNAP and abs(towards.y() - y) < rect.height() / 2 - 3:
            y = towards.y()
        if abs(towards.x() - x) < self.SNAP and abs(towards.x() - x) < rect.width() / 2 - 3:
            x = towards.x()
        return QPointF(x, y)

    @staticmethod
    def _inside(item: _NodeItem, point: QPointF) -> bool:
        local = point - item.pos()
        rect = item.rect()
        a, b = rect.width() / 2, rect.height() / 2
        if isinstance(item, PlaceItem):
            return (local.x() / a) ** 2 + (local.y() / b) ** 2 <= 1.0
        return abs(local.x()) <= a and abs(local.y()) <= b

    def _crop(self, item: _NodeItem, inside: QPointF, outside: QPointF) -> QPointF:
        """The point where the segment ``inside`` -> ``outside`` leaves the node,
        plus two pixels of air so the arrowhead does not touch the outline."""
        if not self._inside(item, inside):
            inside = item.pos()
        if self._inside(item, outside):
            return outside                   # overlapping nodes: nothing to crop
        low, high = 0.0, 1.0
        for _ in range(24):                  # bisection: exact to well under a pixel
            middle = (low + high) / 2
            if self._inside(item, inside + (outside - inside) * middle):
                low = middle
            else:
                high = middle
        direction = outside - inside
        length = math.hypot(direction.x(), direction.y()) or 1.0
        return inside + direction * high + direction * (2.0 / length)

    def _append_arrowhead(self, path: QPainterPath, tail: QPointF, tip: QPointF) -> None:
        """Add a filled triangle at ``tip``, pointing away from ``tail``."""
        direction = tip - tail
        length = math.hypot(direction.x(), direction.y())
        if length < 1e-6:
            return
        unit = QPointF(direction.x() / length, direction.y() / length)
        normal = QPointF(-unit.y(), unit.x())

        base = tip - unit * self.ARROW_LENGTH
        path.addPolygon(
            QPolygonF([
                tip,
                base + normal * self.ARROW_HALF_WIDTH,
                base - normal * self.ARROW_HALF_WIDTH,
                tip,
            ])
        )

    def shape(self) -> QPainterPath:
        """Widen the clickable region (a 1.5 px line is very hard to hit), but
        only around the line and the arrowheads, not the area a bent arc
        encloses."""
        stroker = QPainterPathStroker()
        stroker.setWidth(10.0)
        return stroker.createStroke(self.line_path).united(self.arrow_path)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: N802
        painter.setRenderHint(QPainter.Antialiasing)
        selected = bool(option.state & QStyle.State_Selected)
        if selected:
            colour = theme.palette().accent
            pen = QPen(colour, 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        else:
            pen = QPen(self.pen())
            colour = pen.color()
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)          # never fill the line itself
        painter.drawPath(self.line_path)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(colour))
        painter.drawPath(self.arrow_path)

    def set_error(self, has_error: bool) -> None:
        """Draw the arc in red when its inscription failed to compile."""
        palette = theme.palette()
        colour = palette.danger if has_error else palette.border_strong
        self.setPen(QPen(colour, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        self.setBrush(QBrush(colour))
        self.inscription_label.setBrush(
            QBrush(palette.danger if has_error else palette.inscription)
        )
