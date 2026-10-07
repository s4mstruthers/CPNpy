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

With a folder open (File ▸ Open Folder…, e.g. "Week 2"; internally a
:class:`.workspace.Workspace`), the folder and the sidebar always match:

* the sidebar lists every log and net in the folder, open or not (lighter),
  with its subfolders (the Folder view) or grouped by kind;
* folder → app: files added, renamed or deleted in Finder show up by
  themselves, an open file changed on disk is reloaded, and one deleted on
  disk is marked as missing;
* app → folder: new nets and logs are files in the folder from the start,
  edits are saved as you go (autosave), and files can be moved between
  subfolders, renamed or moved to the Bin from the sidebar;
* files opened from elsewhere can be copied or moved into the folder.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import (
    QEvent, QFile, QFileSystemWatcher, QRect, QRectF, QSettings, QSize, Qt, QTimer, QUrl, Signal,
)
from PySide6.QtGui import (
    QAction, QColor, QDesktopServices, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QSizePolicy, QSplitter, QStackedWidget, QStyle, QStyledItemDelegate,
    QToolButton, QTreeWidgetItem, QTreeWidgetItemIterator, QVBoxLayout, QWidget,
)

from ...mining.csv_import import ColumnMapping, guess_mapping, read_csv, sniff
from ...mining.log import EventLog, parse_simple_log
from ...mining.pnml import read_pnml, write_pnml
from ...mining.xes import read_xes, write_xes
from .. import theme
from . import style
from ..canvas import NetScene, NetView
from .compare_page import ComparePage
from .cpn_page import CpnPage
from .petri_page import PetriNetPage
from .documents import ComparisonDocument, CpnDocument, LogDocument, ModelDocument
from .file_dialogs import IMPORT_CHOICES, ImportDialog, SettingsDialog, ask_about_clash
from .graph_view import GraphView, ZoomControls
from .log_page import LogPage
from .model_page import ModelPage
from .sidebar import FILE_ROLE, FOLDER_ROLE, SidebarTree
from .widgets import (
    Card, ElidedLabel, NoticeBar, SegmentedControl, button, dialog_folder, hbox, label,
    round_menus, scroll, set_dialog_folder, shortcut_text, vbox,
)
from .workspace import (
    FORBIDDEN_CHARACTERS, Workspace, WorkspaceFolder, display_name, file_kind, file_stem,
    file_suffix,
    made_by_cpnpy, safe_file_name, unique_path,
)
from .workers import run_in_background

APPLICATION_NAME = "CPNpy Studio"

#: Sidebar item data: the iCloud placeholder of a file that is only in iCloud.
CLOUD_ROLE = Qt.UserRole + 3

#: How long after the last edit a net in the folder is saved (milliseconds).
AUTOSAVE_DELAY = 1000

#: Name of the Bin on this system (macOS says Bin in British English, as here).
BIN = "Recycle Bin" if sys.platform == "win32" else "Bin"


def _file_suffix(path: Path) -> str:
    """The whole extension, so ``log.xes.gz`` gives ``.xes.gz`` (not just ``.gz``)."""
    return file_suffix(path.name)


def _file_stem(path: Path) -> str:
    """The file name without :func:`_file_suffix`: what a document opened from it is called."""
    return file_stem(path.name)


def _same_file(a: Path, b: Path) -> bool:
    """True when two paths name one file (e.g. a case-only change on macOS)."""
    try:
        return a.samefile(b)
    except OSError:
        return False


def _signature(path: str | Path) -> tuple[int, int] | None:
    """(modification time, size) of a file, or None when it is not there."""
    try:
        status = os.stat(path)
    except OSError:
        return None
    return status.st_mtime_ns, status.st_size


def move_to_trash(path: str | Path) -> bool:
    """Move a file or folder to the Bin (recoverable).  Tests replace this."""
    return bool(QFile.moveToTrash(str(path)))


def reveal_label() -> str:
    return {"darwin": "Show in Finder", "win32": "Show in Explorer"}.get(
        sys.platform, "Open Containing Folder")

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


