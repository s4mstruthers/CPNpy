"""Exercise mode: a quiet place to work through an exercise pack.

Opening an exercise (or a pack of them) swaps the whole window for this
view, the way a log and a net each have a page of their own::

    +--------------------------------------------------------------------------+
    | ‹ Overview   Demo exercises · 2 Soundness      ● ● ◐ ○   ‹  2 / 4  ›  Exit |
    +-------------------------------+------------------------------------------+
    | SOUNDNESS                     |  [ Given net | Your net ]                |
    | Exercise 2.1 — Spot the flaw  |                                          |
    |                               |     the net editor, the log, the         |
    | The net shows how …           |     transition system: whatever the      |
    | a. Is the net a WF-net?       |     exercise gives                       |
    |  ┌ YOUR ANSWER ──── ✓ Correct ┐|                                          |
    |  │ (Yes) ( No )               │|                                          |
    |  │ [Check]  Hint  Show answer │|                                          |
    |  └────────────────────────────┘|                                          |
    +-------------------------------+------------------------------------------+

* **The worksheet** (left) is ``question.md`` top to bottom, with an answer
  box wherever the author put one (see :mod:`cpnpy.teaching.sheet` and
  :mod:`.answer_boxes`).  Answers are saved as you type, in the exercise's
  folder, and checked on request.
* **The materials** (right) are what the exercise gives: the log, the
  transition system, the given net, and your net for each *draw a net*
  answer.  Results that would give answers away (soundness, the footprint,
  discovered models, regions …) are hidden until revealed
  (:mod:`.concealment`).
* **The top bar** goes back to the pack's overview, steps through the
  exercises, and shows how far you are (one dot per exercise).

Nothing here touches the sidebar's documents: *Exit* returns to the window
exactly as it was.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMenu, QMessageBox, QSizePolicy, QSplitter, QStackedWidget,
    QToolButton, QVBoxLayout, QWidget,
)

from ...teaching.checks import CORRECT, INCORRECT, PARTIAL, Context, Result, TaskError
from ...teaching.checks import check as check_answer
from ...teaching.checks import footprint_of, model_answer_text
from ...teaching.pack import Exercise, Pack, load_pack
from .answer_boxes import TaskCard, debounce, make_editor
from .concealment import Concealment
from .markdown_view import MarkdownLabel
from .widgets import SegmentedControl, button, hbox, label, scroll
from .workers import run_in_background

#: How long after the last keystroke an answer is saved (milliseconds).
SAVE_DELAY = 400
#: How long after the last edit your net is saved.
NET_SAVE_DELAY = 800


def _tool(text: str, tooltip: str, slot, name: str = "exerciseBarButton") -> QToolButton:
    tool = QToolButton()
    tool.setObjectName(name)
    tool.setText(text)
    tool.setToolTip(tooltip)
    tool.setCursor(Qt.PointingHandCursor)
    tool.clicked.connect(slot)
    return tool


# ---------------------------------------------------------------------------
# The mode: top bar, overview, one exercise at a time
# ---------------------------------------------------------------------------
class ExerciseMode(QWidget):
    """The whole window while doing exercises (see the module docstring)."""

    exit_requested = Signal()
    status = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("exerciseMode")
        self.pack: Pack | None = None
        self.index: int | None = None
        self.view: ExerciseView | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_bar())
        self.stack = QStackedWidget()
        self.home = QWidget()
        self.home_area = scroll(self.home)
        self.stack.addWidget(self.home_area)
        root.addWidget(self.stack, 1)

    # -- the bar ---------------------------------------------------------------------------
    def _build_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("exerciseBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        self.overview_button = _tool("‹  Overview", "All the exercises of this pack",
                                     self.show_home)
        layout.addWidget(self.overview_button)
        self.where = label("", "exerciseWhere")
        self.where.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self.where, 1)
        self.dots_host = QWidget()
        self.dots = QHBoxLayout(self.dots_host)
        self.dots.setContentsMargins(0, 0, 0, 0)
        self.dots.setSpacing(5)
        layout.addWidget(self.dots_host)
        layout.addSpacing(10)
        self.previous_button = _tool("‹", "Previous exercise", lambda: self.step(-1))
        self.position = label("", "exercisePosition")
        self.next_button = _tool("›", "Next exercise", lambda: self.step(1))
        for widget in (self.previous_button, self.position, self.next_button):
            layout.addWidget(widget)
        self.more_button = _tool("⋯", "More", lambda: None)
        self.more_button.setPopupMode(QToolButton.InstantPopup)
        self.more_menu = QMenu(self.more_button)
        self.more_menu.aboutToShow.connect(self._fill_more_menu)
        self.more_button.setMenu(self.more_menu)
        layout.addWidget(self.more_button)
        self.exit_button = button("Exit", self.leave, tooltip="Back to your folder and files")
        self.exit_button.setObjectName("exerciseExit")
        layout.addWidget(self.exit_button)
        return bar

    def _fill_more_menu(self) -> None:
        menu = self.more_menu
        menu.clear()
        view = self.view if self.stack.currentWidget() is self.view else None
        if view is not None:
            reveal = menu.addAction("Reveal Every Hidden Result", view.concealment.reveal_all)
            reveal.setEnabled(view.concealment.anything_hidden)
            menu.addAction("Start This Exercise Again…", self.reset_exercise)
            menu.addAction(_reveal_label(), lambda: _reveal(view.exercise.folder))
            menu.addSeparator()
        elif self.pack is not None:
            menu.addAction(_reveal_label(), lambda: _reveal(self.pack.root))
            menu.addSeparator()
        menu.addAction("Writing Exercise Packs", lambda: open_help("exercise-packs"))

    def _update_bar(self) -> None:
        in_exercise = self.view is not None and self.stack.currentWidget() is self.view
        count = len(self.pack.exercises) if self.pack else 0
        self.overview_button.setVisible(in_exercise and count > 1)
        for widget in (self.previous_button, self.position, self.next_button, self.dots_host):
            widget.setVisible(in_exercise and count > 1)
        if self.pack is None:
            return
        if in_exercise:
            exercise = self.pack.exercises[self.index]
            chapter = self.pack.chapter(exercise)
            self.where.setText(" · ".join(x for x in (self.pack.title, chapter) if x))
            self.position.setText(f"{self.index + 1} / {count}")
            self.previous_button.setEnabled(self.index > 0)
            self.next_button.setEnabled(self.index < count - 1)
        else:
            self.where.setText(self.pack.title)
        self._fill_dots()

    def _fill_dots(self) -> None:
        while self.dots.count():
            item = self.dots.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if self.pack is None or len(self.pack.exercises) > 24:
            return                                     # too many to show as dots
        for index, exercise in enumerate(self.pack.exercises):
            state = exercise.summary().state
            dot = _tool("", f"{exercise.title} — " + {"done": "done", "started": "started",
                                                       "new": "not started"}[state],
                        lambda _=False, i=index: self.open_index(i), "progressDot")
            dot.setProperty("state", state)
            dot.setProperty("current", index == self.index and self.view is not None
                            and self.stack.currentWidget() is self.view)
            dot.setFixedSize(12, 12)
            self.dots.addWidget(dot)

    # -- opening ---------------------------------------------------------------------------
    def open_pack(self, root: str | Path, start: str | Path | None = None) -> bool:
        """Show the pack at ``root``: its overview, or ``start`` (an exercise in it)."""
        self.close_view()
        self.pack = load_pack(root)
        if not self.pack.exercises:
            self.pack = None
            return False
        self._build_home()
        index = self.pack.index(start) if start is not None else None
        if index is None and len(self.pack.exercises) == 1:
            index = 0
        if index is not None:
            self.open_index(index)
        else:
            self.show_home()
        return True

    def open_index(self, index: int) -> None:
        if self.pack is None or not 0 <= index < len(self.pack.exercises):
            return
        if self.view is not None and self.index == index:
            self.stack.setCurrentWidget(self.view)
            self._update_bar()
            return
        self.close_view()
        self.index = index
        # Read it again: the author may have changed the files meanwhile.
        exercise = Exercise(self.pack.exercises[index].files)
        self.pack.exercises[index] = exercise
        self.view = ExerciseView(exercise, self.pack.chapter(exercise),
                                 has_next=index < len(self.pack.exercises) - 1)
        self.view.status.connect(self.status.emit)
        self.view.progress_changed.connect(self._update_bar)
        self.view.next_requested.connect(lambda: self.step(1))
        self.stack.addWidget(self.view)
        self.stack.setCurrentWidget(self.view)
        self._update_bar()

    def step(self, delta: int) -> None:
        if self.index is not None:
            self.open_index(self.index + delta)

    def show_home(self) -> None:
        if self.view is not None:
            self.view.flush()
        self._build_home()
        self.stack.setCurrentWidget(self.home_area)
        self._update_bar()

    def close_view(self) -> None:
        if self.view is not None:
            self.view.flush()
            self.view.shutdown()
            self.stack.removeWidget(self.view)
            self.view.deleteLater()
            self.view = None

    def leave(self) -> None:
        self.close_view()
        self.exit_requested.emit()

    def reset_exercise(self) -> None:
        view = self.view
        if view is None:
            return
        answer = QMessageBox.question(
            self, "Start again", f"Start “{view.exercise.title}” again? Your answers and "
            "nets for it are deleted.", QMessageBox.Yes | QMessageBox.Cancel)
        if answer != QMessageBox.Yes:
            return
        index = self.index
        view.discard()
        self.close_view()
        view.exercise.reset()
        self.index = None
        self.open_index(index)

    # -- the overview -------------------------------------------------------------------------
    def _build_home(self) -> None:
        # A new page each time (the scroll area deletes the old one).
        self.home = QWidget()
        self.home.setObjectName("exerciseHome")
        layout = QVBoxLayout(self.home)
        pack = self.pack
        column = QVBoxLayout()
        column.setSpacing(10)
        column.setContentsMargins(0, 32, 0, 40)
        column.addWidget(label("EXERCISES", "sheetChapter"))
        column.addWidget(label(pack.title, "sheetTitle", wrap=True))
        if pack.intro:
            column.addWidget(MarkdownLabel(pack.intro, pack.root))
        summaries = [e.summary() for e in pack.exercises]
        done = sum(s.state == "done" for s in summaries)
        column.addWidget(label(f"{done} of {len(summaries)} exercises done", "muted"))
        upcoming = next((i for i, s in enumerate(summaries) if s.state != "done"), 0)
        start = button("Continue" if any(s.tried for s in summaries) else "Start",
                       lambda: self.open_index(upcoming), kind="primary")
        column.addLayout(hbox(start, None))
        column.addSpacing(12)
        number = 0
        for chapter, exercises in pack.chapters():
            if chapter:
                column.addSpacing(6)
                column.addWidget(label(chapter.upper(), "sectionLabel"))
            for exercise in exercises:
                summary = summaries[number]
                column.addWidget(ExerciseRow(exercise, summary, lambda i=number:
                                             self.open_index(i)))
                number += 1
        column.addStretch(1)
        holder = QWidget()
        holder.setLayout(column)
        holder.setMaximumWidth(720)
        holder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.addLayout(_centred(holder))
        self.home_area.setWidget(self.home)


def _centred(widget: QWidget) -> QHBoxLayout:
    """``widget`` as wide as it may be (its maximum width), in the middle."""
    row = QHBoxLayout()
    row.addStretch(1)
    row.addWidget(widget, 100)
    row.addStretch(1)
    return row


class ExerciseRow(QFrame):
    """An exercise in the overview: its state, title and how far you got."""

    def __init__(self, exercise: Exercise, summary, open_it) -> None:
        super().__init__()
        self.setObjectName("exerciseRow")
        self.setCursor(Qt.PointingHandCursor)
        self.open_it = open_it
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(12)
        mark = label({"done": "✓", "started": "◐", "new": "○"}[summary.state], "rowMark")
        mark.setProperty("state", summary.state)
        mark.setFixedWidth(18)
        layout.addWidget(mark)
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(label(exercise.title, "rowTitle", wrap=True))
        detail = (f"{summary.done} of {summary.total} answers done" if summary.total
                  else "Read and try it")
        if exercise.error:
            detail = "This exercise has a mistake in it: " + exercise.error
        text.addWidget(label(detail, "muted", wrap=True))
        layout.addLayout(text, 1)
        layout.addWidget(label("›", "rowChevron"))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.open_it()
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# One exercise
# ---------------------------------------------------------------------------
class ExerciseView(QWidget):
    """The worksheet beside the exercise's materials."""

    status = Signal(str)
    progress_changed = Signal()
    next_requested = Signal()

    def __init__(self, exercise: Exercise, chapter: str = "", has_next: bool = False,
                 parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("exerciseView")
        self.exercise = exercise
        self.context = Context(exercise)
        self.concealment = Concealment(self)
        self.progress = exercise.load_progress()
        self.cards: dict[str, TaskCard] = {}
        #: Material tabs: (name, page); and the net page of each net task.
        self.materials: list[tuple[str, QWidget]] = []
        self.net_pages: dict[str, QWidget] = {}
        self.given_net_page = None
        self._net_timers: dict[str, object] = {}
        self._save_timer = debounce(self, SAVE_DELAY, self.save_progress)

        self._build_materials()
        worksheet = self._build_worksheet(chapter, has_next)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if self.materials:
            splitter = QSplitter(Qt.Horizontal)
            splitter.setObjectName("exerciseSplitter")
            splitter.setHandleWidth(1)
            splitter.addWidget(worksheet)
            splitter.addWidget(self.material_area)
            splitter.setStretchFactor(0, 2)
            splitter.setStretchFactor(1, 3)
            splitter.setSizes([460, 760])
            splitter.setChildrenCollapsible(False)
            self.splitter = splitter
            layout.addWidget(splitter)
        else:
            layout.addWidget(worksheet)
        for card in self.cards.values():
            self._restore(card)

    # -- materials ----------------------------------------------------------------------------
    def _build_materials(self) -> None:
        files = self.exercise.files
        if files.log is not None:
            page = self._log_page(files.log)
            if page is not None:
                self.materials.append(("Log", page))
        if files.ts is not None:
            page = self._ts_page(files.ts)
            if page is not None:
                self.materials.append(("Transition system", page))
        net_tasks = self.exercise.net_tasks()
        if files.net is not None and (not net_tasks or any(
                t.type == "trace" for t in self.exercise.sheet.tasks)
                or all(self.exercise.start_net(t) != files.net for t in net_tasks)):
            page = self._net_page(files.net, None, editable=False)
            if page is not None:
                self.given_net_page = page
                self.materials.append(("Given net", page))
        for number, task in enumerate(net_tasks, 1):
            name = "Your net" if len(net_tasks) == 1 else f"Your net {number}"
            page = self._net_page(self.exercise.start_net(task),
                                  self.exercise.answer_net_path(task), editable=True,
                                  task=task)
            if page is not None:
                self.net_pages[task.id] = page
                self.materials.append((name, page))
        self.material_area = QWidget()
        self.material_area.setObjectName("materials")
        column = QVBoxLayout(self.material_area)
        column.setContentsMargins(0, 10, 0, 0)
        column.setSpacing(6)
        self.tab_row = hbox(margins=(16, 0, 16, 0))
        column.addLayout(self.tab_row)
        self.material_stack = QStackedWidget()
        for _, page in self.materials:
            self.material_stack.addWidget(scroll(page, horizontal=True))
        column.addWidget(self.material_stack, 1)
        self.material_tabs = None
        self._make_tabs()
        # Your net first when there is one to draw: that is where the work is.
        if self.net_pages and len(self.materials) > 1 and not self.exercise.files.log \
                and not self.exercise.files.ts:
            self.show_material(next(iter(self.net_pages.values())))

    def _make_tabs(self) -> None:
        """One tab per material (again after a discovered model was added)."""
        if self.material_tabs is not None:
            self.tab_row.removeWidget(self.material_tabs)
            self.material_tabs.deleteLater()
        while self.tab_row.count():
            self.tab_row.takeAt(0)
        self.material_tabs = SegmentedControl([name for name, _ in self.materials],
                                              compact=True)
        self.material_tabs.setVisible(len(self.materials) > 1)
        self.material_tabs.changed.connect(self.material_stack.setCurrentIndex)
        self.tab_row.addWidget(self.material_tabs)
        self.tab_row.addStretch(1)

    def show_material(self, page: QWidget) -> None:
        for index, (_, candidate) in enumerate(self.materials):
            if candidate is page:
                self.material_tabs.set_index(index)
                self.material_stack.setCurrentIndex(index)

    def _log_page(self, path: Path):
        from ...mining.csv_import import guess_mapping, read_csv, sniff
        from ...mining.log import EventLog, parse_simple_log
        from ...mining.xes import read_xes
        from .documents import LogDocument
        from .log_page import LogPage
        try:
            lower = path.name.lower()
            if lower.endswith(".txt"):
                text = path.read_text(encoding="utf-8", errors="replace")
                document = LogDocument(EventLog.from_simple_log(parse_simple_log(text), "L"),
                                       path=str(path), notation=text.strip())
            elif lower.endswith(".csv"):
                document = LogDocument(read_csv(str(path), guess_mapping(sniff(str(path))[1])),
                                       path=str(path))
            else:
                document = LogDocument(read_xes(str(path)), path=str(path))
        except Exception as error:  # noqa: BLE001
            self.status.emit(f"Could not read {path.name}: {error}")
            return None
        self.log_document = document
        page = LogPage(document)
        page.edit_button.hide()
        page.header.hide()
        page.open_model.connect(self._open_model)
        page.status.connect(self.status.emit)
        page.set_concealment(self.concealment)
        return page

    def _ts_page(self, path: Path):
        from ...mining.transition_system import parse_transition_system
        from .documents import TransitionSystemDocument
        from .regions_view import TransitionSystemPage
        try:
            ts = parse_transition_system(path.read_text(encoding="utf-8", errors="replace"),
                                         "Transition system")
        except Exception as error:  # noqa: BLE001
            self.status.emit(f"Could not read {path.name}: {error}")
            return None
        # No path: trying changes to the system never writes over the given file.
        page = TransitionSystemPage(TransitionSystemDocument(ts))
        page.header.hide()
        page.open_model.connect(self._open_model)
        page.status.connect(self.status.emit)
        page.set_concealment(self.concealment)
        return page

    def _net_page(self, start: Path | None, target: Path | None, editable: bool, task=None):
        from ...mining.pnml import read_pnml
        from ...model.plain import from_petri_net, new_plain_net
        from .documents import CpnDocument
        from .petri_page import PetriNetPage
        source = target if target is not None and target.exists() else start
        try:
            if source is not None:
                petri = read_pnml(str(source))
                petri.name = source.stem
                net = from_petri_net(petri)
            else:
                net = new_plain_net(target.stem if target is not None else "my answer")
        except Exception as error:  # noqa: BLE001
            self.status.emit(f"Could not read {source.name}: {error}")
            return None
        path = str(target) if target is not None and target.exists() else None
        page = PetriNetPage(CpnDocument(net, path=path))
        page.header.hide()
        page.status.connect(self.status.emit)
        page.set_concealment(self.concealment)
        if editable:
            page.edited.connect(lambda t=task, p=page, target=target: self._net_edited(t, p,
                                                                                     target))
        else:
            # The given net stays as it is: play it, but not change it.
            page.mode_switch.set_index(1)
            page.mode_switch.buttons[0].hide()
        return page

    def _open_model(self, document) -> None:
        """A model discovered from the log (or synthesised): one more tab."""
        from .model_page import ModelPage
        logs = [self.log_document] if getattr(self, "log_document", None) else []
        page = ModelPage(document, lambda: logs)
        page.header.hide()
        if hasattr(page, "set_concealment"):
            page.set_concealment(self.concealment)
        self.materials.append((document.name, page))
        self.material_stack.addWidget(scroll(page, horizontal=True))
        self._make_tabs()
        self.show_material(page)

    def _net_edited(self, task, page, target: Path) -> None:
        timer = self._net_timers.get(task.id)
        if timer is None:
            timer = debounce(self, NET_SAVE_DELAY, lambda: self._save_net(page, target))
            self._net_timers[task.id] = timer
        timer.start()
        card = self.cards.get(task.id)
        if card is not None and card.status in (CORRECT, PARTIAL, INCORRECT):
            card.editor.changed.emit()             # the old verdict no longer applies

    def _save_net(self, page, target: Path) -> None:
        if not page.document.dirty and page.document.path:
            return
        if not page.document.path:
            page._take_file_name(target)
        if not page._write(target, quiet=True):
            self.status.emit(f"Could not save {target.name}: "
                             f"{getattr(page, 'save_error', 'unknown error')}")

    # -- the worksheet ----------------------------------------------------------------------------
    def _build_worksheet(self, chapter: str, has_next: bool) -> QWidget:
        sheet = self.exercise.sheet
        folder = self.exercise.folder
        column = QVBoxLayout()
        column.setContentsMargins(0, 26, 0, 40)
        column.setSpacing(12)
        if chapter:
            column.addWidget(label(chapter.split(" › ")[-1].upper(), "sheetChapter"))
        self.title = label(self.exercise.title, "sheetTitle", wrap=True)
        column.addWidget(self.title)
        if self.exercise.error:
            problem = label("This exercise has a mistake in it, so its answer boxes are "
                            "missing: " + self.exercise.error, "sheetProblem", wrap=True)
            column.addWidget(problem)
        question = self.exercise.files.question
        if question.suffix.lower() not in (".md", ".txt"):
            column.addWidget(self._picture_or_pdf(question))
        net_names = {task_id: name for name, page in self.materials
                     for task_id, net_page in self.net_pages.items() if net_page is page}
        for block in sheet.blocks:
            if isinstance(block, str):
                column.addWidget(MarkdownLabel(block, folder))
                continue
            card = self._card(block, net_names.get(block.id, "Your net"))
            if card is not None:
                column.addWidget(card)
        if self.exercise.files.answer_text is not None and not any(
                t.type == "open" and t.id == "answer" for t in sheet.tasks):
            column.addWidget(self._worked_answer())
        self.summary_label = label("", "muted")
        footer = hbox(self.summary_label, None, spacing=8)
        if has_next:
            footer.addWidget(button("Next exercise  ›", self.next_requested.emit,
                                    kind="primary"))
        column.addSpacing(8)
        column.addLayout(footer)
        column.addStretch(1)
        holder = QWidget()
        holder.setObjectName("sheetColumn")
        holder.setLayout(column)
        holder.setMaximumWidth(720)
        holder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        page = QWidget()
        page.setObjectName("worksheet")
        outer = QHBoxLayout(page)
        outer.setContentsMargins(26, 0, 22, 0)
        outer.addWidget(holder)
        if not self.materials:
            outer.removeWidget(holder)
            outer.addLayout(_centred(holder))
        area = scroll(page)
        area.setObjectName("worksheetArea")
        area.setMinimumWidth(340)
        self._update_summary()
        return area

    def _card(self, task, net_name: str) -> TaskCard | None:
        activities = None
        if task.type == "footprint":
            try:
                activities = footprint_of(self.context, task).activities
            except Exception as error:  # noqa: BLE001
                return self._broken(task, error)
        editor = make_editor(task, activities, net_name)
        card = TaskCard(task, editor, self.exercise.folder)
        if task.type == "net":
            page = self.net_pages.get(task.id)
            editor.go_to_net.connect(lambda p=page: p is not None and self.show_material(p))
        if task.type == "trace" and self.given_net_page is not None:
            editor.row.addWidget(button("Play in net", lambda t=task, e=editor:
                                        self.play_trace(e.value()),
                                        tooltip="Fire these steps in the given net's token "
                                                "game, as far as they go"))
        card.check_requested.connect(self.check)
        card.changed.connect(self._answer_changed)
        card.solution_requested.connect(self._show_solution)
        self.cards[task.id] = card
        return card

    def _broken(self, task, error) -> QWidget:
        return label(f"This answer box cannot be shown: {error}", "sheetProblem", wrap=True)

    def _picture_or_pdf(self, path: Path) -> QWidget:
        if path.suffix.lower() == ".pdf":
            try:
                from PySide6.QtPdf import QPdfDocument
                from PySide6.QtPdfWidgets import QPdfView
            except ImportError:
                return button(f"Open {path.name}", lambda: QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(path))), kind="primary")
            view = QPdfView()
            document = QPdfDocument(view)
            document.load(str(path))
            view.setDocument(document)
            view.setPageMode(QPdfView.PageMode.MultiPage)
            view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            view.setMinimumHeight(520)
            self._pdf = document
            return view
        picture = QLabel()
        pixmap = QPixmap(str(path))
        picture.setPixmap(pixmap.scaledToWidth(640, Qt.SmoothTransformation)
                          if pixmap.width() > 640 else pixmap)
        return picture

    def _worked_answer(self) -> QWidget:
        text = self.exercise.files.answer_text.read_text(encoding="utf-8", errors="replace")
        holder = QFrame()
        holder.setObjectName("taskNote")
        column = QVBoxLayout(holder)
        column.setContentsMargins(12, 10, 12, 10)
        body = MarkdownLabel(text, self.exercise.folder)
        body.setHidden(True)
        show = button("Show the worked answer", kind="ghost")
        show.clicked.connect(lambda: (body.setHidden(False), show.setHidden(True)))
        column.addWidget(label("WORKED ANSWER", "taskCaption"))
        column.addWidget(show, 0, Qt.AlignLeft)
        column.addWidget(body)
        self.worked_answer = body
        return holder

    # -- answers and checking ---------------------------------------------------------------------
    def _restore(self, card: TaskCard) -> None:
        saved = self.progress.get(card.task.id, {})
        if card.task.type != "net" and "answer" in saved:
            card.editor.set_value(saved["answer"])
        status = saved.get("status")
        if status:
            card.set_status(status)

    def _answer_changed(self, task) -> None:
        card = self.cards[task.id]
        entry = dict(self.progress.get(task.id, {}))
        if task.type != "net":
            entry["answer"] = card.editor.value()
        if card.status:
            entry["status"] = card.status
        else:
            entry.pop("status", None)
        self.progress[task.id] = entry
        self._save_timer.start()
        self._update_summary()

    def save_progress(self) -> None:
        self._save_timer.stop()
        try:
            self.exercise.save_progress(self.progress)
        except OSError as error:
            self.status.emit(f"Could not save your answers: {error}")
            return
        self.progress_changed.emit()

    def _update_summary(self) -> None:
        if not hasattr(self, "summary_label"):
            return
        tasks = self.exercise.sheet.tasks
        done = sum(1 for t in tasks if (self.cards.get(t.id) and self.cards[t.id].status
                                        in (CORRECT, "done")))
        self.summary_label.setText(f"{done} of {len(tasks)} answers done" if tasks else "")

    def check(self, task) -> None:
        card = self.cards[task.id]
        if task.type == "net":
            page = self.net_pages.get(task.id)
            if page is None:
                return
            answer = page.petri_net()
        else:
            answer = card.editor.value()
        card.show_checking()
        exercise, context = self.exercise, self.context

        def compute():
            try:
                return check_answer(exercise, task, answer, context)
            except TaskError as error:
                return Result("unknown", f"This answer box cannot be checked: {error}.")

        def done(result) -> None:
            if task.id not in self.cards:
                return
            card.show_result(result, self._comparison_detail(task, result))
            self._answer_changed(task)
            self.save_progress()
            self._update_summary()

        def failed(message: str) -> None:
            if task.id in self.cards:
                card.show_result(Result("unknown", f"The check failed: {message}"))

        if task.type in ("net", "trace", "set", "footprint", "yesno", "number"):
            run_in_background(compute, done, failed)
        else:
            done(compute())

    def _comparison_detail(self, task, result) -> QWidget | None:
        comparison = getattr(result, "comparison", None)
        if comparison is None or comparison.equivalent:
            return None
        from .net_comparison import NetComparisonView
        page = self.net_pages.get(task.id)
        return NetComparisonView(comparison, "yours", "the model answer",
                                 replay=(lambda trace, _f, p=page: self._replay(p, trace))
                                 if page is not None else None)

    def _show_solution(self, task) -> None:
        card = self.cards[task.id]
        card.show_solution(model_answer_text(self.exercise, task, self.context))

    # -- the token game -----------------------------------------------------------------------------
    def play_trace(self, text: str) -> None:
        from ...teaching import answers
        if self.given_net_page is None:
            return
        try:
            steps = answers.trace(text)
        except answers.AnswerSyntaxError as error:
            self.status.emit(f"Could not read the steps: {error}")
            return
        self.show_material(self.given_net_page)
        self._replay(self.given_net_page, steps)

    def _replay(self, page, trace) -> None:
        from ...mining.analysis import check_workflow_net
        from ...mining.compare_nets import replayable_prefix
        if page is None:
            return
        petri = page.petri_net()
        source = None
        if not petri.initial_marking:
            workflow = check_workflow_net(petri)
            source = workflow.source if workflow.is_workflow_net else None
        path, done = replayable_prefix(petri, trace)
        self.show_material(page)
        page.replay(path, source)
        shown = "⟨" + ", ".join(trace) + "⟩"
        if done < len(trace):
            self.status.emit(f"{shown}: the net can do the first {done} step(s), then not "
                             f"“{trace[done]}”")
        else:
            self.status.emit(f"{shown}: replayed")

    # -- leaving ------------------------------------------------------------------------------------
    def flush(self) -> None:
        """Save everything now (leaving the exercise or quitting)."""
        if self._save_timer.isActive():
            self.save_progress()
        for task_id, timer in self._net_timers.items():
            if timer.isActive():
                timer.stop()
                timer.timeout.emit()

    def discard(self) -> None:
        """Starting again: nothing pending may be written afterwards."""
        self._save_timer.stop()
        for timer in self._net_timers.values():
            timer.stop()

    def shutdown(self) -> None:
        for _, page in self.materials:
            if hasattr(page, "shutdown"):
                page.shutdown()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _reveal_label() -> str:
    import sys
    return {"darwin": "Show in Finder", "win32": "Show in Explorer"}.get(
        sys.platform, "Open Folder")


def _reveal(path: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def open_help(name: str, parent=None) -> None:
    """One of the guides in ``docs/`` (exercise-packs, references) in a window."""
    from .definition_view import show_guide
    show_guide(name, parent)


__all__ = ["ExerciseMode", "ExerciseView"]
