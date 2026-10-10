"""Editing an event log inside the app.

Two ways to edit, both on a working copy that only replaces the log when you
press *Save changes*:

* **Notation** -- the log as the course writes it, ``[<a,b,c>^3, <a,c>]``,
  with live checking.  A log typed with *Log from notation…* (or opened from
  a ``….log.txt`` file) opens here with exactly the text you typed, so you
  can go back to the notation and change it.
* **Cases and events** -- one case at a time: rename it, add, remove,
  duplicate and reorder events, edit their activity, timestamp, resource and
  lifecycle, and rename or remove an activity throughout the log.  This keeps
  every other attribute of a log read from XES or CSV.

Saving a log in notation form keeps only the activity sequences, so for a log
with timestamps or other attributes the notation tab says so before you use
it.  The page then writes the edited log back to its file (see
:meth:`.app.StudioWindow._log_edited`).
"""

from __future__ import annotations

import copy
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHeaderView,
    QInputDialog, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
    QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...mining.log import (
    KEY_LIFECYCLE, KEY_NAME, KEY_RESOURCE, KEY_TIME, Event, EventLog, Trace,
    format_simple_log, parse_simple_log,
)
from .. import theme
from . import style
from .widgets import SegmentedControl, button, hbox, label

#: Logs to start from in the notation editor.
EXAMPLES = {
    "Textbook L₁ (α-algorithm example)": "[<a,b,c,d>^3, <a,c,b,d>^2, <a,e,d>]",
    "Textbook L₂ (loop)": "[<a,b,c,d>^3, <a,c,b,d>^4, <a,b,c,e,f,b,c,d>^2, "
                          "<a,b,c,e,f,c,b,d>, <a,c,b,e,f,b,c,d>^2, <a,c,b,e,f,b,c,e,f,c,b,d>]",
    "Textbook L₃ (IM paper)": "[<a,b,c,d,e,f,b,d,c,e,g>, <a,b,d,c,e,g>^2, "
                              "<a,b,c,d,e,f,b,c,d,e,f,b,d,c,e,g>]",
    "Short loops (α limitation)": "[<a,c>^2, <a,b,c>^3, <a,b,b,c>^2, <a,b,b,b,b,c>]",
    "Non-free choice": "[<a,c,d>^45, <b,c,e>^42]",
}

NOTATION_HELP = ("Write traces as <a,b,c>^n, separated by commas. Activity names may contain "
                 "spaces. <> is the empty trace. Pasting ⟨a,b,c⟩³ from the book or the slides "
                 "works too.")


def is_plain(log: EventLog) -> bool:
    """Nothing but activity names: saving it in notation loses nothing."""
    for trace in log.traces:
        if set(trace.attributes) - {KEY_NAME}:
            return False
        for event in trace.events:
            if set(event.attributes) - {KEY_NAME}:
                return False
    return True


def notation_of(log: EventLog, classifier=None) -> str:
    """The log in the course's notation (most frequent trace first)."""
    return format_simple_log(log.simple_log(classifier))


def log_from_notation(text: str, name: str) -> EventLog:
    return EventLog.from_simple_log(parse_simple_log(text), name)


