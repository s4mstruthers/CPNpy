"""The workflow canvas: boxes, wires, and dragging a wire to connect.

A :class:`BoxItem` draws one node of the workflow the way the sketch does:
the group as a small eyebrow, the name, a line about its result, a status
dot, and its connection points as coloured dots (inputs on the left,
outputs on the right).  A :class:`WireItem` is a curve between an output
and an input.  The :class:`WorkflowScene` keeps the items in step with a
:class:`~cpnpy.flow.workflow.Workflow` and handles the gestures:

* drag a box to move it (snapped to the grid, wires follow);
* drag from an output dot to connect it: while dragging, only the inputs
  it may go to light up, the others fade, and letting go near one makes
  the edge (the workflow refuses the wrong type, a loop, a duplicate);
* click a wire to select it, Delete removes it;
* double-click the background to add a box there (the page shows a list).

The scene only edits the workflow and says what changed (``edited``); the
page runs the boxes and shows the results.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QGraphicsPathItem, QGraphicsScene

from ...flow.box import Port
from ...flow.runner import BLOCKED, DONE, FAILED, IDLE, RUNNING, WAITING
from ...flow.types import type_info
from ...flow.workflow import Edge, Node, Workflow
from .. import theme
from ..studio import style
from ..studio.graph_view import GraphView

NODE_W = 178.0
GRID = 10.0
PORT_R = 6.0
STATUS_COLOUR = {DONE: "good", RUNNING: "accent", FAILED: "critical", BLOCKED: "warning",
                 WAITING: "muted", IDLE: "muted"}


def port_colour(port: Port) -> str:
    info = type_info(port.type) if port.type is not None else None
    return info.colour if info else style.tokens().text_muted


def _font(size: float, bold: bool = False) -> QFont:
    font = theme.ui_font(size)
    font.setBold(bold)
    return font


def node_height(inputs: int, outputs: int) -> float:
    rows = max(inputs, outputs)
    return 72 + 20 * (rows - 1) + 14 if rows > 1 else 66


class BoxItem(QGraphicsObject):
    """One box on the canvas."""

    def __init__(self, scene: "WorkflowScene", node: Node) -> None:
        super().__init__()
        self.flow_scene = scene
        self.node = node
        self.spec = scene.workflow.spec(node)
        self.status = WAITING
        self.subtitle = ""
        self.highlight: set[str] = set()      # inputs that fit the wire being dragged
        self.dimmed = False
        self.locked = False
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setZValue(2)
        self.setPos(*node.position)
        self._moving = False

    # -- geometry ------------------------------------------------------------------
    @property
    def height(self) -> float:
        return node_height(len(self.spec.inputs), len(self.spec.outputs))

    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(-PORT_R - 2, -14, NODE_W + 2 * PORT_R + 4, self.height + 18)

    def rect(self) -> QRectF:
        return QRectF(0, 0, NODE_W, self.height)

    def port_point(self, side: str, name: str) -> QPointF:
        """Where a port's dot is, in item coordinates."""
        ports = self.spec.inputs if side == "in" else self.spec.outputs
        index = max(0, next((i for i, p in enumerate(ports) if p.name == name), 0))
        y = 72 + 20 * index if len(ports) > 1 else self.height / 2
        return QPointF(0 if side == "in" else NODE_W, y)

    def scene_port(self, side: str, name: str) -> QPointF:
        return self.mapToScene(self.port_point(side, name))

    def port_at(self, point: QPointF) -> tuple[str, Port] | None:
        """The (side, port) whose dot is under ``point`` (item coordinates)."""
        for side, ports in (("out", self.spec.outputs), ("in", self.spec.inputs)):
            for port in ports:
                centre = self.port_point(side, port.name)
                if math.hypot(point.x() - centre.x(), point.y() - centre.y()) <= PORT_R + 4:
                    return side, port
        return None

    # -- state ---------------------------------------------------------------------------
    def set_status(self, status: str, subtitle: str, tooltip: str = "") -> None:
        self.status, self.subtitle = status, subtitle
        self.setToolTip(tooltip)
        self.update()

    def set_highlight(self, inputs: set[str], dimmed: bool) -> None:
        self.highlight, self.dimmed = inputs, dimmed
        self.update()

    # -- Qt --------------------------------------------------------------------------------
    def itemChange(self, change, value):  # noqa: N802
        if change == QGraphicsItem.ItemPositionChange and not self.locked:
            snapped = QPointF(round(value.x() / GRID) * GRID, round(value.y() / GRID) * GRID)
            return snapped
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.node.position = (self.pos().x(), self.pos().y())
            self.flow_scene.wires_of(self.node.id, rebuild=True)
            self._moving = True
        return super().itemChange(change, value)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        hit = self.port_at(event.pos())
        if hit is not None and hit[0] == "out" and event.button() == Qt.LeftButton:
            self.flow_scene.begin_wire(self, hit[1], event.scenePos())
            event.accept()
            return
        self._moving = False
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        if self._moving:
            self._moving = False
            self.flow_scene.moved.emit(self.node.id)

    def hoverMoveEvent(self, event) -> None:  # noqa: N802
        hit = self.port_at(event.pos())
        self.setCursor(Qt.CrossCursor if hit and hit[0] == "out" else Qt.SizeAllCursor
                       if not self.locked else Qt.ArrowCursor)

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802
        self.unsetCursor()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        t = style.tokens()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        failed = self.status == FAILED
        if self.dimmed:
            painter.setOpacity(0.32)
        fill = QColor(style.qc(style.STATUS["critical"], 0.10)) if failed else QColor(t.surface)
        stroke = QColor(t.selection) if self.isSelected() else \
            QColor(style.STATUS["critical"]) if failed else QColor(t.border)
        pen = QPen(stroke, 2.0 if self.isSelected() else 1.5 if failed else 1.0)
        if self.locked:
            pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 9, 9)
        # Eyebrow: the group (and "Yours" for a custom box).
        painter.setPen(QColor(t.text_muted))
        painter.setFont(_font(8.5, True))
        eyebrow = ("Yours · " if self.spec.custom else "") + self.spec.group.upper()
        painter.drawText(QPointF(12, 16), eyebrow)
        # Status dot.
        colour = STATUS_COLOUR.get(self.status, "muted")
        dot = QColor({"good": style.STATUS["good"], "accent": t.accent, "critical": style.STATUS["critical"],
                      "warning": style.STATUS["warning"], "muted": t.text_muted}[colour])
        painter.setPen(QPen(dot, 1.5))
        painter.setBrush(dot if self.status not in (WAITING, IDLE) else Qt.NoBrush)
        painter.drawEllipse(QPointF(NODE_W - 14, 13), 4.5, 4.5)
        # Title and subtitle.
        painter.setPen(QColor(t.text))
        painter.setFont(_font(12.5, True))
        metrics = QFontMetricsF(painter.font())
        title = self.node.title or self.spec.name
        painter.drawText(QPointF(12, 34), metrics.elidedText(title, Qt.ElideRight, NODE_W - 36))
        painter.setPen(QColor(style.STATUS["critical"] if failed else t.text_muted))
        painter.setFont(_font(10.5))
        metrics = QFontMetricsF(painter.font())
        painter.drawText(QPointF(12, 52), metrics.elidedText(self.subtitle, Qt.ElideRight, NODE_W - 24))
        # Ports.
        for side, ports in (("in", self.spec.inputs), ("out", self.spec.outputs)):
            for port in ports:
                centre = self.port_point(side, port.name)
                lit = side == "in" and port.name in self.highlight
                painter.setPen(QPen(QColor(t.selection if lit else t.surface), 3 if lit else 2))
                painter.setBrush(QColor(port_colour(port)))
                painter.drawEllipse(centre, PORT_R + (2 if lit else 0), PORT_R + (2 if lit else 0))
                if len(ports) > 1:
                    painter.setPen(QColor(t.text_secondary))
                    painter.setFont(_font(9.5))
                    text = port.label or port.name
                    if side == "in":
                        painter.drawText(QPointF(centre.x() + 10, centre.y() + 3.5), text)
                    else:
                        width = QFontMetricsF(painter.font()).horizontalAdvance(text)
                        painter.drawText(QPointF(centre.x() - 10 - width, centre.y() + 3.5), text)
        painter.setOpacity(1.0)


