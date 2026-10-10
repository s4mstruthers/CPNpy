"""What the side panel shows for a box: its result, how it got there, its
code, and its settings.

:func:`result_widget` picks a viewer by the result's type: the net drawing
(with *Edit a copy*), a log's figures and variants (with *Open as log*),
a transition system, a process tree, a process map, a footprint, a replay
or alignment table, scores as meters, a table, a figure, a report.
:func:`how_widget` lays out a box's :class:`~openprocess.flow.explain.Explanation`
in order: notes as lines, derivation steps as a two-column table, shown
values each in their own viewer.  :func:`code_widget` shows the source with
a small Python highlighter.  :class:`SettingsWidget` makes one control per
setting from the box's spec and reports changes.

Every tab can be opened in its own window (:func:`pop_out`), for a figure
for a paper, a replay table with a hundred rows, or an algorithm of five
hundred lines.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from PySide6.QtCore import QRegularExpression, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLayout, QLineEdit, QPlainTextEdit, QProgressBar, QSizePolicy, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ...flow.box import BoxSpec, Called, Setting, algorithm_calls, clean_path
from ...flow.explain import Explanation
from ...flow.runner import Result
from ...flow.sweep import Sweep, is_sweep
from ...flow.types import (AlignmentResult, CPNet, DFG, Dataset, EventLog, Figure, Footprint, PetriNet,
                           Predictions, Predictor, ProcessTree, Regions, ReplayResult, Scores, SimpleLog,
                           Table, Text, TransitionSystem)
from .. import theme
from ..studio import style
from ..studio.graph_builders import dfg_specs, petri_net_specs
from ..studio.graph_view import GraphView
from ..studio.widgets import Card, StatTile, button, footprint_table, hbox, label, scroll, vbox


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _table(columns: list[str], rows: list[list], max_rows: int = 500) -> QTableWidget:
    table = QTableWidget(min(len(rows), max_rows), len(columns))
    table.setHorizontalHeaderLabels([str(c) for c in columns])
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    for r, row in enumerate(rows[:max_rows]):
        for c, value in enumerate(row):
            text = f"{value:.4f}" if isinstance(value, float) else "" if value is None else str(value)
            item = QTableWidgetItem(text)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(r, c, item)
    table.resizeColumnsToContents()
    table.horizontalHeader().setStretchLastSection(True)
    height = table.horizontalHeader().height() + sum(table.rowHeight(i) for i in range(table.rowCount())) + 6
    table.setMinimumHeight(min(max(height, 60), 420))
    table.setMaximumHeight(min(max(height, 60), 420))
    return table


def _graph(nodes, edges, positions=None, layer_gap: float = 48.0, height: int = 260) -> GraphView:
    view = GraphView()
    view.setMinimumHeight(height)
    view.graph.populate(nodes, edges, positions, layer_gap=layer_gap)
    QTimer.singleShot(0, view.fit)
    return view


class _OpenCard(QFrame):
    """A card that is one big link: *Open as log ›* with a line on what the page has."""

    def __init__(self, title: str, caption: str, slot) -> None:
        super().__init__()
        self.setObjectName("openCard")
        self.setCursor(Qt.PointingHandCursor)
        self.slot = slot
        self.setToolTip(caption)
        heading = label(title, "openCardTitle")
        text = label(caption, wrap=True)
        self.setLayout(vbox(heading, text, spacing=2, margins=(14, 10, 14, 10)))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.slot()
            event.accept()
            return
        super().mousePressEvent(event)


def _open_card(title: str, caption: str, slot) -> QWidget:
    return _OpenCard(title, caption, slot)


def _meter(name: str, value) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    caption = label(name[:1].upper() + name[1:])
    caption.setMinimumWidth(110)
    layout.addWidget(caption)
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= float(value) <= 1:
        bar = QProgressBar()
        bar.setRange(0, 1000)
        bar.setValue(int(float(value) * 1000))
        bar.setTextVisible(False)
        bar.setFixedHeight(8)
        layout.addWidget(bar, 1)
        number = label(f"{float(value):.3f}")
        number.setStyleSheet("font-weight: 600;")
        number.setMinimumWidth(44)
        number.setAlignment(Qt.AlignRight)
        layout.addWidget(number)
    else:
        text = label(str(value))
        good = str(value).lower().startswith(("sound", "yes", "true"))
        bad = str(value).lower().startswith(("not", "no", "false"))
        if good or bad:
            text.setStyleSheet(f"font-weight: 600; color: {style.STATUS['good' if good else 'critical']};")
        layout.addWidget(text, 1)
    return row


# ---------------------------------------------------------------------------
# Result viewers
# ---------------------------------------------------------------------------
def result_widget(value, page=None) -> QWidget:
    """A viewer for ``value``.  ``page`` (the workflow page) receives the
    *Open as …* requests; None gives a read-only viewer."""
    host = QWidget()
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    def add(widget) -> None:
        if isinstance(widget, QLayout):
            layout.addLayout(widget)
        else:
            layout.addWidget(widget)

    from ...mining.discovery.alpha import AlphaResult
    from ...mining.discovery.heuristics import HeuristicsResult
    from ...mining.discovery.inductive import InductiveResult
    from ...mining.discovery.state_regions import RegionResult
    if isinstance(value, (AlphaResult, InductiveResult, HeuristicsResult)):
        from ..studio.derivation_view import derivation_view
        add(derivation_view(value))              # the typeset derivation the Discover tab shows
    elif isinstance(value, RegionResult):
        from ..studio.regions_view import RegionsPanel
        add(RegionsPanel(value, show_net=False, flat=True))
    elif isinstance(value, PetriNet):
        nodes, edges = petri_net_specs(value, show_place_names=len(value.places) <= 40)
        positions = None
        if all(p.position for p in value.places.values()) and all(t.position for t in value.transitions.values()):
            positions = {p.id: p.position for p in value.places.values()}
            positions |= {t.id: t.position for t in value.transitions.values()}
        add(_graph(nodes, edges, positions))
        add(label(value.summary() + (f" · {value.info['algorithm']}" if value.info.get("algorithm") else ""),
                  "muted", wrap=True))
        if page is not None:
            add(hbox(button("Open as model", lambda: page.open_as_model(value),
                            tooltip="Open it as a model page: token game, analysis, conformance"),
                     button("✎ Edit a copy", lambda: page.edit_copy(value),
                            tooltip="Open a copy on the net canvas, to play and change it"), None))
    elif isinstance(value, EventLog):
        from ...mining.stats import format_duration, summarise
        summary = summarise(value)
        tiles = hbox(StatTile("Cases", f"{summary.case_count:,}"), StatTile("Events", f"{summary.event_count:,}"),
                     StatTile("Variants", f"{summary.variant_count:,}"),
                     StatTile("Activities", f"{len(summary.activities):,}"), spacing=8)
        add_layout = QWidget()
        add_layout.setLayout(tiles)
        add(add_layout)
        if page is not None:
            # The log page has the views a workflow box does not draw: the
            # dotted chart, the process map, the footprint, variants and cases.
            add(_open_card("Open as log  ›", "Dotted chart, process map, footprint, variants and cases, "
                           "on the log page.", lambda: page.open_as_log(value)))
        rows = [["⟨" + ", ".join(v.sequence) + "⟩", v.count] for v in summary.variants[:200]]
        add(_table(["variant", "cases"], rows))
        if summary.start:
            add(label(f"From {summary.start:%Y-%m-%d} to {summary.end:%Y-%m-%d}; median case duration "
                      f"{format_duration(summary.median_case_duration)}", "muted", wrap=True))
    elif isinstance(value, SimpleLog):
        from ...mining.log import format_simple_log
        text = QPlainTextEdit(format_simple_log(value))
        text.setReadOnly(True)
        text.setMaximumHeight(120)
        add(text)
    elif isinstance(value, TransitionSystem):
        from ..studio.regions_view import TransitionSystemView
        view = TransitionSystemView(value)
        add(view)
        add(label(f"{len(value.states)} states, {len(value.transitions)} transitions"
                  + (f" ({value.abstraction})" if value.abstraction else ""), "muted", wrap=True))
    elif isinstance(value, ProcessTree):
        from ..studio.derivation_view import TreeView, tree_formula, tree_specs
        nodes, edges, positions = tree_specs(value)
        view = TreeView()
        view.graph.populate(nodes, edges, positions, layer_gap=60)
        QTimer.singleShot(0, view.fit_height)
        add(view)
        formula = label(tree_formula(value), wrap=True)
        formula.setTextFormat(Qt.RichText)
        add(formula)
    elif isinstance(value, DFG):
        nodes, edges = dfg_specs(value)
        add(_graph(nodes, edges, layer_gap=90))
        add(label(f"{len(value.activities)} activities, {len(value.edges)} arcs, {value.trace_count} cases",
                  "muted"))
    elif isinstance(value, Footprint):
        add(footprint_table(value, compact=len(value.activities) > 8))
    elif isinstance(value, ReplayResult):
        rows = [["⟨" + ", ".join(t.trace) + "⟩", t.count, t.produced, t.consumed, t.missing, t.remaining,
                 round(t.fitness, 4)] for t in value.traces]
        add(_table(["variant", "cases", "p", "c", "m", "r", "fitness"], rows))
        add(label(f"Fitness {value.fitness:.4f}: p = {value.produced}, c = {value.consumed}, "
                  f"m = {value.missing}, r = {value.remaining}; {value.fitting_traces} of "
                  f"{value.trace_count} cases fit.", "muted", wrap=True))
    elif isinstance(value, AlignmentResult):
        rows = [["⟨" + ", ".join(a.trace) + "⟩", a.count, a.cost, round(a.fitness, 4),
                 " ".join(f"({m.log}|{m.model})" for m in a.moves)] for a in value.alignments]
        add(_table(["variant", "cases", "cost", "fitness", "alignment"], rows))
        add(label(f"Average fitness {value.average_fitness:.4f}; {value.fitting_traces} of "
                  f"{value.trace_count} cases align without a deviation.", "muted", wrap=True))
    elif isinstance(value, Regions):
        rows = [[value.name_of(r), value.region_text(r), "minimal" if r in value.minimal else ""]
                for r in value.regions[:200]]
        add(_table(["region", "states", ""], rows))
        add(label(f"{len(value.regions)} regions, {len(value.minimal)} minimal; "
                  f"elementary: {value.elementary}", "muted", wrap=True))
    elif isinstance(value, Scores):
        box = QWidget()
        meters = QVBoxLayout(box)
        meters.setContentsMargins(0, 0, 0, 0)
        meters.setSpacing(6)
        for name, metric in value.metrics.items():
            meters.addWidget(_meter(name, metric))
        add(label(value.model, "cardTitle"))
        add(box)
        if value.context:
            add(label("Settings: " + ", ".join(f"{k} = {v}" for k, v in value.context.items()), "muted", wrap=True))
        if value.note:
            add(label(value.note, "muted", wrap=True))
    elif isinstance(value, Table):
        add(label(value.name, "cardTitle"))
        add(_table(value.columns, value.rows))
        if value.samples:
            add(label(f"{len(value.samples)} samples behind these rows (for Compare samples and Plot).", "muted",
                      wrap=True))
        if value.note:
            add(label(value.note, "muted", wrap=True))
    elif isinstance(value, Figure):
        shown = False
        if value.svg:
            try:
                from PySide6.QtSvgWidgets import QSvgWidget
                svg = QSvgWidget()
                svg.load(value.svg.encode("utf-8"))
                svg.setMinimumHeight(260)
                svg.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                size = svg.renderer().defaultSize()
                if size.width() > 0:
                    svg.setMaximumHeight(int(min(600, max(260, size.height() * 1.4))))
                add(svg)
                shown = True
            except ImportError:
                pass
        if not shown and value.png:
            from PySide6.QtGui import QPixmap
            pixmap = QPixmap()
            pixmap.loadFromData(value.png)
            picture = QLabel()
            picture.setPixmap(pixmap.scaledToWidth(560, Qt.SmoothTransformation))
            add(picture)
            shown = True
        if not shown:
            add(label("The figure has no SVG or PNG form.", "muted"))
        if value.caption:
            add(label(value.caption, "muted", wrap=True))
        if page is not None:
            add(hbox(button("Save as SVG…", lambda: page.save_figure(value)), None))
    elif isinstance(value, Text):
        text = QPlainTextEdit(value.text)
        text.setReadOnly(True)
        text.setFont(theme.mono_font(11))
        text.setMinimumHeight(200)
        add(text)
    elif isinstance(value, Dataset):
        add(label(f"{len(value)} rows × {len(value.feature_names)} features · label: {value.label} "
                  f"({value.kind})", "muted", wrap=True))
        rows = [[*(list(row) if not hasattr(row, "tolist") else row.tolist()), y]
                for row, y in zip(value.X[:50], value.y[:50])]
        add(_table([*value.feature_names, value.label], rows))
    elif isinstance(value, Predictions):
        rows = [[str(v), str(t), "✓" if v == t else ""] for v, t in zip(value.values[:100], value.dataset.y[:100])]
        add(_table(["predicted", "actual", ""], rows))
        add(label(f"{len(value.values)} predictions by {value.name}", "muted"))
    elif isinstance(value, Predictor):
        add(label(f"{getattr(value, 'name', type(value).__name__)}: a fitted model. Connect it to Predict.",
                  "muted", wrap=True))
    elif isinstance(value, CPNet):
        add(label(f"{value.name}: {sum(1 for _ in value.all_places())} places, "
                  f"{sum(1 for _ in value.all_transitions())} transitions, {len(value.pages)} page(s)",
                  "muted", wrap=True))
        if page is not None:
            add(hbox(button("Open as coloured net", lambda: page.open_as_cpn(value)), None))
    elif value is None:
        add(label("This box gives nothing back (it saves, or shows).", "muted", wrap=True))
    else:
        text = QPlainTextEdit(repr(value)[:5000])
        text.setReadOnly(True)
        text.setMaximumHeight(160)
        add(label(type(value).__name__, "muted"))
        add(text)
    return host


# ---------------------------------------------------------------------------
# How
# ---------------------------------------------------------------------------
def how_widget(explanation: Explanation, page=None) -> QWidget:
    host = QWidget()
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    if explanation.empty:
        layout.addWidget(label("This box has nothing to add: its result is all there is.", "muted", wrap=True))
        return host
    t = style.tokens()
    for entry in explanation.entries:
        if entry[0] == "note":
            text = label("· " + entry[1], "muted" if not entry[1].startswith("Warning") else None, wrap=True,
                         selectable=True)
            if entry[1].startswith("Warning"):
                text.setStyleSheet(f"color: {style.STATUS['warning']};")
            layout.addWidget(text)
        elif entry[0] == "steps":
            rows = []
            for title, content in entry[1]:
                rows.append(f"<tr><td valign='top' style='padding: 4px 10px 4px 0; color: {t.text_muted}; "
                            f"white-space: nowrap'><b>{escape(title)}</b></td>"
                            f"<td style='padding: 4px 0; font-family: {theme.mono_font(11).family()}; "
                            f"font-size: 11.5px'>{escape(content)}</td></tr>")
            table = QLabel(f"<table cellspacing='0' width='100%'>{''.join(rows)}</table>")
            table.setTextFormat(Qt.RichText)
            table.setWordWrap(True)
            table.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(table)
        elif entry[0] == "show":
            caption, value = entry[1], entry[2]
            if caption:
                layout.addWidget(label(caption.upper(), "sectionLabel"))
            layout.addWidget(result_widget(value, page))
    return host


# ---------------------------------------------------------------------------
# Code
# ---------------------------------------------------------------------------
class PythonHighlighter(QSyntaxHighlighter):
    KEYWORDS = ("def", "return", "if", "elif", "else", "for", "in", "while", "import", "from", "as", "class",
                "raise", "try", "except", "finally", "with", "lambda", "not", "and", "or", "is", "None", "True",
                "False", "yield", "pass", "global", "del", "assert")

    def __init__(self, document) -> None:
        super().__init__(document)
        t = style.tokens()
        self.rules = []
        keyword = QTextCharFormat()
        keyword.setForeground(QColor(t.accent))
        keyword.setFontWeight(QFont.DemiBold)
        self.rules.append((QRegularExpression(r"\b(" + "|".join(self.KEYWORDS) + r")\b"), keyword))
        decorator = QTextCharFormat()
        decorator.setForeground(QColor(style.categorical(1)))
        self.rules.append((QRegularExpression(r"^\s*@\w+(\([^)]*\))?"), decorator))
        string = QTextCharFormat()
        string.setForeground(QColor(style.STATUS["good"]))
        self.rules.append((QRegularExpression(r"(f|r|b)?\"[^\"\n]*\"|(f|r|b)?'[^'\n]*'"), string))
        comment = QTextCharFormat()
        comment.setForeground(QColor(t.text_muted))
        comment.setFontItalic(True)
        self.rules.append((QRegularExpression(r"#[^\n]*"), comment))
        self.docstring = QTextCharFormat()
        self.docstring.setForeground(QColor(style.categorical(3)))
        self.triple = QRegularExpression('"""')

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        for pattern, fmt in self.rules:
            match = pattern.globalMatch(text)
            while match.hasNext():
                found = match.next()
                self.setFormat(found.capturedStart(), found.capturedLength(), fmt)
        # Docstrings span lines: state 1 = inside one.
        self.setCurrentBlockState(0)
        start = 0 if self.previousBlockState() == 1 else text.find('"""')
        while start >= 0:
            end = text.find('"""', start + (3 if self.previousBlockState() != 1 or start else 0))
            if end < 0:
                self.setCurrentBlockState(1)
                self.setFormat(start, len(text) - start, self.docstring)
                break
            self.setFormat(start, end + 3 - start, self.docstring)
            start = text.find('"""', end + 3)