# ---------------------------------------------------------------------------
# The notation editor (also used by "New log from notation…")
# ---------------------------------------------------------------------------
class NotationEditor(QWidget):
    """A text box for a log in notation, with live feedback and examples."""

    def __init__(self, text: str = "", examples: bool = True, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.help = label(NOTATION_HELP, "muted", wrap=True)
        layout.addWidget(self.help)
        self.editor = QPlainTextEdit(text)
        self.editor.setFont(theme.mono_font(13))
        self.editor.setMinimumHeight(120)
        layout.addWidget(self.editor, 1)
        self.feedback = label("", "muted", wrap=True)
        self.examples = QComboBox()
        self.examples.addItem("Insert an example…")
        self.examples.addItems(list(EXAMPLES))
        self.examples.currentTextChanged.connect(self._example)
        self.examples.setVisible(examples)
        row = hbox()
        row.addWidget(self.feedback, 1)
        row.addWidget(self.examples)
        layout.addLayout(row)
        self.editor.textChanged.connect(self.validate)
        self.example_name = None
        self.validate()

    def _example(self, name: str) -> None:
        if name in EXAMPLES:
            self.example_name = name.split(" (")[0]
            self.editor.setPlainText(EXAMPLES[name])

    def text(self) -> str:
        return self.editor.toPlainText()

    def set_text(self, text: str) -> None:
        self.editor.setPlainText(text)

    def validate(self) -> bool:
        try:
            log = parse_simple_log(self.text())
        except ValueError as error:
            self.feedback.setText(str(error))
            self.feedback.setStyleSheet(f"color: {style.STATUS['critical']};")
            self.valid = False
            return False
        activities = {a for trace in log for a in trace}
        self.feedback.setStyleSheet("")
        self.feedback.setText(f"{sum(log.values())} traces · {len(log)} variants · "
                              f"{len(activities)} activities")
        self.valid = True
        return True


class NotationDialog(QDialog):
    """Create a log from the textbook's multiset notation."""

    def __init__(self, parent=None, text: str = "", name: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("New log from notation")
        self.setMinimumWidth(560)
        self.name = QLineEdit(name or "My log")
        self.notation = NotationEditor(text or EXAMPLES["Textbook L₁ (α-algorithm example)"])
        self.editor, self.feedback = self.notation.editor, self.notation.feedback
        self.examples = self.notation.examples
        self.examples.currentTextChanged.connect(
            lambda _name: self.notation.example_name and self.name.setText(
                self.notation.example_name))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Create log")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.ok = buttons.button(QDialogButtonBox.Ok)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Name", self.name)
        layout.addLayout(form)
        layout.addWidget(self.notation, 1)
        layout.addWidget(label("You can come back to this text later: Edit… on the log's "
                               "page.", "muted", wrap=True))
        layout.addWidget(buttons)
        self.editor.textChanged.connect(lambda: self.ok.setEnabled(self.notation.valid))
        self.ok.setEnabled(self.notation.valid)

    def text(self) -> str:
        return self.notation.text().strip()

    def log(self) -> EventLog:
        return log_from_notation(self.notation.text(), self.name.text().strip() or "Log")


# ---------------------------------------------------------------------------
# Cases and events
# ---------------------------------------------------------------------------
#: The event columns the editor can show: (attribute key, heading).
COLUMNS = [(KEY_NAME, "Activity"), (KEY_TIME, "Timestamp"), (KEY_RESOURCE, "Resource"),
           (KEY_LIFECYCLE, "Lifecycle")]


def format_time(value) -> str:
    if isinstance(value, datetime):
        text = value.isoformat(sep=" ")
        return text
    return "" if value is None else str(value)


def parse_time(text: str):
    """A timestamp typed in the table (ISO 8601: ``2024-03-01 09:30``), or None."""
    text = text.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text.replace("T", " ", 1) if "T" in text else text)


