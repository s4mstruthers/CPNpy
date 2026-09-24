"""CPNpy Studio: the main window of the process-mining workspace.

Layout
------
::

    +------------+-------------------------------------------------+
    | CPNpy      |  Page header (title, subtitle, actions)          |
    |            |  [Overview | Variants | Cases | ...]             |
    | EVENT LOGS |                                                  |
    |  ▤ log A   |                page content                      |
    | MODELS     |                                                  |
    |  ◇ α(L)    |                                                  |
    | COLOURED   |                                                  |
    |  NETS      |                                                  |
    |  ◈ plane   |                                                  |
    | Open…      |                                                  |
    +------------+-------------------------------------------------+

The sidebar lists every open *document*: an event log, a Petri net, or a
coloured Petri net (CPN Tools model).  Selecting one shows its page.
Discovering a model from a log adds the model to the sidebar, and exporting
a CPN simulation adds its event log, so a whole analysis lives side by side
in one window.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QEvent, QRect, QRectF, QSettings, QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QAction, QColor, QDesktopServices, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QFrame, QGridLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QSizePolicy, QSplitter, QStackedWidget, QStyle, QStyledItemDelegate,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ...mining.csv_import import ColumnMapping, guess_mapping, read_csv, sniff
from ...mining.log import EventLog, parse_simple_log
from ...mining.pnml import read_pnml, write_pnml
from ...mining.xes import read_xes, write_xes
from .. import theme
from . import style
from ..canvas import NetView
from .compare_page import ComparePage
from .cpn_page import CpnPage
from .petri_page import PetriNetPage
from .documents import ComparisonDocument, CpnDocument, LogDocument, ModelDocument
from .graph_view import GraphView, ZoomControls
from .log_page import LogPage
from .model_page import ModelPage
from .widgets import Card, button, hbox, label, scroll, vbox
from .workers import run_in_background

APPLICATION_NAME = "CPNpy Studio"

EXAMPLES = {
    "Textbook L₁ (α-algorithm example)": "[<a,b,c,d>^3, <a,c,b,d>^2, <a,e,d>]",
    "Textbook L₂ (loop)": "[<a,b,c,d>^3, <a,c,b,d>^4, <a,b,c,e,f,b,c,d>^2, "
                          "<a,b,c,e,f,c,b,d>, <a,c,b,e,f,b,c,d>^2, <a,c,b,e,f,b,c,e,f,c,b,d>]",
    "Textbook L₃ (IM paper)": "[<a,b,c,d,e,f,b,d,c,e,g>, <a,b,d,c,e,g>^2, "
                              "<a,b,c,d,e,f,b,c,d,e,f,b,d,c,e,g>]",
    "Short loops (α limitation)": "[<a,c>^2, <a,b,c>^3, <a,b,b,c>^2, <a,b,b,b,b,c>]",
    "Non-free choice": "[<a,c,d>^45, <b,c,e>^42]",
}


def app_icon() -> QIcon:
    """The CPNpy logo (Dock, window and About box)."""
    return QIcon(str(Path(__file__).resolve().parents[1] / "resources" / "cpnpy-icon.png"))


def _icon(kind: str) -> QIcon:
    """Tiny painted icons, so the app ships no image files.

    Drawn twice: in colour, and in the selected row's text colour, which Qt
    uses for the selected row (a blue icon on the blue highlight vanished).
    """
    icon = QIcon(_icon_pixmap(kind, None))
    icon.addPixmap(_icon_pixmap(kind, QColor(style.tokens().accent_text)), QIcon.Selected)
    return icon


def _icon_pixmap(kind: str, ink: QColor | None) -> QPixmap:
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    colour = ink if ink is not None else QColor(
        {"log": style.categorical(0), "cpn": style.categorical(2)}.get(kind, style.categorical(6)))
    pen = QPen(colour, 3)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    if kind == "compare":
        painter.setPen(Qt.NoPen)
        for index, (x, height) in enumerate(((5, 12), (12, 20), (19, 8), (26, 16))):
            painter.setBrush(ink if ink is not None else QColor(style.categorical(index % 2)))
            painter.drawRoundedRect(QRectF(x - 2, 27 - height, 5, height), 1.5, 1.5)
    elif kind == "cpn":
        painter.drawEllipse(QRectF(3, 9, 13, 13))
        painter.drawRoundedRect(QRectF(19, 8, 10, 15), 2, 2)
        painter.setBrush(colour)
        painter.drawEllipse(QRectF(8, 14, 3, 3))
    elif kind == "log":
        for y in (9, 16, 23):
            painter.drawLine(7, y, 25, y)
        painter.setBrush(colour)
        painter.drawEllipse(4, 7, 1, 1)
    else:
        painter.drawEllipse(QRectF(4, 10, 11, 11))
        painter.drawRect(QRectF(19, 9, 9, 13))
    painter.end()
    return pixmap


# ---------------------------------------------------------------------------
# Sidebar: a remove button that appears on hover
# ---------------------------------------------------------------------------
class SidebarDelegate(QStyledItemDelegate):
    """Draws a small ✕ on the hovered (or selected) document row.

    Clicking it asks the window to remove that document from the workspace --
    the same gesture as closing a tab in Safari or a document in Xcode's
    sidebar.  Section headers ("EVENT LOGS", "MODELS") never get one.
    """

    remove_clicked = Signal(int)        # document id
    BUTTON = 18

    def _button_rect(self, row: QRect) -> QRect:
        size = self.BUTTON
        return QRect(row.right() - size - 8, row.center().y() - size // 2 + 1, size, size)

    def paint(self, painter: QPainter, option, index) -> None:
        super().paint(painter, option, index)
        if index.data(Qt.UserRole) is None:
            return
        hovered = bool(option.state & QStyle.State_MouseOver)
        selected = bool(option.state & QStyle.State_Selected)
        if not (hovered or selected):
            return
        t = style.tokens()
        rect = QRectF(self._button_rect(option.rect))
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        ink = QColor(t.accent_text if selected else t.text_secondary)
        backdrop = QColor(ink)
        backdrop.setAlphaF(0.18)
        painter.setPen(Qt.NoPen)
        painter.setBrush(backdrop)
        painter.drawEllipse(rect)
        pen = QPen(ink, 1.6)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        inset = rect.adjusted(5.5, 5.5, -5.5, -5.5)
        painter.drawLine(inset.topLeft(), inset.bottomRight())
        painter.drawLine(inset.topRight(), inset.bottomLeft())
        painter.restore()

    def editorEvent(self, event, model, option, index) -> bool:  # noqa: N802
        if index.data(Qt.UserRole) is not None and event.type() in (
                QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
            if self._button_rect(option.rect).contains(event.position().toPoint()):
                if event.type() == QEvent.MouseButtonRelease:
                    self.remove_clicked.emit(int(index.data(Qt.UserRole)))
                return True     # swallow the press too, so the row is not selected
        return super().editorEvent(event, model, option, index)


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------
class CompareDialog(QDialog):
    """Pick the logs to compare (at least two)."""

    def __init__(self, logs: list, preselected: list, parent=None) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QListWidget, QListWidgetItem
        self.setWindowTitle("Compare logs")
        self.logs = logs
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(label("Choose two or more event logs to show side by side.",
                               "muted", wrap=True))
        self.list = QListWidget()
        chosen = {d.id for d in preselected}
        for log in logs:
            item = QListWidgetItem(log.name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if log.id in chosen or len(logs) == 2
                               else Qt.Unchecked)
            self.list.addItem(item)
        self.list.itemChanged.connect(lambda _item: self._validate())
        layout.addWidget(self.list)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Compare")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._validate()

    def chosen(self) -> list:
        return [log for index, log in enumerate(self.logs)
                if self.list.item(index).checkState() == Qt.Checked]

    def _validate(self) -> None:
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(len(self.chosen()) >= 2)


class NotationDialog(QDialog):
    """Create a log from the textbook's multiset notation."""

    def __init__(self, parent=None, text: str = "", name: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("New log from notation")
        self.setMinimumWidth(560)
        self.name = QLineEdit(name or "My log")
        self.editor = QPlainTextEdit(text or EXAMPLES["Textbook L₁ (α-algorithm example)"])
        self.editor.setFont(theme.mono_font(13))
        self.editor.setMinimumHeight(120)
        self.feedback = label("", "muted", wrap=True)
        self.examples = QComboBox()
        self.examples.addItem("Insert an example…")
        self.examples.addItems(list(EXAMPLES))
        self.examples.currentTextChanged.connect(self._example)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Create log")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.ok = buttons.button(QDialogButtonBox.Ok)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Name", self.name)
        layout.addLayout(form)
        layout.addWidget(label("Write traces as <a,b,c>^n, separated by commas. Activity "
                               "names may contain spaces. <> is the empty trace. Pasting "
                               "⟨a,b,c⟩³ from the book or the slides works too.", "muted",
                               wrap=True))
        layout.addWidget(self.editor)
        layout.addLayout(hbox(self.feedback, None, self.examples))
        layout.addWidget(buttons)
        self.editor.textChanged.connect(self._validate)
        self._validate()

    def _example(self, name: str) -> None:
        if name in EXAMPLES:
            self.editor.setPlainText(EXAMPLES[name])
            self.name.setText(name.split(" (")[0])

    def _validate(self) -> None:
        try:
            log = parse_simple_log(self.editor.toPlainText())
        except ValueError as error:
            self.feedback.setText(str(error))
            self.ok.setEnabled(False)
            return
        activities = {a for trace in log for a in trace}
        self.feedback.setText(f"{sum(log.values())} traces · {len(log)} variants · "
                              f"{len(activities)} activities")
        self.ok.setEnabled(True)

    def log(self) -> EventLog:
        return EventLog.from_simple_log(parse_simple_log(self.editor.toPlainText()),
                                        self.name.text().strip() or "Log")