def _code_view(source: str, compact: bool, placeholder: str = "(the source is not available)") -> QPlainTextEdit:
    """Read-only, highlighted Python; in the panel sized to the code (120–420 px)."""
    editor = QPlainTextEdit(source or placeholder)
    editor.setReadOnly(True)
    editor.setFont(theme.mono_font(11))
    editor.setLineWrapMode(QPlainTextEdit.NoWrap)
    PythonHighlighter(editor.document())
    lines = (source or "").count("\n") + 1
    if compact:
        editor.setMinimumHeight(min(max(lines * 18 + 20, 120), 420))
        editor.setMaximumHeight(min(max(lines * 18 + 20, 120), 420))
    return editor


def _open_in_editor(file: str) -> None:
    QDesktopServices.openUrl(__import__("PySide6.QtCore", fromlist=["QUrl"]).QUrl.fromLocalFile(file))


def show_file(called: Called, parent=None) -> QDialog:
    """The whole file an algorithm lives in, in a window of its own, scrolled to
    the function: the module's docstring at its top says what the algorithm
    does and where it comes from."""
    from PySide6.QtGui import QTextCursor

    def make() -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        try:
            text = Path(called.file).read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            text = f"(could not read {called.file}: {error})"
        layout.addWidget(label(f"{called.where}  ·  the whole file; <b>{escape(called.name)}</b> starts at "
                               f"line {called.line}", "muted", wrap=True, selectable=True))
        editor = _code_view(text, compact=False)
        editor.setMinimumHeight(560)
        layout.addWidget(editor, 1)
        if Path(called.file).is_file():
            layout.addLayout(hbox(button("Open in your editor", lambda: _open_in_editor(called.file)), None))

        def scroll_to_function() -> None:
            block = editor.document().findBlockByNumber(max(called.line - 1, 0))
            cursor = QTextCursor(block)
            editor.setTextCursor(cursor)
            editor.centerCursor()
        QTimer.singleShot(0, scroll_to_function)
        return host
    return pop_out(f"{Path(called.file).name} · {called.name}", make, parent)


