"""The *Runs* view of an analysis: its snapshots, two of them compared.

Every finished run is kept (the last twenty) with what changed before it
and every box's key figure.  Pick A and B and the boxes line up side by
side, the ones whose result differs marked; *Use these settings* puts a
run's settings back on the canvas, so a run can be returned to.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QHeaderView, QRadioButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ...flow.snapshots import Snapshot, compare
from ..studio import style
from ..studio.widgets import Card, button, hbox, label


class RunsWidget(QWidget):
    """Snapshots on top, the comparison of A and B under them; :meth:`refresh` rebuilds both."""

    def __init__(self, page, parent=None) -> None:
        super().__init__(parent)
        self.page = page
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(label(
            "Every finished run is kept here (the last twenty), with what changed before it and every box's "
            "key figure. Pick two, A and B, to see them side by side; Use these settings goes back to a run.",
            "muted", wrap=True))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["A", "B", "When", "What changed", "Boxes"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        for column in (0, 1, 2, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setMinimumHeight(140)
        layout.addWidget(self.table)
        self.group_a = QButtonGroup(self)
        self.group_b = QButtonGroup(self)
        self.group_a.idClicked.connect(lambda _i: self._compare())
        self.group_b.idClicked.connect(lambda _i: self._compare())
        self.comparison = Card("A and B, box by box", "Run the analysis: each finished run appears above.")
        self.diff = QTableWidget(0, 4)
        self.diff.setHorizontalHeaderLabels(["Box", "A", "B", "Changed"])
        self.diff.verticalHeader().setVisible(False)
        self.diff.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.diff.setSelectionMode(QAbstractItemView.NoSelection)
        self.diff.setShowGrid(False)
        diff_header = self.diff.horizontalHeader()
        for column in (0, 1, 2):
            diff_header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        diff_header.setSectionResizeMode(3, QHeaderView.Stretch)
        self.diff.setMinimumHeight(120)
        self.comparison.add(self.diff)
        self.use_a = button("Use A's settings", lambda: self._use(self.a))
        self.use_b = button("Use B's settings", lambda: self._use(self.b))
        self.comparison.add(hbox(self.use_a, self.use_b, None))
        layout.addWidget(self.comparison)
        layout.addStretch(1)
        self.snapshots: list[Snapshot] = []
        self.a: Snapshot | None = None
        self.b: Snapshot | None = None

    def refresh(self) -> None:
        """Rebuild from the page's history: newest first, A the run before the latest, B the latest."""
        for group in (self.group_a, self.group_b):
            for radio in group.buttons():
                group.removeButton(radio)
        self.snapshots = list(reversed(self.page.history.snapshots))
        self.table.setRowCount(len(self.snapshots))
        for row, snapshot in enumerate(self.snapshots):
            for column, group in ((0, self.group_a), (1, self.group_b)):
                radio = QRadioButton()
                radio.setToolTip("A: the run to compare from" if column == 0 else "B: the run to compare to")
                group.addButton(radio, row)
                holder = QWidget()
                holder.setLayout(hbox(radio, margins=(10, 0, 4, 0)))
                self.table.setCellWidget(row, column, holder)
            when = snapshot.taken.replace("T", " ")
            self.table.setItem(row, 2, QTableWidgetItem(when))
            self.table.setItem(row, 3, QTableWidgetItem(snapshot.label))
            self.table.setItem(row, 4, QTableWidgetItem(f"{snapshot.done} of {len(snapshot.statuses)} done"))
        if self.snapshots:
            self.group_b.button(0).setChecked(True)
            self.group_a.button(1 if len(self.snapshots) > 1 else 0).setChecked(True)
        self._compare()

    def _picked(self, group: QButtonGroup) -> Snapshot | None:
        index = group.checkedId()
        return self.snapshots[index] if 0 <= index < len(self.snapshots) else None

    def _compare(self) -> None:
        self.a, self.b = self._picked(self.group_a), self._picked(self.group_b)
        self.diff.setRowCount(0)
        if self.a is None or self.b is None:
            self.comparison.caption_label.setText("Run the analysis: each finished run appears above.")
            self.use_a.setEnabled(False)
            self.use_b.setEnabled(False)
            return
        rows = compare(self.a, self.b)
        changed = sum(1 for r in rows if r.changed)
        self.comparison.caption_label.setText(
            f"A: {self.a.taken.replace('T', ' ')} ({self.a.label}). B: {self.b.taken.replace('T', ' ')} "
            f"({self.b.label}). {changed} of {len(rows)} boxes give a different result.")
        self.diff.setRowCount(len(rows))
        for index, row in enumerate(rows):
            self.diff.setItem(index, 0, QTableWidgetItem(row.title))
            self.diff.setItem(index, 1, QTableWidgetItem(row.a or "–"))
            self.diff.setItem(index, 2, QTableWidgetItem(row.b or "–"))
            what = ("; ".join(row.changes) if row.changes else ("yes" if row.changed else "no"))
            item = QTableWidgetItem(what)
            if row.changed:
                item.setForeground(style.qc(style.STATUS["warning"]))
            self.diff.setItem(index, 3, item)
        self.use_a.setEnabled(True)
        self.use_b.setEnabled(True)

    def _use(self, snapshot: Snapshot | None) -> None:
        if snapshot is not None:
            self.page.apply_snapshot(snapshot)


__all__ = ["RunsWidget"]