class CsvDialog(QDialog):
    """Confirm which CSV columns hold case id, activity, timestamp, ..."""

    def __init__(self, path: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Import {Path(path).name}")
        _, header = sniff(path)
        guess = guess_mapping(header) or ColumnMapping(header[0] if header else "",
                                                       header[1] if len(header) > 1 else "")
        self.boxes: dict[str, QComboBox] = {}
        form = QFormLayout()
        for role, title, optional in (("case", "Case id", False), ("activity", "Activity", False),
                                      ("timestamp", "Timestamp", True),
                                      ("resource", "Resource", True),
                                      ("lifecycle", "Lifecycle", True)):
            box = QComboBox()
            if optional:
                box.addItem("— none —", None)
            for column in header:
                box.addItem(column, column)
            current = getattr(guess, role)
            if current is not None:
                box.setCurrentIndex(box.findData(current))
            self.boxes[role] = box
            form.addRow(title, box)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(label("Choose the columns that identify cases and activities. "
                               "Other columns become event attributes.", "muted", wrap=True))
        layout.addLayout(form)
        layout.addWidget(buttons)

    def mapping(self) -> ColumnMapping:
        return ColumnMapping(**{role: box.currentData() for role, box in self.boxes.items()})


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class StudioWindow(QMainWindow):
    """The Studio window.

    ``persist=True`` (what the real app uses) remembers the files that were
    open and reopens them on the next launch, and keeps an *Open Recent*
    list.  Tests pass ``persist=False`` so they never touch your settings.
    """

    RECENT_LIMIT = 12

    def __init__(self, persist: bool = False) -> None:
        super().__init__()
        self.setWindowTitle(APPLICATION_NAME)
        self.setAcceptDrops(True)
        self.documents: list[LogDocument | ModelDocument] = []
        self.pages: dict[int, QWidget] = {}
        self.items: dict[int, QTreeWidgetItem] = {}
        self.holders: dict[int, QWidget] = {}
        self.persist = persist
        self.settings = QSettings("CPNpy", "Studio")
        #: How each file-backed document was opened (CSV column mapping etc.),
        #: keyed by document id, so the session can reopen it the same way.
        self.open_options: dict[int, dict] = {}
        self._restoring = False
        #: The tab you were last on, per kind of page.  Selecting another
        #: document opens the same tab, so e.g. flicking between logs in the
        #: dotted chart keeps showing dotted charts.
        self.remembered = {"log_tab": 0, "model_inspector": 0, "model_view": 0}
        # Any size down to this works: pages scroll when they do not fit.
        self.setMinimumSize(720, 480)
        self._fit_to_screen()

        root = QSplitter()
        root.setObjectName("studioRoot")
        root.setHandleWidth(1)
        root.addWidget(self._build_sidebar())
        self.content = QStackedWidget()
        self.content.addWidget(scroll(self._build_welcome(), horizontal=True))
        root.addWidget(self.content)
        root.setStretchFactor(1, 1)
        root.setSizes([220, 1260])
        self.setCentralWidget(root)
        self.statusBar().showMessage("Ready")
        self._build_menus()

    def _fit_to_screen(self) -> None:
        """Start at a size that fits the screen we are on (at most 1440 × 900).

        A fixed size larger than a laptop's screen is what made the window run
        off the edge; macOS cannot shrink a window below its minimum size.
        """
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            self.resize(1280, 800)
            return
        area = screen.availableGeometry()
        width = min(1440, int(area.width() * 0.94))
        height = min(900, int(area.height() * 0.94))
        self.resize(width, height)
        self.move(area.x() + (area.width() - width) // 2, area.y() + (area.height() - height) // 2)

    # ---------------------------------------------------------------- sidebar
    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        self.sidebar = sidebar
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(180)
        sidebar.setMaximumWidth(360)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(8, 16, 8, 10)
        layout.setSpacing(8)
        title = label(APPLICATION_NAME, "sidebarTitle")
        title.setContentsMargins(10, 0, 0, 6)
        layout.addWidget(title)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(10)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setRootIsDecorated(False)
        self.tree.setMouseTracking(True)                  # hover state for the ✕ button
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)   # ⌘/⇧-click
        self.tree.setTextElideMode(Qt.ElideRight)
        self.delegate = SidebarDelegate(self.tree)
        self.delegate.remove_clicked.connect(lambda doc_id: self.remove_documents([doc_id]))
        self.tree.setItemDelegate(self.delegate)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._sidebar_menu)
        # ⌫ / Delete removes the selection while the sidebar has focus.
        for key in (QKeySequence.Delete, QKeySequence(Qt.Key_Backspace)):
            shortcut = QShortcut(key, self.tree)
            shortcut.setContext(Qt.WidgetShortcut)
            shortcut.activated.connect(self.remove_selected)
        self.logs_section = self._section("EVENT LOGS")
        self.petri_section = self._section("PETRI NETS")
        self.models_section = self._section("MODELS")
        self.cpn_section = self._section("COLOURED NETS")
        self.compare_section = self._section("COMPARISONS")
        self.tree.currentItemChanged.connect(self._on_select)
        layout.addWidget(self.tree, 1)

        footer = QWidget()
        footer.setObjectName("sidebarFooter")
        footer.setLayout(vbox(button("＋  Open file…", self.action_open),
                              button("✎  Log from notation…", self.action_notation),
                              button("⇄  Compare logs…", lambda: self.action_compare()),
                              spacing=0))
        layout.addWidget(footer)
        return sidebar

    def _section(self, title: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem(self.tree, [title])
        item.setFlags(Qt.ItemIsEnabled)
        font = theme.ui_font(10, theme.QFont.Bold)
        item.setFont(0, font)
        item.setForeground(0, QColor(style.tokens().text_muted))
        item.setExpanded(True)
        item.setHidden(True)
        return item

    # ---------------------------------------------------------------- welcome
    def _build_welcome(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(32, 40, 32, 32)
        outer.addStretch(1)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(96, 96))
        outer.addWidget(logo, 0, Qt.AlignHCenter)
        title = label(APPLICATION_NAME)
        title.setStyleSheet("font-size: 34px; font-weight: 700;")
        outer.addWidget(title, 0, Qt.AlignHCenter)
        subtitle = label("Event logs, process discovery, conformance checking and "
                         "Petri nets — a modern ProM and CPN IDE in one app.", "pageSubtitle")
        subtitle.setStyleSheet("font-size: 15px;")
        outer.addWidget(subtitle, 0, Qt.AlignHCenter)
        outer.addSpacing(30)

        grid = QGridLayout()
        grid.setSpacing(14)
        cards = [
            ("Open an event log", "XES, XES.GZ or CSV. Explore variants, the dotted chart "
             "and the process map, then discover a model.", "Open event log…", self.action_open),
            ("Type a textbook log", "Write L = [<a,b,c>^3, <a,c>^2] exactly as in the course "
             "and mine it immediately.", "Log from notation…", self.action_notation),
            ("Draw a Petri net", "Places, transitions and arcs as in the lectures, or open a "
             "PNML file. Soundness with counterexamples, footprint, reachability graph, "
             "token game.", "New Petri net", self.action_new_petri),
            ("Coloured Petri nets", "CPN Tools models (.cpn): edit, simulate step by step or "
             "automatically, analyse the state space, and mine the simulated behaviour.",
             "Open CPN model…", self.action_open_cpn),
        ]
        for index, (heading, text, action, slot) in enumerate(cards):
            card = Card(heading)
            card.setMinimumWidth(240)
            card.add(label(text, "muted", wrap=True))
            card.add(hbox(button(action, slot, kind="primary" if index == 0 else None), None))
            grid.addWidget(card, index // 2, index % 2)
        holder = QWidget()
        holder.setLayout(grid)
        holder.setMaximumWidth(760)
        holder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # Centre with stretches rather than an alignment flag: an aligned
        # widget is sized by its sizeHint and its wrapped labels get clipped.
        outer.addLayout(hbox(None, holder, None))
        outer.addSpacing(20)
        tip = label("Tip: drop files anywhere on this window to open them. "
                    "Hover a file in the sidebar and click ✕ (or press ⌫) to "
                    "remove it.", "muted", wrap=True)
        tip.setAlignment(Qt.AlignHCenter)
        tip.setMaximumWidth(760)
        tip.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        outer.addLayout(hbox(None, tip, None))
        outer.addStretch(2)
        return page

    # ---------------------------------------------------------------- menus
    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        self._action(file_menu, "Open…", QKeySequence.Open, self.action_open)
        self._action(file_menu, "New Log from Notation…", "Ctrl+L", self.action_notation)
        self._action(file_menu, "New Petri Net", QKeySequence.New, self.action_new_petri)
        self._action(file_menu, "New Coloured Petri Net", "Ctrl+Shift+N", self.action_new_cpn)
        examples = file_menu.addMenu("Open Example Log")
        for name, text in EXAMPLES.items():
            examples.addAction(name, lambda n=name, t=text: self.add_document(LogDocument(
                EventLog.from_simple_log(parse_simple_log(t), n.split(" (")[0]))))
        from ...model.examples import EXAMPLES as PETRI_EXAMPLES
        petri_examples = file_menu.addMenu("Open Example Petri Net")
        for name, build in PETRI_EXAMPLES.items():
            petri_examples.addAction(name, lambda b=build: self.open_example_net(b()))
        self.recent_menu = file_menu.addMenu("Open Recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent_menu)
        file_menu.addSeparator()
        self._action(file_menu, "Open Coloured Petri Net…", "Ctrl+Shift+O", self.action_open_cpn)
        self._action(file_menu, "Compare Logs…", "Ctrl+Shift+C", lambda: self.action_compare())
        file_menu.addSeparator()
        self._action(file_menu, "Save", QKeySequence.Save, self.action_save)
        self._action(file_menu, "Save As / Export…", "Ctrl+Shift+S", self.export_selected)
        self._action(file_menu, "Export Selected…", "Ctrl+E", self.export_selected)
        self._action(file_menu, "Rename…", None, self.rename_selected)
        file_menu.addSeparator()
        self._action(file_menu, "Remove from Workspace", QKeySequence.Close, self.remove_selected)
        self._action(file_menu, "Remove All…", "Ctrl+Shift+W", self.remove_all)
        file_menu.addSeparator()
        self.restore_action = QAction("Reopen Files at Launch", self)
        self.restore_action.setCheckable(True)
        self.restore_action.setChecked(self.settings.value("session/restore", True, type=bool))
        self.restore_action.toggled.connect(
            lambda on: self.settings.setValue("session/restore", on))
        file_menu.addAction(self.restore_action)

        view_menu = self.menuBar().addMenu("&View")
        self._action(view_menu, "Show Welcome Page", "Ctrl+1",
                     lambda: self.content.setCurrentIndex(0))
        self._action(view_menu, "Toggle Sidebar", "Ctrl+Alt+S",
                     lambda: self.sidebar.setVisible(not self.sidebar.isVisible()))
        view_menu.addSeparator()
        zoom_in = self._action(view_menu, "Zoom In", QKeySequence.ZoomIn,
                               lambda: self._zoom("zoom_in"))
        zoom_in.setShortcuts([QKeySequence.ZoomIn, QKeySequence("Ctrl+=")])
        self._action(view_menu, "Zoom Out", QKeySequence.ZoomOut, lambda: self._zoom("zoom_out"))
        self._action(view_menu, "Zoom to Fit", "Ctrl+0", lambda: self._zoom("fit"))
        self._action(view_menu, "Actual Size", "Ctrl+Alt+0", lambda: self._zoom("actual_size"))

        help_menu = self.menuBar().addMenu("&Help")
        self._action(help_menu, "Definitions", None, self._definitions)
        self._action(help_menu, f"About {APPLICATION_NAME}", None, self._about)

    def _action(self, menu, text, shortcut, slot) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    def _definitions(self) -> None:
        """Every analysis property, defined mathematically (docs/definitions.md)."""
        from .definition_view import show_reference
        show_reference(None, self)

    def _about(self) -> None:
        QMessageBox.about(self, APPLICATION_NAME,
                          f"<b>{APPLICATION_NAME}</b><p>Process mining and Petri nets in pure "
                          "Python. Algorithms follow the TU/e course readings; see the "
                          "docstrings in <code>cpnpy.mining</code>.</p>")

    # ---------------------------------------------------------------- documents
    def logs(self) -> list[LogDocument]:
        return [d for d in self.documents if isinstance(d, LogDocument)]

    def add_document(self, document, options: dict | None = None) -> None:
        """Add a document to the workspace and show it.

        Opening a file that is already open just selects it, so the sidebar
        never fills up with duplicates.
        """
        if document.path:
            for existing in self.documents:
                if existing.path and Path(existing.path) == Path(document.path) and \
                        type(existing) is type(document):
                    self.tree.setCurrentItem(self.items[existing.id])
                    self.statusBar().showMessage(f"{Path(document.path).name} is already open", 5000)
                    return
        self.documents.append(document)
        if options:
            self.open_options[document.id] = options
        if isinstance(document, LogDocument):
            page = LogPage(document)
            page.open_model.connect(self.add_document)
            page.open_log.connect(self.add_document)
            page.tabs.changed.connect(lambda i: self.remembered.__setitem__("log_tab", i))
            parent, kind = self.logs_section, "log"
        elif isinstance(document, ComparisonDocument):
            page = ComparePage(document)
            page.tabs.changed.connect(lambda i: self.remembered.__setitem__("compare_tab", i))
            parent, kind = self.compare_section, "compare"
        elif isinstance(document, CpnDocument):
            plain = getattr(document.net, "plain", False)
            page = PetriNetPage(document) if plain else CpnPage(document)
            page.log_generated.connect(lambda log: self.add_document(LogDocument(log)))
            page.dirty_changed.connect(lambda _dirty, doc=document: self._refresh_item(doc))
            page.inspector_tabs.changed.connect(
                lambda i, key="petri_inspector" if plain else "cpn_inspector":
                self.remembered.__setitem__(key, i))
            if plain:
                page.open_model.connect(self.add_document)
                parent, kind = self.petri_section, "model"
            else:
                parent, kind = self.cpn_section, "cpn"
        else:
            page = ModelPage(document, self.logs)
            page.inspector_tabs.changed.connect(
                lambda i: self.remembered.__setitem__("model_inspector", i))
            page.view_switch.changed.connect(
                lambda i: self.remembered.__setitem__("model_view", i))
            page.log_generated.connect(lambda log: self.add_document(LogDocument(log)))
            page.edit_requested.connect(self.edit_petri_net)
            parent, kind = self.models_section, "model"
        page.status.connect(lambda message: self.statusBar().showMessage(message, 8000))
        page.saved.connect(lambda doc=document: self._document_saved(doc))
        self.pages[document.id] = page
        # The page sits in a scroll area: if the window is made smaller than
        # the page's minimum size, scroll bars appear instead of the window
        # refusing to shrink (which is what pushed it off the screen).
        holder = scroll(page, horizontal=True)
        self.holders[document.id] = holder
        self.content.addWidget(holder)
        parent.setHidden(False)
        item = QTreeWidgetItem(parent, [document.name])
        item.setIcon(0, _icon(kind))
        item.setData(0, Qt.UserRole, document.id)
        self._set_item_tooltip(item, document)
        self.items[document.id] = item
        self.tree.clearSelection()
        self.tree.setCurrentItem(item)
        self._refresh_log_choices()
        if document.path:
            self._remember_recent(document.path)
        self._save_session()

    def _refresh_item(self, document) -> None:
        """Sidebar text: the name, plus a dot while a model has unsaved edits."""
        item = self.items.get(document.id)
        if item is not None:
            item.setText(0, document.name + ("  •" if getattr(document, "dirty", False) else ""))
            self._set_item_tooltip(item, document)

    def _set_item_tooltip(self, item: QTreeWidgetItem, document) -> None:
        where = document.path or "Not saved to a file — export it to keep it"
        item.setToolTip(0, f"{document.name}\n{where}")

    def _refresh_log_choices(self) -> None:
        for page in self.pages.values():
            if isinstance(page, ModelPage):
                page.refresh_logs()

    def _on_select(self, current, _previous=None) -> None:
        if current is None or current.data(0, Qt.UserRole) is None:
            return
        holder = self.holders.get(current.data(0, Qt.UserRole))
        if holder is not None:
            self._restore_tab(self.pages[current.data(0, Qt.UserRole)])
            self.content.setCurrentWidget(holder)
            document = self._document(current.data(0, Qt.UserRole))
            self.setWindowTitle(f"{document.name} — {APPLICATION_NAME}")

    def _restore_tab(self, page: QWidget) -> None:
        """Show the same tab on the newly selected page as on the last one."""
        if isinstance(page, LogPage):
            wanted = self.remembered["log_tab"]
            if page.tabs.index() != wanted:
                page.tabs.set_index(wanted)
        elif isinstance(page, ModelPage):
            if page.inspector_tabs.index() != self.remembered["model_inspector"]:
                page.inspector_tabs.set_index(self.remembered["model_inspector"])
            if page.view_switch.index() != self.remembered["model_view"]:
                page.view_switch.set_index(self.remembered["model_view"])
        elif isinstance(page, ComparePage):
            wanted = self.remembered.get("compare_tab", 0)
            if page.tabs.index() != wanted:
                page.tabs.set_index(wanted)
        elif isinstance(page, CpnPage):
            wanted = self.remembered.get("cpn_inspector", 0)
            if page.inspector_tabs.index() != wanted:
                page.inspector_tabs.set_index(wanted)

    def active_graph_view(self) -> GraphView | None:
        """The canvas the zoom commands act on: the focused one, else the
        largest canvas visible on the current page."""
        widget = QApplication.focusWidget()
        while widget is not None:
            if isinstance(widget, (GraphView, NetView)) and widget.isVisible():
                return widget
            widget = widget.parentWidget()
        page = self.current_page()
        if page is None:
            return None
        views = [v for v in page.findChildren(GraphView) + page.findChildren(NetView)
                 if v.isVisible()]
        return max(views, key=lambda v: v.width() * v.height(), default=None)

    def _zoom(self, how: str) -> None:
        view = self.active_graph_view()
        if view is not None:
            getattr(view, how)()

    def restyle(self) -> None:
        """Re-apply colours after a light/dark switch."""
        for controls in self.findChildren(ZoomControls):
            controls.restyle()
        for page in self.pages.values():
            if isinstance(page, CpnPage):
                page.restyle()
        self.update()

    def current_page(self) -> QWidget | None:
        """The LogPage or ModelPage being shown (None on the welcome page)."""
        holder = self.content.currentWidget()
        for document_id, candidate in self.holders.items():
            if candidate is holder:
                return self.pages[document_id]
        return None

    def _document(self, document_id: int):
        return next(d for d in self.documents if d.id == document_id)

    def selected_ids(self) -> list[int]:
        """Selected documents in sidebar order; the current one if none is selected."""
        ids = [item.data(0, Qt.UserRole) for item in self.tree.selectedItems()
               if item.data(0, Qt.UserRole) is not None]
        if not ids and self.tree.currentItem() is not None:
            current = self.tree.currentItem().data(0, Qt.UserRole)
            if current is not None:
                ids = [current]
        return ids

    # -- removing ----------------------------------------------------------------
    def remove_selected(self) -> None:
        self.remove_documents(self.selected_ids())

    def remove_all(self) -> None:
        if self.documents:
            self.remove_documents([d.id for d in self.documents])

    def remove_documents(self, ids: list[int]) -> None:
        """Remove documents from the workspace.  Files on disk are never touched.

        Only documents that exist nowhere else (a log typed in notation, a
        model just discovered) need a confirmation, because removing them
        loses them; anything opened from a file can simply be opened again.
        """
        documents = [d for d in self.documents if d.id in set(ids)]
        if not documents:
            return
        # Comparisons of removed logs go too (they cannot outlive their logs).
        removed_logs = {d.id for d in documents if isinstance(d, LogDocument)}
        for other in self.documents:
            if isinstance(other, ComparisonDocument) and other not in documents and \
                    any(log.id in removed_logs for log in other.logs):
                documents.append(other)
        # A comparison is recreated in a moment, so it needs no confirmation.
        unsaved = [d for d in documents if not isinstance(d, ComparisonDocument) and
                   (not d.path or getattr(d, "dirty", False))]
        if unsaved:
            names = "\n".join(f"• {d.name}" for d in unsaved[:8])
            more = f"\n… and {len(unsaved) - 8} more" if len(unsaved) > 8 else ""
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Remove from workspace")
            box.setText(f"Remove {len(documents)} item(s)? These have changes that exist only "
                        "in this window and will be lost:")
            box.setInformativeText(names + more + "\n\nSave or export them first to keep "
                                   "them.")
            remove = box.addButton("Remove", QMessageBox.DestructiveRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() is not remove:
                return

        # Choose what to select afterwards: the row below the last removed one.
        order = [item.data(0, Qt.UserRole) for item in self._document_items()]
        removed = {d.id for d in documents}
        after = [i for i in order[order.index(max(removed, key=order.index)) + 1:]
                 if i not in removed] if order else []
        before = [i for i in order if i not in removed]
        target = after[0] if after else (before[-1] if before else None)

        for document in documents:
            page = self.pages.pop(document.id)
            if hasattr(page, "shutdown"):
                page.shutdown()
            holder = self.holders.pop(document.id)
            self.content.removeWidget(holder)
            holder.deleteLater()
            item = self.items.pop(document.id)
            parent = item.parent()
            parent.removeChild(item)
            parent.setHidden(parent.childCount() == 0)
            self.open_options.pop(document.id, None)
        self.documents = [d for d in self.documents if d.id not in removed]
        self._refresh_log_choices()
        self._save_session()

        if target is not None:
            self.tree.clearSelection()
            self.tree.setCurrentItem(self.items[target])
        else:
            self.content.setCurrentIndex(0)
            self.setWindowTitle(APPLICATION_NAME)
        noun = "item" if len(documents) == 1 else "items"
        self.statusBar().showMessage(f"Removed {len(documents)} {noun} from the workspace", 5000)

    # Kept for the ⌘W binding in older code paths.
    close_current = remove_selected

    def _document_items(self) -> list[QTreeWidgetItem]:
        items = []
        for section in (self.logs_section, self.petri_section, self.models_section,
                        self.cpn_section, self.compare_section):
            items += [section.child(i) for i in range(section.childCount())]
        return items

    # -- renaming, exporting, revealing ---------------------------------------------
    def rename_selected(self) -> None:
        ids = self.selected_ids()
        if len(ids) != 1:
            return
        document = self._document(ids[0])
        if isinstance(document, ComparisonDocument):
            return
        name, ok = QInputDialog.getText(self, "Rename", "Name:", text=document.name)
        name = name.strip()
        if not ok or not name:
            return
        if isinstance(document, CpnDocument):
            self.pages[document.id]._checkpoint()          # renaming can be undone
        if isinstance(document, LogDocument):
            document.log.attributes["concept:name"] = name
        else:
            document.net.name = name
        if isinstance(document, CpnDocument):
            self.pages[document.id].set_dirty(True)
        self._refresh_item(document)
        self.pages[document.id].refresh_title()
        self.setWindowTitle(f"{name} — {APPLICATION_NAME}")
        self._refresh_log_choices()

    def export_selected(self) -> None:
        ids = self.selected_ids()
        if len(ids) == 1:
            self.pages[ids[0]].export()

    def _document_saved(self, document) -> None:
        """A page exported its document: it is now backed by that file."""
        self._refresh_item(document)
        self.open_options.pop(document.id, None)      # it is XES/PNML now, not CSV
        if document.path and document.path.lower().endswith(".csv"):
            # Reopen the exported CSV with its own (standard) columns, unasked.
            mapping = guess_mapping(sniff(document.path)[1])
            if mapping is not None:
                self.open_options[document.id] = {"csv_mapping": asdict(mapping)}
        self._remember_recent(document.path)
        self._save_session()

    def reveal(self, path: str) -> None:
        """Show the file in Finder / Explorer (selected), or open its folder."""
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", path], check=False)
        elif sys.platform == "win32":
            subprocess.run(["explorer", "/select,", str(Path(path))], check=False)
        else:   # Linux: no standard "select this file", so open the folder
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def _sidebar_menu(self, position) -> None:
        item = self.tree.itemAt(position)
        menu = QMenu(self)
        if item is not None and item.data(0, Qt.UserRole) is None:
            # A section header: offer to clear that section.
            section = item
            ids = [section.child(i).data(0, Qt.UserRole) for i in range(section.childCount())]
            kind = {id(self.logs_section): "Logs", id(self.petri_section): "Petri Nets",
                    id(self.models_section): "Models",
                    id(self.compare_section): "Comparisons"}.get(id(section), "Coloured Nets")
            menu.addAction(f"Remove All {kind}…", lambda: self.remove_documents(ids))
        else:
            if item is not None and not item.isSelected():
                self.tree.clearSelection()
                self.tree.setCurrentItem(item)
            ids = self.selected_ids()
            if not ids:
                menu.addAction("Open File…", self.action_open)
                menu.addAction("New Log from Notation…", self.action_notation)
            elif len(ids) == 1 and isinstance(self._document(ids[0]), ComparisonDocument):
                menu.addAction("Export Figures as CSV…", self.export_selected)
                menu.addSeparator()
                menu.addAction("Remove from Workspace", self.remove_selected)
            elif len(ids) == 1:
                document = self._document(ids[0])
                menu.addAction("Rename…", self.rename_selected)
                if isinstance(document, LogDocument) and len(self.logs()) > 1:
                    menu.addAction("Compare with…", lambda d=document: self.action_compare([d]))
                if isinstance(document, CpnDocument):
                    menu.addAction("Save", self.pages[document.id].save)
                    label_text = "Save As…"
                elif isinstance(document, LogDocument):
                    menu.addAction("Filter…", self.pages[document.id].filter_log)
                    label_text = "Export Log (XES or CSV)…"
                else:
                    label_text = "Export Model as PNML…"
                menu.addAction(label_text, self.export_selected)
                if document.path:
                    reveal = {"darwin": "Show in Finder", "win32": "Show in Explorer"}.get(
                        sys.platform, "Open Containing Folder")
                    menu.addAction(reveal, lambda p=document.path: self.reveal(p))
                menu.addSeparator()
                menu.addAction("Remove from Workspace", self.remove_selected)
            else:
                chosen = [self._document(i) for i in ids]
                if all(isinstance(d, LogDocument) for d in chosen):
                    menu.addAction(f"Compare {len(ids)} Logs", lambda: self.compare(chosen))
                    menu.addSeparator()
                menu.addAction(f"Remove {len(ids)} Items from Workspace", self.remove_selected)
        menu.exec(self.tree.viewport().mapToGlobal(position))

    # -- session and recent files -----------------------------------------------------
    def _session_entries(self) -> list[dict]:
        entries = []
        for document in self.documents:
            if document.path:
                entry = {"path": document.path}
                entry.update(self.open_options.get(document.id, {}))
                entries.append(entry)
        return entries

    def _save_session(self) -> None:
        if self.persist and not self._restoring:
            self.settings.setValue("session/files", json.dumps(self._session_entries()))

    def restore_session(self) -> None:
        """Reopen the files that were open when the app was last closed."""
        if not self.settings.value("session/restore", True, type=bool):
            return
        try:
            entries = json.loads(self.settings.value("session/files", "[]"))
        except (TypeError, ValueError):
            entries = []
        missing = []
        self._restoring = True
        try:
            for entry in entries:
                path = entry.get("path", "")
                if not Path(path).exists():
                    missing.append(Path(path).name)
                    continue
                self.open_path(path, csv_mapping=entry.get("csv_mapping"))
        finally:
            self._restoring = False
        self._save_session()
        if missing:
            self.statusBar().showMessage("Could not find: " + ", ".join(missing), 10000)

    def _remember_recent(self, path: str) -> None:
        if not self.persist or not path:
            return
        recent = [p for p in self._recent() if Path(p) != Path(path)]
        recent.insert(0, path)
        self.settings.setValue("recent", json.dumps(recent[:self.RECENT_LIMIT]))

    def _recent(self) -> list[str]:
        try:
            return list(json.loads(self.settings.value("recent", "[]")))
        except (TypeError, ValueError):
            return []

    def _fill_recent_menu(self) -> None:
        self.recent_menu.clear()
        recent = [p for p in self._recent() if Path(p).exists()]
        if not recent:
            action = self.recent_menu.addAction("No Recent Files")
            action.setEnabled(False)
            return
        for path in recent:
            self.recent_menu.addAction(Path(path).name, lambda p=path: self.open_path(p)) \
                .setToolTip(path)
        self.recent_menu.addSeparator()
        self.recent_menu.addAction("Clear Menu", lambda: self.settings.setValue("recent", "[]"))

    # ---------------------------------------------------------------- opening
    def action_open(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open", "",
            "Supported files (*.xes *.gz *.csv *.pnml *.cpn);;Event logs (*.xes *.gz *.csv);;"
            "Petri nets (*.pnml);;CPN Tools models (*.cpn);;All files (*)")
        for path in paths:
            self.open_path(path)

    def action_open_cpn(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open coloured Petri net", "",
                                              "CPN Tools models (*.cpn)")
        if path:
            self.open_path(path)

    def action_notation(self) -> None:
        dialog = NotationDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.add_document(LogDocument(dialog.log()))

    def open_path(self, path: str, csv_mapping: dict | None = None) -> None:
        lower = path.lower()
        name = Path(path).name
        try:
            if lower.endswith(".pnml"):
                from ...model.plain import from_petri_net
                petri = read_pnml(path)
                petri.name = Path(path).stem
                self.add_document(CpnDocument(from_petri_net(petri), path=path))
                self.statusBar().showMessage(f"Opened {name} — edit it, play the token game, "
                                             "or see the Analysis tab for soundness and more",
                                             10000)
            elif lower.endswith(".cpn"):
                from ...io.cpn_reader import read_cpn
                self.statusBar().showMessage(f"Reading {name}…")
                net = read_cpn(path)
                self.add_document(CpnDocument(net, path=path))
                problems = len(net.errors)
                self.statusBar().showMessage(
                    f"Opened {name}" + (f" — {problems} problem(s), see the Problems tab"
                                        if problems else ""), 10000)
            elif lower.endswith(".csv"):
                if csv_mapping is not None:          # reopening: reuse the saved mapping
                    mapping = ColumnMapping(**csv_mapping)
                else:
                    dialog = CsvDialog(path, self)
                    if dialog.exec() != QDialog.Accepted:
                        return
                    mapping = dialog.mapping()
                log = read_csv(path, mapping)
                self.add_document(LogDocument(log, path=path),
                                  options={"csv_mapping": asdict(mapping)})
            elif lower.endswith((".xes", ".xes.gz", ".gz")):
                self.statusBar().showMessage(f"Reading {name}…")
                run_in_background(
                    lambda: read_xes(path),
                    lambda log: (self.add_document(LogDocument(log, path=path)),
                                 self.statusBar().showMessage(
                                     f"Opened {name}: {len(log):,} cases", 6000)),
                    lambda message: QMessageBox.warning(self, "Could not open log",
                                                        f"{name}\n\n{message}"))
            else:
                QMessageBox.information(self, "Unsupported file",
                                        f"{name}: open .xes, .csv, .pnml or .cpn files.")
        except Exception as error:  # noqa: BLE001 - surface any import problem
            QMessageBox.warning(self, "Could not open file", f"{name}\n\n{error}")

    # ---------------------------------------------------------------- comparing
    def action_compare(self, preselected: list | None = None) -> None:
        """Compare the selected logs, or ask which logs to compare."""
        logs = self.logs()
        if len(logs) < 2:
            QMessageBox.information(self, "Compare logs", "Open at least two event logs to "
                                    "compare them.")
            return
        if preselected is None:
            chosen = [self._document(i) for i in self.selected_ids()]
            chosen = [d for d in chosen if isinstance(d, LogDocument)]
            if len(chosen) >= 2:
                self.compare(chosen)
                return
            preselected = chosen
        dialog = CompareDialog(logs, preselected, self)
        if dialog.exec() == QDialog.Accepted:
            self.compare(dialog.chosen())

    def compare(self, logs: list) -> None:
        for existing in self.documents:
            if isinstance(existing, ComparisonDocument) and \
                    [d.id for d in existing.logs] == [d.id for d in logs]:
                self.tree.setCurrentItem(self.items[existing.id])
                return
        self.add_document(ComparisonDocument(list(logs)))

    def action_new_petri(self) -> None:
        from ...model.plain import new_plain_net
        self.add_document(CpnDocument(new_plain_net(self._unique_cpn_name())))
        self.statusBar().showMessage("New Petri net: pick Place or Transition and click on the "
                                     "canvas; drag from one node to another to connect them",
                                     10000)

    def open_example_net(self, net) -> None:
        from ...model.plain import from_petri_net
        self.add_document(CpnDocument(from_petri_net(net)))

    def edit_petri_net(self, net) -> None:
        """Open a (discovered or imported) Petri net in the editor, as a copy."""
        from ...model.plain import from_petri_net
        editable = from_petri_net(net)
        editable.name = f"{net.name} (edited)"
        self.add_document(CpnDocument(editable))

    def action_new_cpn(self) -> None:
        from ...model.net import CPNet
        net = CPNet(self._unique_cpn_name())
        net.add_declaration("colset UNIT = unit;")
        net.add_declaration("colset INT = int;")
        net.add_page("Top")
        document = CpnDocument(net)
        self.add_document(document)
        self.statusBar().showMessage("New coloured Petri net: pick Place or Transition and "
                                     "click on the canvas to draw", 8000)

    def _unique_cpn_name(self) -> str:
        names = {d.name for d in self.documents}
        index = 1
        while f"Untitled {index}" in names:
            index += 1
        return f"Untitled {index}"

    def action_save(self) -> None:
        page = self.current_page()
        if isinstance(page, CpnPage):
            page.save()
        elif page is not None:
            page.export()

    def closeEvent(self, event) -> None:  # noqa: N802
        dirty = [d for d in self.documents if isinstance(d, CpnDocument) and d.dirty]
        if dirty:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Unsaved changes")
            box.setText("Save changes to " + ", ".join(f"“{d.name}”" for d in dirty[:4])
                        + (" and others" if len(dirty) > 4 else "") + " before quitting?")
            save = box.addButton("Save", QMessageBox.AcceptRole)
            discard = box.addButton("Don’t Save", QMessageBox.DestructiveRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            clicked = box.clickedButton()
            if clicked is save:
                if not all(self.pages[d.id].save() for d in dirty):
                    event.ignore()
                    return
            elif clicked is not discard:
                event.ignore()
                return
        self._save_session()
        event.accept()

    # ---------------------------------------------------------------- drag & drop
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.open_path(url.toLocalFile())


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if sys.platform == "win32":
        # Without its own AppUserModelID, Windows groups the window under
        # python.exe and shows Python's icon in the taskbar.
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CPNpy.Studio")
        except (AttributeError, OSError):
            pass
    application = QApplication.instance() or QApplication(argv)
    application.setApplicationName(APPLICATION_NAME)
    application.setWindowIcon(app_icon())
    application.setStyle("Fusion")
    application.setFont(theme.ui_font(13))
    application.setStyleSheet(style.stylesheet())
    window = StudioWindow(persist=True)
    # Follow the system appearance live: every colour is looked up through
    # style.tokens() at paint time, so re-applying the stylesheet and
    # repainting is enough when the user switches light <-> dark.
    hints = application.styleHints()
    if hasattr(hints, "colorSchemeChanged"):
        hints.colorSchemeChanged.connect(
            lambda *_: (application.setStyleSheet(style.stylesheet()), window.restyle()))
    window.show()
    window.restore_session()
    for path in argv[1:]:
        if path == "--new-cpn":             # `cpn-ide` without a file
            window.action_new_cpn()
        elif not path.startswith("-"):
            window.open_path(path)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
