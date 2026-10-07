"""The exercise panel: the question beside the canvas, and one Check button.

An *exercise* is an ordinary folder with a ``question`` file (see
:func:`.workspace.exercise_files`).  Opening one shows this panel between
the sidebar and the page:

* **the question** -- ``question.md`` rendered as Markdown (tables, and maths
  between ``$…$`` or ``$$…$$`` typeset by :mod:`.mathtext`), or the
  ``question.png`` / ``question.pdf`` itself;
* **Check** -- with an ``answer.pnml``, compares your net with it on
  behaviour (:func:`cpnpy.mining.compare_nets.compare_nets`): same complete
  traces or not, the shortest traces that differ both ways (each one can be
  replayed in the token game), and your net's soundness; otherwise it
  reveals the worked answer, ``answer.md``;
* **Reveal all** -- shows every analysis result the exercise hides
  (:mod:`.concealment`).

The window does the work (it knows your net); the panel only shows it.
:class:`NetComparisonView` is also what *Compare nets…* shows outside
exercises.
"""

from __future__ import annotations

import re
from html import escape
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QPixmap, QTextDocument
from PySide6.QtWidgets import (
    QComboBox, QFrame, QLabel, QSizePolicy, QSplitter, QTableWidget, QTextBrowser, QToolButton,
    QVBoxLayout, QWidget,
)

from . import style
from .mathtext import MATH_FONT, render
from .widgets import Card, Verdict, button, hbox, label, scroll, status_for


# ---------------------------------------------------------------------------
# Markdown with maths
# ---------------------------------------------------------------------------
_DISPLAY = re.compile(r"\$\$(.+?)\$\$", re.S)
_INLINE = re.compile(r"(?<![\\$])\$([^$\n]+?)\$")


def _maths(source: str, size: int) -> str:
    try:
        body = render(source.strip())
    except ValueError:                 # not in the supported subset: show it as written
        body = escape(source.strip())
    return f"<span style='font-family: {MATH_FONT}; font-size: {size}px'>{body}</span>"


def markdown_html(text: str) -> str:
    """Markdown (GitHub flavour: tables, lists, emphasis) with ``$…$`` maths, as HTML."""
    formulas: list[str] = []

    def stash(match, size: int) -> str:
        formulas.append(_maths(match.group(1), size))
        return f"MATHXPLACEHOLDER{len(formulas) - 1}X"

    text = _DISPLAY.sub(lambda m: "\n\n" + stash(m, 17) + "\n\n", text)
    text = _INLINE.sub(lambda m: stash(m, 15), text)
    document = QTextDocument()
    document.setMarkdown(text, QTextDocument.MarkdownDialectGitHub)
    html = document.toHtml()
    return re.sub(r"MATHXPLACEHOLDER(\d+)X", lambda m: formulas[int(m.group(1))], html)


def _browser() -> QTextBrowser:
    browser = QTextBrowser()
    browser.setObjectName("plainBrowser")        # borderless inside its card
    browser.setOpenExternalLinks(True)
    browser.setFrameShape(QFrame.NoFrame)
    return browser


def show_document(browser: QTextBrowser, path: Path) -> None:
    """A Markdown (or plain text) file in ``browser``, images relative to its folder."""
    text = path.read_text(encoding="utf-8", errors="replace")
    browser.document().setBaseUrl(QUrl.fromLocalFile(str(path.parent) + "/"))
    browser.setSearchPaths([str(path.parent)])
    if path.suffix.lower() == ".md":
        browser.setHtml(markdown_html(text))
    else:
        browser.setPlainText(text)


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


