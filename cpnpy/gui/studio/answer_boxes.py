"""The answer boxes of a worksheet (see :mod:`cpnpy.teaching.sheet`).

Every answer block of ``question.md`` becomes a :class:`TaskCard`: the box to
answer in (an *editor*, one per type), a **Check** button, and *Hint* and
*Show answer* when the block has them.  Editors share a small interface:

* ``value()`` -- the answer as stored in ``my answers.json`` (JSON);
* ``set_value(value)`` -- put a saved answer back;
* ``changed`` -- emitted on every edit (the card saves and clears old feedback);
* ``show_result(result)`` -- mark what was wrong (the footprint's cells).

The card does not check anything itself: it asks (``check_requested``) and
the exercise view answers with :meth:`TaskCard.show_result`.
"""

from __future__ import annotations

import re
from html import escape

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QPlainTextEdit, QPushButton, QRadioButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from ...teaching import answers
from ...teaching.checks import CORRECT, INCORRECT, PARTIAL, UNKNOWN
from .markdown_view import MarkdownLabel
from .widgets import button, hbox, label

#: What the card's caption says above each kind of box.
CAPTIONS = {
    "net": "Draw your net", "footprint": "Your footprint", "yesno": "Your answer",
    "choice": "Your answer", "set": "Your answer", "trace": "Your firing sequence",
    "number": "Your answer", "text": "Your answer", "open": "Your answer",
}

#: Status of a task -> (chip text, status colour key).
STATUS = {
    CORRECT: ("Correct", "good"), PARTIAL: ("Almost", "warning"),
    INCORRECT: ("Not yet", "critical"), "done": ("Done", "good"),
}


def inline_markdown(text: str) -> str:
    """``*x*``, ``**x**`` and `` `x` `` as rich text (option labels, captions)."""
    html = escape(text)
    html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html)
    html = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", html)
    html = re.sub(r"`(.+?)`", r"<code>\1</code>", html)
    return html


# ---------------------------------------------------------------------------
# Editors
# ---------------------------------------------------------------------------
class Editor(QWidget):
    changed = Signal()

    def value(self):
        return None

    def set_value(self, value) -> None:
        pass

    def show_result(self, result) -> None:
        pass


