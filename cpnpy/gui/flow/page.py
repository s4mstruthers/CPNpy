"""The Workflows page: the box list, the canvas and the side panel.

Click a box to see its result in the side panel, with four tabs: *Result*
(the viewer for its output type), *How* (what it reported while it ran:
notes, intermediate values, the derivation), *Code* (its source) and
*Settings* (one control per setting).  Change a setting and only the boxes
after it run again.  Every box shows a status dot: waiting, running, done,
failed, or waiting for your OK (a custom box).

Boxes run on a worker thread (:mod:`cpnpy.gui.studio.workers`); the runner
reports each box's status through a signal, so the canvas updates while
the rest keeps working.  An exception stays in its box.

The page edits a :class:`~cpnpy.flow.workflow.Workflow` and saves it as a
``.cpnflow`` file with its record (:mod:`cpnpy.flow.record`).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit,
    QSplitter, QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ...flow import record as records
from ...flow.library import GROUP_ORDER, Library
from ...flow.runner import BLOCKED, DONE, FAILED, IDLE, RUNNING, WAITING, Cache, Result, Run, Runner
from ...flow.types import EventLog, Figure, PetriNet, Scores, Table
from ...flow.workflow import Edge, Workflow, to_python
from .. import theme
from ..studio import style
from ..studio.widgets import Card, NoticeBar, PageHeader, SegmentedControl, button, hbox, label, scroll, vbox
from ..studio.workers import run_in_background
from .canvas import WorkflowScene, WorkflowView
from .viewers import SettingsWidget, code_widget, how_widget, pop_out, result_widget, status_text

TABS = ["Result", "How", "Code", "Settings"]


class _Relay(QObject):
    """Carries a box's status from the worker thread to the page (queued)."""

    status = Signal(object)
    finished = Signal(object)


def brief(value) -> str:
    """One line about a result, for the box's subtitle."""
    if isinstance(value, Scores):
        first = next(((k, v) for k, v in value.metrics.items()), None)
        if first is None:
            return value.model
        key, number = first
        return f"{key} {number:.2f}" if isinstance(number, float) else f"{key} {number}"
    if isinstance(value, Table):
        return f"table {len(value.rows)} × {len(value.columns)}"
    if isinstance(value, Figure):
        return value.caption[:40] or "figure"
    if isinstance(value, PetriNet):
        return f"{len(value.places)} places · {len(value.transitions)} transitions"
    if isinstance(value, EventLog):
        return f"{len(value)} cases · {value.event_count} events"
    summary = getattr(value, "summary", None)
    if callable(summary):
        try:
            return str(summary())[:48]
        except Exception:   # noqa: BLE001
            pass
    if value is None:
        return "done"
    if hasattr(value, "__len__"):
        try:
            return f"{len(value)} {type(value).__name__.lower()}"
        except TypeError:
            pass
    return type(value).__name__


