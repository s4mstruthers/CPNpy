"""The event log workspace: overview, variants, cases, dotted chart,
process map, footprint, and discovery.

Everything shown is derived from one :class:`LogDocument` under its current
*classifier* (the rule that turns events into activity labels).  Changing the
classifier in the header recomputes every tab.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QGridLayout, QHeaderView, QLabel,
    QGraphicsOpacityEffect, QLineEdit, QPlainTextEdit, QSlider, QSplitter, QStackedWidget, QTableView,
    QVBoxLayout, QWidget,
)

from ...mining import pm4py_bridge
from ...mining.dfg import discover_dfg
from ...mining.discovery.alpha import AlphaResult, alpha_miner
from ...mining.discovery.heuristics import heuristics_miner, heuristics_net
from ...mining.discovery.inductive import InductiveResult, inductive_miner
from ...mining.footprint import footprint_of_log
from ...mining.stats import format_duration
from ...mining.xes import write_xes
from .. import theme
from . import style
from .charts import ColumnChart
from .documents import LogDocument, ModelDocument
from .dotted_chart import DottedChartPanel
from .graph_builders import dependency_specs, dfg_specs, petri_net_specs
from .graph_view import GraphView
from .widgets import (
    suggested_path,
    footprint_table,
    BarDelegate, Card, ElidedLabel, Legend, LegendSwatch, PageHeader, SegmentedControl,
    SequenceDelegate, StatTile, Verdict,
    button, hbox, label, scroll, vbox,
)
from .workers import run_in_background

def plural(count: int, singular: str, many: str | None = None) -> str:
    return f"{count:,} {singular if count == 1 else many or singular + 's'}"


TABS = ["Overview", "Variants", "Cases", "Dotted chart", "Process map", "Footprint", "Discover"]


def _item(text, align_right: bool = False, data=None, colour: str | None = None) -> QStandardItem:
    item = QStandardItem("" if text is None else str(text))
    item.setEditable(False)
    if align_right:
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if data is not None:
        item.setData(data, Qt.UserRole)
    if colour is not None:
        item.setData(colour, Qt.UserRole + 1)
    return item


def _runs(sequence) -> list[tuple[str, int]]:
    """Collapse repeats: (a, b, b, b, c) -> [(a, 1), (b, 3), (c, 1)]."""
    runs: list[tuple[str, int]] = []
    for activity in sequence:
        if runs and runs[-1][0] == activity:
            runs[-1] = (activity, runs[-1][1] + 1)
        else:
            runs.append((activity, 1))
    return runs


def _table(model: QStandardItemModel) -> QTableView:
    view = QTableView()
    view.setModel(model)
    view.setAlternatingRowColors(True)
    view.setSelectionBehavior(QAbstractItemView.SelectRows)
    view.setSelectionMode(QAbstractItemView.SingleSelection)
    view.setShowGrid(False)
    view.verticalHeader().setVisible(False)
    view.verticalHeader().setDefaultSectionSize(30)
    view.horizontalHeader().setHighlightSections(False)
    view.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    view.setEditTriggers(QAbstractItemView.NoEditTriggers)
    view.setWordWrap(False)
    return view


class LogPage(QWidget):
    open_model = Signal(object)          # ModelDocument
    open_log = Signal(object)            # LogDocument (a filtered copy)
    status = Signal(str)
    #: Emitted after the log was exported; the document now lives in that file.
    saved = Signal()

    def __init__(self, document: LogDocument, parent=None) -> None:
        super().__init__(parent)
        self.document = document
        self._built: set[int] = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header = PageHeader()
        self.classifier_box = QComboBox()
        self.classifier_box.setToolTip("How events become activity labels")
        # Let the combo shrink below its longest entry instead of widening the window.
        self.classifier_box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.classifier_box.setMinimumContentsLength(14)
        for classifier in document.log.available_classifiers():
            self.classifier_box.addItem(classifier.name, classifier)
        index = self.classifier_box.findText(document.classifier.name)
        self.classifier_box.setCurrentIndex(max(index, 0))
        self.classifier_box.currentIndexChanged.connect(self._classifier_changed)
        self.header.actions.addWidget(label("Classifier", "muted"))
        self.header.actions.addWidget(self.classifier_box)
        self.header.actions.addWidget(button("Filter…", self.filter_log,
                                             tooltip="Keep part of the log (variants, "
                                                     "activities, start/end, length, time) "
                                                     "as a new log"))
        self.header.actions.addWidget(button("Export…", self.export,
                                             tooltip="Save the log as XES or CSV"))
        root.addWidget(self.header)

        self.tabs = SegmentedControl(TABS)
        root.addLayout(hbox(self.tabs, None, margins=(20, 0, 20, 12)))

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.pages = [QWidget() for _ in TABS]
        for page in self.pages:
            QVBoxLayout(page).setContentsMargins(20, 0, 20, 16)
            self.stack.addWidget(page)
        self.tabs.changed.connect(self._show_tab)
        self._refresh_header()
        self._show_tab(0)

    # ------------------------------------------------------------------ util
    def _refresh_header(self) -> None:
        s = self.document.summary
        from pathlib import Path
        where = Path(self.document.path).name if self.document.path else "created in the app"
        self.header.set_text(self.document.name,
                             f"{s.case_count:,} cases · {s.event_count:,} events · "
                             f"{s.activity_count} activities · {where}")

    def _classifier_changed(self) -> None:
        self.document.set_classifier(self.classifier_box.currentData())
        self._refresh_header()
        # Rebuild lazily: forget every built tab, then rebuild the visible one.
        self._built.clear()
        for page in self.pages:
            layout = page.layout()
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().hide()
                    item.widget().deleteLater()
        self._show_tab(self.tabs.index())

    def refresh_title(self) -> None:
        self._refresh_header()

    def export(self) -> None:
        """Save the log as XES (or CSV).  The document then refers to that file,
        so it can be reopened at the next launch and removed without losing it."""
        path, chosen = QFileDialog.getSaveFileName(
            self, "Export event log", suggested_path(f"{self.document.name}.xes"),
            "XES (*.xes *.xes.gz);;CSV, one row per event (*.csv)")
        if not path:
            return
        if chosen.startswith("CSV") and not path.lower().endswith(".csv"):
            path += ".csv"
        self.write_to(path)

    def write_to(self, path: str, quiet: bool = False) -> None:
        """Save the log to ``path`` (XES, or CSV by its extension); it is then that file."""
        from .workspace import atomic_write
        if path.lower().endswith(".csv"):
            from ...mining.csv_import import write_csv
            atomic_write(path, lambda temporary: write_csv(self.document.log, temporary))
        else:
            atomic_write(path, lambda temporary: write_xes(self.document.log, temporary))
        self.document.path = path
        self.document.missing = False
        self._refresh_header()
        if not quiet:
            self.status.emit(f"Saved {path}")
        self.saved.emit()

    def filter_log(self) -> None:
        """Filter this log into a new one (the Filter… dialog)."""
        from .filter_dialog import FilterDialog
        dialog = FilterDialog(self.document, self)
        if dialog.exec() != FilterDialog.Accepted:
            return
        filtered = LogDocument(dialog.result_log())
        if self.document.classifier in filtered.log.available_classifiers():
            filtered.set_classifier(self.document.classifier)
        self.open_log.emit(filtered)

    def _show_tab(self, index: int) -> None:
        if index not in self._built:
            builder = [self._build_overview, self._build_variants, self._build_cases,
                       self._build_dotted, self._build_map, self._build_footprint,
                       self._build_discover][index]
            builder(self.pages[index].layout())
            self._built.add(index)
        self.stack.setCurrentIndex(index)

    # -------------------------------------------------------------- overview
    def _build_overview(self, layout) -> None:
        s = self.document.summary
        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(14)

        span = "–"
        if s.start and s.end:
            span = format_duration(s.end - s.start)
        tiles = [
            StatTile("Cases", f"{s.case_count:,}"),
            StatTile("Events", f"{s.event_count:,}",
                     f"{self.document.log.event_count:,} before classifier"
                     if s.event_count != self.document.log.event_count else ""),
            StatTile("Activities", f"{s.activity_count}"),
            StatTile("Variants", f"{s.variant_count:,}",
                     f"{s.variant_count / max(s.case_count, 1):.2f} variants per case"),
            StatTile("Median case duration", format_duration(s.median_case_duration),
                     f"mean {format_duration(s.mean_case_duration)}"),
            StatTile("Time span", span, s.start.strftime("%d %b %Y %H:%M") if s.start else ""),
        ]
        grid = QGridLayout()
        grid.setSpacing(12)
        for i, tile in enumerate(tiles):
            grid.addWidget(tile, 0, i)
        column.addLayout(grid)

        # Activity table with inline bars
        activities = Card("Activities", "Frequency of each activity; colour identifies it "
                          "in the dotted chart and variant views.")
        model = QStandardItemModel(0, 5)
        model.setHorizontalHeaderLabels(["Activity", "Events", "Cases", "Starts", "Ends"])
        top = max((a.occurrences for a in s.activities), default=1)
        colours = self.document.colours
        for a in s.activities:
            colour = colours.colour(a.name)
            name = _item(a.name)
            name.setData(QColor(colour), Qt.DecorationRole)
            model.appendRow([name, _item(f"{a.occurrences:,}", data=a.occurrences / top,
                                         colour=colour),
                             _item(f"{a.cases:,}", True), _item(f"{a.as_start:,}", True),
                             _item(f"{a.as_end:,}", True)])
        table = _table(model)
        table.setItemDelegateForColumn(1, BarDelegate(Qt.UserRole + 1, table))
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for c in (2, 3, 4):
            header.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        table.setMinimumHeight(min(60 + 30 * len(s.activities), 420))
        activities.add(table)

        lengths = Card("Case length", "Number of events per case")
        chart = ColumnChart("length", "cases")
        if s.events_per_case:
            longest = max(s.events_per_case)
            chart.set_values([(str(n), s.events_per_case.get(n, 0))
                              for n in range(min(s.events_per_case), longest + 1)])
        lengths.add(chart, 1)

        row = QGridLayout()
        row.setSpacing(12)
        row.addWidget(activities, 0, 0)
        row.addWidget(lengths, 0, 1)
        row.setColumnStretch(0, 3)
        row.setColumnStretch(1, 2)
        column.addLayout(row)

        attributes = Card("Log attributes")
        rows = [(k, str(v)) for k, v in self.document.log.attributes.items()]
        rows += [("classifier (file)", c.name) for c in self.document.log.declared_classifiers]
        text = "\n".join(f"{k}:  {v}" for k, v in rows) or "No log-level attributes."
        attributes.add(label(text, "muted", wrap=True, selectable=True))
        column.addWidget(attributes)
        column.addStretch(1)
        layout.addWidget(scroll(content))

    # -------------------------------------------------------------- variants
    def _build_variants(self, layout) -> None:
        s = self.document.summary
        colours = self.document.colours
        card = Card("Variants", "Distinct activity sequences, most frequent first.")
        model = QStandardItemModel(0, 5)
        model.setHorizontalHeaderLabels(["#", "Cases", "Share", "Length", "Sequence"])
        for number, variant in enumerate(s.variants, 1):
            chips = [(f"{a} ×{n}" if n > 1 else a, colours.colour(a), None)
                     for a, n in _runs(variant.sequence)]
            sequence_item = _item(" → ".join(variant.sequence), data=chips)
            sequence_item.setToolTip(" → ".join(variant.sequence))
            model.appendRow([
                _item(number, True), _item(f"{variant.count:,}", True),
                _item(f"{variant.count / max(s.case_count, 1):.1%}", True),
                _item(len(variant.sequence), True), sequence_item])
        table = _table(model)
        table.setItemDelegateForColumn(4, SequenceDelegate(table))
        header = table.horizontalHeader()
        for c in range(4):
            header.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        card.add(table, 1)
        layout.addWidget(card, 1)

    # ----------------------------------------------------------------- cases
    def _build_cases(self, layout) -> None:
        log = self.document.log
        s = self.document.summary
        variant_of = {}
        for number, variant in enumerate(s.variants, 1):
            for index in variant.trace_indices:
                variant_of[index] = number

        cases = QStandardItemModel(0, 5)
        cases.setHorizontalHeaderLabels(["Case", "Events", "Start", "Duration", "Variant"])
        for index, trace in enumerate(log.traces):
            stamps = [e.timestamp for e in trace.events if e.timestamp]
            start = min(stamps).strftime("%Y-%m-%d %H:%M") if stamps else "–"
            duration = format_duration(max(stamps) - min(stamps)) if stamps else "–"
            first = _item(trace.case_id, data=index)
            cases.appendRow([first, _item(len(trace), True), _item(start),
                             _item(duration, True), _item(variant_of.get(index, ""), True)])
        case_table = _table(cases)
        case_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        case_table.horizontalHeader().setStretchLastSection(True)

        search = QLineEdit()
        search.setPlaceholderText("Filter cases…")
        search.setClearButtonEnabled(True)

        def filter_rows(text: str) -> None:
            for row in range(cases.rowCount()):
                case_table.setRowHidden(row, text.lower() not in cases.item(row, 0).text().lower())
        search.textChanged.connect(filter_rows)

        events = QStandardItemModel(0, 5)
        event_table = _table(events)
        colours = self.document.colours
        classifier = self.document.classifier

        def show_case(current, _previous=None) -> None:
            events.clear()
            events.setHorizontalHeaderLabels(["#", "Activity", "Timestamp", "Lifecycle",
                                              "Resource", "Other attributes"])
            if not current.isValid():
                return
            trace = log.traces[cases.item(current.row(), 0).data(Qt.UserRole)]
            standard = {"concept:name", "time:timestamp", "lifecycle:transition", "org:resource"}
            for number, event in enumerate(trace.events, 1):
                included = classifier.accepts(event)
                name = _item(classifier.label(event) if included else event.activity)
                if included:
                    name.setData(QColor(colours.colour(classifier.label(event))), Qt.DecorationRole)
                else:
                    name.setForeground(QColor(style.tokens().text_muted))
                    name.setToolTip("Not included by the current classifier")
                others = ", ".join(f"{k}={v}" for k, v in event.attributes.items()
                                   if k not in standard)
                events.appendRow([
                    _item(number, True), name,
                    _item(event.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                          if event.timestamp else "–"),
                    _item(event.lifecycle or ""), _item(event.resource or ""), _item(others)])
            header = event_table.horizontalHeader()
            header.setSectionResizeMode(QHeaderView.ResizeToContents)
            header.setStretchLastSection(True)

        case_table.selectionModel().currentRowChanged.connect(show_case)

        left = Card("Cases")
        left.add(search)
        left.add(case_table, 1)
        right = Card("Events of the selected case")
        right.add(event_table, 1)
        splitter = QSplitter()
        splitter.setHandleWidth(12)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([380, 700])
        splitter.setStyleSheet("QSplitter::handle { background: transparent; }")
        layout.addWidget(splitter, 1)
        if cases.rowCount():
            case_table.selectRow(0)

    # ---------------------------------------------------------- dotted chart
    def _build_dotted(self, layout) -> None:
        layout.addWidget(DottedChartPanel(self.document), 1)

    # ----------------------------------------------------------- process map
    def _build_map(self, layout) -> None:
        dfg = discover_dfg(self.document.log, self.document.classifier)
        view = GraphView()
        mode = SegmentedControl(["Frequency", "Performance"])
        has_time = bool(dfg.durations)
        mode.buttons[1].setEnabled(has_time)
        if not has_time:
            mode.buttons[1].setToolTip("The log has no timestamps")
        activities = QSlider(Qt.Horizontal)
        paths = QSlider(Qt.Horizontal)
        for slider, value in ((activities, 100), (paths, 100)):
            slider.setRange(0, 100)
            slider.setValue(value)
            slider.setMinimumWidth(70)
            slider.setMaximumWidth(220)
        activity_label, path_label = label("100%", "muted"), label("100%", "muted")
        info = ElidedLabel("", "muted")
        legend = Legend()

        def update_legend(simplified) -> None:
            if mode.index() == 1:
                means = [m for m in (simplified.mean_duration(e) for e in simplified.edges)
                         if m is not None]
                slowest = max(means, default=0)
                legend.set_items([
                    (LegendSwatch("ramp"), "activity: darker = more events (count inside)"),
                    (LegendSwatch("line"), "label = mean time until the next activity"),
                    (LegendSwatch("widths"), "thicker = slower (relative to the slowest path)"),
                    (LegendSwatch("line", style.STATUS["critical"], 3.5),
                     f"red = slow: mean ≥ ⅔ of the slowest ({format_duration(slowest)})"),
                    (LegendSwatch("dashed"), "case start / end"),
                ])
            else:
                legend.set_items([
                    (LegendSwatch("ramp"), "activity: darker = more events (count inside)"),
                    (LegendSwatch("widths"), "thicker = path taken more often (label = times)"),
                    (LegendSwatch("line", style.tokens().text_muted), "grey = rare path (< 15 % of the busiest)"),
                    (LegendSwatch("dashed"), "case start / end"),
                ])

        def redraw(fit: bool = True) -> None:
            simplified = dfg.simplified(activities.value() / 100, paths.value() / 100)
            activity_label.setText(f"{activities.value()}%")
            path_label.setText(f"{paths.value()}%")
            nodes, edges = dfg_specs(simplified, "performance" if mode.index() == 1 else "frequency")
            view.graph.populate(nodes, edges, layer_gap=64)
            update_legend(simplified)
            info.setText(f"{len(simplified.activities)} of {len(dfg.activities)} activities · "
                         f"{len(simplified.all_edges())} of {len(dfg.all_edges())} paths")
            if fit:
                view.fit()

        activities.valueChanged.connect(lambda _: redraw())
        paths.valueChanged.connect(lambda _: redraw())
        mode.changed.connect(lambda _: redraw(True))

        card = Card("Process map", "Directly-follows graph: an arrow a → b means b directly "
                    "followed a in some case. Drag the sliders to simplify.")
        top_row = hbox(mode, 12, info)
        top_row.setStretch(2, 1)          # the info text takes the slack
        card.add(top_row)
        card.add(hbox(label("Activities"), activities, activity_label, 16,
                      label("Paths"), paths, path_label, None))
        card.add(view, 1)
        card.add(legend)
        layout.addWidget(card, 1)
        redraw()

    # ------------------------------------------------------------- footprint
    def _build_footprint(self, layout) -> None:
        fp = footprint_of_log(self.document.simple_log())
        table = footprint_table(fp)
        card = Card("Footprint matrix", "Log-based ordering relations derived from the "
                    "directly-follows relation >_L (row activity vs column activity).")
        card.add(label("→ causality: a > b and not b > a     ← inverse     "
                       "‖ parallel: a > b and b > a     # choice: neither", "muted", wrap=True))
        card.add(table, 1)
        start_end = (f"Start activities: {', '.join(sorted(fp.start))}     "
                     f"End activities: {', '.join(sorted(fp.end))}")
        card.add(label(start_end, "muted", wrap=True, selectable=True))
        card.body.addStretch(0)
        layout.addWidget(card, 1)

    # -------------------------------------------------------------- discover
    def _build_discover(self, layout) -> None:
        algorithms = [
            ("im", "Inductive Miner", "Divide-and-conquer on the DFG. Always sound, always fits "
             "the log perfectly."),
            ("imf", "Inductive Miner – infrequent", "IM with a noise filter: simpler models, "
             "fitness may drop slightly."),
            ("alpha", "α-algorithm", "Classic footprint-based miner. Shows the eight steps; "
             "cannot handle short loops, noise or silent steps."),
            ("heuristics", "Heuristics Miner",
             "Frequency-based dependency measures, robust to noise. Produces a dependency graph."),
            ("heuristics_net", "Heuristics Miner → Petri net",
             "The same, plus which forks are AND or XOR (learned from the log as a causal "
             "net), as a Petri net. Fits well; not always sound."),
        ]
        if pm4py_bridge.available():
            algorithms += [
                ("pm_heuristics", "Heuristics → Petri net (PM4Py)",
                 "Full heuristics net with split/join semantics, converted by PM4Py."),
                ("pm_ilp", "ILP Miner (PM4Py)", "Region-based miner via integer programming."),
            ]
        names = {key: name for key, name, _ in algorithms}
        descriptions = {key: text for key, _, text in algorithms}

        # --- toolbar: algorithm, its parameter, and the way out to a model.
        # A compact bar rather than a sidebar, so the model and its derivation
        # get the whole width.
        chooser = QComboBox()
        for key, name, _ in algorithms:
            chooser.addItem(name, key)
        chooser.setSizeAdjustPolicy(QComboBox.AdjustToContents)

        def slider_row(text: str, value: int, tooltip: str):
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(value)
            slider.setFixedWidth(160)
            # Rediscover when the slider is let go, not at every step of a drag.
            slider.setTracking(False)
            shown = label(f"{value / 100:.2f}", "muted")
            slider.sliderMoved.connect(lambda v: shown.setText(f"{v / 100:.2f}"))
            slider.valueChanged.connect(lambda v: shown.setText(f"{v / 100:.2f}"))
            row = QWidget()
            row.setLayout(hbox(label(text), slider, shown))
            row.setToolTip(tooltip)
            return slider, row

        noise, noise_row = slider_row(
            "Noise threshold f", 20,
            "Edges weaker than f × the strongest outgoing edge are ignored when no cut is found.")
        dependency, dependency_row = slider_row(
            "Dependency threshold", 50,
            "Keep a → b when (|a>b| − |b>a|) / (|a>b| + |b>a| + 1) reaches this value.")

        open_button = button("Open as model  →", kind="primary")
        open_button.setEnabled(False)
        toolbar = Card()
        toolbar.body.addLayout(hbox(label("Algorithm"), chooser, 16, noise_row, dependency_row,
                                    None, open_button, spacing=10))
        description = label("", "muted", wrap=True)
        toolbar.add(description)

        def current_key() -> str:
            return chooser.currentData()

        def update_params() -> None:
            key = current_key()
            noise_row.setVisible(key == "imf")
            dependency_row.setVisible(key in ("heuristics", "heuristics_net", "pm_heuristics"))
            description.setText(descriptions[key])
        update_params()

        # --- result: the model beside how it was derived
        result_card = Card("Model", " ")
        caption = result_card.caption_label
        preview = GraphView()
        preview.setMinimumHeight(140)
        result_card.add(preview, 1)
        derivation_body = QWidget()
        steps_host = QVBoxLayout(derivation_body)
        steps_host.setContentsMargins(0, 0, 0, 0)
        derivation = Card("How it was derived")
        steps = scroll(derivation_body)
        derivation.add(steps, 1)
        derivation.setMinimumWidth(260)
        results = QSplitter(Qt.Horizontal)
        results.addWidget(result_card)
        results.addWidget(derivation)
        results.setStretchFactor(0, 3)
        results.setStretchFactor(1, 2)
        results.setSizes([600, 400])
        results.setHandleWidth(14)
        results.setStyleSheet("QSplitter::handle { background: transparent; }")

        # Faded while a new model is on its way, so the old one reads as stale.
        fades = []
        for widget in (preview, steps):
            fades.append(QGraphicsOpacityEffect(widget))
            fades[-1].setEnabled(False)
            widget.setGraphicsEffect(fades[-1])

        def fade(opacity: float) -> None:
            for effect in fades:
                effect.setOpacity(opacity)
                # Off when opaque: the views then paint exactly as elsewhere.
                effect.setEnabled(opacity < 1.0)

        # Only the newest request's result is shown, so quickly switching
        # algorithms cannot leave an older model on screen.
        state: dict = {"request": 0}

        def clear_steps() -> None:
            while steps_host.count():
                item = steps_host.takeAt(0)
                if item.widget():
                    item.widget().hide()
                    item.widget().deleteLater()

        def show(result) -> None:
            request, key, payload = result
            if request != state["request"]:
                return
            fade(1.0)
            clear_steps()
            state["model"] = None
            log_name = self.document.name
            if key == "heuristics":
                nodes, edges = dependency_specs(payload)
                preview.graph.populate(nodes, edges)
                steps_host.addWidget(label(
                    "Dependency graph: edge labels are a ⇒ b values. It has no split/join "
                    "semantics, so it is not a Petri net — “Heuristics Miner → Petri net” "
                    "learns those from the log.", "muted", wrap=True))
                open_button.setEnabled(False)
                size = (f"{plural(len(payload.activities), 'activity', 'activities')} · "
                        f"{plural(len(payload.edges), 'dependency', 'dependencies')}")
            else:
                net = payload.net if hasattr(payload, "net") else payload
                net.name = f"{net.info.get('algorithm', 'Model')} · {log_name}"
                nodes, edges = petri_net_specs(net, show_place_names=key == "alpha")
                preview.graph.populate(nodes, edges, layer_gap=48)
                state["model"] = ModelDocument(net, origin=f"{net.info.get('algorithm')} on "
                                               f"“{log_name}”", derivation=payload,
                                               source_log=self.document)
                open_button.setEnabled(True)
                steps_host.addWidget(derivation_widget(payload))
                silent = sum(t.silent for t in net.transitions.values())
                size = " · ".join(filter(None, [
                    plural(len(net.places), "place"),
                    plural(len(net.transitions) - silent, "transition"),
                    silent and f"{silent} silent",
                    plural(len(net.arcs), "arc"),
                ]))
            steps_host.addStretch(1)
            preview.fit()
            caption.setText(size)

        def failed(request: int, key: str, message: str) -> None:
            if request != state["request"]:
                return
            fade(1.0)
            clear_steps()
            preview.graph.populate([], [])
            state["model"] = None
            open_button.setEnabled(False)
            caption.setText(f"{names[key]} found no model")
            steps_host.addWidget(Verdict("Discovery failed", "critical", message))
            steps_host.addStretch(1)

        def discover() -> None:
            key = current_key()
            simple = self.document.simple_log()
            f, d = noise.value() / 100, dependency.value() / 100
            functions = {
                "alpha": lambda: alpha_miner(simple),
                "im": lambda: inductive_miner(simple),
                "imf": lambda: inductive_miner(simple, noise_threshold=f),
                "heuristics": lambda: heuristics_miner(simple, dependency_threshold=d),
                "heuristics_net": lambda: heuristics_net(simple, dependency_threshold=d),
                "pm_heuristics": lambda: pm4py_bridge.heuristics_petri_net(simple, d),
                "pm_ilp": lambda: pm4py_bridge.ilp_petri_net(simple),
            }
            state["request"] += 1
            request = state["request"]
            # The previous model stays up until the new one arrives.
            open_button.setEnabled(False)
            fade(0.35)
            caption.setText(f"Discovering with {names[key]}…")
            run_in_background(lambda: (request, key, functions[key]()), show,
                              lambda message: failed(request, key, message))

        # Rediscover whenever the choice changes.
        chooser.currentIndexChanged.connect(lambda _i: (update_params(), discover()))
        noise.valueChanged.connect(lambda _v: discover())
        dependency.valueChanged.connect(lambda _v: discover())
        open_button.clicked.connect(lambda: state.get("model") and self.open_model.emit(state["model"]))

        layout.addWidget(toolbar)
        layout.addWidget(results, 1)
        discover()


def derivation_widget(payload) -> QWidget:
    """Typeset account of a discovery result (see :mod:`derivation_view`)."""
    from .derivation_view import derivation_view
    # The Discover tab already shows the model, so skip the tree drawing there
    # only when the model *is* the tree (it is not: the tree is a separate view).
    return derivation_view(payload)
