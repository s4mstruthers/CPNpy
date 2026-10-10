"""The *+ Add box* popover: every box, a click away, without a panel of its own.

The Workflows page has no permanent box list.  *+ Add box* in its header
(and a double-click on the canvas, and *Add box here…* in its menu) opens
this popover: a search field, the six core groups (Input, Filter, Discover,
Check, Compare, Output) side by side, and one line for the rest (Science,
Predict, Coloured nets, Sweep, a folder's own boxes) with *Show all*.
Typing searches every box, core or not.  Enter adds the first match.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QFrame, QGraphicsDropShadowEffect, QGridLayout, QLineEdit, QPushButton, QVBoxLayout,
                               QWidget)

from ...flow.library import GROUP_ORDER, Library
from .. import theme
from ..studio import motion, style
from ..studio.widgets import hbox, label, vbox
from ..studio.workspace import display_name, file_kind

#: The groups shown before *Show all*: what most workflows are made of.
CORE_GROUPS = GROUP_ORDER[:6]
COLUMNS = 3
#: How many of the folder's files the Input group lists before "… more".
FILE_LIMIT = 6
#: The input box for each kind of file in the folder (see workspace.file_kind).
INPUT_BOXES = {"log": "open_log", "petri": "open_net", "cpn": "open_cpn",
               "ts": "open_transition_system", "typed": "typed_log"}


def input_box_for(library: Library, kind: str | None) -> str | None:
    """The id of the box that reads files of ``kind`` (None: no such box)."""
    function = INPUT_BOXES.get(kind)
    if function is None:
        return None
    for spec in library.specs.values():
        if spec.id.endswith("." + function) or spec.id == function:
            return spec.id
    return None


def folder_files(folder: str | Path | None, limit: int = 200) -> list[tuple[str, str]]:
    """(relative path, kind) of the folder's logs, nets and transition systems."""
    if folder is None or not Path(folder).is_dir():
        return []
    found = []
    for path in sorted(Path(folder).rglob("*")):
        if len(found) >= limit:
            break
        if not path.is_file() or path.name.startswith(".") or any(
                part.startswith(".") for part in path.relative_to(folder).parts[:-1]):
            continue
        kind = file_kind(path)
        if kind in INPUT_BOXES:
            found.append((path.relative_to(folder).as_posix(), kind))
    return found
#: Room around the card for its shadow, inside the see-through popup window.
SHADOW_MARGIN = 24