class CaseEditor(QWidget):
    """Cases on the left, the events of the selected case on the right."""

    def __init__(self, log: EventLog, columns: list[str] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.log = log
        present = {key for trace in log.traces for event in trace.events
                   for key in event.attributes}
        self.columns = [(k, h) for k, h in COLUMNS
                        if k == KEY_NAME or (columns is None and k in present)
                        or (columns is not None and k in columns)]
        self.changed = False
        self._filling = False
        #: The time zone of the log's timestamps: a time typed without an offset
        #: gets it (naive and zone-aware times cannot be compared).
        self.zone = next((e.timestamp.tzinfo for t in log.traces for e in t.events
                          if e.timestamp is not None and e.timestamp.tzinfo is not None), None)
        self.bad_cells: set[tuple[int, int, int]] = set()     # (trace id, row, column)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addLayout(hbox(
            button("Rename activity…", self.rename_activity,
                   tooltip="Rename an activity in every case"),
            button("Remove activity…", self.remove_activity,
                   tooltip="Remove every event of an activity"),
            None, spacing=6))

        # Cases
        left = QWidget()
        column = QVBoxLayout(left)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a case or activity")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        column.addWidget(self.search)
        self.cases = QListWidget()
        self.cases.currentRowChanged.connect(lambda _row: self._show_case())
        column.addWidget(self.cases, 1)
        column.addLayout(hbox(button("＋ Case", self.add_case, tooltip="Add an empty case"),
                              button("Duplicate", self.duplicate_case,
                                     tooltip="Add a copy of this case"),
                              button("Delete", self.delete_case, tooltip="Delete this case"),
                              None, spacing=4))

        # Events
        right = QWidget()
        column = QVBoxLayout(right)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        self.case_name = QLineEdit()
        self.case_name.setPlaceholderText("Case id")
        self.case_name.editingFinished.connect(self._rename_case)
        column.addLayout(hbox(label("Case"), self.case_name, spacing=6))
        self.events = QTableWidget(0, len(self.columns))
        self.events.setHorizontalHeaderLabels([h for _, h in self.columns])
        self.events.verticalHeader().setVisible(True)
        self.events.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.events.setSelectionMode(QAbstractItemView.SingleSelection)
        header = self.events.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        for index, (key, _) in enumerate(self.columns):
            if key == KEY_TIME:                   # a timestamp is read whole
                header.setSectionResizeMode(index, QHeaderView.ResizeToContents)
        self.events.itemChanged.connect(self._cell_changed)
        column.addWidget(self.events, 1)
        column.addLayout(hbox(button("＋ Event", self.add_event,
                                     tooltip="Add an event below the selected one"),
                              button("Delete", self.delete_event, tooltip="Delete the event"),
                              button("↑", lambda: self.move_event(-1), tooltip="Move up"),
                              button("↓", lambda: self.move_event(1), tooltip="Move down"),
                              None, spacing=4))
        self.problem = label("", "muted", wrap=True)
        column.addWidget(self.problem)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([230, 520])
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)
        self._fill_cases()

    # -- cases -----------------------------------------------------------------------
    def _case_text(self, trace: Trace) -> str:
        return f"{trace.case_id or '(no id)'}  ·  {len(trace.events)}"

    def _fill_cases(self, select: int = 0) -> None:
        self.cases.blockSignals(True)
        self.cases.clear()
        for index, trace in enumerate(self.log.traces):
            item = QListWidgetItem(self._case_text(trace))
            item.setData(Qt.UserRole, index)
            item.setToolTip(" → ".join(str(e.activity) for e in trace.events))
            self.cases.addItem(item)
        self.cases.blockSignals(False)
        self._filter(self.search.text())
        if self.log.traces:
            self.cases.setCurrentRow(max(0, min(select, len(self.log.traces) - 1)))
        self._show_case()

    def _filter(self, text: str) -> None:
        needle = text.strip().lower()
        for row in range(self.cases.count()):
            trace = self.log.traces[row]
            hit = not needle or needle in trace.case_id.lower() or any(
                needle in str(e.activity or "").lower() for e in trace.events)
            self.cases.item(row).setHidden(not hit)

    def current_trace(self) -> Trace | None:
        row = self.cases.currentRow()
        return self.log.traces[row] if 0 <= row < len(self.log.traces) else None

    def _refresh_case_row(self) -> None:
        row = self.cases.currentRow()
        trace = self.current_trace()
        if trace is not None:
            self.cases.item(row).setText(self._case_text(trace))
            self.cases.item(row).setToolTip(" → ".join(str(e.activity) for e in trace.events))

    def _unique_case_id(self, base: str = "case") -> str:
        taken = {t.case_id for t in self.log.traces}
        number = len(self.log.traces) + 1
        while f"{base} {number}" in taken:
            number += 1
        return f"{base} {number}"

    def add_case(self) -> None:
        self.log.traces.append(Trace(attributes={KEY_NAME: self._unique_case_id()}))
        self._modified()
        self._fill_cases(len(self.log.traces) - 1)

    def duplicate_case(self) -> None:
        trace = self.current_trace()
        if trace is None:
            return
        twin = copy.deepcopy(trace)
        twin.attributes[KEY_NAME] = self._unique_case_id()
        index = self.cases.currentRow() + 1
        self.log.traces.insert(index, twin)
        self._modified()
        self._fill_cases(index)

    def delete_case(self) -> None:
        row = self.cases.currentRow()
        if row < 0:
            return
        gone = id(self.log.traces[row])
        del self.log.traces[row]
        self.bad_cells = {cell for cell in self.bad_cells if cell[0] != gone}
        self._modified()
        self._fill_cases(row)

    def _rename_case(self) -> None:
        trace = self.current_trace()
        if trace is None or self.case_name.text() == trace.case_id:
            return
        trace.attributes[KEY_NAME] = self.case_name.text()
        self._modified()
        self._refresh_case_row()

    # -- events -----------------------------------------------------------------------
    def _show_case(self) -> None:
        trace = self.current_trace()
        self._filling = True
        self.events.setRowCount(0)
        self.case_name.setText(trace.case_id if trace else "")
        self.case_name.setEnabled(trace is not None)
        if trace is not None:
            self.events.setRowCount(len(trace.events))
            for row, event in enumerate(trace.events):
                for column, (key, _heading) in enumerate(self.columns):
                    value = event.attributes.get(key)
                    item = QTableWidgetItem(format_time(value) if key == KEY_TIME
                                            else "" if value is None else str(value))
                    if (id(trace), row, column) in self.bad_cells:
                        item.setBackground(QColor(style.STATUS["critical"]).lighter(170))
                    self.events.setItem(row, column, item)
        self._filling = False
        self._update_problem()

    def _cell_changed(self, item: QTableWidgetItem) -> None:
        if self._filling:
            return
        trace = self.current_trace()
        if trace is None or item.row() >= len(trace.events):
            return
        event = trace.events[item.row()]
        key = self.columns[item.column()][0]
        text = item.text()
        cell = (id(trace), item.row(), item.column())
        if key == KEY_TIME:
            try:
                value = parse_time(text)
                if value is not None and value.tzinfo is None and self.zone is not None:
                    value = value.replace(tzinfo=self.zone)
            except ValueError:
                self.bad_cells.add(cell)
                self._filling = True
                item.setBackground(QColor(style.STATUS["critical"]).lighter(170))
                self._filling = False
                self._update_problem()
                return
        else:
            value = text.strip() or None
        self.bad_cells.discard(cell)
        self._filling = True
        item.setData(Qt.BackgroundRole, None)
        self._filling = False
        if value is None and key != KEY_NAME:
            event.attributes.pop(key, None)
        else:
            event.attributes[key] = value if value is not None else ""
        self._modified()
        self._refresh_case_row()
        self._update_problem()

    def _selected_event(self) -> int:
        rows = self.events.selectionModel().selectedRows() if self.events.selectionModel() else []
        return rows[0].row() if rows else self.events.currentRow()

    def add_event(self) -> None:
        trace = self.current_trace()
        if trace is None:
            return
        row = self._selected_event()
        index = row + 1 if row >= 0 else len(trace.events)
        attributes = {KEY_NAME: "new activity"}
        neighbour = trace.events[index - 1] if index > 0 else (
            trace.events[0] if trace.events else None)
        if neighbour is not None:
            for key in (KEY_TIME, KEY_LIFECYCLE):
                if key in neighbour.attributes and any(k == key for k, _ in self.columns):
                    attributes[key] = neighbour.attributes[key]
        trace.events.insert(index, Event(attributes))
        self._shift_bad_cells(trace, index, 1)
        self._modified()
        self._show_case()
        self._refresh_case_row()
        self.events.selectRow(index)
        self.events.setCurrentCell(index, 0)
        self.events.editItem(self.events.item(index, 0))

    def delete_event(self) -> None:
        trace = self.current_trace()
        row = self._selected_event()
        if trace is None or not 0 <= row < len(trace.events):
            return
        del trace.events[row]
        self.bad_cells = {c for c in self.bad_cells if not (c[0] == id(trace) and c[1] == row)}
        self._shift_bad_cells(trace, row + 1, -1)
        self._modified()
        self._show_case()
        self._refresh_case_row()
        if trace.events:
            self.events.selectRow(min(row, len(trace.events) - 1))

    def move_event(self, step: int) -> None:
        trace = self.current_trace()
        row = self._selected_event()
        target = row + step
        if trace is None or not (0 <= row < len(trace.events) and 0 <= target < len(trace.events)):
            return
        events = trace.events
        events[row], events[target] = events[target], events[row]
        swapped = set()
        for cell in self.bad_cells:
            if cell[0] == id(trace) and cell[1] in (row, target):
                cell = (cell[0], target if cell[1] == row else row, cell[2])
            swapped.add(cell)
        self.bad_cells = swapped
        self._modified()
        self._show_case()
        self._refresh_case_row()
        self.events.selectRow(target)

    def _shift_bad_cells(self, trace: Trace, start: int, step: int) -> None:
        self.bad_cells = {(t, r + step if t == id(trace) and r >= start else r, c)
                          for t, r, c in self.bad_cells}

    # -- whole log ----------------------------------------------------------------------
    def activities(self) -> list[str]:
        return sorted({str(e.activity) for t in self.log.traces for e in t.events
                       if e.activity is not None})

    def rename_activity(self) -> None:
        names = self.activities()
        if not names:
            return
        old, ok = QInputDialog.getItem(self, "Rename activity", "Activity", names, 0, False)
        if not ok:
            return
        new, ok = QInputDialog.getText(self, "Rename activity", f"New name for “{old}”",
                                       text=old)
        new = new.strip()
        if not ok or not new or new == old:
            return
        for trace in self.log.traces:
            for event in trace.events:
                if event.activity == old:
                    event.attributes[KEY_NAME] = new
        self._modified()
        self._fill_cases(self.cases.currentRow())

    def remove_activity(self) -> None:
        names = self.activities()
        if not names:
            return
        old, ok = QInputDialog.getItem(self, "Remove activity", "Remove every event of",
                                       names, 0, False)
        if not ok:
            return
        for trace in self.log.traces:
            trace.events = [e for e in trace.events if e.activity != old]
        self.bad_cells.clear()
        self._modified()
        self._fill_cases(self.cases.currentRow())

    def _modified(self) -> None:
        self.changed = True

    def _update_problem(self) -> None:
        if self.bad_cells:
            self.problem.setText("A timestamp is not a date and time. Write it as "
                                 "2024-03-01 09:30 (or 2024-03-01T09:30:00+01:00).")
            self.problem.setStyleSheet(f"color: {style.STATUS['critical']};")
        else:
            self.problem.setText("")
            self.problem.setStyleSheet("")

    @property
    def valid(self) -> bool:
        return not self.bad_cells


