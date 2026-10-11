"""Step through an algorithm: the How tab, one moment at a time.

The How tab lists everything a box reported: notes, the derivation's steps,
intermediate values.  For learning, seeing it all at once is too much and
too little: too much text, and nothing moves.  :class:`StepThrough` plays
the same report as a sequence of *moments*, one step row or one note or one
shown value each, with ◀ ▶ and a Play button, and keeps the box's result (a
net or a process tree) drawn above, lighting up the places, transitions or
activities the current step names and dimming the rest.  So the eight steps
of the α-algorithm become eight pictures: all activities, the start ones, the
end ones, the candidate pairs, the maximal pairs, the places…

Nothing is computed here.  The moments are the box's own report, in order.
"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from ...flow.explain import Explanation
from ...flow.types import PetriNet, ProcessTree
from .. import theme
from ..studio import style
from ..studio.graph_builders import petri_net_specs
from ..studio.graph_view import GraphView, NodeSpec
from ..studio.widgets import button, hbox, label

#: How long Play rests on each moment.
PLAY_MS = 1400


def moments_of(explanation: Explanation) -> list[tuple]:
    """The report as a flat sequence: ("note", text), ("step", title, content), ("show", label, value)."""
    out: list[tuple] = []
    for entry in explanation.entries:
        if entry[0] == "note":
            out.append(("note", entry[1]))
        elif entry[0] == "steps":
            for title, content in entry[1]:
                out.append(("step", title, content))
        elif entry[0] == "show":
            out.append(("show", entry[1], entry[2]))
    return out


_PLACE = re.compile(r"[io]_L|p\(\{[^()]*\},\{[^()]*\}\)")
_WORD = re.compile(r"[^\W\d_][\w\-']*", re.UNICODE)


def named_in(moment: tuple) -> set[str]:
    """The element names a moment mentions: words (activities, transitions)
    and α-style place names such as ``p({a},{b})``."""
    if moment[0] == "step":
        text = f"{moment[1]} {moment[2]}"
    elif moment[0] == "note":
        text = moment[1]
    else:
        text = str(moment[1])
    names = set(_WORD.findall(text))
    names |= set(_PLACE.findall(text.replace(" ", "")))
    return names


class StepThrough(QWidget):
    """The How tab as a player; :attr:`changed` carries the current moment's index."""

    changed = Signal(int)

    def __init__(self, explanation: Explanation, value=None, page=None, parent=None) -> None:
        super().__init__(parent)
        self.moments = moments_of(explanation)
        self.value = value
        self.page = page
        self.index = 0
        self.setFocusPolicy(Qt.StrongFocus)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        # The controls.
        self.back_button = button("◀", self.previous, tooltip="The step before (←)")
        self.next_button = button("▶", self.next, tooltip="The next step (→)")
        self.play_button = button("Play", self.toggle_play, tooltip="One step every second and a half")
        self.counter = label("", "muted")
        self.title = QLabel("")
        self.title.setObjectName("cardTitle")
        self.title.setWordWrap(True)
        layout.addLayout(hbox(self.back_button, self.next_button, self.play_button, 10, self.counter, None))
        layout.addWidget(self.title)
        # The result, drawn once; its nodes light up per step.
        self.view: GraphView | None = None
        self._base: dict[str, NodeSpec] = {}
        self._names: dict[str, str] = {}             # node id -> the name a step would use
        if isinstance(value, PetriNet):
            nodes, edges = petri_net_specs(value, show_place_names=len(value.places) <= 40)
            positions = None
            if all(p.position for p in value.places.values()) and all(t.position for t in value.transitions.values()):
                positions = {p.id: p.position for p in value.places.values()}
                positions |= {t.id: t.position for t in value.transitions.values()}
            self._names = {p.id: p.name for p in value.places.values()}
            self._names |= {t.id: t.name for t in value.transitions.values()}
            self._draw(nodes, edges, positions)
        elif isinstance(value, ProcessTree):
            from ..studio.derivation_view import tree_specs
            nodes, edges, positions = tree_specs(value)
            self._names = {n.id: n.text for n in nodes}
            self._draw(nodes, edges, positions, layer_gap=40)
        # The moments shown so far.
        self.body = QWidget()
        self.body.setObjectName("plain")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        layout.addWidget(self.body)
        layout.addStretch(1)
        self.timer = QTimer(self)
        self.timer.setInterval(PLAY_MS)
        self.timer.timeout.connect(self._tick)
        self.show_moment(0)

    # -- drawing -----------------------------------------------------------------------------
    def _draw(self, nodes, edges, positions, layer_gap: float = 48.0) -> None:
        self.view = GraphView()
        self.view.setMinimumHeight(220)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.view.graph.populate(nodes, edges, positions, layer_gap=layer_gap)
        self._base = {n.id: n for n in nodes}
        self.layout().addWidget(self.view)
        QTimer.singleShot(0, self.view.fit)

    def highlighted(self, index: int) -> set[str]:
        """The ids of the drawn nodes the moment at ``index`` names."""
        if not self._names or not (0 <= index < len(self.moments)):
            return set()
        names = named_in(self.moments[index])
        compact = {name.replace(" ", "") for name in names}
        return {node_id for node_id, name in self._names.items()
                if name and (name in names or name.replace(" ", "") in compact)}

    def _light(self, index: int) -> None:
        if self.view is None:
            return
        t = style.tokens()
        lit = self.highlighted(index)
        for node_id, base in self._base.items():
            spec = NodeSpec(**{**base.__dict__})
            if lit:
                if node_id in lit:
                    spec.fill = t.accent_soft
                    spec.stroke = t.accent
                    spec.emphasis = True
                else:
                    spec.dimmed = True
            self.view.graph.update_node(spec)

    # -- stepping ----------------------------------------------------------------------------
    def show_moment(self, index: int) -> None:
        """Show the moments up to ``index`` and light up what the last one names."""
        count = len(self.moments)
        index = max(0, min(index, count - 1)) if count else 0
        self.index = index
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        t = style.tokens()
        for position, moment in enumerate(self.moments[:index + 1]):
            current = position == index
            self.body_layout.addWidget(self._render(moment, current, t))
        moment = self.moments[index] if count else None
        self.counter.setText(f"Step {index + 1} of {count}" if count else "Nothing to step through")
        self.title.setText(moment[1] if moment and moment[0] == "step" else
                           ("Note" if moment and moment[0] == "note" else (moment[1] if moment else "")))
        self.back_button.setEnabled(index > 0)
        self.next_button.setEnabled(index < count - 1)
        self._light(index)
        self.changed.emit(index)

    def _render(self, moment: tuple, current: bool, t) -> QWidget:
        from .viewers import result_widget
        if moment[0] == "note":
            text = label("· " + moment[1], None if current else "muted", wrap=True, selectable=True)
            return text
        if moment[0] == "step":
            title, content = moment[1], moment[2]
            colour = t.text if current else t.text_muted
            html = (f"<table cellspacing='0' width='100%'><tr><td valign='top' style='padding: 2px 10px 2px 0; "
                    f"color: {t.text_muted}; white-space: nowrap'><b>{title}</b></td>"
                    f"<td style='padding: 2px 0; color: {colour}; font-family: {theme.mono_font(11).family()}; "
                    f"font-size: 11.5px'>{content}</td></tr></table>")
            row = QLabel(html)
            row.setTextFormat(Qt.RichText)
            row.setWordWrap(True)
            row.setTextInteractionFlags(Qt.TextSelectableByMouse)
            return row
        host = QWidget()
        host.setObjectName("plain")
        column = QVBoxLayout(host)
        column.setContentsMargins(0, 0, 0, 0)
        if moment[1]:
            column.addWidget(label(str(moment[1]).upper(), "sectionLabel"))
        column.addWidget(result_widget(moment[2], self.page))
        return host

    def next(self) -> None:
        self.show_moment(self.index + 1)

    def previous(self) -> None:
        self.show_moment(self.index - 1)

    def toggle_play(self) -> None:
        if self.timer.isActive():
            self.timer.stop()
            self.play_button.setText("Play")
            return
        if self.index >= len(self.moments) - 1:
            self.show_moment(0)
        self.play_button.setText("Pause")
        self.timer.start()

    def _tick(self) -> None:
        if self.index >= len(self.moments) - 1:
            self.timer.stop()
            self.play_button.setText("Play")
            return
        self.next()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Right, Qt.Key_Space):
            self.next()
        elif event.key() == Qt.Key_Left:
            self.previous()
        else:
            super().keyPressEvent(event)


__all__ = ["StepThrough", "moments_of", "named_in", "PLAY_MS"]