class WorkflowPage(QWidget):
    status = Signal(str)
    saved = Signal()
    #: Something changed that should be saved (the window autosaves in a folder).
    edited = Signal()
    #: A result should open as a page of its own (a LogDocument, ModelDocument, CpnDocument).
    open_document = Signal(object)
    #: "Edit a copy" of a net: open it on the net canvas.
    edit_requested = Signal(object)
    keep_requested = Signal()
    #: The user allowed the folder's custom boxes to run.
    custom_allowed_changed = Signal()

    def __init__(self, document, library: Library, folder: str | Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self.document = document
        self.workflow: Workflow = document.workflow
        self.library = library
        self.folder = Path(folder) if folder else None
        self.runner = Runner(library, Cache(), folder=self.folder)
        self.run: Run | None = None
        self._running = False
        self._queued: list[str] | None = None
        self._stop = threading.Event()
        self._relay = _Relay()
        self._relay.status.connect(self._status_arrived)
        self._relay.finished.connect(self._run_finished)
        self.selected: str | None = None
        self.tab = 0
        self.custom_allowed = False
        self._setting_timer = QTimer(self)
        self._setting_timer.setSingleShot(True)
        self._setting_timer.setInterval(400)
        self._setting_timer.timeout.connect(self._apply_pending_settings)
        self._pending: dict[str, dict] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = PageHeader(self.workflow.name, self._subtitle())
        self.keep_button = button("Keep", self.keep_requested.emit, kind="primary",
                                  tooltip="Save this workflow into the folder")
        self.keep_button.setVisible(False)
        self.header.actions.addWidget(self.keep_button)
        self.run_button = button("Run ▶", lambda: self.run_from(None), tooltip="Run every box")
        self.header.actions.addWidget(self.run_button)
        self.header.actions.addWidget(button("Re-run", self.rerun,
                                             tooltip="Run again, after checking the record for changed inputs"))
        self.header.actions.addWidget(button("Record", self.show_record,
                                             tooltip="The workflow as Python, and the file with its record"))
        self.header.actions.addWidget(button("Save", self.save, tooltip="Save the workflow and its record"))
        root.addWidget(self.header)
        self.custom_bar = NoticeBar()
        root.addWidget(self.custom_bar)

        self.scene = WorkflowScene(self.workflow)
        self.view = WorkflowView(self.scene)
        self.scene.selected.connect(self._select)
        self.scene.edited.connect(self._edited)
        self.scene.moved.connect(lambda _id: self._mark_edited())
        self.scene.add_here.connect(self.quick_add)
        self.scene.menu.connect(self._menu)
        self.scene.refused.connect(lambda text: self.status.emit(text))

        splitter = QSplitter()
        splitter.setHandleWidth(14)
        splitter.setStyleSheet("QSplitter::handle { background: transparent; }")
        splitter.addWidget(self._build_box_list())
        canvas = Card()
        canvas.add(self.view, 1)
        self.legend = label("", "muted", wrap=True)
        canvas.add(self.legend)
        splitter.addWidget(canvas)
        self.panel_host = QWidget()
        self.panel_layout = QVBoxLayout(self.panel_host)
        self.panel_layout.setContentsMargins(0, 0, 0, 0)
        self.panel = scroll(self.panel_host)
        self.panel.setMinimumWidth(300)
        splitter.addWidget(self.panel)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([220, 760, 380])
        self.splitter = splitter
        wrapper = QWidget()
        wrapper.setLayout(vbox(splitter, margins=(20, 0, 20, 16)))
        root.addWidget(wrapper, 1)

        QShortcut(QKeySequence(Qt.Key_Delete), self.view, self.scene.remove_selected)
        QShortcut(QKeySequence(Qt.Key_Backspace), self.view, self.scene.remove_selected)
        QShortcut(QKeySequence("Ctrl+D"), self.view, lambda: self.scene.duplicate(self.selected) if self.selected else None)
        self._refresh_custom_bar()
        self._render_panel()
        QTimer.singleShot(0, self.view.fit)
        if not self.workflow.nodes:
            self.status.emit("An empty workflow: double-click the canvas or click a box in the list to add one")

    # -- header --------------------------------------------------------------------------
    def _subtitle(self) -> str:
        count = len(self.workflow.nodes)
        text = f"{count} box{'es' if count != 1 else ''}"
        if self.run is not None:
            text += " · " + self.run.summary()
        return text

    def refresh_title(self) -> None:
        self.header.set_text(self.workflow.name, self._subtitle())

    # -- the box list -----------------------------------------------------------------------
    def _build_box_list(self) -> QWidget:
        card = Card("Boxes")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search boxes")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._fill_box_list)
        card.add(self.search)
        self.box_tree = QTreeWidget()
        self.box_tree.setHeaderHidden(True)
        self.box_tree.setIndentation(10)
        self.box_tree.setRootIsDecorated(False)
        self.box_tree.itemClicked.connect(self._box_list_clicked)
        self.box_tree.setToolTip("Click a box to add it to the canvas")
        card.add(self.box_tree, 1)
        card.add(label("Click a box to add it. Your own boxes come from the folder's boxes/ subfolder.",
                       "muted", wrap=True))
        self._fill_box_list()
        return card

    def _fill_box_list(self) -> None:
        wanted = self.search.text().strip().lower()
        self.box_tree.clear()
        t = style.tokens()
        from PySide6.QtGui import QBrush, QColor
        for group, specs in self.library.by_group().items():
            shown = [s for s in specs if not wanted or wanted in s.name.lower() or wanted in group.lower()]
            if not shown:
                continue
            head = QTreeWidgetItem([group.upper()])
            head.setFlags(Qt.ItemIsEnabled)
            head.setForeground(0, QBrush(QColor(t.text_muted)))
            font = theme.ui_font(10, theme.QFont.DemiBold)
            head.setFont(0, font)
            self.box_tree.addTopLevelItem(head)
            for spec in shown:
                item = QTreeWidgetItem([spec.name + ("  (Yours)" if spec.custom else "")])
                item.setData(0, Qt.UserRole, spec.id)
                tip = (spec.help or "").strip().split("\n")[0]
                if not spec.available:
                    tip += f"\n({spec.unavailable_reason})"
                    item.setForeground(0, QBrush(QColor(t.text_muted)))
                item.setToolTip(0, tip)
                head.addChild(item)
            head.setExpanded(True)
        for broken in self.library.broken:
            head = QTreeWidgetItem([f"{Path(broken.file).name}: {broken.reason}"])
            head.setFlags(Qt.ItemIsEnabled)
            head.setForeground(0, QBrush(QColor(style.STATUS["critical"])))
            head.setToolTip(0, "This box file could not be loaded; fix it and it reloads when saved")
            self.box_tree.addTopLevelItem(head)

    def _box_list_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        box_id = item.data(0, Qt.UserRole)
        if not box_id:
            return
        count = len(self.workflow.nodes) % 6
        rect = self.view.mapToScene(self.view.viewport().rect()).boundingRect()
        self.add_box(box_id, QPointF(rect.left() + 30 + count * 24, rect.bottom() - 150 - count * 12))

    def add_box(self, box_id: str, where: QPointF) -> None:
        node = self.scene.add_node(box_id, where)
        self.status.emit(f"Added {self.workflow.spec(node).name}: drag from a dot on the right of a box to "
                         "connect it")
        self.refresh_title()

    def reload_library(self) -> None:
        """The folder's boxes changed: load them again and refresh the list."""
        if self.folder is not None:
            self.library.load_folder(self.folder / "boxes")
        self._fill_box_list()
        self._refresh_custom_bar()
        self.scene.rebuild()
        self.run_from(None)

    # -- custom boxes ----------------------------------------------------------------------------
    def custom_specs(self) -> list:
        return [s for s in self.library if s.custom]

    def _refresh_custom_bar(self) -> None:
        customs = self.custom_specs()
        if not customs or self.custom_allowed:
            self.custom_bar.clear("custom")
            return
        names = ", ".join(sorted({Path(s.file).name for s in customs if s.file}))
        self.custom_bar.show_notice(
            "custom", f"<b>This folder has {len(customs)} custom box{'es' if len(customs) != 1 else ''}</b> "
            f"({names}). They run Python code from the folder. Run them?",
            [("Run them", self.allow_custom), ("Not now", lambda: self.custom_bar.clear("custom"))])

    def allow_custom(self) -> None:
        self.custom_allowed = True
        self.custom_bar.clear("custom")
        self.custom_allowed_changed.emit()
        self.run_from([n.id for n in self.workflow.nodes.values() if self.workflow.spec(n).custom])

    # -- running ---------------------------------------------------------------------------------
    def run_from(self, changed: list[str] | None) -> None:
        """Run the boxes from ``changed`` on (all of them: None), in the background."""
        if self._running:
            self._queued = None if changed is None or self._queued is None else sorted(set(self._queued) | set(changed))
            if changed is None:
                self._queued = None
            self._stop.set()
            return
        problems = [p for p in self.workflow.validate() if "connect" not in p.lower()]
        for problem in problems[:1]:
            self.status.emit(problem)
        customs = {n.id for n in self.workflow.nodes.values() if self.workflow.spec(n).custom}
        self._running = True
        self._stop = threading.Event()
        previous = self.run
        library, workflow, relay, stop, allowed = self.library, self.workflow, self._relay, self._stop, self.custom_allowed
        blocked = set() if allowed else customs
        for node in workflow.order():
            if changed is None or node.id in workflow.descendants(changed):
                self.scene.set_status(node.id, WAITING, "Waiting…")

        def work():
            if blocked:
                # Custom boxes wait for the user's OK: run with them marked unavailable.
                return self._run_with_blocked(workflow, changed, previous, stop, relay, blocked)
            return self.runner.run(workflow, changed, previous, stop, on_status=relay.status.emit)

        run_in_background(work, relay.finished.emit, lambda message: relay.finished.emit(message))

    def _run_with_blocked(self, workflow, changed, previous, stop, relay, blocked):
        """Like the runner, but custom boxes (not yet allowed) are blocked."""
        original = {node_id: workflow.spec(node_id).needs for node_id in blocked}
        for node_id in blocked:
            spec = workflow.spec(node_id)
            spec.needs = ("your OK",)
        try:
            run = self.runner.run(workflow, changed, previous, stop, on_status=relay.status.emit)
        finally:
            for node_id, needs in original.items():
                workflow.spec(node_id).needs = needs
        for (node_id, _variant), result in run.results.items():
            if node_id in blocked and result.status == BLOCKED:
                result.message = "Waiting for your OK (a custom box)"
        return run

    def _status_arrived(self, result: Result) -> None:
        self._show_status(result)
        if self.selected == result.node:
            self._render_panel()

    def _show_status(self, result: Result) -> None:
        if result.variant != 0:
            return
        if result.status == DONE:
            subtitle = brief(result.value)
        elif result.status == FAILED:
            subtitle = "Failed. Click for details"
        elif result.status == RUNNING:
            subtitle = "Running…"
        elif result.status == BLOCKED:
            subtitle = result.message or "Waiting for your OK"
        else:
            subtitle = result.message or "Waiting…"
        self.scene.set_status(result.node, result.status, subtitle, result.error or result.message)

    def _run_finished(self, outcome) -> None:
        self._running = False
        if isinstance(outcome, Run):
            self.run = outcome
            for result in outcome.results.values():
                self._show_status(result)
            failed = outcome.failed()
            if failed:
                self.status.emit(f"{len(failed)} box{'es' if len(failed) != 1 else ''} failed: "
                                 + ", ".join(self.workflow.title(r.node) for r in failed))
            elif not outcome.stopped:
                self.status.emit(outcome.summary())
        else:
            self.status.emit(f"The run stopped: {outcome}")
        self.refresh_title()
        self._render_panel()
        if self._queued is not None or (isinstance(outcome, Run) and outcome.stopped):
            queued, self._queued = self._queued, None
            self.run_from(queued)

    def rerun(self) -> None:
        """Run everything again, after saying what differs from the record."""
        record = getattr(self.document, "record", None)
        differences = records.differences(record, self.workflow, self.folder) if record and record.results else []
        if differences:
            box = QMessageBox(self)
            box.setWindowTitle("This is not the recorded experiment")
            box.setText("Re-running now would not reproduce the saved results, because:")
            box.setInformativeText("\n".join("• " + d for d in differences))
            box.setStandardButtons(QMessageBox.Cancel | QMessageBox.Ok)
            box.button(QMessageBox.Ok).setText("Run anyway")
            if box.exec() != QMessageBox.Ok:
                return
        self.runner.cache.clear()
        self.run = None
        self.run_from(None)

    # -- edits ----------------------------------------------------------------------------------
    def _edited(self, changed: list[str]) -> None:
        self._mark_edited()
        self.refresh_title()
        self.run_from(changed if changed else None)

    def _mark_edited(self) -> None:
        self.document.dirty = True
        self.edited.emit()

    def _setting_changed(self, node_id: str, name: str, value) -> None:
        self._pending.setdefault(node_id, {})[name] = value
        self._setting_timer.start()

    def _apply_pending_settings(self) -> None:
        pending, self._pending = self._pending, {}
        changed = []
        for node_id, values in pending.items():
            if node_id not in self.workflow.nodes:
                continue
            try:
                self.workflow.set(node_id, **values)
            except (ValueError, TypeError) as error:
                self.status.emit(str(error))
                continue
            changed.append(node_id)
        if changed:
            self._mark_edited()
            self.run_from(changed)

    # -- selection and the side panel ----------------------------------------------------------
    def _select(self, node_id: str | None) -> None:
        if node_id != self.selected:
            self.selected = node_id
            self._render_panel()

    def select(self, node_id: str | None, tab: int | None = None) -> None:
        if tab is not None:
            self.tab = tab
        self.scene.select(node_id)
        self.selected = node_id
        self._render_panel()

    def _render_panel(self) -> None:
        layout = self.panel_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout() is not None:
                _delete_layout(item.layout())
        node = self.workflow.nodes.get(self.selected) if self.selected else None
        if node is None:
            layout.addWidget(label("Click a box to see its result, how it got there, its code and its settings.",
                                   "muted", wrap=True))
            layout.addStretch(1)
            return
        spec = self.workflow.spec(node)
        result = self.run.result(node) if self.run else None
        title = label(node.title or spec.name, "pageTitle")
        layout.addWidget(title)
        chip_text, chip_kind = status_text(result)
        colour = {"good": style.STATUS["good"], "critical": style.STATUS["critical"], "warning": style.STATUS["warning"],
                  "accent": style.tokens().accent, "muted": style.tokens().text_muted}[chip_kind]
        chips = label(f"<span style='color: {style.tokens().text_muted}'>{'Yours · ' if spec.custom else ''}{spec.group}"
                      f"</span> &nbsp; <span style='color: {colour}; font-weight: 600'>{chip_text}</span>")
        chips.setTextFormat(Qt.RichText)
        layout.addWidget(chips)
        help_text = label((spec.help or "").strip(), "muted", wrap=True)
        layout.addWidget(help_text)
        tabs = SegmentedControl(TABS, compact=True)
        tabs.set_index(self.tab)
        tabs.changed.connect(self._tab_changed)
        pop = button("⤢", lambda: self.pop_out_tab(), tooltip="Open this tab in its own window")
        pop.setFixedWidth(34)
        layout.addLayout(hbox(tabs, None, pop))
        self.tabs = tabs
        layout.addWidget(self._tab_widget(node, spec, result, self.tab))
        connections = ", ".join(f"{p.label or p.name}: {p.type_name}" for p in spec.inputs) or "nothing"
        gives = ", ".join(p.type_name for p in spec.outputs)
        layout.addWidget(label(f"Takes {connections}." + (f" Gives a {gives}." if gives else ""), "muted", wrap=True))
        layout.addLayout(hbox(button("Duplicate", lambda: self.scene.duplicate(node.id)),
                              button("Disconnect all", lambda: self.scene.disconnect_all(node.id)),
                              button("Remove box", lambda: self.scene.remove_node(node.id), kind="danger"), None))
        layout.addStretch(1)

    def _tab_changed(self, index: int) -> None:
        self.tab = index
        self._render_panel()

    def _tab_widget(self, node, spec, result: Result | None, index: int) -> QWidget:
        if index == 0:
            if result is None:
                return label("Runs first; the result shows here.", "muted", wrap=True)
            if result.status == FAILED:
                host = QWidget()
                host.setLayout(vbox(label("WHAT WENT WRONG", "sectionLabel"), _error_box(result.traceback or result.error),
                                    label("The rest of the workflow keeps working. Fix the setting or the file, and "
                                          "it runs again on its own.", "muted", wrap=True)))
                return host
            if result.status == BLOCKED:
                host = QWidget()
                host.setLayout(vbox(label(result.message or "Not allowed to run yet", wrap=True),
                                    hbox(button("Run it", self.allow_custom, kind="primary"), None)
                                    if spec.custom and not self.custom_allowed else label("")))
                return host
            if result.status != DONE:
                return label((result.message or "Waiting for the boxes before it") + ".", "muted", wrap=True)
            if spec.result_type is not None and len(result.values) > 1:
                host = QWidget()
                column = QVBoxLayout(host)
                column.setContentsMargins(0, 0, 0, 0)
                for port in spec.outputs:
                    column.addWidget(label(port.name.upper(), "sectionLabel"))
                    column.addWidget(result_widget(result.values.get(port.name), self))
                return host
            widget = result_widget(result.value, self)
            if self.run and len(self.run.variants) > 1 and self.run.result(node, 1) is not None:
                host = QWidget()
                host.setLayout(vbox(label(f"The first of {len(self.run.variants)} sweep values; the collecting "
                                          "boxes after it show all of them.", "muted", wrap=True), widget))
                return host
            return widget
        if index == 1:
            if result is None or result.status not in (DONE, FAILED):
                return label("Runs first, then shows how it got there.", "muted", wrap=True)
            return how_widget(result.explanation, self)
        if index == 2:
            return code_widget(spec, self)
        settings = SettingsWidget(spec, node.settings, self.folder)
        settings.changed.connect(lambda name, value, nid=node.id: self._setting_changed(nid, name, value))
        return settings

    def pop_out_tab(self) -> None:
        node = self.workflow.nodes.get(self.selected) if self.selected else None
        if node is None:
            return
        spec, index = self.workflow.spec(node), self.tab
        result = self.run.result(node) if self.run else None
        title = f"{node.title or spec.name} · {TABS[index]}"
        if index == 2:
            pop_out(title, lambda: code_widget(spec, self, compact=False), self.window())
        else:
            pop_out(title, lambda: self._tab_widget(node, spec, result, index), self.window())

    # -- results opening elsewhere ------------------------------------------------------------
    def open_as_log(self, log: EventLog) -> None:
        from ..studio.documents import LogDocument
        self.open_document.emit(LogDocument(log))

    def open_as_model(self, net: PetriNet) -> None:
        from ..studio.documents import ModelDocument
        self.open_document.emit(ModelDocument(net, origin=f"from {self.workflow.name}"))

    def open_as_cpn(self, net) -> None:
        from ..studio.documents import CpnDocument
        self.open_document.emit(CpnDocument(net))

    def edit_copy(self, net: PetriNet) -> None:
        self.edit_requested.emit(net)

    def save_figure(self, figure: Figure) -> None:
        from ..studio.widgets import suggested_path
        path, _ = QFileDialog.getSaveFileName(self, "Save figure", suggested_path(f"{figure.name}.svg"),
                                              "SVG (*.svg);;PNG (*.png)")
        if path:
            try:
                figure.save(path)
                self.status.emit(f"Saved {Path(path).name}")
            except ValueError as error:
                QMessageBox.warning(self, "Could not save the figure", str(error))

    # -- menus and quick add --------------------------------------------------------------
    def _menu(self, kind: str, what, screen_pos) -> None:
        menu = QMenu(self)
        if kind == "node":
            node_id = what
            menu.addAction("Run from here", lambda: self.run_from([node_id]))
            menu.addAction("Duplicate", lambda: self.scene.duplicate(node_id))
            menu.addAction("Disconnect all", lambda: self.scene.disconnect_all(node_id))
            menu.addSeparator()
            menu.addAction("Remove", lambda: self.scene.remove_node(node_id))
        elif kind == "edge":
            edge: Edge = what
            menu.addAction("Remove connection", lambda: self.scene.remove_edge(edge))
        else:
            point: QPointF = what
            menu.addAction("Add box here…", lambda: self.quick_add(point))
            menu.addAction("Fit to window", self.view.fit)
        menu.exec(QPoint(int(screen_pos.x()), int(screen_pos.y())) if hasattr(screen_pos, "x") else screen_pos)

    def quick_add(self, where: QPointF) -> None:
        """A small search list at ``where`` (scene coordinates): pick a box to add."""
        popup = QFrame(self.view, Qt.Popup)
        popup.setObjectName("card")
        edit = QLineEdit()
        edit.setPlaceholderText("Add a box…")
        listing = QListWidget()
        listing.setMinimumWidth(240)
        popup.setLayout(vbox(edit, listing, spacing=4, margins=(6, 6, 6, 6)))

        def fill() -> None:
            listing.clear()
            wanted = edit.text().strip().lower()
            for spec in self.library:
                if not wanted or wanted in spec.name.lower() or wanted in spec.group.lower():
                    item = QListWidgetItem(f"{spec.name}   ·  {spec.group}")
                    item.setData(Qt.UserRole, spec.id)
                    listing.addItem(item)
            if listing.count():
                listing.setCurrentRow(0)

        def choose(item=None) -> None:
            item = item or listing.currentItem()
            popup.close()
            if item is not None:
                self.add_box(item.data(Qt.UserRole), QPointF(where.x() - 89, where.y() - 30))

        edit.textChanged.connect(fill)
        edit.returnPressed.connect(choose)
        listing.itemClicked.connect(choose)
        fill()
        point = self.view.mapFromScene(where)
        popup.move(self.view.mapToGlobal(point))
        popup.show()
        edit.setFocus()
        self._quick = popup

    # -- the record, saving ------------------------------------------------------------------
    def show_record(self) -> None:
        python = to_python(self.workflow)
        record = records.make_record(self.workflow, self.run, self.folder, lock=False)
        data = {"format": records.FORMAT, **self.workflow.to_dict(), "record": record.to_dict()}
        text = json.dumps(data, indent=2, ensure_ascii=False, default=str)
        dialog = QDialog(self.window())
        dialog.setWindowTitle(f"{self.workflow.name}: the record")
        dialog.resize(900, 700)
        code = QPlainTextEdit(python)
        code.setReadOnly(True)
        code.setFont(theme.mono_font(11))
        from .viewers import PythonHighlighter
        PythonHighlighter(code.document())
        file_text = QPlainTextEdit(text)
        file_text.setReadOnly(True)
        file_text.setFont(theme.mono_font(11))
        from PySide6.QtWidgets import QApplication
        dialog.setLayout(vbox(
            label("Everything needed to run this experiment again and get the same numbers. The Python and the "
                  "canvas are two views of the same workflow.", "muted", wrap=True),
            label("AS PYTHON", "sectionLabel"), code, label("THE WORKFLOW FILE", "sectionLabel"), file_text,
            hbox(button("Copy Python", lambda: QApplication.clipboard().setText(python)),
                 button("Copy file", lambda: QApplication.clipboard().setText(text)), None,
                 button("Done", dialog.accept, kind="primary")), margins=(16, 16, 16, 16)))
        dialog.show()
        self._record_dialog = dialog

    def write_to(self, path: str, quiet: bool = False) -> None:
        """Save the workflow and its record to ``path`` (the window's Keep / Save As)."""
        target = Path(path)
        self.workflow.name = target.stem if target.stem else self.workflow.name
        self.document.record = records.save(self.workflow, target, self.run, self.folder or target.parent)
        self.document.path = str(target)
        self.document.dirty = False
        self.refresh_title()
        if not quiet:
            self.status.emit(f"Saved {target.name}")
        self.saved.emit()

    def save(self) -> bool:
        if self.document.path:
            self.write_to(self.document.path)
            return True
        self.export()
        return bool(self.document.path)

    def autosave(self) -> bool:
        try:
            self.write_to(self.document.path, quiet=True)
            return True
        except OSError as error:
            self.save_error = str(error)
            return False

    def export(self) -> None:
        from ..studio.widgets import suggested_path
        path, _ = QFileDialog.getSaveFileName(self, "Save workflow", suggested_path(f"{self.workflow.name}.cpnflow"),
                                              "Workflow (*.cpnflow)")
        if path:
            if not path.lower().endswith(".cpnflow"):
                path += ".cpnflow"
            self.write_to(path)

    def stop(self) -> None:
        self._stop.set()


def _delete_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            _delete_layout(item.layout())


def _error_box(text: str) -> QPlainTextEdit:
    box = QPlainTextEdit(text)
    box.setReadOnly(True)
    box.setFont(theme.mono_font(10))
    box.setMaximumHeight(220)
    box.setStyleSheet(f"color: {style.STATUS['critical']};")
    return box
