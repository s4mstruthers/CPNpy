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
    QAbstractItemView, QButtonGroup, QComboBox, QFileDialog, QGridLayout, QHeaderView, QLabel,
    QLineEdit, QPlainTextEdit, QRadioButton, QSlider, QSplitter, QStackedWidget, QTableView,
    QVBoxLayout, QWidget,
)

from ...mining import pm4py_bridge
from ...mining.dfg import discover_dfg
from ...mining.discovery.alpha import AlphaResult, alpha_miner
from ...mining.discovery.heuristics import heuristics_miner
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
    footprint_table,
    BarDelegate, Card, ElidedLabel, Legend, LegendSwatch, PageHeader, SegmentedControl,
    SequenceDelegate, StatTile, Verdict,
    button, hbox, label, scroll, vbox,
)
from .workers import run_in_background

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
        self.header.actions.addWidget(button("Export XES…", self.export))
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
        """Save the log as XES.  The document then refers to that file, so it
        can be reopened at the next launch and removed without losing it."""
        path, _ = QFileDialog.getSaveFileName(self, "Export event log",
                                              f"{self.document.name}.xes", "XES (*.xes *.xes.gz)")
        if path:
            write_xes(self.document.log, path)
            self.document.path = path
            self._refresh_header()
            self.status.emit(f"Saved {path}")
            self.saved.emit()

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
        layout.addWidget(card, 1)

    # -------------------------------------------------------------- discover
    def _build_discover(self, layout) -> None:
        algorithms = [
            ("alpha", "α-algorithm", "Classic footprint-based miner. Shows the eight steps; "
             "cannot handle short loops, noise or silent steps."),
            ("im", "Inductive Miner", "Divide-and-conquer on the DFG. Always sound, always fits "
             "the log perfectly."),
            ("imf", "Inductive Miner – infrequent", "IM with a noise filter: simpler models, "
             "fitness may drop slightly."),
            ("heuristics", "Heuristics Miner",
             "Frequency-based dependency measures, robust to noise. Produces a dependency graph."),
        ]
        if pm4py_bridge.available():
            algorithms += [
                ("pm_heuristics", "Heuristics → Petri net (PM4Py)",
                 "Full heuristics net with split/join semantics, converted by PM4Py."),
                ("pm_ilp", "ILP Miner (PM4Py)", "Region-based miner via integer programming."),
            ]

        chooser = Card("Algorithm")
        group = QButtonGroup(chooser)
        for index, (key, name, description) in enumerate(algorithms):
            radio = QRadioButton(name)
            radio.setProperty("key", key)
            group.addButton(radio, index)
            chooser.add(radio)
            hint = label(description, "muted", wrap=True)
            hint.setContentsMargins(26, 0, 0, 6)
            chooser.add(hint)
        group.button(1).setChecked(True)

        params = Card("Parameters")
        noise = QSlider(Qt.Horizontal)
        noise.setRange(0, 100)
        noise.setValue(20)
        noise_value = label("0.20", "muted")
        noise.valueChanged.connect(lambda v: noise_value.setText(f"{v / 100:.2f}"))
        dependency = QSlider(Qt.Horizontal)
        dependency.setRange(0, 100)
        dependency.setValue(50)
        dependency_value = label("0.50", "muted")
        dependency.valueChanged.connect(lambda v: dependency_value.setText(f"{v / 100:.2f}"))
        noise_row = QWidget()
        noise_row.setLayout(vbox(label("Noise threshold f"), hbox(noise, noise_value),
                                 label("Edges weaker than f × the strongest outgoing edge are "
                                       "ignored when no cut is found.", "muted", wrap=True)))
        dependency_row = QWidget()
        dependency_row.setLayout(vbox(label("Dependency threshold"), hbox(dependency, dependency_value),
                                      label("Keep a → b when (|a>b| − |b>a|) / (|a>b| + |b>a| + 1) "
                                            "reaches this value.", "muted", wrap=True)))
        none_row = label("No parameters.", "muted")
        params.add(noise_row)
        params.add(dependency_row)
        params.add(none_row)

        def update_params() -> None:
            key = group.checkedButton().property("key")
            noise_row.setVisible(key == "imf")
            dependency_row.setVisible(key in ("heuristics", "pm_heuristics"))
            none_row.setVisible(key not in ("imf", "heuristics", "pm_heuristics"))
        group.idToggled.connect(lambda *_: update_params())
        update_params()

        run = button("Discover", kind="primary")
        left_content = QWidget()
        left_content.setLayout(vbox(chooser, params, run, None, spacing=12))
        # Scrollable, so a short window never forces the page taller.
        left = scroll(left_content)
        left.setMinimumWidth(240)
        left.setMaximumWidth(330)

        # --- result side
        result_card = Card("Result", "Choose an algorithm and press Discover.")
        preview = GraphView()
        preview.setMinimumHeight(140)
        open_button = button("Open as model  →", kind="primary")
        open_button.setEnabled(False)
        result_card.header.addWidget(open_button)
        result_card.add(preview, 1)
        derivation_body = QWidget()
        steps_host = QVBoxLayout(derivation_body)
        steps_host.setContentsMargins(0, 0, 0, 0)
        derivation = Card("How it was derived")
        derivation.add(scroll(derivation_body), 1)
        derivation.setVisible(False)
        right = QSplitter(Qt.Vertical)
        right.addWidget(result_card)
        right.addWidget(derivation)
        right.setSizes([520, 260])
        right.setStyleSheet("QSplitter::handle { background: transparent; }")

        state: dict = {}

        def clear_steps() -> None:
            while steps_host.count():
                item = steps_host.takeAt(0)
                if item.widget():
                    item.widget().hide()
                    item.widget().deleteLater()

        def show(result) -> None:
            run.setEnabled(True)
            run.setText("Discover")
            key, payload = result
            clear_steps()
            state["model"] = None
            log_name = self.document.name
            if key == "heuristics":
                nodes, edges = dependency_specs(payload)
                preview.graph.populate(nodes, edges)
                derivation.setVisible(True)
                steps_host.addWidget(label(
                    "Dependency graph: edge labels are a ⇒ b values. It has no split/join "
                    "semantics, so it is not a Petri net"
                    + (" — use “Heuristics Miner → Petri net (PM4Py)” for that."
                       if pm4py_bridge.available() else
                       " (install the optional PM4Py extra to convert it)."), "muted", wrap=True))
                open_button.setEnabled(False)
            else:
                net = payload.net if hasattr(payload, "net") else payload
                net.name = f"{net.info.get('algorithm', 'Model')} · {log_name}"
                nodes, edges = petri_net_specs(net, show_place_names=key == "alpha")
                preview.graph.populate(nodes, edges, layer_gap=48)
                state["model"] = ModelDocument(net, origin=f"{net.info.get('algorithm')} on "
                                               f"“{log_name}”", derivation=payload,
                                               source_log=self.document)
                open_button.setEnabled(True)
                derivation.setVisible(True)
                steps_host.addWidget(derivation_widget(payload))
            steps_host.addStretch(1)
            preview.fit()
            result_card.findChild(QLabel, "cardCaption").setText(
                f"{dict((a[0], a[1]) for a in algorithms)[key]} on “{log_name}”")

        def failed(message: str) -> None:
            run.setEnabled(True)
            run.setText("Discover")
            clear_steps()
            derivation.setVisible(True)
            steps_host.addWidget(Verdict("Discovery failed", "critical", message))

        def discover() -> None:
            key = group.checkedButton().property("key")
            simple = self.document.simple_log()
            f, d = noise.value() / 100, dependency.value() / 100
            functions = {
                "alpha": lambda: alpha_miner(simple),
                "im": lambda: inductive_miner(simple),
                "imf": lambda: inductive_miner(simple, noise_threshold=f),
                "heuristics": lambda: heuristics_miner(simple, dependency_threshold=d),
                "pm_heuristics": lambda: pm4py_bridge.heuristics_petri_net(simple, d),
                "pm_ilp": lambda: pm4py_bridge.ilp_petri_net(simple),
            }
            run.setEnabled(False)
            run.setText("Discovering…")
            run_in_background(lambda: (key, functions[key]()), show, failed)

        run.clicked.connect(discover)
        open_button.clicked.connect(lambda: state.get("model") and self.open_model.emit(state["model"]))

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([310, 1000])
        splitter.setHandleWidth(14)
        splitter.setStyleSheet("QSplitter::handle { background: transparent; }")
        layout.addWidget(splitter, 1)
        discover()


def derivation_widget(payload) -> QWidget:
    """Typeset account of a discovery result (see :mod:`derivation_view`)."""
    from .derivation_view import derivation_view
    # The Discover tab already shows the model, so skip the tree drawing there
    # only when the model *is* the tree (it is not: the tree is a separate view).
    return derivation_view(payload)