def _faded_icon(kind: str) -> QIcon:
    """The kind's icon at reduced opacity: a workspace file that is not open yet."""
    source = _icon_pixmap(kind, None)
    faded = QPixmap(source.size())
    faded.fill(Qt.transparent)
    painter = QPainter(faded)
    painter.setOpacity(0.45)
    painter.drawPixmap(0, 0, source)
    painter.end()
    icon = QIcon(faded)
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
    if kind == "folder":
        painter.setPen(Qt.NoPen)
        painter.setBrush(ink if ink is not None else QColor(style.tokens().accent))
        tab = QRectF(3, 7, 11, 6)
        painter.drawRoundedRect(tab, 2, 2)
        painter.drawRoundedRect(QRectF(3, 10, 26, 16), 2.5, 2.5)
    elif kind == "compare":
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
        round_menus(QApplication.instance())
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
        #: The open folder (None: just loose files, as before).
        self.workspace: Workspace | None = None
        #: Its subfolders and files, as last listed (see _rescan_workspace).
        self._tree: WorkspaceFolder | None = None
        self._tree_signature: tuple = ()
        #: In a folder: the sidebar shows its subfolders ("folder") or groups by kind ("kind").
        self.view_mode = "folder"
        #: Expanded subfolders (relative paths), remembered in the folder's .cpnpy.
        self._expanded: set[str] = set()
        #: Sidebar rows by what they stand for (rebuilt by _rebuild_sidebar).
        self.placeholders: dict[str, QTreeWidgetItem] = {}       # files not open, by path key
        self.folder_items: dict[str, QTreeWidgetItem] = {}       # subfolders, by relative path
        #: Reopening a folder: files still loading, and the one that was selected.
        self._restore_paths: dict[str, dict] = {}
        self._restore_selected: str | None = None
        #: When a click last opened a file of the folder (see _on_double_click).
        self._clicked_open_at = 0.0
        #: Files being opened by a click (shown with "…"), and iCloud downloads to open.
        self._opening: set[str] = set()
        self._pending_downloads: set[str] = set()
        # Files added, removed or renamed in the folder (in Finder, say) show
        # up by themselves; the timer folds a burst of changes into one rescan.
        self.watcher = QFileSystemWatcher(self)
        self._rescan_timer = QTimer(self)
        self._rescan_timer.setSingleShot(True)
        # macOS reports a change about half a second after it happens; this
        # only folds a burst of events (a whole folder copied in) into one.
        self._rescan_timer.setInterval(100)
        self._rescan_timer.timeout.connect(self._rescan_workspace)
        self.watcher.directoryChanged.connect(lambda _path: self._rescan_timer.start())
        # Open files are watched too: one changed on disk is reloaded.
        self._changed_files: set[str] = set()
        self._file_timer = QTimer(self)
        self._file_timer.setSingleShot(True)
        self._file_timer.setInterval(150)       # also: how long a file must stay unchanged
        self._file_timer.timeout.connect(self._check_changed_files)
        self.watcher.fileChanged.connect(self._file_changed)
        #: (mtime, size) of files the app wrote itself, so its own saves are not
        #: mistaken for changes made elsewhere; and of changes not settled yet.
        self._own_writes: dict[str, tuple] = {}
        self._unsettled: dict[str, tuple] = {}
        self._gone_checks: dict[str, int] = {}
        self._reload_attempts: dict[str, int] = {}
        #: Each open file's identity on disk, so a file moved or renamed in
        #: Finder is recognised in its new place (see _relocate).
        self._identities: dict[int, tuple] = {}
        #: Documents with a "changed on disk" question open: not autosaved meanwhile.
        self._conflicts: set[int] = set()
        # One Snap to grid setting for every editor, kept between launches.
        NetScene.snap_to_grid = self._setting("editor/snap_to_grid", False)
        #: Autosave: one timer per document, restarted on each edit.
        self.autosave_enabled = self._setting("files/autosave", True)
        self._autosave_timers: dict[int, QTimer] = {}
        #: Documents whose autosave failed (read-only folder, full disk): saved
        #: with ⌘S again, with the "edited" dot, until a save works.
        self._autosave_failed: set[int] = set()
        #: .cpn documents whose file CPNpy wrote (only those are autosaved).
        self._cpnpy_files: set[int] = set()
        #: Files the app created by itself this session (a new net's "Untitled 1.pnml").
        self._created: set[str] = set()
        #: The bytes of each net's file as it was opened (File ▸ Revert to Saved).
        self._originals: dict[int, bytes] = {}
        #: Each page's notice bar ("changed on disk", "missing").
        self.banners: dict[int, NoticeBar] = {}
        #: Counts folder switches (opening or closing one), so a log still
        #: loading from the folder that was left is not added to the new one.
        self._folder_switches = 0
        #: Software updates: a check is running; the installer to run on quitting.
        self._checking_updates = False
        self._installer: list[str] | None = None
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
        # Hidden and shown only by toggle_sidebar, so its button and menu tick agree.
        root.setCollapsible(0, False)
        self.content = QStackedWidget()
        self.content.addWidget(scroll(self._build_welcome(), horizontal=True))
        # Above the pages: "a new version is out" (see check_automatically).
        from .updates import UpdateBar
        self.update_bar = UpdateBar()
        self.update_bar.whats_new.connect(lambda: self._show_update_dialog(
            self.update_bar.release))
        self.update_bar.install.connect(lambda: self._update_action(
            self.update_bar.release, "install"))
        self.update_bar.skip.connect(lambda: self._update_action(
            self.update_bar.release, "skip"))
        right = QWidget()
        right.setLayout(vbox(self.update_bar, self.content, spacing=0))
        right.layout().setStretch(1, 1)
        root.addWidget(right)
        root.setStretchFactor(1, 1)
        root.setSizes([220, 1260])
        self.setCentralWidget(root)
        self.statusBar().showMessage("Ready")
        self._build_menus()
        if not self._setting("window/sidebar", True):
            self.toggle_sidebar(False)

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

    def _setting(self, key: str, default):
        """A setting of the app (the default in tests, which must not see yours)."""
        if not self.persist:
            return default
        return self.settings.value(key, default, type=type(default))

    def _set_setting(self, key: str, value) -> None:
        if self.persist:
            self.settings.setValue(key, value)

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
        layout.addWidget(self._build_sidebar_header())

        # In a folder: its subfolders, or grouped by kind as without one.
        self.view_switch = SegmentedControl(["Folders", "By kind"], compact=True)
        self.view_switch.setToolTip("Show the folder's subfolders, or group the files by kind")
        self.view_switch.changed.connect(
            lambda index: self.set_view_mode(("folder", "kind")[index]))
        self.view_row = QWidget()
        self.view_row.setLayout(hbox(self.view_switch, None, margins=(10, 0, 0, 2)))
        self.view_row.setHidden(True)
        layout.addWidget(self.view_row)

        self.tree = SidebarTree()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setRootIsDecorated(False)
        self.tree.setMouseTracking(True)                  # hover state for the ✕ button
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)   # ⌘/⇧-click
        self.tree.setTextElideMode(Qt.ElideRight)
        self.tree.path_for = self._row_path
        self.tree.drop_folder = self._drop_folder
        self.tree.paths_dropped.connect(self._sidebar_drop)
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
        # The Folder view: documents with no file (a model just discovered)
        # on top, then the folder's subfolders and files, then open files
        # from elsewhere and comparisons.
        self.unsaved_section = self._section("UNSAVED")
        self.logs_section = self._section("EVENT LOGS")
        self.petri_section = self._section("PETRI NETS")
        self.models_section = self._section("MODELS")
        self.cpn_section = self._section("COLOURED NETS")
        self.elsewhere_section = self._section("OTHER FILES")
        self.elsewhere_section.setToolTip(0, "Open files that are not in the folder")
        self.compare_section = self._section("COMPARISONS")
        # Shown in an empty folder, so an empty sidebar is not a mystery.
        self.empty_hint = QTreeWidgetItem(self.tree, ["No logs or nets yet"])
        self.empty_hint.setFlags(Qt.NoItemFlags)
        self.empty_hint.setToolTip(0, "Save a net or export a log into the folder, or add "
                                      "files to it in Finder: they appear here.")
        self.empty_hint.setHidden(True)
        # Shown when a huge folder was only partly listed.
        self.more_row = QTreeWidgetItem(["… more files not shown"])
        self.more_row.setFlags(Qt.NoItemFlags)
        self.more_row.setToolTip(0, "The sidebar lists up to 500 files, three subfolders deep. "
                                    "Open a smaller folder to see everything.")
        self.tree.currentItemChanged.connect(self._on_select)
        # A file that is not open yet opens with one click (or Return).
        self.tree.itemClicked.connect(lambda item, _column: self._open_placeholder(item))
        self.tree.itemActivated.connect(lambda item, _column: self._open_placeholder(item))
        # Double-click an open document to rename it (section headings have no id).
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.itemExpanded.connect(lambda item: self._folder_toggled(item, True))
        self.tree.itemCollapsed.connect(lambda item: self._folder_toggled(item, False))
        layout.addWidget(self.tree, 1)

        footer = QWidget()
        footer.setObjectName("sidebarFooter")
        footer.setLayout(vbox(button("＋  Open file…", self.action_open),
                              button("✎  Log from notation…", self.action_notation),
                              button("⇄  Compare logs…", lambda: self.action_compare()),
                              spacing=0))
        layout.addWidget(footer)
        return sidebar

    def _build_sidebar_header(self) -> QWidget:
        """"CPNpy Studio", or the workspace's name with a ⋯ menu."""
        header = QWidget()
        row = QHBoxLayout(header)
        row.setContentsMargins(10, 0, 2, 6)
        row.setSpacing(4)
        text = QVBoxLayout()
        text.setSpacing(1)
        self.workspace_caption = label("FOLDER", "sidebarCaption")
        self.workspace_caption.setHidden(True)
        self.sidebar_title = ElidedLabel(APPLICATION_NAME, "sidebarTitle")
        text.addWidget(self.workspace_caption)
        text.addWidget(self.sidebar_title)
        row.addLayout(text, 1)
        self.workspace_button = QToolButton()
        self.workspace_button.setObjectName("sidebarMenuButton")
        self.workspace_button.setText("⋯")
        self.workspace_button.setToolTip("Folder")
        self.workspace_button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.workspace_button)
        reveal = {"darwin": "Show in Finder", "win32": "Show in Explorer"}.get(
            sys.platform, "Open Folder")
        menu.addAction(reveal, lambda: self.workspace and self.reveal(str(self.workspace.folder)))
        menu.addAction("New Folder…", lambda: self.new_folder())
        menu.addSeparator()
        menu.addAction("Open Another Folder…", self.action_open_workspace)
        menu.addSeparator()
        menu.addAction("Close Folder", self.close_workspace)
        self.workspace_button.setMenu(menu)
        self.workspace_button.setHidden(True)
        row.addWidget(self.workspace_button, 0, Qt.AlignVCenter)
        return header

    def toggle_sidebar(self, show: bool | None = None) -> None:
        """Show or hide the sidebar (hidden, every page gets the full width)."""
        if show is None:
            show = self.sidebar.isHidden()
        self.sidebar.setHidden(not show)
        action = getattr(self, "sidebar_action", None)
        if action is not None and action.isChecked() != show:
            action.blockSignals(True)
            action.setChecked(show)
            action.blockSignals(False)
        self._set_setting("window/sidebar", show)

    def _sidebar_button(self) -> QToolButton:
        """The button at the top left of every page that hides or shows the sidebar."""
        from .tool_icons import sidebar_icon
        toggle = QToolButton()
        toggle.setObjectName("sidebarToggle")
        toggle.setIcon(sidebar_icon())
        toggle.setIconSize(QSize(20, 20))
        toggle.setCursor(Qt.PointingHandCursor)
        toggle.setToolTip(f"Show or hide the sidebar ({shortcut_text('Ctrl+Alt+S')})")
        toggle.clicked.connect(lambda: self.toggle_sidebar())
        return toggle

    def _section(self, title: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem(self.tree, [title])
        # No ▸ for a heading: the sidebar only draws one for subfolders (a
        # DontShowIndicator policy would also make Qt hide the heading's rows).
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
        outer.setContentsMargins(20, 16, 32, 32)
        outer.addLayout(hbox(self._sidebar_button(), None))
        outer.addSpacing(24)
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
        # A whole-width card on top: working in a folder is the main way in.
        workspace_card = Card("Work in a folder")
        workspace_card.add(label(
            "Open a folder such as “Week 2”: its event logs and Petri nets are listed in "
            "the sidebar, and the nets you draw are saved there. "
            "Next time, everything you had open comes back.", "muted", wrap=True))
        self.welcome_recent = QWidget()
        self.welcome_recent.setObjectName("plain")
        self.welcome_recent.setStyleSheet("#plain { background: transparent; border: none; }")
        self.welcome_recent.setLayout(hbox(spacing=8))
        workspace_card.add(hbox(button("Open folder…", self.action_open_workspace,
                                       kind="primary"), self.welcome_recent, None))
        self.welcome_folder_card = workspace_card
        grid.addWidget(workspace_card, 0, 0, 1, 2)
        # Inside a workspace the top card is about that folder instead.
        inside = Card("Folder")
        self.welcome_inside_title = inside.title_label
        self.welcome_inside_text = label("", "muted", wrap=True)
        inside.add(self.welcome_inside_text)
        reveal = {"darwin": "Show in Finder", "win32": "Show in Explorer"}.get(
            sys.platform, "Open Folder")
        inside.add(hbox(button("New Petri net", self.action_new_petri, kind="primary"),
                        button("New coloured net", self.action_new_cpn),
                        button(reveal, lambda: self.workspace and
                               self.reveal(str(self.workspace.folder))),
                        None,
                        button("Close folder", self.close_workspace)))
        inside.setHidden(True)
        self.welcome_inside_card = inside
        grid.addWidget(inside, 0, 0, 1, 2)
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
            card.add(hbox(button(action, slot), None))
            grid.addWidget(card, 1 + index // 2, index % 2)
        holder = QWidget()
        holder.setLayout(grid)
        holder.setMaximumWidth(760)
        holder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # Centre with stretches rather than an alignment flag: an aligned
        # widget is sized by its sizeHint and its wrapped labels get clipped.
        outer.addLayout(hbox(None, holder, None))
        outer.addSpacing(20)
        tip = label("Tip: drop files (or a folder, to work in it) anywhere on this "
                    "window. Hover a file in the sidebar and click ✕ (or press "
                    f"{shortcut_text('Backspace')}) to close "
                    "it; double-click a name to rename it.", "muted", wrap=True)
        tip.setAlignment(Qt.AlignHCenter)
        tip.setMaximumWidth(760)
        tip.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        outer.addLayout(hbox(None, tip, None))
        outer.addStretch(2)
        self._refresh_welcome_recent()
        return page

    # ---------------------------------------------------------------- menus
    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        self._action(file_menu, "Open…", QKeySequence.Open, self.action_open)
        self._action(file_menu, "Open Folder…", "Ctrl+Alt+O", self.action_open_workspace)
        self.recent_workspaces_menu = file_menu.addMenu("Open Recent Folder")
        self.recent_workspaces_menu.aboutToShow.connect(self._fill_recent_workspaces_menu)
        self.close_workspace_action = self._action(file_menu, "Close Folder", None,
                                                   self.close_workspace)
        self.close_workspace_action.setEnabled(False)
        file_menu.addSeparator()
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
        self._action(file_menu, "Revert to Saved…", None, self.revert_selected)
        self.autosave_action = QAction("Autosave", self)
        self.autosave_action.setCheckable(True)
        self.autosave_action.setChecked(self.autosave_enabled)
        self.autosave_action.setToolTip("Save edits to nets in the open folder as you go")
        self.autosave_action.toggled.connect(self.set_autosave)
        file_menu.addAction(self.autosave_action)
        file_menu.addSeparator()
        self._action(file_menu, f"Move to {BIN}", None, self.trash_selected)
        self._action(file_menu, "Close", QKeySequence.Close, self.remove_selected)
        self._action(file_menu, "Close All", "Ctrl+Shift+W", self.remove_all)
        file_menu.addSeparator()
        self.restore_action = QAction("Reopen Files at Launch", self)
        self.restore_action.setCheckable(True)
        self.restore_action.setChecked(self._setting("session/restore", True))
        self.restore_action.toggled.connect(lambda on: self._set_setting("session/restore", on))
        file_menu.addAction(self.restore_action)
        settings = self._action(file_menu, "Settings…", QKeySequence.Preferences,
                                self.show_settings)
        settings.setMenuRole(QAction.PreferencesRole)      # the app menu, on macOS

        view_menu = self.menuBar().addMenu("&View")
        self._action(view_menu, "Show Welcome Page", "Ctrl+1",
                     lambda: self.content.setCurrentIndex(0))
        self.sidebar_action = self._action(view_menu, "Show Sidebar", "Ctrl+Alt+S",
                                           lambda on: self.toggle_sidebar(on))
        self.sidebar_action.setCheckable(True)
        self.sidebar_action.setChecked(True)
        view_menu.addSeparator()
        zoom_in = self._action(view_menu, "Zoom In", QKeySequence.ZoomIn,
                               lambda: self._zoom("zoom_in"))
        zoom_in.setShortcuts([QKeySequence.ZoomIn, QKeySequence("Ctrl+=")])
        self._action(view_menu, "Zoom Out", QKeySequence.ZoomOut, lambda: self._zoom("zoom_out"))
        self._action(view_menu, "Zoom to Fit", "Ctrl+0", lambda: self._zoom("fit"))
        self._action(view_menu, "Actual Size", "Ctrl+Alt+0", lambda: self._zoom("actual_size"))

        help_menu = self.menuBar().addMenu("&Help")
        self._action(help_menu, "Definitions", None, self._definitions)
        self._action(help_menu, "Check for Updates…", None,
                     lambda: self.check_for_updates(manual=True))
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
        from ... import __version__
        QMessageBox.about(self, APPLICATION_NAME,
                          f"<b>{APPLICATION_NAME}</b> {__version__}"
                          "<p>Process mining and Petri nets in pure "
                          "Python. Algorithms follow the TU/e course readings; see the "
                          "docstrings in <code>cpnpy.mining</code>.</p>")

    # ---------------------------------------------------------------- documents
    def logs(self) -> list[LogDocument]:
        return [d for d in self.documents if isinstance(d, LogDocument)]

    def add_document(self, document, options: dict | None = None,
                     near: str | None = None) -> None:
        """Add a document to the window and show it.

        Opening a file that is already open just selects it, so the sidebar
        never fills up with duplicates.  With a folder open, a new log or net
        (one with no file yet) is saved into the folder straight away, next
        to ``near`` (the file it was made from) when that is in the folder.
        """
        if document.path:
            for existing in self.documents:
                if existing.path and self._key(existing.path) == self._key(document.path) \
                        and type(existing) is type(document):
                    self._select_document(existing)
                    self.statusBar().showMessage(f"{Path(document.path).name} is already open", 5000)
                    return
        self.documents.append(document)
        if options:
            self.open_options[document.id] = options
        self._make_page(document)
        self._materialise(document, near)
        if document.path:
            key = self._key(document.path)
            self._opening.discard(key)
            self._remember_identity(document)
            if isinstance(document, CpnDocument):
                if not document.path.lower().endswith(".cpn") or made_by_cpnpy(document.path):
                    self._cpnpy_files.add(document.id)
                self._keep_original(document)
        self._update_autosave(document)
        # Reopening a folder loads logs in the background, in any order: of
        # those files, only the one that was selected last time takes the
        # selection.  Anything you open yourself is always selected.
        key = self._key(document.path) if document.path else None
        restored = key is not None and key in self._restore_paths
        self._restore_paths.pop(key, None)
        self._rebuild_sidebar()
        if not restored or self._restore_selected in (None, key):
            self._select_document(document)
        self._refresh_log_choices()
        if document.path:
            self._remember_recent(document.path)
        self._save_session()

    def _make_page(self, document) -> QWidget:
        """Build the page showing ``document`` (and its holder in the stack)."""
        if isinstance(document, LogDocument):
            page = LogPage(document)
            page.open_model.connect(self.add_document)
            page.open_log.connect(lambda log, source=document: self.add_document(
                log, near=source.path))
            page.tabs.changed.connect(lambda i: self.remembered.__setitem__("log_tab", i))
        elif isinstance(document, ComparisonDocument):
            page = ComparePage(document)
            page.tabs.changed.connect(lambda i: self.remembered.__setitem__("compare_tab", i))
        elif isinstance(document, CpnDocument):
            plain = getattr(document.net, "plain", False)
            page = PetriNetPage(document) if plain else CpnPage(document)
            page.log_generated.connect(lambda log, source=document: self.add_document(
                LogDocument(log), near=source.path))
            page.dirty_changed.connect(lambda _dirty, doc=document: self._refresh_item(doc))
            page.edited.connect(lambda doc=document: self._schedule_autosave(doc))
            page.snap_changed.connect(self._snap_changed)
            page.inspector_tabs.changed.connect(
                lambda i, key="petri_inspector" if plain else "cpn_inspector":
                self.remembered.__setitem__(key, i))
            if plain:
                page.open_model.connect(self.add_document)
        else:
            page = ModelPage(document, self.logs)
            page.inspector_tabs.changed.connect(
                lambda i: self.remembered.__setitem__("model_inspector", i))
            page.view_switch.changed.connect(
                lambda i: self.remembered.__setitem__("model_view", i))
            page.log_generated.connect(lambda log, source=document: self.add_document(
                LogDocument(log), near=source.path or (source.source_log.path
                                                       if source.source_log else None)))
            page.edit_requested.connect(self.edit_petri_net)
            page.keep_requested.connect(lambda doc=document: self.keep_model(doc))
        page.status.connect(lambda message: self.statusBar().showMessage(message, 8000))
        page.saved.connect(lambda doc=document: self._document_saved(doc))
        if not isinstance(document, ComparisonDocument):
            page.header.title_double_clicked.connect(
                lambda doc=document: self.rename_document(doc))
            page.header.title.set_hint("Double-click to rename")
        self.pages[document.id] = page
        page.header.layout().insertWidget(0, self._sidebar_button(), 0, Qt.AlignTop)
        # The page sits in a scroll area: if the window is made smaller than
        # the page's minimum size, scroll bars appear instead of the window
        # refusing to shrink (which is what pushed it off the screen).
        # Above it, a bar for news about its file ("changed on disk", …).
        banner = NoticeBar()
        holder = QWidget()
        holder.setLayout(vbox(banner, scroll(page, horizontal=True), spacing=0))
        holder.layout().setStretch(1, 1)
        self.banners[document.id] = banner
        self.holders[document.id] = holder
        self.content.addWidget(holder)
        return page

    def _snap_changed(self, on: bool) -> None:
        """Snap to grid was ticked in one editor: the same everywhere, and next time."""
        self._set_setting("editor/snap_to_grid", on)
        for page in self.pages.values():
            box = getattr(page, "grid_box", None)
            if box is not None and box.isChecked() != on:
                box.blockSignals(True)
                box.setChecked(on)
                box.blockSignals(False)

    def _select_document(self, document) -> None:
        item = self.items.get(document.id)
        if item is None:
            return
        parent = item.parent()
        while parent is not None:                  # inside a collapsed subfolder
            parent.setExpanded(True)
            parent = parent.parent()
        self.tree.clearSelection()
        self.tree.setCurrentItem(item)

    def _refresh_item(self, document) -> None:
        """Sidebar text: the name, plus a dot while a model has unsaved edits."""
        item = self.items.get(document.id)
        if item is None:
            return
        if item.text(0) != self._row_text(document) and self.workspace is not None:
            self._rebuild_sidebar()               # a new name: keep the rows in order
        else:
            self._style_document_row(item, document)

    def _row_text(self, document) -> str:
        dirty = getattr(document, "dirty", False) and not getattr(document, "autosave", False)
        return document.name + ("  •" if dirty else "")

    def _style_document_row(self, item: QTreeWidgetItem, document) -> None:
        item.setText(0, self._row_text(document))
        font = item.font(0)
        font.setItalic(bool(getattr(document, "missing", False)))
        item.setFont(0, font)
        self._set_item_tooltip(item, document)

    def _set_item_tooltip(self, item: QTreeWidgetItem, document) -> None:
        if getattr(document, "missing", False):
            where = f"{document.path}\nThe file is missing (moved or deleted) — Save As… to keep it"
        else:
            where = document.path or "Not saved to a file — export it to keep it"
        item.setToolTip(0, f"{document.name}\n{where}")

    def _refresh_log_choices(self) -> None:
        for page in self.pages.values():
            if isinstance(page, ModelPage):
                page.refresh_logs()

    def _on_select(self, current, previous=None) -> None:
        # Switching to another file saves the one you were editing.
        try:
            left = previous.data(0, Qt.UserRole) if previous is not None else None
        except RuntimeError:                      # a row the sidebar has just rebuilt
            left = None
        if left is not None:
            self._flush_autosaves([left])
        if current is None or current.data(0, Qt.UserRole) is None:
            return
        holder = self.holders.get(current.data(0, Qt.UserRole))
        if holder is not None:
            self._restore_tab(self.pages[current.data(0, Qt.UserRole)])
            self.content.setCurrentWidget(holder)
            self._set_title(self._document(current.data(0, Qt.UserRole)))

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

    def remove_documents(self, ids: list[int], confirm: bool = True) -> bool:
        """Close documents.  Files on disk are never touched (edits are saved
        first where autosave applies).

        Returns False when the user cancelled.  In a folder, a closed file
        stays listed (lighter) so it can be opened again with one click.

        Only documents that exist nowhere else (a log typed in notation, a
        model just discovered) need a confirmation, because removing them
        loses them; anything opened from a file can simply be opened again.
        ``confirm=False`` skips that question (the caller asked already).
        """
        documents = [d for d in self.documents if d.id in set(ids)]
        if not documents:
            return True
        self._flush_autosaves([d.id for d in documents])
        # Comparisons of removed logs go too (they cannot outlive their logs).
        removed_logs = {d.id for d in documents if isinstance(d, LogDocument)}
        for other in self.documents:
            if isinstance(other, ComparisonDocument) and other not in documents and \
                    any(log.id in removed_logs for log in other.logs):
                documents.append(other)
        # A comparison is recreated in a moment, so it needs no confirmation.
        unsaved = [d for d in documents if not isinstance(d, ComparisonDocument) and
                   (not d.path or d.missing or getattr(d, "dirty", False))]
        if unsaved and confirm:
            names = "\n".join(f"• {d.name}" for d in unsaved[:8])
            more = f"\n… and {len(unsaved) - 8} more" if len(unsaved) > 8 else ""
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Close")
            box.setText(f"Close {len(documents)} item(s)? These have changes that exist only "
                        "in this window and will be lost:")
            box.setInformativeText(names + more + "\n\nSave or export them first to keep "
                                   "them.")
            remove = box.addButton("Close", QMessageBox.DestructiveRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() is not remove:
                return False

        # Choose what to select afterwards: the row below the last removed one.
        order = [item.data(0, Qt.UserRole) for item in self._document_items()]
        removed = {d.id for d in documents}
        after = [i for i in order[order.index(max(removed, key=order.index)) + 1:]
                 if i not in removed] if order else []
        before = [i for i in order if i not in removed]
        target = after[0] if after else (before[-1] if before else None)

        for document in documents:
            self._drop_page(document)
            self.open_options.pop(document.id, None)
            for store in (self._originals, self._autosave_timers):
                store.pop(document.id, None)
            self._cpnpy_files.discard(document.id)
            self._conflicts.discard(document.id)
        self.documents = [d for d in self.documents if d.id not in removed]
        self._rebuild_sidebar()             # closed files of the folder are listed again
        self._refresh_log_choices()
        self._save_session()

        if target is not None:
            self._select_document(self._document(target))
        else:
            self.tree.clearSelection()
            self.tree.setCurrentItem(None)
            self.content.setCurrentIndex(0)
            self._set_title(None)
        noun = "item" if len(documents) == 1 else "items"
        self.statusBar().showMessage(f"Closed {len(documents)} {noun}", 5000)
        return True

    # Kept for the ⌘W binding in older code paths.
    close_current = remove_selected

    def _drop_page(self, document) -> None:
        page = self.pages.pop(document.id)
        if hasattr(page, "shutdown"):
            page.shutdown()
        holder = self.holders.pop(document.id)
        self.content.removeWidget(holder)
        holder.deleteLater()
        self.banners.pop(document.id, None)
        timer = self._autosave_timers.get(document.id)
        if timer is not None:
            timer.stop()

    def _document_items(self) -> list[QTreeWidgetItem]:
        """The open documents' rows, top to bottom (not the "not open" ones)."""
        items = []
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value() is not None:
            item = iterator.value()
            if item.data(0, Qt.UserRole) is not None:
                items.append(item)
            iterator += 1
        return items

    # -- renaming, exporting, revealing ---------------------------------------------
    def rename_selected(self) -> None:
        ids = self.selected_ids()
        if len(ids) == 1:
            self.rename_document(self._document(ids[0]))

    #: Characters macOS, Windows or Linux do not allow in a file name.
    FILE_NAME_FORBIDDEN = FORBIDDEN_CHARACTERS

    def _rename_on_disk(self, source: Path, target: Path) -> bool:
        """Rename a file or folder, explaining why not if it cannot be done."""
        problem = None
        name = target.name if source.is_dir() else _file_stem(target)
        if self.FILE_NAME_FORBIDDEN & set(name) or name in (".", "..") \
                or name.startswith("."):
            problem = ("A name cannot start with a dot or contain any of  "
                       "/ \\ : * ? \" < > |")
        elif target.exists() and not _same_file(source, target):
            problem = f"There is already something called “{target.name}” in that folder."
        else:
            self._flush_autosaves()
            try:
                source.rename(target)          # a case-only change works too (same file)
            except OSError as error:
                problem = f"It could not be renamed: {error.strerror or error}"
        if problem is not None:
            QMessageBox.warning(self, "Could not rename", problem)
            return False
        self._paths_moved(source, target)
        return True

    def rename_document(self, document) -> None:
        """Ask for a new name; if the document is named after its file, rename the file too.

        A net opened from ``order.pnml`` (or saved as it) is called "order", so
        renaming it to "order v2" also renames the file to ``order v2.pnml``
        in the same folder.  A document whose name is not its file's name (an
        event log is named by its ``concept:name``, e.g. "Wilma 50 passengers"
        in ``PlaneBoarding_Wilma_50.xes``) only gets a new name in the app.
        """
        if isinstance(document, ComparisonDocument):
            return
        old_name = document.name
        name, ok = QInputDialog.getText(self, "Rename", "Name:", text=old_name)
        name = name.strip()
        if not ok or not name or name == old_name:
            return

        source = Path(document.path) if document.path else None
        renames_file = (source is not None and source.exists()
                        and _file_stem(source) == old_name)
        if renames_file:
            if self.FILE_NAME_FORBIDDEN & set(name) or name in (".", ".."):
                QMessageBox.warning(self, "Could not rename", "A file name cannot contain any "
                                    "of  / \\ : * ? \" < > |")
                return
            target = source.with_name(name + _file_suffix(source))
            if not self._rename_on_disk(source, target):
                return
            self.statusBar().showMessage(f"Renamed the file to {target.name}", 8000)
        elif isinstance(document, CpnDocument):
            # Only the name in the model changes: it is an edit, so it can be undone.
            self.pages[document.id]._checkpoint()

        if isinstance(document, LogDocument):
            document.log.attributes["concept:name"] = name
        else:
            document.net.name = name
        if isinstance(document, CpnDocument) and not renames_file:
            self.pages[document.id].set_dirty(True)
        self._rebuild_sidebar()
        self.pages[document.id].refresh_title()
        self._set_title(document)
        self._refresh_log_choices()
        self._save_session()

    def rename_path(self, path: str) -> None:
        """Rename a file that is not open, or a subfolder (the sidebar's Rename…)."""
        source = Path(path)
        folder = source.is_dir()
        old_name = source.name if folder else _file_stem(source)
        name, ok = QInputDialog.getText(self, "Rename", "Name:", text=old_name)
        name = name.strip()
        if not ok or not name or name == old_name:
            return
        target = source.with_name(name if folder else name + _file_suffix(source))
        if self._rename_on_disk(source, target):
            self.statusBar().showMessage(f"Renamed to {target.name}", 6000)
            self._rescan_workspace()

    def _paths_moved(self, old: Path, new: Path) -> None:
        """A file or folder was moved or renamed (by the app): follow it.

        Open documents in it get their new path (unsaved edits stay, with
        their dot), and so do the remembered recent files and expanded folders.
        """
        old, new = Path(old), Path(new)

        base = old.resolve()

        def moved(path: str) -> Path | None:
            candidate = Path(path).resolve()
            if candidate == base:
                return new
            try:
                return new / candidate.relative_to(base)
            except ValueError:
                return None

        for document in self.documents:
            if document.path and (target := moved(document.path)) is not None:
                self._forget_recent(document.path)
                previous_key = self._key(document.path)
                document.path = str(target)
                if previous_key in self._own_writes:
                    self._own_writes[self._key(target)] = self._own_writes.pop(previous_key)
                if previous_key in self._created:     # still the app's own "Untitled 1"
                    self._created.discard(previous_key)
                    self._created.add(self._key(target))
                if getattr(document, "_last_path", None):
                    document._last_path = str(target)
                self._remember_recent(document.path)
                self.pages[document.id].refresh_title()
                self._update_autosave(document)
        if self.workspace is not None:
            old_relative, new_relative = self.workspace.relative(old), self.workspace.relative(new)
            renamed = set()
            for relative in self._expanded:
                if relative == old_relative or relative.startswith(old_relative + "/"):
                    renamed.add(new_relative + relative[len(old_relative):])
                else:
                    renamed.add(relative)
            if renamed != self._expanded:
                self._expanded = renamed
                self.workspace.update_settings(expanded=sorted(self._expanded))
        self._save_session()

    def export_selected(self) -> None:
        ids = self.selected_ids()
        if len(ids) == 1:
            self.pages[ids[0]].export()

    def _document_saved(self, document) -> None:
        """A page saved or exported its document: it is now backed by that file."""
        previous = getattr(document, "_last_path", None)
        document._last_path = document.path
        signature = _signature(document.path) if document.path else None
        if signature is not None:
            self._own_writes[self._key(document.path)] = signature
            self._remember_identity(document)     # a safe save is a new file on disk
        if previous and self._key(previous) != self._key(document.path) \
                and self._key(previous) in self._created and Path(previous).exists():
            # Save As of a net the app created ("Untitled 1.pnml"): the old file
            # was only ever the app's, so it does not stay behind as a duplicate.
            self._created.discard(self._key(previous))
            move_to_trash(previous)
        if isinstance(document, CpnDocument):
            self._cpnpy_files.add(document.id)      # CPNpy wrote it: autosaving is safe
        if document.id in self._autosave_failed:    # saving works again
            self._autosave_failed.discard(document.id)
            self.banners[document.id].clear("unsaved")
        self._update_autosave(document)
        banner = self.banners.get(document.id)
        if banner is not None:
            banner.clear("missing")
        if document.id in self.items:
            self._refresh_item(document)
            if self.selected_ids() == [document.id]:
                # Save As may have renamed it after the file (see CpnPage._take_file_name).
                self._set_title(document)
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
        in_folder = self.workspace is not None
        if item is not None and item.data(0, FOLDER_ROLE):
            path = item.data(0, FOLDER_ROLE)
            menu.addAction("New Folder…", lambda: self.new_folder(path))
            menu.addAction("Rename…", lambda: self.rename_path(path))
            menu.addAction(reveal_label(), lambda: self.reveal(path))
            menu.addSeparator()
            menu.addAction(f"Move to {BIN}", lambda: self.trash_paths([path]))
            menu.exec(self.tree.viewport().mapToGlobal(position))
            return
        if item is not None and item.data(0, FILE_ROLE):
            path = item.data(0, FILE_ROLE)
            if item.data(0, CLOUD_ROLE):
                menu.addAction("Download from iCloud", lambda: self._open_placeholder(item))
            else:
                menu.addAction("Open", lambda: self._open_placeholder(item))
                menu.addAction("Rename…", lambda: self.rename_path(path))
            menu.addAction(reveal_label(), lambda: self.reveal(path))
            menu.addSeparator()
            menu.addAction(f"Move to {BIN}", lambda: self.trash_paths([path]))
            menu.exec(self.tree.viewport().mapToGlobal(position))
            return
        if item is not None and item.data(0, Qt.UserRole) is None:
            # A section header: offer to clear that section.
            section = item
            ids = [section.child(i).data(0, Qt.UserRole) for i in range(section.childCount())]
            kind = {id(self.logs_section): "Logs", id(self.petri_section): "Petri Nets",
                    id(self.models_section): "Models", id(self.unsaved_section): "Unsaved",
                    id(self.elsewhere_section): "Other Files",
                    id(self.compare_section): "Comparisons"}.get(id(section), "Coloured Nets")
            ids = [i for i in ids if i is not None]          # not the "not open" rows
            if ids:
                menu.addAction(f"Close All {kind}", lambda: self.remove_documents(ids))
        else:
            if item is not None and not item.isSelected():
                self.tree.clearSelection()
                self.tree.setCurrentItem(item)
            ids = self.selected_ids() if item is not None else []
            if not ids:
                if in_folder:
                    menu.addAction("New Folder…", lambda: self.new_folder())
                    menu.addSeparator()
                menu.addAction("Open File…", self.action_open)
                menu.addAction("New Log from Notation…", self.action_notation)
            elif len(ids) == 1 and isinstance(self._document(ids[0]), ComparisonDocument):
                menu.addAction("Export Figures as CSV…", self.export_selected)
                menu.addSeparator()
                menu.addAction("Close", self.remove_selected)
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
                    if in_folder and not document.path:
                        menu.addAction("Keep in Folder", lambda d=document: self.keep_model(d))
                    label_text = "Export Model as PNML…"
                menu.addAction(label_text, self.export_selected)
                if document.path and not document.missing:
                    menu.addAction(reveal_label(), lambda p=document.path: self.reveal(p))
                menu.addSeparator()
                menu.addAction("Close", self.remove_selected)
                if document.path and not document.missing:
                    menu.addAction(f"Move to {BIN}", self.trash_selected)
            else:
                chosen = [self._document(i) for i in ids]
                if all(isinstance(d, LogDocument) for d in chosen):
                    menu.addAction(f"Compare {len(ids)} Logs", lambda: self.compare(chosen))
                    menu.addSeparator()
                menu.addAction(f"Close {len(ids)} Items", self.remove_selected)
                if all(d.path and not d.missing for d in chosen):
                    menu.addAction(f"Move {len(ids)} Items to {BIN}", self.trash_selected)
        menu.exec(self.tree.viewport().mapToGlobal(position))

    # -- session and recent files -----------------------------------------------------
    def _session_entries(self) -> list[dict]:
        entries = []
        for document in self.documents:
            if document.path:
                entry = {"path": document.path}
                entry.update(self.open_options.get(document.id, {}))
                entries.append(entry)
        # Files of a reopened workspace still loading in the background count as open.
        entries += list(self._restore_paths.values())
        return entries

    def _save_session(self) -> None:
        """Remember what is open: in the workspace folder, or in the app's settings."""
        if self._restoring:
            return
        if self.workspace is not None:
            # Written even in tests (persist=False): it lives in the folder, not in
            # your settings.
            self.workspace.save_state(self._session_entries(), self._selected_path())
            if self.persist:
                self.settings.setValue("workspace/current", str(self.workspace.folder))
        elif self.persist:
            self.settings.setValue("session/files", json.dumps(self._session_entries()))

    def _selected_path(self) -> str | None:
        ids = self.selected_ids()
        if len(ids) == 1:
            return self._document(ids[0]).path
        return None

    def restore_session(self) -> None:
        """Reopen the files that were open when the app was last closed."""
        if not self.settings.value("session/restore", True, type=bool):
            return
        folder = self.settings.value("workspace/current", "") or ""
        if folder and Path(folder).is_dir():
            self.open_workspace(folder)
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

    def _forget_recent(self, path: str) -> None:
        if self.persist and path:
            recent = [p for p in self._recent() if Path(p) != Path(path)]
            self.settings.setValue("recent", json.dumps(recent))

    def _recent(self) -> list[str]:
        if not self.persist:                      # tests: never your recent files
            return []
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
            self.recent_menu.addAction(Path(path).name, lambda p=path: self.open_files([p])) \
                .setToolTip(path)
        self.recent_menu.addSeparator()
        self.recent_menu.addAction("Clear Menu", lambda: self.settings.setValue("recent", "[]"))

    # ---------------------------------------------------------------- opening
    def action_open(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open", dialog_folder(),
            "Supported files (*.xes *.gz *.csv *.pnml *.cpn);;Event logs (*.xes *.gz *.csv);;"
            "Petri nets (*.pnml);;CPN Tools models (*.cpn);;All files (*)")
        self.open_files(paths)

    def action_open_cpn(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open coloured Petri net", dialog_folder(),
                                              "CPN Tools models (*.cpn)")
        if path:
            self.open_files([path])

    def action_notation(self) -> None:
        dialog = NotationDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.add_document(LogDocument(dialog.log()))

    def open_files(self, paths: list[str], folder: str | None = None) -> None:
        """Open files the user chose (Open…, Open Recent, a drop, the command line).

        With a folder open, files from elsewhere are first copied or moved
        into it (or ``folder``, a subfolder), or opened where they are, as the
        user says (once, or always for this folder): see :meth:`_bring_in`.
        """
        outside = [p for p in paths if self.workspace is not None and Path(p).is_file()
                   and not self.workspace.contains(p)]
        for path in paths:
            if path not in outside:
                self.open_path(path)
        if outside:
            for path in self._bring_in(outside, folder):
                self.open_path(path)

    def _import_choice(self, names: list[str], allow_open: bool) -> str | None:
        """Copy, move or open in place?  The folder's choice, the app's, or the user's."""
        remembered = self.workspace.settings().get("import")
        if remembered not in IMPORT_CHOICES:
            remembered = self._setting("files/import", "ask")
        if remembered in ("copy", "move"):
            return remembered
        if remembered == "open":
            return "open" if allow_open else "copy"
        dialog = ImportDialog(names, self.workspace.name, self, allow_open=allow_open)
        if dialog.exec() != QDialog.Accepted:
            return None
        choice = dialog.choice()
        if dialog.always.isChecked():
            self.workspace.update_settings(**{"import": choice})
        return choice

    def _bring_in(self, paths: list[str], folder: str | None = None) -> list[str]:
        """Copy or move files from elsewhere into the open folder; the paths to open.

        ``folder``: the subfolder they were dropped on (then "open where it
        is" is not on offer: the drop says where they go).  A file with the
        same name already there is never overwritten silently: the user
        keeps both (``"name 2.xes"``) or replaces it (the old one goes to the Bin).
        """
        target_folder = Path(folder) if folder else self.workspace.folder
        choice = self._import_choice([Path(p).name for p in paths],
                                     allow_open=folder is None
                                     or Path(folder).resolve() == self.workspace.folder)
        if choice is None:
            return []
        if choice == "open":
            return list(paths)
        result = []
        for source in map(Path, paths):
            target = target_folder / source.name
            if target.exists():
                if _same_file(source, target):
                    result.append(str(target))
                    continue
                answer = ask_about_clash(self, target)
                if answer is None:
                    continue
                if answer == "keep":
                    target = unique_path(target_folder, source.name)
                elif not move_to_trash(target):
                    QMessageBox.warning(self, "Could not replace", f"“{target.name}” could not "
                                        f"be moved to the {BIN}, so it was left as it is.")
                    continue
            try:
                if choice == "move":
                    shutil.move(str(source), str(target))
                    self._forget_recent(str(source))
                else:
                    shutil.copy2(source, target)          # keeps the file's dates
            except OSError as error:
                QMessageBox.warning(self, "Could not add the file",
                                    f"{source.name}\n\n{error.strerror or error}")
                continue
            result.append(str(target))
        if result:
            verb = "Moved" if choice == "move" else "Copied"
            where = target_folder.name
            self.statusBar().showMessage(
                f"{verb} {Path(result[0]).name if len(result) == 1 else f'{len(result)} files'} "
                f"into {where}", 8000)
        self._rescan_workspace()
        return result

    def open_path(self, path: str, csv_mapping: dict | None = None) -> None:
        lower = path.lower()
        name = Path(path).name
        if lower.endswith(".icloud") and Path(path).name.startswith("."):
            self._download_from_icloud(Path(path).with_name(name[1:-len(".icloud")]), Path(path))
            return
        size = _signature(path)
        try:
            if lower.endswith(".pnml"):
                self.add_document(CpnDocument(self._read_net(path), path=path))
                self.statusBar().showMessage(f"Opened {name} — edit it, play the token game, "
                                             "or see the Analysis tab for soundness and more",
                                             10000)
            elif lower.endswith(".cpn"):
                self.statusBar().showMessage(f"Reading {name}…")
                net = self._read_net(path)
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
                        self._opening.discard(self._key(path))
                        self._rebuild_sidebar()
                        return
                    mapping = dialog.mapping()
                log = read_csv(path, mapping)
                self.add_document(LogDocument(log, path=path),
                                  options={"csv_mapping": asdict(mapping)})
            elif lower.endswith((".xes", ".xes.gz", ".gz")):
                self.statusBar().showMessage(f"Reading {name}…")
                folder = self._folder_switches

                def loaded(log) -> None:
                    if folder != self._folder_switches:
                        # The folder was switched or closed while this was
                        # loading: it belongs to the folder that was left.
                        self._opening.discard(self._key(path))
                        return
                    self.add_document(LogDocument(log, path=path))
                    self.statusBar().showMessage(f"Opened {name}: {len(log):,} cases", 6000)

                run_in_background(lambda: read_xes(path), loaded,
                                  lambda message: self._could_not_open(path, message, size))
            else:
                QMessageBox.information(self, "Unsupported file",
                                        f"{name}: open .xes, .csv, .pnml or .cpn files.")
        except Exception as error:  # noqa: BLE001 - surface any import problem
            self._could_not_open(path, str(error), size)

    def _could_not_open(self, path: str, message: str, before: tuple | None) -> None:
        self._opening.discard(self._key(path))
        self._rebuild_sidebar()
        name = Path(path).name
        if before is not None and _signature(path) != before:
            # A big file still being copied in (from Finder, a download, iCloud):
            # what was read was only part of it.
            self.statusBar().showMessage(f"{name} is still being copied — open it again when "
                                         "it has finished", 10000)
            return
        QMessageBox.warning(self, "Could not open file", f"{name}\n\n{message}")

    @staticmethod
    def _read_net(path: str):
        """The net in a .pnml or .cpn file, as the editor edits it."""
        if path.lower().endswith(".pnml"):
            from ...model.plain import from_petri_net
            petri = read_pnml(path)
            petri.name = _file_stem(Path(path))
            return from_petri_net(petri)
        from ...io.cpn_reader import read_cpn
        return read_cpn(path)

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
        self._flush_autosaves()
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
        if self._installer is not None:         # an update is ready: swap the apps now
            from . import updates
            updates.run_detached(self._installer)

    # ---------------------------------------------------------------- updates
    def check_automatically(self) -> None:
        """At launch: look for a newer version, quietly unless there is one.

        Every time the app opens, so nobody misses a release; "Skip This
        Version" in the dialog keeps a version from being offered again.
        """
        if not self.persist or not self._setting("updates/automatic", True):
            return
        self.check_for_updates(manual=False)

    def check_for_updates(self, manual: bool = True) -> None:
        """Help ▸ Check for Updates…: compare with the latest release on GitHub.

        ``manual=False`` (the check at launch) says nothing unless there is a
        new version the user has not skipped, and nothing at all when offline.
        """
        from . import updates
        if self._checking_updates:
            return
        self._checking_updates = True
        if manual:
            self.statusBar().showMessage("Checking for updates…")

        def failed(message: str) -> None:
            self._checking_updates = False
            if manual:
                self.statusBar().clearMessage()
                QMessageBox.warning(self, "Software Update", "Could not check for updates "
                                    f"(are you online?).\n\n{message}")

        run_in_background(updates.fetch_latest,
                          lambda release: self._update_found(release, manual), failed)

    def _update_found(self, release, manual: bool) -> None:
        from ... import __version__
        from . import updates
        self._checking_updates = False
        if manual:
            self.statusBar().clearMessage()
        if release.prerelease or not updates.is_newer(release.version):
            if manual:
                QMessageBox.information(self, "Software Update", "You have the latest version "
                                        f"of CPNpy ({__version__}).")
            return
        if not manual and self._setting("updates/skipped", "") == release.version:
            return
        if manual:
            self._show_update_dialog(release)      # asked for: the dialog with the notes
        else:
            # At launch: a bar at the top that does not stop anyone working.
            self.update_bar.offer(release, self._can_install(release))

    def _can_install(self, release) -> bool:
        from . import updates
        return updates.installed_app() is not None and release.download_for() is not None

    def _show_update_dialog(self, release) -> None:
        """What's new in ``release`` (and the versions before it), and what to do."""
        from . import updates
        dialog = updates.UpdateDialog(release, self._can_install(release), self)
        dialog.exec()
        self._update_action(release, {dialog.SKIP: "skip", dialog.PAGE: "page",
                                      dialog.INSTALL: "install"}.get(dialog.outcome))

    def _update_action(self, release, action: str | None) -> None:
        if action is None:                          # Later
            return
        self.update_bar.hide()
        if action == "skip":
            self._set_setting("updates/skipped", release.version)
            self.statusBar().showMessage(f"CPNpy {release.version} skipped — you will be told "
                                         "about the next version", 6000)
        elif action == "page":
            QDesktopServices.openUrl(QUrl(release.page))
        elif not self._can_install(release):       # "How to Update" (run from source)
            self._show_update_dialog(release)
        else:
            self._install_update(release)

    def _install_update(self, release) -> None:
        """Download and unpack the update in the background, then restart into it."""
        from PySide6.QtWidgets import QProgressDialog
        from . import updates
        progress = QProgressDialog(f"Downloading CPNpy {release.version}…", "Cancel", 0, 100,
                                   self)
        progress.setWindowTitle("Software Update")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        # By default the dialog resets and hides itself at 100 %; with the
        # value set to 100 again every 0.1 s while the download is checked and
        # unpacked, it kept popping up and vanishing.  It stays up until done.
        progress.setAutoReset(False)
        progress.setAutoClose(False)
        self.update_progress = progress
        state = {"done": 0, "total": 0, "cancelled": False, "unpacking": False}
        progress.canceled.connect(lambda: state.__setitem__("cancelled", True))

        def tick() -> None:
            if state["unpacking"]:
                return
            if state["total"] and state["done"] >= state["total"]:
                # Downloaded: now checked and unpacked, which cannot be
                # stopped half-way -- a busy bar, no Cancel.
                state["unpacking"] = True
                progress.setLabelText(f"Preparing CPNpy {release.version}…")
                progress.setCancelButton(None)
                progress.setRange(0, 0)
            else:
                progress.setValue(int(100 * state["done"] / state["total"])
                                  if state["total"] else 0)
        poll = QTimer(self)
        poll.timeout.connect(tick)
        poll.start(100)
        progress.show()

        def finish() -> None:
            poll.stop()
            progress.close()

        def failed(message: str) -> None:
            finish()
            if not state["cancelled"]:
                QMessageBox.warning(self, "Software Update", "The update could not be "
                                    f"installed.\n\n{message}\n\nYou can download it from "
                                    f"{release.page}")

        def ready(command: list[str]) -> None:
            finish()
            box = QMessageBox(self)
            box.setWindowTitle("Software Update")
            box.setText(f"CPNpy {release.version} is ready.")
            box.setInformativeText("CPNpy quits and starts again to finish updating. Your "
                                   "open files come back.")
            restart = box.addButton("Restart Now", QMessageBox.AcceptRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() is restart:
                self._installer = command
                if self.close():
                    QApplication.quit()
                    return
                self._installer = None         # quitting was cancelled
            # Not installed: tidy up the unpacked copy.
            work = Path(command[-1]).parent
            if work.name.startswith(".cpnpy-update-"):
                shutil.rmtree(work, ignore_errors=True)

        run_in_background(lambda: updates.prepare(
            release, progress=lambda done, total: state.update(done=done, total=total),
            cancelled=lambda: state["cancelled"]), ready, failed)

    # ---------------------------------------------------------------- folders
    def action_open_workspace(self) -> None:
        start = str(self.workspace.folder.parent) if self.workspace else dialog_folder()
        folder = QFileDialog.getExistingDirectory(self, "Open folder",
                                                  start or str(Path.home()))
        if folder:
            self.open_workspace(folder)

    def open_workspace(self, folder: str) -> bool:
        """Work in ``folder``: list its logs and nets, reopen what was open there.

        Documents that are not in the folder are closed first (asking about
        unsaved changes), as when switching projects in other editors; files
        of the folder that are already open stay open.
        """
        workspace = Workspace(folder)
        if not workspace.exists():
            QMessageBox.warning(self, "Open folder", f"{folder}\n\nThis folder no longer "
                                "exists.")
            self._forget_workspace(folder)
            return False
        if self.workspace is not None and self.workspace.folder == workspace.folder:
            return True
        self._save_session()                    # the old folder, as it was
        outside = [d.id for d in self.documents
                   if not (d.path and workspace.contains(d.path))]
        self._restoring = True                  # closing is not a change to remember
        try:
            if outside and not self.remove_documents(outside):
                return False
        finally:
            self._restoring = False
        self._stop_watching()
        self._folder_switches += 1

        self.workspace = workspace
        settings = workspace.settings()
        self.view_mode = "kind" if settings.get("view") == "kind" else "folder"
        self._expanded = {e for e in settings.get("expanded", []) if isinstance(e, str)}
        self.view_switch.blockSignals(True)
        self.view_switch.set_index(0 if self.view_mode == "folder" else 1)
        self.view_switch.blockSignals(False)
        set_dialog_folder(str(workspace.folder))
        self._remember_workspace(str(workspace.folder))
        self._show_workspace_header()
        for document in self.documents:        # files of this folder that stayed open
            self._update_autosave(document)
        self._rescan_workspace(force=True)

        state = workspace.load_state()
        entries = [e for e in state["open"] if Path(e["path"]).exists()]
        self._restore_paths = {self._key(e["path"]): e for e in entries}
        selected = state["selected"]
        self._restore_selected = (self._key(selected) if selected and
                                  self._key(selected) in self._restore_paths else None)
        self._restoring = True
        try:
            for entry in entries:
                self.open_path(entry["path"], csv_mapping=entry.get("csv_mapping"))
        finally:
            self._restoring = False
        self._save_session()
        if not self.documents:
            self.content.setCurrentIndex(0)
        self._set_title(self._current_document())
        count = len(self.placeholders) + sum(1 for d in self.documents if d.path)
        self.statusBar().showMessage(
            f"Opened {workspace.name}: "
            f"{count} file{'s' if count != 1 else ''} to work with", 6000)
        return True

    def close_workspace(self) -> bool:
        """Close every document and go back to working with loose files."""
        if self.workspace is None:
            return True
        self._save_session()
        self._restoring = True
        try:
            if not self.remove_documents([d.id for d in self.documents]):
                return False
        finally:
            self._restoring = False
        self._stop_watching()
        self._folder_switches += 1
        name, self.workspace = self.workspace.name, None
        self._tree, self._tree_signature = None, ()
        set_dialog_folder(None)
        self.statusBar().showMessage(f"Closed {name}", 5000)
        if self.persist:
            self.settings.remove("workspace/current")
        self._show_workspace_header()
        self._rebuild_sidebar()
        self.content.setCurrentIndex(0)
        self._set_title(None)
        self._save_session()
        return True

    def set_view_mode(self, mode: str) -> None:
        """In a folder: show its subfolders ("folder") or group files by kind ("kind")."""
        if mode == self.view_mode:
            return
        self.view_mode = mode
        self.view_switch.blockSignals(True)
        self.view_switch.set_index(0 if mode == "folder" else 1)
        self.view_switch.blockSignals(False)
        if self.workspace is not None:
            self.workspace.update_settings(view=mode)
        self._rebuild_sidebar()

    def _rescan_workspace(self, force: bool = False) -> None:
        """Bring the sidebar in line with the folder's files (and watch its subfolders)."""
        if self.workspace is None:
            return
        if not self.workspace.exists():
            self.statusBar().showMessage(f"The folder {self.workspace.folder} is "
                                         "gone (moved or deleted?)", 10000)
            return
        self._tree = self.workspace.tree()
        signature = tuple((f.relative, tuple((x.relative, x.in_cloud) for x in f.files))
                          for f in self._tree.walk())
        missing_changed = self._check_missing()
        self._open_downloaded()
        if force or signature != self._tree_signature or missing_changed:
            self._tree_signature = signature
            self._rebuild_sidebar()
        # Watch the folder and its subfolders (new subfolders included).
        watched = set(self.watcher.directories())
        current = {str(d) for d in self.workspace.directories(self._tree)}
        if watched - current:
            self.watcher.removePaths(list(watched - current))
        if current - watched:
            self.watcher.addPaths(sorted(current - watched))
            if watched:
                # A file copied into a brand-new subfolder before it was watched
                # would be missed: look once more.
                self._rescan_timer.start()

    def _stop_watching(self) -> None:
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        self._tree, self._tree_signature = None, ()

    # -- the sidebar's rows ---------------------------------------------------------
    def _sections(self) -> list[QTreeWidgetItem]:
        return [self.unsaved_section, self.logs_section, self.petri_section,
                self.models_section, self.cpn_section, self.elsewhere_section,
                self.compare_section]

    def _row_id(self, item: QTreeWidgetItem | None):
        """What a row stands for, so the same row can be found after a rebuild."""
        if item is None:
            return None
        try:
            if item.data(0, Qt.UserRole) is not None:
                return ("document", item.data(0, Qt.UserRole))
            if item.data(0, FILE_ROLE):
                return ("file", self._key(item.data(0, FILE_ROLE)))
            if item.data(0, FOLDER_ROLE):
                return ("folder", self._key(item.data(0, FOLDER_ROLE)))
        except RuntimeError:
            return None
        return None

    def _row_path(self, item: QTreeWidgetItem) -> str | None:
        """The file or folder a row stands for (for dragging it, trashing it, …)."""
        if item.data(0, Qt.UserRole) is not None:
            document = self._document(item.data(0, Qt.UserRole))
            return document.path if document.path and not document.missing else None
        return item.data(0, FOLDER_ROLE) or (item.data(0, FILE_ROLE)
                                              if not item.data(0, CLOUD_ROLE) else None)

    def _listed_files(self) -> list:
        """The folder's files that are not open (iCloud-only ones included)."""
        if self._tree is None:
            return []
        open_paths = {self._key(d.path) for d in self.documents if d.path}
        return [f for folder in self._tree.walk() for f in folder.files
                if self._key(f.path) not in open_paths]

    def _rebuild_sidebar(self) -> None:
        """Lay out the sidebar from the open documents and the folder's files.

        Called after anything that changes them.  The current row, the
        selection, the expanded subfolders and the scroll position stay as
        they were, and the page shown does not change.
        """
        tree = self.tree
        current = self._row_id(tree.currentItem())
        selected = {self._row_id(item) for item in tree.selectedItems()}
        scroll_position = tree.verticalScrollBar().value()
        tree.blockSignals(True)
        tree._target = None
        try:
            while tree.topLevelItemCount():
                tree.takeTopLevelItem(0)
            for section in self._sections():
                section.takeChildren()
            self.items, self.placeholders, self.folder_items = {}, {}, {}
            folder_view = self.workspace is not None and self.view_mode == "folder"
            tree.setRootIsDecorated(folder_view)
            if folder_view:
                self._fill_folder_view()
            else:
                self._fill_kind_view()
            for section in self._sections():
                section.setExpanded(True)
                section.setHidden(section.childCount() == 0)
            self.more_row.setHidden(not (self._tree is not None and self._tree.truncated))
            empty = self.workspace is not None and not self.items and not self.placeholders \
                and not self.folder_items
            self.empty_hint.setHidden(not empty)
            for relative, item in self.folder_items.items():
                item.setExpanded(relative in self._expanded)
            # Put back the current row and the selection.
            rows = {self._row_id(item): item for item in self._all_rows()}
            if current in rows:
                item = rows[current]
                parent = item.parent()
                while parent is not None:
                    parent.setExpanded(True)
                    parent = parent.parent()
                tree.setCurrentItem(item)
            for key in selected:
                if key in rows:
                    rows[key].setSelected(True)
            tree.verticalScrollBar().setValue(scroll_position)
        finally:
            tree.blockSignals(False)
        self._watch_open_files()
        self._update_welcome()

    def _all_rows(self) -> list[QTreeWidgetItem]:
        rows = []
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value() is not None:
            rows.append(iterator.value())
            iterator += 1
        return rows

    def _document_row(self, document) -> QTreeWidgetItem:
        kind = ("compare" if isinstance(document, ComparisonDocument) else
                "log" if isinstance(document, LogDocument) else
                "cpn" if isinstance(document, CpnDocument)
                and not getattr(document.net, "plain", False) else "model")
        item = QTreeWidgetItem([""])
        item.setIcon(0, _icon(kind))
        item.setData(0, Qt.UserRole, document.id)
        self._style_document_row(item, document)
        self.items[document.id] = item
        return item

    def _file_row(self, file, text: str) -> QTreeWidgetItem:
        """A file of the folder that is not open: lighter, opens with a click."""
        kind = {"log": "log", "cpn": "cpn"}.get(file.kind, "model")
        key = self._key(file.path)
        if file.in_cloud:
            text += "  ☁"
        if key in self._opening or key in self._pending_downloads:
            text += "  …"
        item = QTreeWidgetItem([text])
        item.setIcon(0, _faded_icon(kind))
        item.setData(0, FILE_ROLE, str(file.path))
        item.setForeground(0, QColor(style.tokens().text_muted))
        if file.in_cloud:
            item.setData(0, CLOUD_ROLE, str(file.cloud_placeholder))
            item.setToolTip(0, f"{file.relative}\nIn iCloud — click to download and open it")
        else:
            item.setToolTip(0, f"{file.relative}\nNot open — click to open")
        self.placeholders[key] = item
        return item

    def _fill_kind_view(self) -> None:
        """Rows grouped by kind: logs, Petri nets, models, coloured nets, comparisons."""
        tree = self.tree
        for section in (self.logs_section, self.petri_section, self.models_section,
                        self.cpn_section, self.compare_section):
            tree.addTopLevelItem(section)
        for document in self.documents:
            if isinstance(document, LogDocument):
                section = self.logs_section
            elif isinstance(document, ComparisonDocument):
                section = self.compare_section
            elif isinstance(document, CpnDocument):
                section = self.petri_section if getattr(document.net, "plain", False) \
                    else self.cpn_section
            else:
                section = self.models_section
            section.addChild(self._document_row(document))
        files = self._listed_files()
        # Rows show the file's name; the subfolder ("logs/…") only when two
        # files would otherwise look the same.  The tooltip has the full path.
        short = [display_name(f.path.name) for f in files]
        clashes = {name for name in short if short.count(name) > 1}
        sections = {"log": self.logs_section, "petri": self.petri_section,
                    "cpn": self.cpn_section}
        for file, name in zip(files, short):
            sections[file.kind].addChild(self._file_row(file, file.name if name in clashes
                                                        else name))
        if self.workspace is not None:              # rows in a folder are alphabetical
            for section in self._sections():
                self._sort_rows(section)
        tree.addTopLevelItem(self.more_row)
        tree.addTopLevelItem(self.empty_hint)

    def _fill_folder_view(self) -> None:
        """Rows as in the folder: subfolders (expandable) and files, as in Finder."""
        tree = self.tree
        root = tree.invisibleRootItem()
        tree.addTopLevelItem(self.unsaved_section)
        tops: list[QTreeWidgetItem] = []
        if self._tree is not None:
            for folder in list(self._tree.walk())[1:]:
                item = QTreeWidgetItem([folder.name])
                item.setIcon(0, _icon("folder"))
                item.setData(0, FOLDER_ROLE, str(folder.path))
                item.setToolTip(0, folder.relative)
                parent = self.folder_items.get(folder.relative.rpartition("/")[0])
                (parent.addChild(item) if parent is not None else tops.append(item))
                self.folder_items[folder.relative] = item

        def parent_row(relative: str):
            folder = relative.rpartition("/")[0]
            while folder and folder not in self.folder_items:
                folder = folder.rpartition("/")[0]
            return self.folder_items.get(folder)

        for file in self._listed_files():
            item = self._file_row(file, display_name(file.path.name))
            parent = parent_row(file.relative)
            (parent.addChild(item) if parent is not None else tops.append(item))
        for document in self.documents:
            item = self._document_row(document)
            if isinstance(document, ComparisonDocument):
                self.compare_section.addChild(item)
            elif not document.path:
                self.unsaved_section.addChild(item)
            elif not self.workspace.contains(document.path):
                self.elsewhere_section.addChild(item)
            else:
                parent = parent_row(self.workspace.relative(document.path))
                (parent.addChild(item) if parent is not None else tops.append(item))
        for item in sorted(tops, key=self._sort_key):
            root.addChild(item)
        for item in self.folder_items.values():
            self._sort_rows(item)
        tree.addTopLevelItem(self.more_row)
        for section in (self.elsewhere_section, self.compare_section):
            self._sort_rows(section)
            tree.addTopLevelItem(section)
        tree.addTopLevelItem(self.empty_hint)

    @staticmethod
    def _sort_key(item: QTreeWidgetItem):
        """Folders first, then by name, ignoring case (as Finder sorts)."""
        return (0 if item.data(0, FOLDER_ROLE) else 1, item.text(0).casefold())

    def _sort_rows(self, parent: QTreeWidgetItem) -> None:
        children = parent.takeChildren()
        parent.addChildren(sorted(children, key=self._sort_key))

    def _folder_toggled(self, item: QTreeWidgetItem, expanded: bool) -> None:
        """A subfolder was expanded or collapsed: remember it in the folder."""
        path = item.data(0, FOLDER_ROLE)
        if not path or self.workspace is None:
            return
        relative = self.workspace.relative(path)
        changed = (relative not in self._expanded) if expanded else (relative in self._expanded)
        if changed:
            (self._expanded.add if expanded else self._expanded.discard)(relative)
            self.workspace.update_settings(expanded=sorted(self._expanded))

    def _open_placeholder(self, item) -> None:
        try:
            path = item.data(0, FILE_ROLE) if item is not None else None
        except RuntimeError:                         # a row rebuilt meanwhile
            return
        if not path:
            return
        now = time.monotonic()
        # One click and a double-click (which also "activates") must not open
        # the file twice: a log loading in the background is not open yet.
        if self._key(path) == getattr(self, "_last_click_key", None) and \
                now - self._clicked_open_at < 3:
            return
        self._last_click_key = self._key(path)
        self._clicked_open_at = now
        self._restore_paths.pop(self._key(path), None)    # the user chose: it gets selected
        if item.data(0, CLOUD_ROLE):
            self._download_from_icloud(Path(path), Path(item.data(0, CLOUD_ROLE)))
            return
        if path.lower().endswith((".xes", ".gz")):
            self._opening.add(self._key(path))
            item.setText(0, item.text(0) + "  …")
            item.setToolTip(0, "Opening…")
        self.open_path(path)

    def _on_double_click(self, item, _column) -> None:
        """Rename an open document, but not the one a click has just opened."""
        recently = time.monotonic() - self._clicked_open_at
        if recently < QApplication.doubleClickInterval() / 1000 * 2:
            return
        if item.data(0, Qt.UserRole) is not None:
            self.rename_document(self._document(item.data(0, Qt.UserRole)))

    def _current_document(self):
        ids = self.selected_ids()
        return self._document(ids[0]) if len(ids) == 1 else None

    @staticmethod
    def _key(path: str | Path) -> str:
        """One spelling per file, for comparing paths."""
        return os.path.normcase(str(Path(path).resolve()))

    def _update_welcome(self) -> None:
        """The welcome page's top card: "Work in a folder", or about the open one."""
        if not hasattr(self, "welcome_inside_card"):
            return
        inside = self.workspace is not None
        self.welcome_folder_card.setHidden(inside)
        self.welcome_inside_card.setHidden(not inside)
        if inside:
            files = len(self.placeholders) + sum(
                1 for d in self.documents if d.path and self.workspace.contains(d.path)
                and not d.missing)
            self.welcome_inside_title.setText(self.workspace.name)
            if files:
                what = f"{files} logs and nets" if files != 1 \
                    else "1 file"
                self.welcome_inside_text.setText(
                    f"{what} in this folder: click one in the sidebar to open it. "
                    "New nets and logs are saved into this folder, edits are saved as you "
                    "go, and what you have open is remembered for next time.")
            else:
                self.welcome_inside_text.setText(
                    "This folder has no event logs or nets yet. Start a new net (it is saved "
                    "here), or add .xes, .csv, .pnml or .cpn files to the folder: they appear "
                    "in the sidebar by themselves.")

    def _show_workspace_header(self) -> None:
        active = self.workspace is not None
        self.workspace_caption.setHidden(not active)
        self.workspace_button.setHidden(not active)
        self.view_row.setHidden(not active)
        self.sidebar_title.setText(self.workspace.name if active else APPLICATION_NAME)
        self.sidebar_title.setToolTip(str(self.workspace.folder) if active else "")
        self.close_workspace_action.setEnabled(active)

    def _set_title(self, document) -> None:
        """"order — Week 2" in a workspace, "order — CPNpy Studio" without one."""
        context = self.workspace.name if self.workspace else APPLICATION_NAME
        if document is None:
            self.setWindowTitle(context if self.workspace is None
                                else f"{context} — {APPLICATION_NAME}")
        else:
            self.setWindowTitle(f"{document.name} — {context}")

    # -- recent workspaces
    def _recent_workspaces(self) -> list[str]:
        if not self.persist:                      # tests: never your recent folders
            return []
        try:
            return [p for p in json.loads(self.settings.value("workspaces/recent", "[]"))
                    if isinstance(p, str)]
        except (TypeError, ValueError):
            return []

    def _remember_workspace(self, folder: str) -> None:
        if self.persist:
            recent = [p for p in self._recent_workspaces() if Path(p) != Path(folder)]
            self.settings.setValue("workspaces/recent", json.dumps([folder] + recent[:7]))
        self._refresh_welcome_recent()

    def _forget_workspace(self, folder: str) -> None:
        if self.persist:
            recent = [p for p in self._recent_workspaces() if Path(p) != Path(folder)]
            self.settings.setValue("workspaces/recent", json.dumps(recent))
        self._refresh_welcome_recent()

    def _fill_recent_workspaces_menu(self) -> None:
        menu = self.recent_workspaces_menu
        menu.clear()
        recent = [p for p in self._recent_workspaces() if Path(p).is_dir()]
        if not recent:
            menu.addAction("No Recent Folders").setEnabled(False)
            return
        for folder in recent:
            menu.addAction(Path(folder).name, lambda f=folder: self.open_workspace(f)) \
                .setToolTip(folder)
        menu.addSeparator()
        menu.addAction("Clear Menu", lambda: (self.settings.setValue("workspaces/recent", "[]"),
                                              self._refresh_welcome_recent()))

    def _refresh_welcome_recent(self) -> None:
        """Up to three recent workspaces as quick buttons on the welcome page."""
        holder = getattr(self, "welcome_recent", None)
        if holder is None:
            return
        layout = holder.layout()
        while layout.count():
            widget = layout.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        recent = [p for p in self._recent_workspaces() if Path(p).is_dir()][:3]
        if recent:
            layout.addWidget(label("Recent:", "muted"))
        for folder in recent:
            # clicked sends "checked" (False) first: it must not land in f.
            shortcut = button(Path(folder).name,
                              lambda _checked=False, f=folder: self.open_workspace(f))
            shortcut.setToolTip(f"Open the folder {folder}")
            layout.addWidget(shortcut)

    # ---------------------------------------------------------------- app → folder
    def _materialise(self, document, near: str | None = None) -> None:
        """In a folder, a new log or net becomes a file in it straight away.

        A net is named after its file, so "Untitled 1" is ``Untitled 1.pnml``
        (or ``Untitled 2`` when that name is taken).  It goes next to ``near``
        (the log a filtered log came from, the net a simulation ran on) when
        that is in the folder, else at the top of the folder.  A discovered
        model waits for Keep, so trying algorithms does not fill the folder.
        """
        if self.workspace is None or document.path or self._restoring:
            return
        page = self.pages[document.id]
        if isinstance(document, ModelDocument):
            page.keep_button.setVisible(True)
            return
        if not isinstance(document, (LogDocument, CpnDocument)):
            return
        folder = self.workspace.folder
        if near and self.workspace.contains(near) and Path(near).parent.is_dir():
            folder = Path(near).resolve().parent
        try:
            if isinstance(document, LogDocument):
                target = unique_path(folder, safe_file_name(document.name) + ".xes")
                page.write_to(str(target), quiet=True)
            else:
                plain = getattr(document.net, "plain", False)
                target = unique_path(folder, safe_file_name(document.name)
                                     + (".pnml" if plain else ".cpn"))
                if document.net.name != _file_stem(target):
                    document.net.name = _file_stem(target)     # named after its file
                    page.refresh_title()
                if not page._write(target, quiet=True):
                    self.statusBar().showMessage(
                        f"Could not save {document.name} into the folder "
                        f"({getattr(page, 'save_error', 'unknown error')}) — it stays "
                        "unsaved here", 10000)
                    return
        except Exception as error:  # noqa: BLE001 - the document stays, unsaved
            self.statusBar().showMessage(f"Could not save {document.name} into the folder: "
                                         f"{error}", 10000)
            return
        self._created.add(self._key(target))

    def keep_model(self, document) -> None:
        """Save a discovered model into the folder (the Keep button)."""
        if self.workspace is None or document.path:
            self.pages[document.id].export()
            return
        source = document.source_log.path if document.source_log else None
        folder = Path(source).resolve().parent if source and self.workspace.contains(source) \
            else self.workspace.folder
        target = unique_path(folder, safe_file_name(document.name) + ".pnml")
        try:
            self.pages[document.id].write_to(str(target), quiet=True)
        except Exception as error:  # noqa: BLE001
            QMessageBox.warning(self, "Could not keep the model", str(error))
            return
        self.statusBar().showMessage(f"Kept as {target.name}", 8000)
        self._rebuild_sidebar()

    # -- autosave
    def _autosaves(self, document) -> bool:
        """Edits to this document are saved by themselves.

        Only nets, only in the open folder, and a ``.cpn`` only if CPNpy wrote
        it: a model made in CPN Tools is saved (in CPNpy's writer) only when you
        press ⌘S, after which it is CPNpy's too.
        """
        return (self.autosave_enabled and self.workspace is not None
                and document.id not in self._autosave_failed
                and isinstance(document, CpnDocument) and bool(document.path)
                and self.workspace.contains(document.path) and not document.missing
                and (not document.path.lower().endswith(".cpn")
                     or document.id in self._cpnpy_files))

    def _update_autosave(self, document) -> None:
        if not isinstance(document, CpnDocument):
            return
        autosave = self._autosaves(document)
        if autosave != document.autosave:
            document.autosave = autosave
            page = self.pages.get(document.id)
            if page is not None:
                page.refresh_title()
            if document.id in self.items:
                self._refresh_item(document)
        if autosave and document.dirty:
            self._schedule_autosave(document)

    def _schedule_autosave(self, document) -> None:
        """An edit: save a moment after the last one."""
        if not document.autosave or document.id in self._conflicts:
            return
        timer = self._autosave_timers.get(document.id)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(AUTOSAVE_DELAY)
            timer.timeout.connect(lambda doc=document: self._autosave(doc))
            self._autosave_timers[document.id] = timer
        timer.start()

    def _autosave(self, document) -> None:
        page = self.pages.get(document.id)
        if page is None or not document.autosave or document.id in self._conflicts:
            return
        if not Path(document.path).exists():
            self._set_missing(document, True)      # do not quietly bring a deleted file back
            return
        if not page.autosave():
            # Say so once, and fall back to saving by hand (the dot comes back).
            self._autosave_failed.add(document.id)
            self._update_autosave(document)
            name = Path(document.path).name
            self.banners[document.id].show_notice(
                "unsaved", f"<b>{name} could not be saved</b> automatically: "
                f"{getattr(page, 'save_error', 'unknown error')}. Your edits are still "
                "here; save it somewhere else to keep them.",
                [("Save As…", page.export),
                 ("Try Again", lambda: page.save())])

    def _flush_autosaves(self, ids: list[int] | None = None) -> None:
        """Save now what autosave would save in a moment (switching, closing, quitting)."""
        for document in list(self.documents):
            if (ids is None or document.id in ids) and getattr(document, "autosave", False) \
                    and document.dirty:
                timer = self._autosave_timers.get(document.id)
                if timer is not None:
                    timer.stop()
                self._autosave(document)

    def set_autosave(self, on: bool) -> None:
        """File ▸ Autosave."""
        if on == self.autosave_enabled:
            return
        self.autosave_enabled = on
        self._set_setting("files/autosave", on)
        if self.autosave_action.isChecked() != on:
            self.autosave_action.setChecked(on)
        for document in self.documents:
            self._update_autosave(document)
        self.statusBar().showMessage("Edits to nets in the folder are saved as you go" if on
                                     else f"Autosave is off: save with {shortcut_text('Ctrl+S')}", 6000)

    # -- revert
    def _keep_original(self, document) -> None:
        """Remember a net's file as it was opened, for Revert to Saved."""
        try:
            if os.path.getsize(document.path) <= 50_000_000:
                self._originals[document.id] = Path(document.path).read_bytes()
        except OSError:
            pass

    def revert_selected(self) -> None:
        """File ▸ Revert to Saved: back to the file as it was when it was opened."""
        document = self._current_document()
        original = self._originals.get(document.id) if document is not None else None
        if document is None or original is None or not document.path:
            QMessageBox.information(self, "Revert to Saved", "Select a net opened from a file "
                                    "to go back to how it was when you opened it.")
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Revert to Saved")
        box.setText(f"Revert “{document.name}” to how it was when you opened it?")
        box.setInformativeText("The changes made since then are lost, and undo cannot bring "
                               "them back.")
        revert = box.addButton("Revert", QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        if box.clickedButton() is not revert:
            return
        from .workspace import atomic_write
        timer = self._autosave_timers.get(document.id)
        if timer is not None:
            timer.stop()
        try:
            atomic_write(document.path, lambda temporary: temporary.write_bytes(original))
        except OSError as error:
            QMessageBox.warning(self, "Revert to Saved", str(error))
            return
        self._own_writes[self._key(document.path)] = _signature(document.path)
        self._reload_document(document, f"Reverted {Path(document.path).name}")

    # ---------------------------------------------------------------- folder → app
    def _watch_open_files(self) -> None:
        """Watch the open documents' files, so a change made elsewhere is noticed."""
        wanted = {str(Path(d.path)) for d in self.documents
                  if d.path and not d.missing and os.path.exists(d.path)}
        current = set(self.watcher.files())
        if current - wanted:
            self.watcher.removePaths(sorted(current - wanted))
        if wanted - current:
            self.watcher.addPaths(sorted(wanted - current))

    def _file_changed(self, path: str) -> None:
        self._changed_files.add(path)
        self._file_timer.start()

    def _check_changed_files(self) -> None:
        """Open files changed (or vanished) on disk: reload, ask, or mark them missing.

        A change is acted on once the file has stopped changing (a big file
        being copied in is not read half-way), and the app's own saves are
        recognised and ignored.
        """
        pending, self._changed_files = self._changed_files, set()
        again: set[str] = set()
        for path in pending:
            key = self._key(path)
            documents = [d for d in self.documents if d.path and self._key(d.path) == key]
            if not documents:
                continue
            signature = _signature(path)
            if signature is None:
                # Gone, or being replaced by a safe save (write elsewhere, then
                # rename): look again a few times before calling it missing.
                tries = self._gone_checks.get(key, 0)
                if tries < 3:
                    self._gone_checks[key] = tries + 1
                    again.add(path)
                else:
                    self._gone_checks.pop(key, None)
                    if self.workspace is not None:
                        # Moved within the folder, perhaps: the rescan looks
                        # for it (_relocate) before calling it missing.
                        self._rescan_workspace(force=True)
                    else:
                        for document in documents:
                            self._set_missing(document, True)
                continue
            self._gone_checks.pop(key, None)
            if path not in self.watcher.files():
                self.watcher.addPath(path)          # a safe save replaced the watched file
            if self._own_writes.get(key) == signature:
                continue
            if self._unsettled.get(key) != signature:
                self._unsettled[key] = signature    # still being written? look again
                again.add(path)
                continue
            self._unsettled.pop(key, None)
            self._own_writes[key] = signature       # handled: not again for the same version
            for document in documents:
                if document.missing:
                    self._set_missing(document, False)
                self._changed_on_disk(document)
        if again:
            self._changed_files |= again
            self._file_timer.start()

    def _changed_on_disk(self, document) -> None:
        name = Path(document.path).name
        if not getattr(document, "dirty", False):
            self._reload_document(document, f"{name} changed on disk — reloaded")
            return
        # Edits here too: the user decides whose version wins.
        self._conflicts.add(document.id)
        timer = self._autosave_timers.get(document.id)
        if timer is not None:
            timer.stop()

        def reload() -> None:
            self._conflicts.discard(document.id)
            self._reload_document(document, f"Reloaded {name}")

        def keep_mine() -> None:
            self._conflicts.discard(document.id)
            self.banners[document.id].clear("changed")
            if document.autosave:
                self._autosave(document)            # ours replaces theirs now
            self.statusBar().showMessage(f"Kept your version of {name}", 6000)

        self.banners[document.id].show_notice(
            "changed", f"<b>{name} changed on disk</b> (in another app?), and it has edits "
            "here that are not saved.",
            [("Reload (lose my edits)", reload), ("Keep Mine", keep_mine)])

    def _reload_document(self, document, message: str) -> None:
        """Read the document's file again and show it afresh."""
        path = document.path
        key = self._key(path)

        def failed(error) -> None:
            tries = self._reload_attempts.get(key, 0)
            if tries < 5:                           # half-written still? try again soon
                self._reload_attempts[key] = tries + 1
                self._unsettled.pop(key, None)
                self._own_writes.pop(key, None)
                QTimer.singleShot(1000, lambda: self._file_changed(path))
                return
            self._reload_attempts.pop(key, None)
            banner = self.banners.get(document.id)
            if banner is not None:
                banner.show_notice("changed", f"<b>{Path(path).name} changed on disk</b> but "
                                   f"could not be read: {error}", [])

        def done(content) -> None:
            if document not in self.documents:
                return
            self._reload_attempts.pop(key, None)
            if isinstance(document, LogDocument):
                document.replace_log(content)
            else:
                document.net = content
                if isinstance(document, CpnDocument):
                    document.dirty = False
            self._remember_identity(document)       # another app's safe save: a new file
            self._replace_page(document)
            for other in self.documents:            # comparisons show the new log too
                if isinstance(other, ComparisonDocument) and document in other.logs:
                    self._replace_page(other)
            self.statusBar().showMessage(message, 8000)

        try:
            if isinstance(document, LogDocument):
                lower = path.lower()
                if lower.endswith(".csv"):
                    mapping = self.open_options.get(document.id, {}).get("csv_mapping")
                    done(read_csv(path, ColumnMapping(**mapping) if mapping
                                  else guess_mapping(sniff(path)[1])))
                else:
                    run_in_background(lambda: read_xes(path), done, failed)
            elif isinstance(document, CpnDocument):
                done(self._read_net(path))
            elif isinstance(document, ModelDocument):
                net = read_pnml(path)
                net.name = document.net.name
                done(net)
        except Exception as error:  # noqa: BLE001
            failed(error)

    def _replace_page(self, document) -> None:
        """Rebuild a document's page (after reloading it), keeping it in view."""
        shown = self.content.currentWidget() is self.holders.get(document.id)
        self._drop_page(document)
        self._make_page(document)
        self._update_autosave(document)
        if document.missing:
            self._show_missing(document)
        if shown:
            self._restore_tab(self.pages[document.id])
            self.content.setCurrentWidget(self.holders[document.id])
        self._refresh_item(document)
        self._refresh_log_choices()

    def _set_missing(self, document, missing: bool) -> None:
        """An open document's file was deleted or moved away (or came back)."""
        if document.missing == missing:
            return
        document.missing = missing
        self._update_autosave(document)
        if missing:
            self._show_missing(document)
            self.statusBar().showMessage(f"{Path(document.path).name} is no longer on disk — "
                                         "it is still open here", 10000)
        else:
            self.banners[document.id].clear("missing")
        if document.id in self.items:
            self._style_document_row(self.items[document.id], document)

    def _show_missing(self, document) -> None:
        name = Path(document.path).name
        self.banners[document.id].show_notice(
            "missing", f"<b>{name} is missing</b>: it was moved or deleted outside the app. "
            "It is still open here — save it to keep it.",
            [("Save As…", self.pages[document.id].export),
             ("Close", lambda: self.remove_documents([document.id]))])

    def _check_missing(self) -> bool:
        """Follow open files moved within the folder; mark the ones that are gone
        (or back) as missing.  True if anything changed."""
        changed = False
        for document in self.documents:
            if not document.path or isinstance(document, ComparisonDocument):
                continue
            there = os.path.exists(document.path)
            if there:
                self._remember_identity(document)
            elif self._relocate(document):
                changed = True
                continue
            if there == document.missing:
                self._set_missing(document, not there)
                if there:
                    self._file_changed(document.path)    # back, perhaps changed
                changed = True
        return changed

    @staticmethod
    def _identity(path) -> tuple | None:
        """What a move or rename keeps: the file's number on disk (device,
        inode), and its size and modification time.  The number alone is not
        enough: Linux hands a deleted file's number to the next new file, and
        that file must not be taken for the one that was open."""
        try:
            status = os.stat(path)
        except (OSError, TypeError):
            return None
        return status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns

    def _remember_identity(self, document) -> None:
        identity = self._identity(document.path)
        if identity is not None:
            self._identities[document.id] = identity

    def _relocate(self, document) -> bool:
        """An open file vanished from its place: was it moved within the folder?

        A file moved or renamed in Finder (or with ``mv``) keeps its identity
        on disk, so it is looked for among the folder's files; if found, the
        document follows it -- open, unsaved edits and all -- instead of being
        marked missing while the file also shows up, unopened, in its new place.
        """
        identity = self._identities.get(document.id)
        if identity is None or self.workspace is None or self._tree is None:
            return False
        taken = {self._key(d.path) for d in self.documents if d.path}
        kind = file_kind(Path(document.path))
        for file in self.workspace.files(self._tree):
            if self._key(file.path) in taken or file.kind != kind:
                continue
            if self._identity(file.path) != identity:
                continue
            old = document.path
            self._paths_moved(Path(old), file.path)
            if document.missing:
                self._set_missing(document, False)
            self.statusBar().showMessage(
                f"{Path(old).name} was moved to {self.workspace.relative(file.path)} — it "
                "is still open", 8000)
            return True
        return False

    # -- iCloud
    def _download_from_icloud(self, path: Path, placeholder: Path) -> None:
        """Ask iCloud Drive for a file that is only in the cloud; open it when it is here."""
        key = self._key(path)
        try:
            subprocess.run(["brctl", "download", str(placeholder)], check=True,
                           capture_output=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            self.statusBar().showMessage(f"{path.name} is in iCloud: open it in Finder to "
                                         "download it", 10000)
            self.reveal(str(placeholder.parent))
            return
        self._pending_downloads.add(key)
        self.statusBar().showMessage(f"Downloading {path.name} from iCloud…", 10000)
        self._rebuild_sidebar()

    def _open_downloaded(self) -> None:
        for key in list(self._pending_downloads):
            path = next((f.path for f in self.workspace.files(self._tree)
                         if self._key(f.path) == key), None) if self._tree else None
            if path is not None:
                self._pending_downloads.discard(key)
                QTimer.singleShot(0, lambda p=str(path): self.open_path(p))

    # ---------------------------------------------------------------- organising
    def _selected_paths(self) -> list[str]:
        paths = [self._row_path(item) for item in self.tree.selectedItems()]
        if not paths and self.tree.currentItem() is not None:
            paths = [self._row_path(self.tree.currentItem())]
        return [p for p in paths if p]

    def trash_selected(self) -> None:
        self.trash_paths(self._selected_paths())

    def trash_paths(self, paths: list[str]) -> None:
        """Move files or folders to the Bin (after asking); open documents in them close."""
        paths = [p for p in paths if os.path.exists(p)]
        if not paths:
            return
        what = f"“{Path(paths[0]).name}”" if len(paths) == 1 else f"{len(paths)} items"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(f"Move to {BIN}")
        box.setText(f"Move {what} to the {BIN}?")
        inside = [d for d in self.documents if d.path and any(
            self._key(d.path) == self._key(p) or self._key(d.path).startswith(
                self._key(p) + os.sep) for p in paths)]
        unsaved = [d for d in inside if getattr(d, "dirty", False)]
        box.setInformativeText(
            f"You can put it back from the {BIN}." if not unsaved else
            f"You can put it back from the {BIN}, but the edits to "
            + ", ".join(f"“{d.name}”" for d in unsaved) + " that are not saved are lost.")
        trash = box.addButton(f"Move to {BIN}", QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        box.exec()
        if box.clickedButton() is not trash:
            return
        for document in inside:
            timer = self._autosave_timers.get(document.id)
            if timer is not None:
                timer.stop()
            if isinstance(document, CpnDocument):
                document.dirty = False          # gone to the Bin: nothing to save
        self.remove_documents([d.id for d in inside], confirm=False)
        failed = []
        for path in paths:
            if move_to_trash(path):
                self._forget_recent(path)
                self._created.discard(self._key(path))
            else:
                failed.append(Path(path).name)
        if failed:
            QMessageBox.warning(self, f"Move to {BIN}", "Could not move to the "
                                f"{BIN}: " + ", ".join(failed))
        else:
            self.statusBar().showMessage(f"Moved {what} to the {BIN}", 6000)
        self._rescan_workspace()

    def new_folder(self, inside: str | None = None) -> None:
        """Make a subfolder (in ``inside``, else at the top of the open folder)."""
        if self.workspace is None:
            return
        parent = Path(inside) if inside else self.workspace.folder
        name, ok = QInputDialog.getText(self, "New Folder", "Name:", text="untitled folder")
        name = name.strip()
        if not ok or not name:
            return
        if FORBIDDEN_CHARACTERS & set(name) or name.startswith("."):
            QMessageBox.warning(self, "New Folder", "A folder name cannot start with a dot or "
                                "contain any of  / \\ : * ? \" < > |")
            return
        target = parent / name
        try:
            target.mkdir()
        except FileExistsError:
            QMessageBox.warning(self, "New Folder", f"There is already something called "
                                f"“{name}” in {parent.name}.")
            return
        except OSError as error:
            QMessageBox.warning(self, "New Folder", str(error.strerror or error))
            return
        if parent.resolve() != self.workspace.folder:
            self._expanded.add(self.workspace.relative(parent))
            self.workspace.update_settings(expanded=sorted(self._expanded))
        if self.view_mode != "folder":
            self.set_view_mode("folder")
        self._rescan_workspace()
        item = self.folder_items.get(self.workspace.relative(target))
        if item is not None:
            self.tree.blockSignals(True)
            self.tree.setCurrentItem(item)
            self.tree.blockSignals(False)
        self.statusBar().showMessage(f"Made the folder {name}", 5000)

    def move_paths(self, paths: list[str], folder: str | Path) -> None:
        """Move files or folders of the open folder into ``folder`` (dragging in the sidebar)."""
        target_folder = Path(folder)
        moved = []
        for source in map(Path, paths):
            if not source.exists() or source.resolve().parent == target_folder.resolve():
                continue
            if source.is_dir() and (source.resolve() == target_folder.resolve()
                                    or source.resolve() in target_folder.resolve().parents):
                QMessageBox.warning(self, "Move", f"“{source.name}” cannot go inside itself.")
                continue
            target = target_folder / source.name
            if target.exists():
                answer = ask_about_clash(self, target)
                if answer is None:
                    continue
                if answer == "keep":
                    target = unique_path(target_folder, source.name)
                else:
                    self.trash_paths_quietly([str(target)])
            self._flush_autosaves()
            try:
                shutil.move(str(source), str(target))
            except OSError as error:
                QMessageBox.warning(self, "Could not move",
                                    f"{source.name}\n\n{error.strerror or error}")
                continue
            self._paths_moved(source, target)
            moved.append(target)
        if moved:
            what = moved[0].name if len(moved) == 1 else f"{len(moved)} items"
            where = target_folder.name if target_folder.resolve() != self.workspace.folder \
                else self.workspace.name
            self.statusBar().showMessage(f"Moved {what} to {where}", 6000)
        self._rescan_workspace(force=True)

    def trash_paths_quietly(self, paths: list[str]) -> None:
        """Replace: the file being replaced goes to the Bin (its document closes)."""
        inside = [d.id for d in self.documents
                  if d.path and any(self._key(d.path) == self._key(p) for p in paths)]
        self.remove_documents(inside, confirm=False)
        for path in paths:
            move_to_trash(path)

    def _drop_folder(self, item) -> str | None:
        """Where a drop on this sidebar row goes, in the Folder view."""
        if self.workspace is None or self.view_mode != "folder":
            return None
        root = str(self.workspace.folder)
        if item is None:
            return root
        if item.data(0, FOLDER_ROLE):
            return item.data(0, FOLDER_ROLE)
        path = self._row_path(item)
        if path and self.workspace.contains(path):
            return str(Path(path).resolve().parent)
        return root

    def _sidebar_drop(self, paths: list[str], folder: str | None, internal: bool) -> None:
        """Files dropped on the sidebar: moved within the folder, or brought in."""
        if folder is None:                          # not the Folder view
            if not internal:
                self._open_dropped(paths)
            return
        inside = [p for p in paths if self.workspace.contains(p)]
        outside = [p for p in paths if p not in inside]
        if inside:
            self.move_paths(inside, folder)
        folders = [p for p in outside if Path(p).is_dir()]
        if folders:
            self.open_workspace(folders[0])         # a folder from elsewhere: work in it
            return
        for path in self._bring_in(outside, folder) if outside else []:
            self.open_path(path)

    # ---------------------------------------------------------------- settings
    def show_settings(self) -> None:
        dialog = SettingsDialog({
            "autosave": self.autosave_enabled,
            "import": self._setting("files/import", "ask"),
            "restore": self.restore_action.isChecked(),
            "check_updates": self._setting("updates/automatic", True),
        }, self)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        self.set_autosave(values["autosave"])
        self._set_setting("files/import", values["import"])
        self.restore_action.setChecked(values["restore"])
        self._set_setting("updates/automatic", values["check_updates"])

    # ---------------------------------------------------------------- drag & drop
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        self._open_dropped([url.toLocalFile() for url in event.mimeData().urls()
                            if url.isLocalFile()])

    def _open_dropped(self, paths: list[str]) -> None:
        folders = [p for p in paths if Path(p).is_dir()]
        if folders:
            self.open_workspace(folders[0])               # a folder: work in it
        self.open_files([p for p in paths if not Path(p).is_dir()])


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
    QTimer.singleShot(3000, window.check_automatically)
    for path in argv[1:]:
        if path == "--new-cpn":             # `cpn-ide` without a file
            window.action_new_cpn()
        elif not path.startswith("-"):
            window.open_files([path])
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