class WireItem(QGraphicsPathItem):
    """A curve from an output dot to an input dot."""

    def __init__(self, scene: "WorkflowScene", edge: Edge | None, colour: str, faint: bool = False) -> None:
        super().__init__()
        self.flow_scene = scene
        self.edge = edge
        self.colour = colour
        self.faint = faint
        self.hovered = False
        self.setZValue(1)
        self.setAcceptHoverEvents(edge is not None)
        if edge is not None:
            self.setFlag(QGraphicsItem.ItemIsSelectable)
            self.setToolTip("Click to select, Delete to remove this connection")
        self.start = QPointF()
        self.end = QPointF()

    def set_points(self, start: QPointF, end: QPointF) -> None:
        self.start, self.end = start, end
        dx = max(40.0, abs(end.x() - start.x()) / 2)
        path = QPainterPath(start)
        path.cubicTo(QPointF(start.x() + dx, start.y()), QPointF(end.x() - dx, end.y()), end)
        self.setPath(path)

    def shape(self) -> QPainterPath:
        from PySide6.QtGui import QPainterPathStroker
        stroker = QPainterPathStroker()
        stroker.setWidth(12)
        return stroker.createStroke(self.path())

    def hoverEnterEvent(self, event) -> None:  # noqa: N802
        self.hovered = True
        self.update()

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802
        self.hovered = False
        self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        colour = QColor(style.tokens().selection) if self.isSelected() else QColor(self.colour)
        if self.faint and not self.isSelected():
            colour.setAlphaF(0.45)
        pen = QPen(colour, 4.0 if self.hovered or self.isSelected() else 2.2)
        if self.edge is None:
            pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self.path())