# ---------------------------------------------------------------------------
# The panel
# ---------------------------------------------------------------------------
class ExercisePanel(QFrame):
    """Question, Check and Reveal all (see the module docstring)."""

    check_requested = Signal()
    close_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("exercisePanel")
        self.setMinimumWidth(280)
        self.setMaximumWidth(580)
        self.files = None
        self.concealment = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 12, 14)
        layout.setSpacing(10)

        # The question: a card with the exercise's name and a close button.
        question_card = Card()
        caption = label("EXERCISE", "sidebarCaption")
        self.title = label("", "exerciseTitle", wrap=True)
        close = QToolButton()
        close.setObjectName("exerciseClose")
        close.setText("✕")
        close.setToolTip("Close the exercise (results are no longer hidden)")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.close_requested.emit)
        heading = QVBoxLayout()
        heading.setSpacing(2)
        heading.addWidget(caption)
        heading.addWidget(self.title)
        top = hbox(spacing=6)
        top.addLayout(heading, 1)
        top.addWidget(close, 0, Qt.AlignTop)
        question_card.add(top)
        self.question_host = QVBoxLayout()
        self.question_host.setContentsMargins(0, 0, 0, 0)
        question_card.add(self.question_host, 1)

        # Check and Reveal all.
        actions = Card(padding=12)
        self.check_button = button("Check", self.check_requested.emit, kind="primary")
        self.reveal_button = button("Reveal all", self._reveal_all,
                                    tooltip="Show every analysis result this exercise hides")
        actions.add(hbox(self.check_button, self.reveal_button, None))
        self.hint = label("", "muted", wrap=True)
        actions.add(self.hint)

        # What Check found (shown once there is something).
        self.result_card = Card("Result", padding=12)
        self.result_host = QVBoxLayout()
        self.result_host.setContentsMargins(0, 0, 6, 0)
        result = QWidget()
        result.setLayout(self.result_host)
        self.result_area = scroll(result)
        self.result_card.add(self.result_area, 1)

        lower = QWidget()
        lower.setLayout(QVBoxLayout())
        lower.layout().setContentsMargins(0, 0, 0, 0)
        lower.layout().setSpacing(10)
        lower.layout().addWidget(actions)
        lower.layout().addWidget(self.result_card, 1)
        lower.layout().addStretch(0)
        self.result_card.setHidden(True)
        splitter = QSplitter(Qt.Vertical)
        self.splitter = splitter
        splitter.addWidget(question_card)
        splitter.addWidget(lower)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)
        splitter.setStyleSheet("QSplitter::handle { background: transparent; }")
        layout.addWidget(splitter, 1)

    # -- content ---------------------------------------------------------------------------
    def set_exercise(self, files, concealment) -> None:
        self.files, self.concealment = files, concealment
        self.title.setText(files.name)
        self._clear(self.question_host)
        self.clear_result()
        total = sum(self.splitter.sizes())
        if total:                                  # the question gets the room again
            self.splitter.setSizes([int(total * 0.75), int(total * 0.25)])
        question = files.question
        suffix = question.suffix.lower()
        self.title.setHidden(False)
        if suffix in (".md", ".txt"):
            self.question = _browser()
            show_document(self.question, question)
            self.question_host.addWidget(self.question)
            # A question with a heading of its own names itself.
            first = question.read_text(encoding="utf-8", errors="replace").lstrip()
            self.title.setHidden(suffix == ".md" and first.startswith("# "))
        elif suffix in (".png", ".jpg", ".jpeg"):
            picture = QLabel()
            pixmap = QPixmap(str(question))
            picture.setPixmap(pixmap.scaledToWidth(500, Qt.SmoothTransformation)
                              if pixmap.width() > 500 else pixmap)
            picture.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
            self.question = picture
            self.question_host.addWidget(scroll(picture))
        else:
            self.question = self._pdf(question)
            self.question_host.addWidget(self.question)
        if files.answer_net is not None:
            self.check_button.setText("Check")
            self.check_button.setToolTip("Compare your net with the model answer")
            self.hint.setText("Check compares your net with the model answer on behaviour.")
        elif files.answer_text is not None:
            self.check_button.setText("Show answer")
            self.check_button.setToolTip("Reveal the worked answer")
            self.hint.setText("Work it out first, then show the worked answer.")
        else:
            self.check_button.setText("Check")
            self.check_button.setEnabled(False)
            self.hint.setText("This exercise has no answer to check against.")
        if files.answer_net is not None or files.answer_text is not None:
            self.check_button.setEnabled(True)
        self._follow()
        concealment.changed.connect(self._follow)

    def _pdf(self, path: Path) -> QWidget:
        try:
            from PySide6.QtPdf import QPdfDocument
            from PySide6.QtPdfWidgets import QPdfView
        except ImportError:
            host = QWidget()
            host.setLayout(QVBoxLayout())
            host.layout().addWidget(label("The question is a PDF.", wrap=True))
            host.layout().addWidget(button(f"Open {path.name}", lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(path))), kind="primary"))
            host.layout().addStretch(1)
            return host
        view = QPdfView()
        document = QPdfDocument(view)
        document.load(str(path))
        view.setDocument(document)
        view.setPageMode(QPdfView.PageMode.MultiPage)
        view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        return view

    def _follow(self) -> None:
        if self.concealment is not None:
            self.reveal_button.setEnabled(self.concealment.anything_hidden)
            self.reveal_button.setText("Reveal all" if self.concealment.anything_hidden
                                       else "All revealed")

    def _reveal_all(self) -> None:
        if self.concealment is not None:
            self.concealment.reveal_all()

    @staticmethod
    def _clear(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()

    def clear_result(self) -> None:
        self._clear(self.result_host)
        self.result_card.setHidden(True)

    def show_result(self, *widgets: QWidget) -> None:
        self.clear_result()
        for widget in widgets:
            self.result_host.addWidget(widget)
        self.result_host.addStretch(1)
        if self.result_card.isHidden():
            # Room for the result: the question keeps a good part, scrollable.
            self.result_card.setHidden(False)
            total = sum(self.splitter.sizes()) or 800
            self.splitter.setSizes([int(total * 0.42), int(total * 0.58)])

    def answer_widget(self) -> QWidget:
        """``answer.md``, rendered."""
        browser = _browser()
        show_document(browser, self.files.answer_text)
        browser.setMinimumHeight(260)
        self.answer_browser = browser
        return browser