class BoxPicker(QWidget):
    """A popup listing the library's boxes by group; emits :attr:`chosen` with a box id.

    The window itself is see-through: what shows is :attr:`card`, a rounded
    panel with a soft shadow, so the popover has the corners of the app's
    menus rather than a square box with a hard edge."""

    chosen = Signal(str)
    #: One of the folder's files was picked: the input box's id and the file, relative to the folder.
    file_chosen = Signal(str, str)

    def __init__(self, library: Library, parent: QWidget | None = None,
                 folder: str | Path | None = None) -> None:
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.card = QFrame()
        self.card.setObjectName("boxPicker")
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(SHADOW_MARGIN + 8)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 110 if theme.is_dark() else 50))
        self.card.setGraphicsEffect(shadow)
        self.library = library
        self.folder = folder
        self.show_all = False
        self.file_buttons: list[QPushButton] = []
        self.search = QLineEdit()
        self.search.setObjectName("boxSearch")
        self.search.setPlaceholderText("Search boxes, e.g. alpha, filter, fitness")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _text: self.refill())
        self.search.returnPressed.connect(self._choose_first)
        self.groups_host = QWidget()
        self.grid = QGridLayout(self.groups_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(10)
        self.more_text = label("", "muted", wrap=True)
        self.more_button = QPushButton()
        self.more_button.clicked.connect(self._toggle_all)
        self.footer = hbox(self.more_text, None, self.more_button)
        self.card.setLayout(vbox(self.search, self.groups_host, self.footer, spacing=12, margins=(16, 16, 16, 16)))
        self.card.setMinimumWidth(560)
        self.setLayout(vbox(self.card, margins=(SHADOW_MARGIN,) * 4))
        self.buttons: list[QPushButton] = []
        self.refill()

    # -- showing ---------------------------------------------------------------------------
    def open_at(self, point: QPoint) -> None:
        """Show the popover with the card's top-left corner at ``point`` (global), kept on screen."""
        self.search.clear()
        self.show_all = False
        self.refill()
        self.adjustSize()
        screen = self.screen().availableGeometry() if self.screen() else None
        width, height = self.card_size()
        x, y = point.x(), point.y()
        if screen is not None:
            x = max(screen.left(), min(x, screen.right() - width))
            y = max(screen.top(), min(y, screen.bottom() - height))
        self.move(x - SHADOW_MARGIN, y - SHADOW_MARGIN)
        self.show()
        motion.fade_in(self)
        self.search.setFocus()

    def card_size(self) -> tuple[int, int]:
        """Width and height of the visible card (the window is larger by the shadow's room)."""
        hint = self.sizeHint()
        return hint.width() - 2 * SHADOW_MARGIN, hint.height() - 2 * SHADOW_MARGIN

    # -- filling -----------------------------------------------------------------------------
    def shown_groups(self) -> dict[str, list]:
        """Group → boxes to list now: the core groups, every group when
        *Show all* is on or a search is typed (a search looks everywhere)."""
        wanted = self.search.text().strip().lower()
        groups = {}
        for group, specs in self.library.by_group().items():
            if not wanted and not self.show_all and group not in CORE_GROUPS:
                continue
            shown = [s for s in specs if not wanted or _matches(s, group, wanted)]
            if shown:
                groups[group] = shown
        return groups

    def refill(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()               # gone now, not at the next event loop turn: no ghosts under the new rows
                widget.setParent(None)
                widget.deleteLater()
        self.buttons, self.file_buttons = [], []
        t = style.tokens()
        groups = self.shown_groups()
        for index, (group, specs) in enumerate(groups.items()):
            column = QWidget()
            column.setObjectName("plain")
            rows = QVBoxLayout(column)
            rows.setContentsMargins(0, 0, 0, 0)
            rows.setSpacing(2)
            rows.addWidget(label(group.upper(), "sectionLabel"))
            for spec in specs:
                choice = QPushButton(spec.name + ("  (Yours)" if spec.custom else ""))
                choice.setObjectName("boxChoice")
                choice.setCursor(Qt.PointingHandCursor)
                tip = (spec.help or "").strip().split("\n\n")[0].replace("\n", " ")
                if not spec.available:
                    tip += f"\n({spec.unavailable_reason})"
                    choice.setStyleSheet(f"color: {t.text_muted};")
                choice.setToolTip(tip)
                choice.clicked.connect(lambda _checked=False, box_id=spec.id: self._choose(box_id))
                rows.addWidget(choice)
                self.buttons.append(choice)
            if group == "Input":
                self._add_files(rows)
            rows.addStretch(1)
            self.grid.addWidget(column, index // COLUMNS, index % COLUMNS, Qt.AlignTop)
        files, _more = self.shown_files()
        if "Input" not in groups and files:
            # A search that matches files but no box: still a column for them.
            column = QWidget()
            column.setObjectName("plain")
            rows = QVBoxLayout(column)
            rows.setContentsMargins(0, 0, 0, 0)
            rows.setSpacing(2)
            rows.addWidget(label("INPUT", "sectionLabel"))
            self._add_files(rows)
            rows.addStretch(1)
            self.grid.addWidget(column, len(groups) // COLUMNS, len(groups) % COLUMNS, Qt.AlignTop)
        elif not groups:
            self.grid.addWidget(label("No box matches. Try another word, or clear the search.", "muted", wrap=True),
                                0, 0, 1, COLUMNS)
        for broken in self.library.broken if (self.show_all or self.search.text().strip()) else []:
            note = label(f"{Path(broken.file).name}: {broken.reason}", "muted", wrap=True)
            note.setStyleSheet(f"color: {style.STATUS['critical']};")
            note.setToolTip("This box file could not be loaded; fix it and it reloads when saved")
            self.grid.addWidget(note, self.grid.rowCount(), 0, 1, COLUMNS)
        self._refresh_footer()
        self.adjustSize()

    def shown_files(self) -> tuple[list[tuple[str, str]], int]:
        """The folder's files to list under Input (those with an input box),
        and how many more there are.  A search looks through all of them."""
        wanted = self.search.text().strip().lower()
        files = [(relative, kind) for relative, kind in folder_files(self.folder)
                 if input_box_for(self.library, kind) is not None
                 and all(word in relative.lower() for word in wanted.split())]
        limit = 12 if wanted else FILE_LIMIT
        return files[:limit], max(0, len(files) - limit)

    def _add_files(self, rows: QVBoxLayout) -> None:
        """Under the Input boxes: the folder's files, one click each."""
        files, more = self.shown_files()
        if not files:
            return
        from ..studio.app import _faded_icon            # the sidebar's file icons (no cycle: app is loaded)
        rows.addSpacing(6)
        rows.addWidget(label("IN THIS FOLDER", "sectionLabel"))
        names = [Path(relative).name for relative, _kind in files]
        icons = {"log": "log", "cpn": "cpn", "ts": "ts", "petri": "model"}
        for relative, kind in files:
            name = Path(relative).name
            text = display_name(name)
            if names.count(name) > 1 and "/" in relative:
                text += f"  ({Path(relative).parent})"
            choice = QPushButton(text)
            choice.setObjectName("boxChoice")
            choice.setIcon(_faded_icon(icons.get(kind, "model")))
            choice.setCursor(Qt.PointingHandCursor)
            choice.setToolTip(f"{relative}\nAdds an input box that reads this file")
            choice.clicked.connect(lambda _checked=False, r=relative, k=kind: self._choose_file(k, r))
            rows.addWidget(choice)
            self.file_buttons.append(choice)
        if more:
            rows.addWidget(label(f"… {more} more (Choose… in Settings)", "muted"))

    def _choose_file(self, kind: str, relative: str) -> None:
        box_id = input_box_for(self.library, kind)
        if box_id is None:
            return
        self.close()
        self.file_chosen.emit(box_id, relative)

    def _refresh_footer(self) -> None:
        searching = bool(self.search.text().strip())
        rest = [g for g in self.library.by_group() if g not in CORE_GROUPS]
        total = len(self.library)
        self.footer_visible = bool(rest) and not searching
        self.more_text.setVisible(self.footer_visible)
        self.more_button.setVisible(self.footer_visible)
        if not self.footer_visible:
            return
        if self.show_all:
            self.more_text.setText(f"All {total} boxes.")
            self.more_button.setText("Core groups only ◂")
        else:
            names = ", ".join(_plain(g) for g in rest)
            self.more_text.setText(f"More: {names}.")
            self.more_button.setText(f"Show all {total} ▸")

    def _toggle_all(self) -> None:
        self.show_all = not self.show_all
        self.refill()

    # -- choosing ---------------------------------------------------------------------------
    def _choose(self, box_id: str) -> None:
        self.close()
        self.chosen.emit(box_id)

    def _choose_first(self) -> None:
        if self.buttons:
            self.buttons[0].click()


def _matches(spec, group: str, wanted: str) -> bool:
    """Every word typed is in the box's name, its group, or its function's
    name ("alpha" finds the α-algorithm, whose function is alpha_miner)."""
    haystack = " ".join([spec.name, group, spec.function.__name__.replace("_", " "), spec.id]).lower()
    return all(word in haystack for word in wanted.split())


def _plain(group: str) -> str:
    return "your own boxes" if group == "Yours" else group


__all__ = ["BoxPicker", "CORE_GROUPS", "folder_files", "input_box_for"]