class WorkflowScene(QGraphicsScene):
    """The items of one workflow, kept in step with it."""

    #: A node was selected (its id), or nothing (None).
    selected = Signal(object)
    #: The workflow changed: the ids of the nodes to run from.
    edited = Signal(list)
    #: A node was moved (position only: nothing to re-run).
    moved = Signal(str)
    #: Double-click on empty canvas, at this scene point.
    add_here = Signal(QPointF)
    #: A context menu was asked for: ("node", id) / ("edge", edge) / ("canvas", point), at a screen position.
    menu = Signal(str, object, object)
    #: Something the user tried and the canvas refused, in plain words.
    refused = Signal(str)

    def __init__(self, workflow: Workflow) -> None:
        super().__init__()
        self.workflow = workflow
        self.boxes: dict[str, BoxItem] = {}
        self.wires: list[WireItem] = []
        self._drag: dict | None = None
        self.selectionChanged.connect(self._selection_changed)
        self.rebuild()

    # -- building ----------------------------------------------------------------------
    def rebuild(self) -> None:
        """Items from the workflow (positions, statuses are kept for known nodes)."""
        statuses = {node_id: (b.status, b.subtitle, b.toolTip()) for node_id, b in self.boxes.items()}
        selected = [b.node.id for b in self.boxes.values() if b.isSelected()]
        self.blockSignals(True)
        self.clear()
        self.boxes, self.wires = {}, []
        for node in self.workflow.nodes.values():
            item = BoxItem(self, node)
            if node.id in statuses:
                item.set_status(*statuses[node.id])
            self.addItem(item)
            self.boxes[node.id] = item
        for edge in self.workflow.edges:
            self._add_wire(edge)
        for node_id in selected:
            if node_id in self.boxes:
                self.boxes[node_id].setSelected(True)
        self.blockSignals(False)
        self.setSceneRect(self.itemsBoundingRect().adjusted(-400, -300, 400, 300))

    def _add_wire(self, edge: Edge) -> WireItem:
        source, target = self.boxes.get(edge.source), self.boxes.get(edge.target)
        port = self.workflow.spec(edge.source).output(edge.output)
        faint = edge.input in ("log", "ref", "true_net") and len(self.workflow.spec(edge.target).inputs) > 1
        wire = WireItem(self, edge, port_colour(port) if port else style.tokens().text_muted, faint)
        if source is not None and target is not None:
            wire.set_points(source.scene_port("out", edge.output), target.scene_port("in", edge.input))
        self.addItem(wire)
        self.wires.append(wire)
        return wire

    def wires_of(self, node_id: str, rebuild: bool = False) -> list[WireItem]:
        found = [w for w in self.wires if w.edge is not None and node_id in (w.edge.source, w.edge.target)]
        if rebuild:
            for wire in found:
                source, target = self.boxes.get(wire.edge.source), self.boxes.get(wire.edge.target)
                if source is not None and target is not None:
                    wire.set_points(source.scene_port("out", wire.edge.output),
                                    target.scene_port("in", wire.edge.input))
        return found

    def set_status(self, node_id: str, status: str, subtitle: str, tooltip: str = "") -> None:
        item = self.boxes.get(node_id)
        if item is not None:
            item.set_status(status, subtitle, tooltip)

    def add_node(self, box, position: QPointF, settings: dict | None = None) -> Node:
        node = self.workflow.add(box, settings, (round(position.x() / GRID) * GRID,
                                                 round(position.y() / GRID) * GRID))
        item = BoxItem(self, node)
        self.addItem(item)
        self.boxes[node.id] = item
        self.clearSelection()
        item.setSelected(True)
        self.setSceneRect(self.itemsBoundingRect().adjusted(-400, -300, 400, 300))
        self.edited.emit([node.id])
        return node

    def remove_node(self, node_id: str) -> None:
        after = [e.target for e in self.workflow.edges if e.source == node_id]
        self.workflow.remove(node_id)
        self.rebuild()
        self.edited.emit(after)

    def remove_edge(self, edge: Edge) -> None:
        self.workflow.disconnect(edge)
        self.rebuild()
        self.edited.emit([edge.target])

    def remove_selected(self) -> None:
        nodes = [item.node.id for item in self.selectedItems() if isinstance(item, BoxItem) and not item.locked]
        edges = [item.edge for item in self.selectedItems() if isinstance(item, WireItem) and item.edge]
        if not nodes and not edges:
            return
        after: list[str] = []
        for edge in edges:
            after.append(edge.target)
            self.workflow.disconnect(edge)
        for node_id in nodes:
            after.extend(e.target for e in self.workflow.edges if e.source == node_id)
            self.workflow.remove(node_id)
        self.rebuild()
        self.edited.emit([n for n in after if n in self.workflow.nodes])

    def duplicate(self, node_id: str) -> Node | None:
        node = self.workflow.nodes.get(node_id)
        if node is None:
            return None
        import copy
        copy_node = self.workflow.add(node.box, copy.deepcopy(node.settings),
                                      (node.position[0] + 30, node.position[1] + node_height(
                                          len(self.workflow.spec(node).inputs),
                                          len(self.workflow.spec(node).outputs)) + 20))
        for edge in [e for e in self.workflow.edges if e.target == node_id]:
            self.workflow.connect(edge.source, copy_node, edge.input, edge.output)
        self.rebuild()
        self.clearSelection()
        self.boxes[copy_node.id].setSelected(True)
        self.edited.emit([copy_node.id])
        return copy_node

    def disconnect_all(self, node_id: str) -> None:
        touching = [e for e in self.workflow.edges if node_id in (e.source, e.target)]
        if not touching:
            return
        for edge in touching:
            self.workflow.disconnect(edge)
        self.rebuild()
        self.edited.emit([node_id] + [e.target for e in touching if e.source == node_id])

    # -- selection ---------------------------------------------------------------------
    def _selection_changed(self) -> None:
        boxes = [item for item in self.selectedItems() if isinstance(item, BoxItem)]
        self.selected.emit(boxes[-1].node.id if boxes else None)

    def selected_node(self) -> str | None:
        boxes = [item for item in self.selectedItems() if isinstance(item, BoxItem)]
        return boxes[-1].node.id if boxes else None

    def select(self, node_id: str | None) -> None:
        self.clearSelection()
        if node_id in self.boxes:
            self.boxes[node_id].setSelected(True)

    # -- dragging a wire -----------------------------------------------------------------
    def begin_wire(self, item: BoxItem, port: Port, at: QPointF) -> None:
        wire = WireItem(self, None, port_colour(port))
        wire.setZValue(3)
        self.addItem(wire)
        self._drag = {"from": item, "port": port, "wire": wire}
        for other in self.boxes.values():
            fitting = {p.name for p in other.spec.inputs
                       if self.workflow.can_connect(item.node, other.node, p.name, port.name)[0]}
            other.set_highlight(fitting, dimmed=other is not item and not fitting)
        self._drag_to(at)

    def _drag_to(self, at: QPointF) -> None:
        drag = self._drag
        drag["wire"].set_points(drag["from"].scene_port("out", drag["port"].name), at)

    def _drop_target(self, at: QPointF) -> tuple[BoxItem, Port] | None:
        drag = self._drag
        best = None
        for other in self.boxes.values():
            local = other.mapFromScene(at)
            inside = other.rect().contains(local)
            for port in other.spec.inputs:
                if port.name not in other.highlight:
                    continue
                centre = other.port_point("in", port.name)
                distance = math.hypot(local.x() - centre.x(), local.y() - centre.y())
                if distance < 30 or (inside and len(other.spec.inputs) == 1):
                    if best is None or distance < best[2]:
                        best = (other, port, distance)
        return (best[0], best[1]) if best else None

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None:
            self._drag_to(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None:
            drag, self._drag = self._drag, None
            self.removeItem(drag["wire"])
            target = self._drop_target(event.scenePos())         # before the highlights go
            for other in self.boxes.values():
                other.set_highlight(set(), False)
            if target is not None:
                item, port = target
                ok, detail = self.workflow.can_connect(drag["from"].node, item.node, port.name, drag["port"].name)
                if ok:
                    self.workflow.connect(drag["from"].node, item.node, port.name, drag["port"].name)
                    self.rebuild()
                    self.edited.emit([item.node.id])
                else:
                    self.refused.emit(detail)
            else:
                # Dropped on a box that does not take it: say why, about the nearest input.
                for other in self.boxes.values():
                    local = other.mapFromScene(event.scenePos())
                    if other.rect().contains(local) and other is not drag["from"] and other.spec.inputs:
                        nearest = min(other.spec.inputs, key=lambda p: abs(other.port_point("in", p.name).y() - local.y()))
                        ok, detail = self.workflow.can_connect(drag["from"].node, other.node, nearest.name,
                                                               drag["port"].name)
                        if not ok:
                            self.refused.emit(detail)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self.itemAt(event.scenePos(), self.views()[0].transform() if self.views() else None) is None:
            self.add_here.emit(event.scenePos())
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        item = self.itemAt(event.scenePos(), self.views()[0].transform() if self.views() else None)
        while item is not None and not isinstance(item, (BoxItem, WireItem)):
            item = item.parentItem()
        if isinstance(item, BoxItem):
            self.select(item.node.id)
            self.menu.emit("node", item.node.id, event.screenPos())
        elif isinstance(item, WireItem) and item.edge is not None:
            self.menu.emit("edge", item.edge, event.screenPos())
        else:
            self.menu.emit("canvas", event.scenePos(), event.screenPos())
        event.accept()


class WorkflowView(GraphView):
    """The canvas view: panning, zooming and the floating zoom bar, from GraphView."""

    drawing_name = "The workflow"

    def __init__(self, scene: WorkflowScene, parent=None) -> None:
        super().__init__(scene, parent)
        self.setDragMode(self.DragMode.RubberBandDrag)

    def fit(self) -> None:
        self.auto_fit = True
        rect = self.graph.itemsBoundingRect()
        if rect.isEmpty():
            return
        self.fitInView(rect.adjusted(-30, -30, 30, 60), Qt.KeepAspectRatio)
        if self.transform().m11() > 1.25:
            self.resetTransform()
            self.scale(1.25, 1.25)
            self.centerOn(rect.center())
        self.zoom_changed.emit(self.transform().m11())

    def mousePressEvent(self, event) -> None:  # noqa: N802
        # Empty canvas: drag pans (as the net editor); on a box, the box moves.
        if event.button() == Qt.LeftButton and self.itemAt(event.position().toPoint()) is None:
            self.setDragMode(self.DragMode.ScrollHandDrag)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        self.setDragMode(self.DragMode.RubberBandDrag)