def _follows(called: Called) -> QLabel | None:
    """The published work(s) the algorithm follows, from the app's References
    (*Help ▸ References*), so the code can be checked against its source."""
    import re
    from ...references import reference, topics_for_module
    lines = []
    for topic in topics_for_module(called.module):
        works = []
        for key in topic.sources:
            work = reference(key)
            if work is None:
                continue
            citation = re.sub(r"\*(.+?)\*", r"<i>\1</i>", escape(work.citation))
            works.append(f"<a href=\"{work.url}\">{citation}</a>" if work.url else citation)
        if works:
            lines.append(f"<b>Follows</b> ({escape(topic.name)}): " + " · ".join(works))
    if not lines:
        return None
    text = label("<br>".join(lines), "muted", wrap=True)
    text.setObjectName("algorithmFollows")
    text.setTextFormat(Qt.RichText)
    text.setOpenExternalLinks(True)
    return text


def code_widget(spec: BoxSpec, page=None, compact: bool = True) -> QWidget:
    """The box's own source and, under it, the code of every algorithm it
    calls (see :func:`openprocess.flow.box.algorithm_calls`): the box is a thin
    wrapper, so the code to read when assessing correctness is the latter."""
    host = QWidget()
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    calls = algorithm_calls(spec)
    where = spec.file if spec.custom else f"openprocess/flow/boxes/{spec.module.rsplit('.', 1)[-1]}.py"
    if calls:
        layout.addWidget(label("THE BOX", "sectionLabel"))
    layout.addWidget(label(f"{where}:{spec.line}" if spec.line else where, "muted", wrap=True, selectable=True))
    layout.addWidget(_code_view(spec.source, compact), 1)
    actions = []
    if spec.file and Path(spec.file).is_file():
        actions.append(button("Open in your editor", lambda: _open_in_editor(spec.file),
                              tooltip="Open the file in the editor your system uses for .py files; the box "
                                      "reloads when you save"))
    if spec.needs:
        actions.append(label("Needs " + ", ".join(spec.needs)
                             + ("" if spec.available else " (not installed: the box is greyed out)"), "muted"))
    if actions:
        layout.addLayout(hbox(*actions, None))
    if calls:
        layout.addSpacing(6)
        layout.addWidget(label("THE ALGORITHM", "sectionLabel"))
        layout.addWidget(label("The box only wraps these: the actual work is in the functions it calls, "
                               "shown here in the order they are called. <i>Whole file</i> opens the module "
                               "they live in, whose docstring explains the algorithm and names its source.",
                               "muted", wrap=True))
        for called in calls:
            title = label(f"<b>{escape(called.name)}</b>  ·  {escape(called.where)}", "muted", wrap=True,
                          selectable=True)
            whole = button("Whole file ⤢", lambda _checked=False, c=called: show_file(c, host.window()),
                           tooltip="The module this function lives in, in a window of its own")
            whole.setObjectName("algorithmFile")
            layout.addLayout(hbox(title, None, whole))
            follows = _follows(called)
            if follows:
                layout.addWidget(follows)
            layout.addWidget(_code_view(called.source, compact))
    layout.addWidget(label("The function is the box: call it from a script or a notebook and it runs the same way.",
                           "muted", wrap=True))
    return host


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class SettingsWidget(QWidget):
    """One control per setting of a box; ``changed`` carries the setting's
    name and its new value (a :class:`Sweep` when swept)."""

    changed = Signal(str, object)

    def __init__(self, spec: BoxSpec, settings: dict, folder: Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self.spec, self.folder = spec, folder
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        if not spec.settings:
            layout.addWidget(label("This box has no settings: its function takes only its inputs.", "muted",
                                   wrap=True))
        self.controls: dict[str, QWidget] = {}
        for setting in spec.settings:
            layout.addWidget(self._row(setting, settings.get(setting.name, setting.default)))
        layout.addStretch(1)

    def _row(self, setting: Setting, value) -> QWidget:
        row = QWidget()
        column = QVBoxLayout(row)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)
        title = label(setting.name.replace("_", " "))
        title.setStyleSheet("font-weight: 500;")
        column.addWidget(title)
        swept = is_sweep(value)
        control: QWidget
        if setting.kind == "choice":
            control = QComboBox()
            for choice in setting.choices:
                control.addItem(str(choice), choice)
            control.setCurrentIndex(max(0, list(setting.choices).index(value) if value in setting.choices else 0))
            control.currentIndexChanged.connect(lambda _i, s=setting, c=control: self.changed.emit(s.name, c.currentData()))
        elif setting.kind == "bool":
            control = QCheckBox("on")
            control.setChecked(bool(value) if not swept else bool(setting.default))
            control.toggled.connect(lambda on, s=setting: self.changed.emit(s.name, on))
        elif setting.kind == "int":
            control = QSpinBox()
            control.setRange(-1_000_000, 1_000_000_000)
            control.setValue(int(value) if not swept else int(setting.default))
            control.valueChanged.connect(lambda v, s=setting: self.changed.emit(s.name, v))
        elif setting.kind == "float":
            control = QDoubleSpinBox()
            control.setRange(-1e9, 1e9)
            control.setDecimals(3)
            control.setSingleStep(0.05)
            control.setValue(float(value) if not swept else float(setting.default))
            control.valueChanged.connect(lambda v, s=setting: self.changed.emit(s.name, v))
        elif setting.kind == "path":
            control = self._path_control(setting, value)
        else:
            control = QLineEdit(str(value) if not swept else "")
            control.editingFinished.connect(lambda s=setting, c=control: self.changed.emit(s.name, c.text()))
        self.controls[setting.name] = control
        if setting.kind == "path":
            choose = button("Choose…", lambda _checked=False, s=setting, c=control: self._choose_file(s, c),
                            tooltip="Pick the file in a dialog")
            choose.setObjectName(f"choose_{setting.name}")
            column.addLayout(hbox(control, choose, spacing=6))
        else:
            column.addWidget(control)
        if setting.kind in ("int", "float"):
            sweep_row = QHBoxLayout()
            sweep_row.setSpacing(6)
            sweep_box = QCheckBox("Sweep")
            sweep_box.setToolTip("Run the boxes after this one once per value, e.g. 0..0.5 step 0.1 or 1, 2, 3")
            sweep_edit = QLineEdit(value.describe().replace(" … ", "..") if swept else "")
            sweep_edit.setPlaceholderText("0..0.5 step 0.1  or  1, 2, 3")
            sweep_edit.setVisible(swept)
            sweep_box.setChecked(swept)
            if swept:
                sweep_edit.setText(", ".join(str(v) for v in value.values) if len(value.values) <= 12
                                   else f"{value.values[0]}..{value.values[-1]} step {value.values[1] - value.values[0]}")

            def toggle(on, s=setting, e=sweep_edit, c=control):
                e.setVisible(on)
                c.setEnabled(not on)
                if not on:
                    self.changed.emit(s.name, c.value())
                elif e.text().strip():
                    self._sweep(s, e)
            sweep_box.toggled.connect(toggle)
            sweep_edit.editingFinished.connect(lambda s=setting, e=sweep_edit: self._sweep(s, e))
            control.setEnabled(not swept)
            sweep_row.addWidget(sweep_box)
            sweep_row.addWidget(sweep_edit, 1)
            column.addLayout(sweep_row)
        if setting.help:
            column.addWidget(label(setting.help, "muted", wrap=True))
        return row

    def _sweep(self, setting: Setting, edit: QLineEdit) -> None:
        try:
            sweep = Sweep.parse(edit.text())
        except ValueError as error:
            edit.setToolTip(str(error))
            edit.setStyleSheet(f"border: 1px solid {style.STATUS['critical']};")
            return
        edit.setStyleSheet("")
        self.changed.emit(setting.name, sweep)

    def _path_control(self, setting: Setting, value) -> QComboBox:
        """The file field: a list of the folder's files to pick from, or a
        path typed or pasted (quotes and shell escapes are tolerated)."""
        control = QComboBox()
        control.setEditable(True)
        control.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        control.lineEdit().setPlaceholderText("Choose… or type a name in the workflow's folder")
        for name in self._files():
            control.addItem(name)
        control.setCurrentText("" if value in (None, "") else str(value))

        def typed(s=setting, c=control):
            text = clean_path(c.currentText())
            if text != c.currentText():
                c.setCurrentText(text)
            self.changed.emit(s.name, text)
        control.lineEdit().editingFinished.connect(typed)
        control.activated.connect(lambda _i: typed())
        return control

    def _choose_file(self, setting: Setting, control: QComboBox) -> None:
        """*Choose…*: a file dialog, starting in the workflow's folder (or
        where the current file is).  A file inside the folder is kept
        relative to it, so the workflow still works when the folder moves;
        one elsewhere is kept as its full path."""
        current = clean_path(control.currentText())
        start = ""
        if current:
            candidate = Path(current) if Path(current).is_absolute() or self.folder is None else Path(self.folder) / current
            if candidate.exists():
                start = str(candidate)
        if not start and self.folder is not None:
            start = str(self.folder)
        path, _ = QFileDialog.getOpenFileName(
            self, f"Choose {setting.name.replace('_', ' ')}", start,
            "Logs and nets (*.xes *.gz *.csv *.txt *.pnml *.cpn);;All files (*)")
        if not path:
            return
        control.setCurrentText(self.display_path(path))
        self.changed.emit(setting.name, control.currentText())

    def display_path(self, path: str | Path) -> str:
        """``path`` relative to the workflow's folder when it is inside it, else as given."""
        chosen = Path(path)
        if self.folder is not None:
            try:
                return str(chosen.resolve().relative_to(Path(self.folder).resolve()))
            except ValueError:
                pass
        return str(chosen)

    def _files(self) -> list[str]:
        if self.folder is None or not Path(self.folder).is_dir():
            return []
        names = []
        for path in sorted(Path(self.folder).rglob("*")):
            if path.is_file() and not path.name.startswith(".") and path.suffix.lower() in (
                    ".xes", ".gz", ".csv", ".txt", ".pnml", ".cpn") and len(names) < 200:
                names.append(str(path.relative_to(self.folder)))
        return names


# ---------------------------------------------------------------------------
# A tab in its own window
# ---------------------------------------------------------------------------
_windows: list[QDialog] = []


def pop_out(title: str, make_widget, parent=None) -> QDialog:
    """Show ``make_widget()`` in a window of its own (non-modal, resizable)."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setModal(False)
    dialog.resize(960, 700)
    dialog.setLayout(vbox(scroll(make_widget()), margins=(16, 16, 16, 16)))
    dialog.show()
    _windows.append(dialog)
    dialog.finished.connect(lambda _r: _windows.remove(dialog) if dialog in _windows else None)
    return dialog


def status_text(result: Result | None) -> tuple[str, str]:
    """(chip text, status word) for a box's result."""
    if result is None:
        return "Waiting", "muted"
    if result.status == "done":
        return (f"Done in {result.duration * 1000:.0f} ms" + (" (kept)" if result.cached else "")), "good"
    if result.status == "running":
        return "Running…", "accent"
    if result.status == "failed":
        return "Failed", "critical"
    if result.status == "blocked":
        return result.message or "Not allowed to run yet", "warning"
    return result.message or "Waiting", "muted"
