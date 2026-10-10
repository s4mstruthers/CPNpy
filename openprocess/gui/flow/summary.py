"""The *Summary* of an analysis: the key figures above the picture.

The process-mining tools open a process on a strip of figures.  Here the
strip writes itself: every box whose result is a score, a table, a figure, a
log or a net contributes a tile, named after the box, in the order the boxes
run.  A click on a tile opens that box's Result on the canvas.  Nothing is
configured, so the Summary can never drift from the workflow, and a box
author gets a tile for free by returning a :class:`~openprocess.flow.types.Scores`.

Under the tiles: the process map of the first event log in the analysis
(a directly-follows graph), with a *Detail* slider that drops the rarer
activities and paths, and a legend.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QLabel, QSlider, QSizePolicy, QVBoxLayout, QWidget

from ...flow.types import EventLog, Figure, PetriNet, Scores, Table, Text
from ..studio import style
from ..studio.graph_builders import dfg_specs
from ..studio.graph_view import GraphView
from ..studio.widgets import Card, ElidedLabel, Legend, LegendSwatch, flow, hbox, label

#: How many tiles at most (an analysis with a sweep can have hundreds of results).
TILE_LIMIT = 24


def _number(value) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.2f}" if abs(value) < 1000 else f"{value:,.0f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def tile_parts(value) -> tuple[str, str] | None:
    """(the big figure, the line under it) for a result, or None for a result
    that has no figure to show (a trace, a prediction model, …)."""
    if isinstance(value, Scores):
        items = [(k, v) for k, v in value.metrics.items() if not isinstance(v, (dict, list))]
        if not items:
            return None
        first, rest = items[0], items[1:4]
        return (f"{_number(first[1])} {first[0]}".strip(),
                " · ".join(f"{k} {_number(v)}" for k, v in rest) or value.model)
    if isinstance(value, Table):
        return f"{len(value.rows):,} × {len(value.columns)}", f"rows × columns · {value.name}"
    if isinstance(value, Figure):
        return "figure", value.caption or value.name
    if isinstance(value, EventLog):
        return f"{len(value):,} cases", f"{value.event_count:,} events"
    if isinstance(value, PetriNet):
        return f"{len(value.places)} · {len(value.transitions)}", "places · transitions"
    if isinstance(value, Text):
        first = str(value).strip().splitlines()[0] if str(value).strip() else ""
        return first[:40], value.name
    return None


class SummaryTile(QFrame):
    """One box's figure: caption (the box), the figure, a line under it.  Clickable."""

    clicked = Signal(str)

    def __init__(self, node_id: str, caption: str, value: str, sub: str) -> None:
        super().__init__()
        self.node_id = node_id
        self.setObjectName("card")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(170)
        self.setMaximumWidth(260)
        self.setToolTip(f"{caption}: open its Result on the canvas")
        column = QVBoxLayout(self)
        column.setContentsMargins(14, 10, 14, 12)
        column.setSpacing(2)
        column.addWidget(ElidedLabel(caption, "muted"))
        big = ElidedLabel(value)
        big.setObjectName("summaryValue")
        column.addWidget(big)
        column.addWidget(ElidedLabel(sub, "muted"))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.node_id)
            event.accept()
            return
        super().mousePressEvent(event)


class SummaryWidget(QWidget):
    """The Summary view of a workflow page; :meth:`refresh` rebuilds it from the run."""

    tile_clicked = Signal(str)

    def __init__(self, page, parent=None) -> None:
        super().__init__(parent)
        self.page = page
        self._dfg_cache: tuple[int, object] | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.tiles_host = QWidget()
        self.tiles_host.setObjectName("plain")
        self.tiles_layout = QVBoxLayout(self.tiles_host)
        self.tiles_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tiles_host)
        self.map_card = Card("Process map", "")
        self.map_mode = ElidedLabel("", "muted")
        self.detail = QSlider(Qt.Horizontal)
        self.detail.setRange(0, 100)
        self.detail.setValue(100)
        self.detail.setMinimumWidth(90)
        self.detail.setMaximumWidth(220)
        self.detail.setToolTip("Less detail drops the rarer activities and paths")
        self.detail_label = label("100%", "muted")
        self.map_view = GraphView()
        self.map_view.setMinimumHeight(260)
        self.map_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.legend = Legend()
        self.map_card.add(hbox(label("Detail"), self.detail, self.detail_label, 16, self.map_mode, None))
        self.map_card.add(self.map_view, 1)
        self.map_card.add(self.legend)
        self.map_card.setVisible(False)
        layout.addWidget(self.map_card, 1)
        layout.addStretch(0)
        self.detail.valueChanged.connect(lambda _v: self._redraw_map())
        self._log = None
        self.tiles: list[SummaryTile] = []

    # -- building ----------------------------------------------------------------------------
    def refresh(self) -> None:
        """Rebuild the tiles and the map from the page's current run."""
        page = self.page
        while self.tiles_layout.count():
            item = self.tiles_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        self.tiles = []
        run = page.run
        tiles = []
        first_log = None
        for node in page.workflow.order():
            result = run.result(node) if run is not None else None
            if result is None or result.status != "done":
                continue
            value = result.value
            if first_log is None and isinstance(value, EventLog):
                first_log = (node, value)
            parts = tile_parts(value)
            if parts is None:
                continue
            tile = SummaryTile(node.id, page.workflow.title(node.id), *parts)
            tile.clicked.connect(self.tile_clicked.emit)
            tiles.append(tile)
            if len(tiles) >= TILE_LIMIT:
                break
        self.tiles = tiles
        if tiles:
            self.tiles_layout.addWidget(flow(*tiles, spacing=10))
        hint = QLabel("Add a box with a score, a table, a figure, a log or a net and its figure appears "
                      "here, in the order the boxes run. Click a tile to open the box."
                      if not tiles else "Click a tile to open that box's Result on the canvas.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        self.tiles_layout.addWidget(hint)
        self._log = None if first_log is None else first_log[1]
        if first_log is None:
            self.map_card.setVisible(False)
            return
        node, _log = first_log
        self.map_card.setVisible(True)
        self.map_card.title_label.setText(f"Process map · from {page.workflow.title(node.id)}")
        self._redraw_map(fit=True)

    def _dfg(self):
        from ...mining.dfg import discover_dfg
        log = self._log
        if log is None:
            return None
        if self._dfg_cache is None or self._dfg_cache[0] != id(log):
            self._dfg_cache = (id(log), discover_dfg(log))
        return self._dfg_cache[1]

    def _redraw_map(self, fit: bool = False) -> None:
        dfg = self._dfg()
        if dfg is None:
            return
        detail = self.detail.value() / 100
        simplified = dfg.simplified(max(0.25, detail), detail)
        self.detail_label.setText(f"{self.detail.value()}%")
        nodes, edges = dfg_specs(simplified, "frequency")
        self.map_view.graph.populate(nodes, edges, layer_gap=64)
        self.map_mode.setText(f"{len(simplified.activities)} of {len(dfg.activities)} activities · "
                              f"{len(simplified.all_edges())} of {len(dfg.all_edges())} paths")
        self.legend.set_items([
            (LegendSwatch("ramp"), "activity: darker = more events (count inside)"),
            (LegendSwatch("widths"), "thicker = path taken more often (label = times)"),
            (LegendSwatch("line", style.tokens().text_muted), "grey = rare path"),
            (LegendSwatch("dashed"), "case start / end"),
        ])
        if fit:
            QTimer.singleShot(0, self.map_view.fit)
        else:
            self.map_view.fit()


__all__ = ["SummaryWidget", "SummaryTile", "tile_parts"]