# ---------------------------------------------------------------------------
# The dialog
# ---------------------------------------------------------------------------
class LogEditorDialog(QDialog):
    """Edit a log in notation or case by case; :meth:`result_log` is the outcome."""

    NOTATION, EVENTS = 0, 1

    def __init__(self, document, parent=None) -> None:
        super().__init__(parent)
        self.document = document
        self.setWindowTitle(f"Edit “{document.name}”")
        self.resize(860, 600)
        self.plain = is_plain(document.log)
        #: The original notation, when the log was written in it.
        self.original_notation = getattr(document, "notation", None)
        self.working = copy.deepcopy(document.log)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.name = QLineEdit(document.name)
        self.modes = SegmentedControl(["Notation", "Cases and events"])
        layout.addLayout(hbox(label("Name"), self.name, 16, self.modes, spacing=8))

        self.stack = QStackedWidget()
        notation_page = QWidget()
        column = QVBoxLayout(notation_page)
        column.setContentsMargins(0, 0, 0, 0)
        self.notation = NotationEditor(self.original_notation
                                       or notation_of(self.working, document.classifier),
                                       examples=False)
        self.notation_warning = label(
            "This log has timestamps or other attributes. Saving it from the notation keeps "
            "only the activity sequences (as seen through the current classifier). Use Cases "
            "and events to keep everything else.", "muted", wrap=True)
        self.notation_warning.setStyleSheet(f"color: {style.STATUS['warning']};")
        self.notation_warning.setVisible(not self.plain)
        column.addWidget(self.notation_warning)
        column.addWidget(self.notation, 1)
        self.stack.addWidget(notation_page)
        self.cases = CaseEditor(self.working, columns=[KEY_NAME] if self.plain else None)
        self.stack.addWidget(self.cases)
        layout.addWidget(self.stack, 1)

        self._notation_text = self._initial_notation = self.notation.text()
        self._mode = self.NOTATION if self.plain else self.EVENTS
        self.modes.set_index(self._mode)
        self.stack.setCurrentIndex(self._mode)
        self.modes.changed.connect(self._switch)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("Save changes")
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.notation.editor.textChanged.connect(self._validate)
        self.cases.events.itemChanged.connect(lambda _item: self._validate())
        self._validate()
        #: Set when accepted: the new log, and its notation (None: not a notation log).
        self.new_log: EventLog | None = None
        self.new_notation: str | None = None

    @property
    def mode(self) -> int:
        return self._mode

    def _switch(self, index: int) -> None:
        if index == self._mode:
            return
        if index == self.EVENTS:
            if self.notation.text() != self._notation_text:
                if not self.notation.valid:
                    QMessageBox.information(self, "Edit log", "Fix the notation first: "
                                            + self.notation.feedback.text())
                    self.modes.blockSignals(True)
                    self.modes.set_index(self.NOTATION)
                    self.modes.blockSignals(False)
                    return
                self._replace_working(log_from_notation(self.notation.text(), self.name.text()))
        else:
            if self.cases.changed:
                if not self.cases.valid:
                    QMessageBox.information(self, "Edit log", "Fix the highlighted timestamp "
                                            "first.")
                    self.modes.blockSignals(True)
                    self.modes.set_index(self.EVENTS)
                    self.modes.blockSignals(False)
                    return
                self.notation.set_text(notation_of(self.working, self._classifier()))
                self._notation_text = self.notation.text()
        self._mode = index
        self.stack.setCurrentIndex(index)
        self._validate()

    def _classifier(self):
        classifier = self.document.classifier
        return classifier if classifier in self.working.available_classifiers() else None

    def _replace_working(self, log: EventLog) -> None:
        """Notation edits made: the case editor starts over from them."""
        log.attributes = dict(self.working.attributes)
        self.working = log
        self.plain = True
        self.notation_warning.setVisible(False)
        old = self.cases
        self.cases = CaseEditor(self.working, columns=[KEY_NAME])
        self.cases.changed = True
        self.cases.events.itemChanged.connect(lambda _item: self._validate())
        self.stack.insertWidget(self.EVENTS, self.cases)
        self.stack.removeWidget(old)
        old.deleteLater()
        self._notation_text = self.notation.text()

    def _validate(self) -> None:
        ok = self.notation.valid if self._mode == self.NOTATION else self.cases.valid
        self.buttons.button(QDialogButtonBox.Save).setEnabled(ok)

    def _accept(self) -> None:
        name = self.name.text().strip() or self.document.name
        if self._mode == self.NOTATION:
            text = self.notation.text().strip()
            if text == self._initial_notation.strip() and not self.cases.changed \
                    and name == self.document.name:
                self.reject()                        # nothing changed
                return
            log = log_from_notation(text, name)
            if not self.plain or self.cases.changed:
                log.attributes = {**self.working.attributes, KEY_NAME: name}
            self.new_log, self.new_notation = log, text
        else:
            if not self.cases.changed and name == self.document.name:
                self.reject()
                return
            self.working.attributes[KEY_NAME] = name
            self.new_log = self.working
            # Still nothing but activities: it stays a notation log.
            self.new_notation = notation_of(self.working) if (
                self.original_notation is not None and is_plain(self.working)) else None
        self.accept()
