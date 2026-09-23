"""The net canvas: the drawing surface and its editing tools.

Two classes:

:class:`NetScene`
    Owns the mapping from model objects to graphics items and rebuilds the
    scene when the page changes.  It also implements the editing tools, because
    a tool's behaviour is defined by where you click in the *scene*.

:class:`NetView`
    A thin :class:`QGraphicsView` adding zooming and panning.  Kept separate so
    that the interaction logic in the scene is testable without a viewport.

Editing model
-------------
The canvas edits the model objects **in place**.  There is no separate
"document" layer: dragging a place writes its new coordinates straight onto
``place.graphics``.  Signals tell the main window what changed so it can mark
the file dirty and refresh the panels.

Tools
-----
``select``
    Default.  Click to select, drag to move.
``place`` / ``transition``
    Click on empty canvas to create one there.
``arc``
    Click a place then a transition (or the reverse) to connect them.  The
    direction is inferred from the order of the two clicks, which is how CPN
    Tools behaves and saves having two separate arc tools.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QTransform
from PySide6.QtWidgets import (
    QGraphicsItem, QGraphicsScene, QGraphicsSceneMouseEvent, QGraphicsView, QMenu,
)

from ..model.net import Arc, CPNet, Page, Place, Transition
from . import theme
from .items import (
    ArcItem, PlaceItem, TransitionItem, to_model, to_scene,
)

#: Grid spacing in scene units: the background dots, and the step nodes and
#: bends land on when "Snap to grid" is on.
GRID_STEP = 28
#: Perpendicular separation between two arcs joining the same pair of nodes.
PARALLEL_ARC_SPACING = 14.0


class NetScene(QGraphicsScene):
    """Draws one page of a model and handles clicks on it."""

    #: Emitted with the selected model object (or ``None``) when selection changes.
    selection_changed = Signal(object)
    #: Emitted whenever the model was modified by a canvas interaction.
    model_changed = Signal()
    #: Emitted when the user clicks a transition while the simulator is active.
    transition_activated = Signal(object)
    #: Emitted just *before* the canvas changes the model (for undo).
    about_to_change = Signal()
    #: A drag may be starting (for undo: the state before a possible move).
    drag_started = Signal()
    #: Elements were dragged to new positions.
    moved = Signal()

    def __init__(self, net: CPNet) -> None:
        super().__init__()
        self.net = net
        self.page: Page | None = net.pages[0] if net.pages else None
        self.tool = "select"
        #: When False, clicking an enabled transition only selects it (edit
        #: mode); when True it fires it (the token game).
        self.fire_on_click = True
        #: Token values next to the count bubbles: None = as the model says
        #: (CPN Tools' per-place "hide marking"), True = all, False = none.
        self.show_token_values: bool | None = None
        #: While the arc tool is mid-draw, the element clicked first.
        self._pending_arc_source: Place | Transition | None = None
        #: Edit mode: labels can be dragged, a selected arc shows handles on
        #: its bends, and the right-click menu offers layout tools.
        self.editable = True
        #: Grid step nodes and bends snap to while dragged (0 = free).
        self.snap_step = 0
        #: Adds entries (tidy layout ...) to the right-click menu; set by the page.
        self.extend_menu: Callable[[QMenu], None] | None = None

        self.place_items: dict[str, PlaceItem] = {}
        self.transition_items: dict[str, TransitionItem] = {}
        self.arc_items: dict[str, ArcItem] = {}

        self.setBackgroundBrush(theme.palette().canvas)
        self.selectionChanged.connect(self._on_selection_changed)

    # =======================================================================
    # Building
    # =======================================================================
    def show_page(self, page: Page | None) -> None:
        """Replace the scene contents with ``page``."""
        self.page = page
        self.rebuild()

    def rebuild(self) -> None:
        """Recreate every item from the model.

        Rebuilding wholesale rather than diffing keeps the code honest: there
        is exactly one way the canvas can get out of step with the model, and
        it is fixed by calling this.  Nets are small enough that the cost is
        irrelevant.
        """
        self.clear()
        self.place_items.clear()
        self.transition_items.clear()
        self.arc_items.clear()

        if self.page is None:
            return

        for place in self.page.places:
            item = PlaceItem(place)
            self.addItem(item)
            self.place_items[place.id] = item

        for transition in self.page.transitions:
            item = TransitionItem(transition)
            self.addItem(item)
            self.transition_items[transition.id] = item

        # Arcs joining the same place and transition must be separated, or a
        # consume-and-return pair would be drawn exactly on top of itself.
        # Group them first, then give each member of a group its own bow.
        groups: dict[tuple[str, str], list[Arc]] = {}
        for arc in self.page.arcs:
            groups.setdefault((arc.place_id, arc.transition_id), []).append(arc)

        bows: dict[str, float] = {}
        for members in groups.values():
            count = len(members)
            for index, arc in enumerate(members):
                # Symmetric offsets about zero: a lone arc gets 0 and stays
                # straight, a pair gets -s/+s, a triple -s/0/+s, and so on.
                bows[arc.id] = (index - (count - 1) / 2) * PARALLEL_ARC_SPACING

        for arc in self.page.arcs:
            place_item = self.place_items.get(arc.place_id)
            transition_item = self.transition_items.get(arc.transition_id)
            if place_item is None or transition_item is None:
                # A dangling arc (endpoint deleted); skip rather than crash.
                continue
            item = ArcItem(arc, place_item, transition_item, bow=bows.get(arc.id, 0.0))
            self.addItem(item)
            self.arc_items[arc.id] = item

        self._apply_error_highlighting()
        # The margin matches zoom_to_fit's, so a fitted page shows no scroll bars.
        self.setSceneRect(self.itemsBoundingRect().adjusted(-40, -40, 40, 40))

    def refresh_labels(self) -> None:
        """Re-read inscriptions from the model without rebuilding the scene."""
        for item in self.place_items.values():
            item.refresh()
        for item in self.transition_items.values():
            item.refresh()
        for item in self.arc_items.values():
            item.reroute()
        self._apply_error_highlighting()

    def _apply_error_highlighting(self) -> None:
        """Outline in red every element whose inscription failed to compile.

        Doing this for all three element kinds -- not just arcs -- means a bad
        initial marking or a bad guard is visible on the canvas, not only in
        the problems list.
        """
        failing = {issue.element_id for issue in self.net.errors}
        for identifier, item in self.arc_items.items():
            item.set_error(identifier in failing)
        for identifier, place_item in self.place_items.items():
            place_item.set_error(identifier in failing)
        for identifier, transition_item in self.transition_items.items():
            transition_item.set_error(identifier in failing)

    # =======================================================================
    # Simulation feedback
    # =======================================================================
    def update_enabling(self, counts: dict[str, int]) -> None:
        """Colour transitions by their number of enabled binding elements."""
        for transition_id, item in self.transition_items.items():
            item.set_enabled_count(counts.get(transition_id, 0))

    def update_markings(self, describe: Callable[[str], tuple[int, str]]) -> None:
        """Show the simulator's current token contents on each place.

        ``describe`` returns ``(token_count, multiset_text)``; the count drives
        the pill and the text the annotation beside it.
        """
        for place_id, item in self.place_items.items():
            count, text = describe(place_id)
            item.set_marking(count, text, self.show_token_values)

    # =======================================================================
    # Interaction
    # =======================================================================
    def _on_selection_changed(self) -> None:
        items = self.selectedItems()
        if not items:
            self.selection_changed.emit(None)
            return
        item = items[0]
        if isinstance(item, PlaceItem):
            self.selection_changed.emit(item.place)
        elif isinstance(item, TransitionItem):
            self.selection_changed.emit(item.transition)
        elif isinstance(item, ArcItem):
            self.selection_changed.emit(item.arc)
        else:
            self.selection_changed.emit(None)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        if self.page is None or event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return

        position = event.scenePos()
        item = self.itemAt(position, QTransform())
        if self.tool == "select":
            # Remember where everything is, to tell on release whether this
            # press turned into a move.
            self._positions_before = self._layout_state()
            self.drag_started.emit()
            self._start_following()

        if self.tool == "place":
            self._create_place(position)
            return
        if self.tool == "transition":
            self._create_transition(position)
            return
        if self.tool == "arc":
            self._handle_arc_click(item)
            return

        # Select tool: a plain click on an enabled transition asks the main
        # window to fire it.  This is the "token game" interaction.
        owner = self._owner_of(item)
        if isinstance(owner, Transition) and event.modifiers() == Qt.NoModifier \
                and self.fire_on_click:
            transition_item = self.transition_items.get(owner.id)
            if transition_item is not None and transition_item.enabled_count:
                self.transition_activated.emit(owner)
        super().mousePressEvent(event)

    def _layout_state(self) -> tuple:
        """Everything a drag can change: node positions, bends, label spots."""
        items = list(self.place_items.items()) + list(self.transition_items.items())
        nodes = {key: (item.pos().x(), item.pos().y(),
                       tuple(sorted(item.graphics().label_offsets.items())))
                 for key, item in items}
        arcs = {key: (tuple(item.arc.bendpoints),
                      item.arc.graphics.label_offsets.get("annot"))
                for key, item in self.arc_items.items()}
        return nodes, arcs

    def _start_following(self) -> None:
        """Bends follow the nodes they connect while those are dragged."""
        for item in self.arc_items.values():
            item.drag_origin = (item.transition_item.pos(), item.place_item.pos(),
                                [to_scene(x, y) for x, y in item.arc.bendpoints])

    def _stop_following(self) -> None:
        for item in self.arc_items.values():
            item.drag_origin = None

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        self._stop_following()
        before = getattr(self, "_positions_before", None)
        self._positions_before = None
        if before is not None and before != self._layout_state():
            self.moved.emit()

    @staticmethod
    def _owner_of(item: QGraphicsItem | None):
        """Walk up to the top-level item and return the model object it draws."""
        while item is not None and not isinstance(item, (PlaceItem, TransitionItem, ArcItem)):
            item = item.parentItem()
        if isinstance(item, PlaceItem):
            return item.place
        if isinstance(item, TransitionItem):
            return item.transition
        if isinstance(item, ArcItem):
            return item.arc
        return None

    # -- creation ------------------------------------------------------------
    def _create_place(self, position: QPointF) -> None:
        assert self.page is not None
        self.about_to_change.emit()
        x, y = to_model(position)
        place = Place(name=self._unique_name("P", [p.name for p in self.page.places]),
                      colour_set_name="UNIT")
        place.graphics.x, place.graphics.y = x, y
        self.page.places.append(place)
        self.rebuild()
        self.model_changed.emit()

    def _create_transition(self, position: QPointF) -> None:
        assert self.page is not None
        self.about_to_change.emit()
        x, y = to_model(position)
        transition = Transition(
            name=self._unique_name("T", [t.name for t in self.page.transitions])
        )
        transition.graphics.x, transition.graphics.y = x, y
        self.page.transitions.append(transition)
        self.rebuild()
        self.model_changed.emit()

    def _handle_arc_click(self, item: QGraphicsItem | None) -> None:
        """Two clicks make an arc: first the source, then the target."""
        owner = self._owner_of(item)
        if not isinstance(owner, (Place, Transition)):
            self._pending_arc_source = None
            return

        if self._pending_arc_source is None:
            self._pending_arc_source = owner
            return

        source, target = self._pending_arc_source, owner
        self._pending_arc_source = None

        # An arc must join a place and a transition, in either order.
        if isinstance(source, Place) and isinstance(target, Transition):
            place, transition, orientation = source, target, "PtoT"
        elif isinstance(source, Transition) and isinstance(target, Place):
            place, transition, orientation = target, source, "TtoP"
        else:
            return

        assert self.page is not None
        self.about_to_change.emit()
        default = "1`()" if place.colour_set_name == "UNIT" else ""
        self.page.arcs.append(
            Arc(place_id=place.id, transition_id=transition.id,
                orientation=orientation, expression_text=default)
        )
        self.rebuild()
        self.model_changed.emit()

    @staticmethod
    def _unique_name(prefix: str, existing: list[str]) -> str:
        index = 1
        while f"{prefix}{index}" in existing:
            index += 1
        return f"{prefix}{index}"

    # -- deletion ------------------------------------------------------------
    def delete_selected(self) -> None:
        """Remove selected elements, plus any arcs left dangling."""
        if self.page is None:
            return
        if self.selectedItems():
            self.about_to_change.emit()
        removed = False
        for item in list(self.selectedItems()):
            owner = self._owner_of(item)
            if isinstance(owner, Place):
                self.page.places.remove(owner)
                self.page.arcs = [a for a in self.page.arcs if a.place_id != owner.id]
                removed = True
            elif isinstance(owner, Transition):
                self.page.transitions.remove(owner)
                self.page.arcs = [a for a in self.page.arcs if a.transition_id != owner.id]
                removed = True
            elif isinstance(owner, Arc) and owner in self.page.arcs:
                self.page.arcs.remove(owner)
                removed = True
        if removed:
            self.rebuild()
            self.model_changed.emit()

    # -- arranging by hand ---------------------------------------------------
    def set_editable(self, editable: bool) -> None:
        self.editable = editable
        for item in self.arc_items.values():
            item.sync_handles()

    def selected_nodes(self) -> list[PlaceItem | TransitionItem]:
        return [i for i in self.selectedItems() if isinstance(i, (PlaceItem, TransitionItem))]

    def selected_arcs(self) -> list[ArcItem]:
        return [i for i in self.selectedItems() if isinstance(i, ArcItem)]

    def _layout_edit(self, change: Callable[[], None]) -> None:
        """Run a layout change as one undoable step (no recompilation needed)."""
        self.about_to_change.emit()
        self._start_following()
        try:
            change()
        finally:
            self._stop_following()
        self.setSceneRect(self.itemsBoundingRect().adjusted(-40, -40, 40, 40))
        self.moved.emit()

    def straighten_arcs(self, items: list[ArcItem] | None = None) -> None:
        """Remove the bends of ``items`` (default: every arc on the page)."""
        targets = list(self.arc_items.values()) if items is None else items
        targets = [item for item in targets if item.arc.bendpoints]
        if targets:
            self._layout_edit(lambda: [item.straighten() for item in targets])

    def set_curved(self, curved: bool, items: list[ArcItem] | None = None) -> None:
        """Draw bent arcs as smooth curves or as straight segments with corners."""
        targets = list(self.arc_items.values()) if items is None else items

        def change() -> None:
            for item in targets:
                item.arc.graphics.smooth = curved
                item.reroute()
        if targets:
            self._layout_edit(change)

    def reset_labels(self, nodes: list | None = None, arcs: list[ArcItem] | None = None) -> None:
        """Put inscriptions back at their default spots."""
        nodes = self.selected_nodes() if nodes is None else nodes
        arcs = self.selected_arcs() if arcs is None else arcs

        def change() -> None:
            for node in nodes:
                offsets = node.graphics().label_offsets
                for key in ("type", "initmark", "cond", "time"):
                    offsets.pop(key, None)
                node.refresh()
            for arc in arcs:
                arc.reset_label()
        self._layout_edit(change)

    def align(self, how: str, nodes: list | None = None) -> None:
        """Line up the selected nodes.

        ``row``: same height (the average); ``column``: same x;
        ``spread-x`` / ``spread-y``: equal gaps between the outermost two.
        """
        nodes = self.selected_nodes() if nodes is None else nodes
        if len(nodes) < 2:
            return

        def change() -> None:
            if how in ("row", "column"):
                values = [n.pos().y() if how == "row" else n.pos().x() for n in nodes]
                target = sum(values) / len(values)
                if self.snap_step:
                    target = round(target / self.snap_step) * self.snap_step
                for node in nodes:
                    if how == "row":
                        node.setPos(node.pos().x(), target)
                    else:
                        node.setPos(target, node.pos().y())
            else:
                horizontal = how == "spread-x"
                ordered = sorted(nodes, key=lambda n: n.pos().x() if horizontal else n.pos().y())
                first = ordered[0].pos().x() if horizontal else ordered[0].pos().y()
                last = ordered[-1].pos().x() if horizontal else ordered[-1].pos().y()
                gap = (last - first) / (len(ordered) - 1)
                for index, node in enumerate(ordered):
                    value = first + gap * index
                    if horizontal:
                        node.setPos(value, node.pos().y())
                    else:
                        node.setPos(node.pos().x(), value)
        self._layout_edit(change)

    def context_menu(self, position: QPointF) -> QMenu:
        """The right-click menu for ``position`` (built separately so it is testable)."""
        menu = QMenu()
        owner_item = self.itemAt(position, QTransform())
        while owner_item is not None and not isinstance(
                owner_item, (PlaceItem, TransitionItem, ArcItem)):
            owner_item = owner_item.parentItem()
        if owner_item is not None and not owner_item.isSelected():
            self.clearSelection()
            owner_item.setSelected(True)

        arcs, nodes = self.selected_arcs(), self.selected_nodes()
        if isinstance(owner_item, ArcItem):
            menu.addSection("Arc")
            menu.addAction("Add a bend here", lambda: self._layout_edit(
                lambda: owner_item.add_bend_near(position)))
            straight = menu.addAction("Straighten", lambda: self.straighten_arcs(arcs))
            straight.setEnabled(any(a.arc.bendpoints for a in arcs))
            curved = menu.addAction("Curved through the bends")
            curved.setCheckable(True)
            curved.setChecked(owner_item.arc.graphics.smooth)
            curved.toggled.connect(lambda on: self.set_curved(on, arcs))
            menu.addAction("Inscription back to its default spot",
                           lambda: self.reset_labels([], arcs))
        if nodes:
            menu.addSection("Selection" if len(nodes) > 1 else "Node")
            if len(nodes) > 1:
                menu.addAction("Align in a row", lambda: self.align("row"))
                menu.addAction("Align in a column", lambda: self.align("column"))
                if len(nodes) > 2:
                    menu.addAction("Space evenly across", lambda: self.align("spread-x"))
                    menu.addAction("Space evenly down", lambda: self.align("spread-y"))
            ids = {n.model_id for n in nodes}
            touching = [a for a in self.arc_items.values()
                        if a.arc.place_id in ids or a.arc.transition_id in ids]
            straight = menu.addAction("Straighten connected arcs",
                                      lambda: self.straighten_arcs(touching))
            straight.setEnabled(any(a.arc.bendpoints for a in touching))
            menu.addAction("Labels back to their default spots",
                           lambda: self.reset_labels(nodes, []))
        menu.addSection("Page")
        menu.addAction("Straighten all arcs", lambda: self.straighten_arcs(None))
        snap = menu.addAction("Snap to grid")
        snap.setCheckable(True)
        snap.setChecked(bool(self.snap_step))
        snap.toggled.connect(lambda on: setattr(self, "snap_step", GRID_STEP if on else 0))
        if self.extend_menu is not None:
            self.extend_menu(menu)
        return menu

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        if self.page is None or not self.editable:
            super().contextMenuEvent(event)
            return
        menu = self.context_menu(event.scenePos())
        menu.exec(event.screenPos())
        event.accept()

    # -- background ----------------------------------------------------------
    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        """A faint dot grid, purely as a visual aid for alignment.

        Drawn with a cosmetic pen so the dots stay one pixel across at every
        zoom level -- a scaled grid quickly turns into either invisible specks
        or distracting blobs.
        """
        painter.fillRect(rect, theme.palette().canvas)

        pen = QPen(theme.palette().grid, 1.4)
        pen.setCosmetic(True)
        painter.setPen(pen)

        left = int(rect.left()) - (int(rect.left()) % GRID_STEP)
        top = int(rect.top()) - (int(rect.top()) % GRID_STEP)
        points = []
        y = top
        while y < rect.bottom():
            x = left
            while x < rect.right():
                points.append(QPointF(x, y))
                x += GRID_STEP
            y += GRID_STEP
        painter.drawPoints(points)


class NetView(QGraphicsView):
    """A viewport with zooming (floating − % + Fit bar, ⌘-scroll, pinch)
    and panning (scroll, or drag with the middle button)."""

    zoom_changed = Signal(float)
    MIN_ZOOM, MAX_ZOOM = 0.1, 5.0
    MIN_SCALE, MAX_SCALE = MIN_ZOOM, MAX_ZOOM      # older names
    STEP = 1.25
    #: Zooming to fit will not magnify beyond this, so a two-node model does
    #: not fill the window with enormous circles.
    FIT_MAX_SCALE = 1.4

    def __init__(self, scene: NetScene, zoom_controls: bool = True) -> None:
        super().__init__(scene)
        self.setRenderHints(
            QPainter.Antialiasing
            | QPainter.TextAntialiasing
            | QPainter.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setFrameShape(QGraphicsView.NoFrame)
        # Repaint the whole viewport on change: with antialiased curves and
        # text, partial updates leave smearing artefacts at the edges.
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        # Zoom towards the pointer rather than the view centre.
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setFocusPolicy(Qt.StrongFocus)
        #: While True, resizing the view re-fits the page; any manual zoom
        #: turns it off so the user's zoom level is respected.
        self.auto_fit = True
        from .studio.graph_view import ZoomControls
        self.zoom_controls = ZoomControls(self) if zoom_controls else None
        self._place_controls()

    # -- zoom -----------------------------------------------------------------
    @property
    def _scale(self) -> float:
        return self.transform().m11()

    def zoom(self) -> float:
        return self.transform().m11()

    def zoom_by(self, factor: float, around_centre: bool = False) -> None:
        self.auto_fit = False
        current = self.transform().m11()
        target = min(max(current * factor, self.MIN_ZOOM), self.MAX_ZOOM)
        if around_centre:
            anchor = self.transformationAnchor()
            self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
            self.scale(target / current, target / current)
            self.setTransformationAnchor(anchor)
        else:
            self.scale(target / current, target / current)
        self.zoom_changed.emit(target)

    def zoom_in(self) -> None:
        self.zoom_by(self.STEP, around_centre=True)

    def zoom_out(self) -> None:
        self.zoom_by(1 / self.STEP, around_centre=True)

    def actual_size(self) -> None:
        self.zoom_by(1 / self.transform().m11(), around_centre=True)

    def zoom_to_fit(self) -> None:
        """Frame the whole page, within sensible magnification limits."""
        self.auto_fit = True
        items_rect = self.scene().itemsBoundingRect()
        if items_rect.isEmpty():
            return
        self.fitInView(items_rect.adjusted(-40, -40, 40, 40), Qt.KeepAspectRatio)
        scale = self.transform().m11()
        if scale > self.FIT_MAX_SCALE:
            # fitInView has already applied the transform, so scale back down.
            self.scale(self.FIT_MAX_SCALE / scale, self.FIT_MAX_SCALE / scale)
        self.zoom_changed.emit(self.transform().m11())

    fit = zoom_to_fit

    def reset_zoom(self) -> None:
        self.auto_fit = False
        self.resetTransform()
        self.zoom_changed.emit(1.0)

    def wheelEvent(self, event) -> None:  # noqa: N802
        """⌘/Ctrl + scroll zooms; plain scrolling pans, as in every Mac app."""
        if event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier):
            self.zoom_by(1.0015 ** event.angleDelta().y())
            event.accept()
            return
        super().wheelEvent(event)

    def event(self, event) -> bool:
        # macOS trackpad pinch arrives as a native zoom gesture.
        if event.type() == event.Type.NativeGesture:
            try:
                if event.gestureType() == Qt.ZoomNativeGesture:
                    self.zoom_by(1 + event.value())
                    return True
            except AttributeError:  # pragma: no cover
                pass
        return super().event(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if event.modifiers() == Qt.NoModifier and key in (Qt.Key_Plus, Qt.Key_Equal):
            self.zoom_in()
        elif event.modifiers() == Qt.NoModifier and key == Qt.Key_Minus:
            self.zoom_out()
        elif event.modifiers() == Qt.NoModifier and key == Qt.Key_0:
            self.zoom_to_fit()
        else:
            super().keyPressEvent(event)

    # -- floating zoom bar --------------------------------------------------------
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place_controls()
        if self.auto_fit:
            self.zoom_to_fit()

    def _place_controls(self) -> None:
        if self.zoom_controls is None:
            return
        self.zoom_controls.adjustSize()
        size = self.zoom_controls.sizeHint()
        area = self.viewport().geometry()
        self.zoom_controls.setVisible(area.width() >= size.width() + 60 and area.height() >= 90)
        self.zoom_controls.move(area.right() - size.width() - 9, area.bottom() - size.height() - 9)
        self.zoom_controls.raise_()

    # -- panning ----------------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MiddleButton:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        if self.dragMode() == QGraphicsView.ScrollHandDrag and self.scene() is not None \
                and getattr(self.scene(), "tool", "select") == "select":
            self.setDragMode(QGraphicsView.RubberBandDrag)