class LineEditor(Editor):
    """One line of text: sets, numbers, short answers, traces."""

    def __init__(self, placeholder: str, preview=None, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.edit = QLineEdit()
        self.edit.setObjectName("answerLine")
        self.edit.setPlaceholderText(placeholder)
        self.edit.textEdited.connect(lambda _text: self._edited())
        self.row = hbox(self.edit, spacing=6)
        layout.addLayout(self.row)
        #: preview(text) -> (shown, ok): how the answer is read, as you type.
        self.preview = preview
        self.reading = label("", "answerReading", wrap=True)
        self.reading.setHidden(True)
        layout.addWidget(self.reading)

    def _edited(self) -> None:
        self._show_reading()
        self.changed.emit()

    def _show_reading(self) -> None:
        if self.preview is None:
            return
        text = self.edit.text()
        if not text.strip():
            self.reading.setHidden(True)
            return
        shown, ok = self.preview(text)
        self.reading.setText(shown)
        self.reading.setProperty("ok", ok)
        self.reading.style().unpolish(self.reading)
        self.reading.style().polish(self.reading)
        self.reading.setHidden(False)

    def value(self):
        return self.edit.text()

    def set_value(self, value) -> None:
        self.edit.setText("" if value is None else str(value))
        self._show_reading()


def set_preview(text: str) -> tuple[str, bool]:
    try:
        items = answers.parse(text)
    except answers.AnswerSyntaxError as error:
        return f"Cannot read this yet: {error}.", False
    if len(items) == 1 and isinstance(items[0], frozenset):
        shown = answers.show(items[0])
    else:
        shown = answers.show(frozenset(items))
    return f"Read as {shown}", True


def trace_preview(text: str) -> tuple[str, bool]:
    try:
        steps = answers.trace(text)
    except answers.AnswerSyntaxError as error:
        return f"Cannot read this yet: {error}.", False
    return f"{len(steps)} step{'s' * (len(steps) != 1)}: " + " → ".join(steps), True


def number_preview(text: str) -> tuple[str, bool]:
    try:
        value = answers.number(text)
    except (ValueError, ZeroDivisionError):
        return "Not a number yet.", False
    return f"Read as {value:g}", True


class OptionRow(QFrame):
    """A choice option: a radio button or check box with rich text, all clickable."""

    def __init__(self, text: str, multiple: bool, group: QButtonGroup) -> None:
        super().__init__()
        self.setObjectName("choiceOption")
        self.setCursor(Qt.PointingHandCursor)
        self.indicator = QCheckBox() if multiple else QRadioButton()
        self.indicator.setCursor(Qt.PointingHandCursor)
        group.addButton(self.indicator)
        text_label = QLabel(inline_markdown(text))
        text_label.setWordWrap(True)
        text_label.setTextFormat(Qt.RichText)
        text_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(10)
        layout.addWidget(self.indicator, 0, Qt.AlignTop)
        layout.addWidget(text_label, 1)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.indicator.click()
        super().mousePressEvent(event)


class ChoiceEditor(Editor):
    def __init__(self, options, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.multiple = sum(o.correct for o in options) > 1
        self.group = QButtonGroup(self)
        self.group.setExclusive(not self.multiple)
        self.rows = []
        for index, option in enumerate(options):
            row = OptionRow(option.text, self.multiple, self.group)
            self.group.setId(row.indicator, index)
            layout.addWidget(row)
            self.rows.append(row)
        if self.multiple:
            layout.addWidget(label("More than one is right: tick all of them.", "muted"))
        self.group.buttonToggled.connect(lambda *_: self.changed.emit())

    def value(self):
        chosen = [i for i, row in enumerate(self.rows) if row.indicator.isChecked()]
        return chosen if self.multiple else (chosen[0] if chosen else None)

    def set_value(self, value) -> None:
        chosen = set(value if isinstance(value, list) else [] if value is None else [value])
        self.group.blockSignals(True)
        for index, row in enumerate(self.rows):
            row.indicator.setChecked(index in chosen)
        self.group.blockSignals(False)


class YesNoEditor(Editor):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.group = QButtonGroup(self)
        self.buttons = {}
        row = hbox(spacing=6)
        for key, text in (("yes", "Yes"), ("no", "No")):
            pill = QPushButton(text)
            pill.setObjectName("choicePill")
            pill.setCheckable(True)
            pill.setCursor(Qt.PointingHandCursor)
            self.group.addButton(pill)
            self.buttons[key] = pill
            row.addWidget(pill)
        row.addStretch(1)
        self.setLayout(row)
        self.group.buttonClicked.connect(lambda _b: self.changed.emit())

    def value(self):
        return next((key for key, pill in self.buttons.items() if pill.isChecked()), None)

    def set_value(self, value) -> None:
        if value in self.buttons:
            self.buttons[value].setChecked(True)


class TextEditor(Editor):
    """A few lines of free text (``open``)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QPlainTextEdit()
        self.edit.setObjectName("answerText")
        self.edit.setPlaceholderText("Write your answer here.")
        self.edit.setFixedHeight(96)
        self.edit.textChanged.connect(self.changed.emit)
        layout.addWidget(self.edit)

    def value(self):
        return self.edit.toPlainText()

    def set_value(self, value) -> None:
        self.edit.blockSignals(True)
        self.edit.setPlainText(value or "")
        self.edit.blockSignals(False)


#: Click order of a footprint cell, and the keys that set each relation.
SYMBOLS = ["→", "←", "‖", "#"]
KEYS = {">": "→", "<": "←", "|": "‖", "#": "#", "=": "#", "p": "‖"}


class FootprintCell(QToolButton):
    def __init__(self, editor: "FootprintEditor", row: str, column: str) -> None:
        super().__init__()
        self.setObjectName("footprintCell")
        self.editor = editor
        self.row, self.column = row, column
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(38, 32)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip(f"{row} and {column}: click to change (or type > < | #)")
        self.symbol = ""
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def set_symbol(self, symbol: str, wrong: bool = False) -> None:
        self.symbol = symbol
        self.setText(symbol)
        self.set_wrong(wrong)

    def set_wrong(self, wrong: bool) -> None:
        if self.property("wrong") != wrong:
            self.setProperty("wrong", wrong)
            self.style().unpolish(self)
            self.style().polish(self)

    def _menu(self, position) -> None:
        menu = QMenu(self)
        for symbol, meaning in zip(SYMBOLS, ("causality", "inverse causality",
                                             "parallel", "choice (never next to each other)")):
            menu.addAction(f"{symbol}   {meaning}", lambda s=symbol: self.editor.choose(self, s))
        menu.addSeparator()
        menu.addAction("Clear", lambda: self.editor.choose(self, ""))
        menu.exec(self.mapToGlobal(position))

    def keyPressEvent(self, event) -> None:  # noqa: N802
        text = event.text()
        if text in KEYS:
            self.editor.choose(self, KEYS[text])
        elif event.key() in (Qt.Key_Backspace, Qt.Key_Delete):
            self.editor.choose(self, "")
        else:
            super().keyPressEvent(event)


class FootprintEditor(Editor):
    """A grid of activities × activities; each cell cycles → ← ‖ #."""

    def __init__(self, activities: list[str], parent=None) -> None:
        super().__init__(parent)
        self.activities = activities
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        grid_host = QWidget()
        grid_host.setObjectName("footprintGrid")
        self.grid = QGridLayout(grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(3)
        self.grid.setVerticalSpacing(3)
        self.cells: dict[tuple[str, str], FootprintCell] = {}
        for index, activity in enumerate(activities):
            top = label(escape(activity), "footprintHeading")
            top.setAlignment(Qt.AlignCenter)
            self.grid.addWidget(top, 0, index + 1)
            side = label(escape(activity), "footprintHeading")
            side.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.grid.addWidget(side, index + 1, 0)
        for r, a in enumerate(activities):
            for c, b in enumerate(activities):
                cell = FootprintCell(self, a, b)
                cell.clicked.connect(lambda _=False, cell=cell: self.cycle(cell))
                self.grid.addWidget(cell, r + 1, c + 1)
                self.cells[(a, b)] = cell
        outer.addLayout(hbox(grid_host, None))
        outer.addWidget(label("Click a cell to change it (→ ← ‖ #), or type > < | # on "
                              "it.", "muted", wrap=True))
        fill = button("Fill the empty cells with #", self.fill_choice, kind="ghost")
        outer.addLayout(hbox(fill, None))

    def cycle(self, cell: FootprintCell) -> None:
        index = SYMBOLS.index(cell.symbol) + 1 if cell.symbol in SYMBOLS else 0
        self.choose(cell, SYMBOLS[index] if index < len(SYMBOLS) else "")

    def choose(self, cell: FootprintCell, symbol: str) -> None:
        cell.set_symbol(symbol)
        self.changed.emit()

    def fill_choice(self) -> None:
        for cell in self.cells.values():
            if not cell.symbol:
                cell.set_symbol("#")
        self.changed.emit()

    def value(self):
        return {f"{a}\t{b}": cell.symbol for (a, b), cell in self.cells.items() if cell.symbol}

    def set_value(self, value) -> None:
        value = value if isinstance(value, dict) else {}
        for (a, b), cell in self.cells.items():
            cell.set_symbol(value.get(f"{a}\t{b}", ""))

    def show_result(self, result) -> None:
        wrong = set(result.wrong_cells) if result is not None else set()
        for key, cell in self.cells.items():
            cell.set_wrong(key in wrong and bool(cell.symbol))


class NetEditor(Editor):
    """The net is drawn in the editor beside the sheet; here only a pointer to it."""

    go_to_net = Signal()

    def __init__(self, tab_name: str, parent=None) -> None:
        super().__init__(parent)
        layout = hbox(spacing=8)
        self.setLayout(layout)
        layout.addWidget(label(f"Draw it in <b>{escape(tab_name)}</b>, on the right. "
                               "It is saved as you go.", "muted", wrap=True), 1)
        layout.addWidget(button(f"Show {tab_name}", self.go_to_net.emit))


# ---------------------------------------------------------------------------
# The card around an editor
# ---------------------------------------------------------------------------
class TaskCard(QFrame):
    """One answer box with its Check, Hint and Show answer."""

    check_requested = Signal(object)          # the task
    changed = Signal(object)                  # the task (save the answer)
    solution_requested = Signal(object)       # the task (the card asks for the text)

    def __init__(self, task, editor: Editor, folder=None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("taskCard")
        self.task = task
        self.editor = editor
        self.folder = folder
        self.status: str | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 12)
        layout.setSpacing(9)

        self.caption = label(CAPTIONS.get(task.type, "Your answer").upper(), "taskCaption")
        self.chip = label("", "statusChip")
        self.chip.setHidden(True)
        layout.addLayout(hbox(self.caption, None, self.chip))
        layout.addWidget(editor)

        self.check_button = button("Check", lambda: self.check_requested.emit(self.task),
                                   kind="primary")
        self.check_button.setVisible(task.checkable)
        self.hint_button = button("Hint", self.toggle_hint, kind="ghost")
        self.hint_button.setVisible(bool(task.hint))
        answer_text = "Show model answer" if task.type == "open" else "Show answer"
        self.answer_button = button(answer_text, self.reveal_solution, kind="ghost")
        # A drawn net or a free answer has a model answer only when the author wrote one.
        self.answer_button.setVisible(task.type not in ("net", "open") or bool(task.solution))
        footer = hbox(self.check_button, self.hint_button, self.answer_button, None, spacing=6)
        layout.addLayout(footer)

        self.feedback = label("", "feedback", wrap=True)
        self.feedback.setTextFormat(Qt.RichText)
        self.feedback.setHidden(True)
        layout.addWidget(self.feedback)
        #: Extra detail under the feedback (a net comparison).
        self.detail_host = QVBoxLayout()
        self.detail_host.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.detail_host)

        self.hint_label = self._note("Hint", task.hint or "")
        layout.addWidget(self.hint_label)
        self.solution_label = self._note("Answer", "")
        layout.addWidget(self.solution_label)
        # Open questions: after the model answer, say how you did.
        self.assess_row = QWidget()
        self.assess_row.setLayout(hbox(label("How did you do?", "muted"),
                                       button("I had it", lambda: self.assess(True)),
                                       button("Not quite", lambda: self.assess(False)),
                                       None, spacing=6))
        self.assess_row.setHidden(True)
        layout.addWidget(self.assess_row)

        editor.changed.connect(self._edited)

    def _note(self, title: str, text: str) -> QFrame:
        note = QFrame()
        note.setObjectName("taskNote")
        note_layout = QVBoxLayout(note)
        note_layout.setContentsMargins(10, 8, 10, 9)
        note_layout.setSpacing(3)
        note_layout.addWidget(label(title.upper(), "taskCaption"))
        note.body = MarkdownLabel(text, self.folder)
        note_layout.addWidget(note.body)
        note.setHidden(True)
        return note

    # -- feedback ------------------------------------------------------------------------
    def _edited(self) -> None:
        # Feedback is about the answer as it was: it goes when you change it.
        if self.status in (CORRECT, PARTIAL, INCORRECT) or not self.feedback.isHidden():
            self.set_status(None)
            self.feedback.setHidden(True)
            self._clear_detail()
            self.editor.show_result(None)
        self.changed.emit(self.task)

    def set_status(self, status: str | None) -> None:
        self.status = status
        shown = STATUS.get(status)
        self.chip.setHidden(shown is None)
        if shown is not None:
            text, colour = shown
            self.chip.setText(("✓ " if colour == "good" else "") + text)
            self.chip.setProperty("state", colour)
            self.chip.style().unpolish(self.chip)
            self.chip.style().polish(self.chip)
        self.setProperty("state", (shown or ("", ""))[1])
        self.style().unpolish(self)
        self.style().polish(self)

    def show_checking(self) -> None:
        self.feedback.setText("Checking…")
        self.feedback.setProperty("state", "")
        self._repolish(self.feedback)
        self.feedback.setHidden(False)
        self.check_button.setEnabled(False)

    def show_result(self, result, detail: QWidget | None = None) -> None:
        self.check_button.setEnabled(True)
        self._clear_detail()
        status = result.status
        icon = {CORRECT: "✓", PARTIAL: "◐", INCORRECT: "✕"}.get(status, "")
        self.feedback.setText(f"<b>{icon}</b>&nbsp; {escape(result.message)}" if icon
                              else escape(result.message))
        self.feedback.setProperty("state", STATUS.get(status, ("", ""))[1])
        self._repolish(self.feedback)
        self.feedback.setHidden(False)
        self.set_status(status if status != UNKNOWN else self.status)
        self.editor.show_result(result)
        if detail is not None:
            self.detail_host.addWidget(detail)

    def _clear_detail(self) -> None:
        while self.detail_host.count():
            item = self.detail_host.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()

    @staticmethod
    def _repolish(widget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    # -- hint and answer -------------------------------------------------------------------
    def toggle_hint(self) -> None:
        self.hint_label.setHidden(not self.hint_label.isHidden())
        self.hint_button.setText("Hide hint" if not self.hint_label.isHidden() else "Hint")

    def reveal_solution(self) -> None:
        self.solution_requested.emit(self.task)

    def show_solution(self, text: str) -> None:
        if not text:
            text = "No model answer for this one."
        self.solution_label.body.set_markdown(text)
        self.solution_label.setHidden(False)
        self.answer_button.setHidden(True)
        if self.task.type == "open" and self.status != "done":
            self.assess_row.setHidden(False)

    def assess(self, had_it: bool) -> None:
        self.assess_row.setHidden(True)
        self.set_status("done" if had_it else INCORRECT)
        self.changed.emit(self.task)


def make_editor(task, activities=None, net_tab: str = "Your net") -> Editor:
    kind = task.type
    if kind == "set":
        return LineEditor("e.g. {a, b}", set_preview)
    if kind == "trace":
        return LineEditor("e.g. register, send letter", trace_preview)
    if kind == "number":
        return LineEditor("a number, e.g. 0.75 or 3/4", number_preview)
    if kind == "text":
        return LineEditor("your answer")
    if kind == "choice":
        return ChoiceEditor(task.options)
    if kind == "yesno":
        return YesNoEditor()
    if kind == "footprint":
        return FootprintEditor(activities or [])
    if kind == "net":
        return NetEditor(net_tab)
    return TextEditor()


def debounce(parent, delay: int, slot) -> QTimer:
    timer = QTimer(parent)
    timer.setSingleShot(True)
    timer.setInterval(delay)
    timer.timeout.connect(slot)
    return timer
