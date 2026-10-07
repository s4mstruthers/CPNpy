"""The result of comparing two nets on behaviour (Compare nets…, and Check in
an exercise)."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QSizePolicy, QTableWidget, QVBoxLayout, QWidget

from .widgets import Verdict, button, hbox, label, status_for


def trace_text(trace) -> str:
    return "⟨" + ", ".join(trace) + "⟩"


# ---------------------------------------------------------------------------
# The result of comparing two nets
# ---------------------------------------------------------------------------
class NetComparisonView(QWidget):
    """Same behaviour or not, the shortest differing traces, and a label mapping.

    ``replay(trace, in_first)`` replays a trace on the first net (yours);
    ``recompare(mapping)`` compares again with labels of the first net
    renamed to labels of the second.
    """

    def __init__(self, comparison, first: str = "yours", second: str = "the answer",
                 replay=None, recompare=None, soundness=None, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.comparison = comparison
        same = comparison.equivalent
        scope = "" if comparison.exact else \
            f" Traces of up to {comparison.max_length} steps were compared (the nets are " \
            "unbounded or very large), so this is not a proof."
        if same:
            layout.addWidget(Verdict("Same behaviour", "good",
                                     f"{first.capitalize()} and {second} allow exactly the "
                                     "same complete traces." + scope))
        else:
            layout.addWidget(Verdict(f"Differs from {second}", "warning",
                                     f"{first.capitalize()} and {second} do not allow the same "
                                     "complete traces. A different model can still be a "
                                     "correct reading of the question." + scope))
        self.replay_buttons: list = []

        def row(text: str, trace, in_first: bool) -> None:
            line = hbox(spacing=6)
            line.addWidget(label(f"<span>{text}</span>", "muted", wrap=True, selectable=True), 1)
            if replay is not None:
                show = button("Replay ▶", lambda _=False, t=trace, f=in_first: replay(t, f),
                              kind="ghost", tooltip="Fire this trace on "
                              f"{first} in the token game, as far as it goes")
                show.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                self.replay_buttons.append(show)
                line.addWidget(show, 0, Qt.AlignTop)
            holder = QWidget()
            holder.setLayout(line)
            layout.addWidget(holder)

        for trace in comparison.only_second:
            row(f"{escape(second.capitalize())} allows <b>{escape(trace_text(trace))}</b>, "
                f"{escape(first)} does not.", trace, False)
        for trace in comparison.only_first:
            row(f"{escape(first.capitalize())} allows <b>{escape(trace_text(trace))}</b>, "
                f"{escape(second)} does not.", trace, True)
        if comparison.labels_only_first or comparison.labels_only_second:
            layout.addWidget(label(
                "Labels only in " + first + ": " + (", ".join(comparison.labels_only_first)
                                                    or "–")
                + ". Only in " + second + ": " + (", ".join(comparison.labels_only_second)
                                                  or "–") + ".", "muted", wrap=True))
            if recompare is not None and comparison.labels_only_first and \
                    comparison.labels_only_second:
                layout.addWidget(self._mapping_table(comparison, first, second, recompare))
        for note in comparison.notes:
            layout.addWidget(label(note, "muted", wrap=True))
        if soundness is not None:
            verdict = soundness.sound
            if not soundness.workflow.is_workflow_net:
                layout.addWidget(Verdict("Not a WF-net", "info", "; ".join(
                    soundness.workflow.problems[:2]), definition="wf_net"))
            else:
                layout.addWidget(Verdict(
                    f"{first.capitalize()}: " + ("sound" if verdict else "not sound"
                                                 if verdict is False else "soundness undecided"),
                    status_for(verdict), soundness.findings[0] if soundness.findings else
                    "every case can complete properly and every transition can fire",
                    definition="sound"))

    def _mapping_table(self, comparison, first: str, second: str, recompare) -> QWidget:
        """Match labels that differ (``register`` vs ``Register request``) by hand."""
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label(f"Match the labels of {first} to those of {second}:", wrap=True))
        table = QTableWidget(len(comparison.labels_only_first), 2)
        table.setHorizontalHeaderLabels([first.capitalize(), second.capitalize()])
        table.verticalHeader().setVisible(False)
        boxes = []
        for row, mine in enumerate(comparison.labels_only_first):
            from PySide6.QtWidgets import QTableWidgetItem
            item = QTableWidgetItem(mine)
            table.setItem(row, 0, item)
            box = QComboBox()
            box.addItem("(no match)", None)
            for theirs in comparison.labels_only_second:
                box.addItem(theirs, theirs)
            table.setCellWidget(row, 1, box)
            boxes.append((mine, box))
        table.horizontalHeader().setStretchLastSection(True)
        table.setMinimumHeight(min(60 + 30 * len(boxes), 220))
        layout.addWidget(table)
        self.mapping_boxes = boxes
        layout.addWidget(button("Compare again", lambda: recompare(
            {mine: box.currentData() for mine, box in boxes if box.currentData()}),
            kind="primary"))
        return host


