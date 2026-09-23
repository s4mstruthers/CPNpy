"""The Petri net editor: draw a plain Petri net or WF-net and analyse it.

This is the editor for the nets of the course -- black tokens, arc weights,
silent τ transitions -- as opposed to coloured nets.  It is the coloured-net
page (:class:`~cpnpy.gui.studio.cpn_page.CpnPage`) with a simpler element
form and, instead of the CPN state space tool, an **Analysis** tab:

* **Soundness** (van der Aalst, *Workflow Verification*): is it a WF-net
  (Definition 11)?  Option to complete, proper completion, no dead
  transitions (Definition 12) -- and for every violation a counterexample,
  which *Show* replays on the net in the token game.
* **Theorem 1**: the short-circuited net N̄ (plus t* from o to i) is live
  and bounded iff the net is sound; also safe and deadlock-free.
* **Structure** (§6): free-choice, well-structured, S-coverable, Lemma 4.
* **Behavioural properties** of the net as drawn: bounded / safe, dead
  transitions, deadlocks, liveness, reversibility.
* **Footprint** of the net's behaviour (the → ← ‖ # matrix of the α
  chapter), to compare with a log's footprint.
* The **reachability graph**, and **conformance checking** against an open
  event log (the net opens as a model next to your logs).

The net is saved as PNML, the standard format ProM, WoPeD and PM4Py read.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QInputDialog, QLineEdit,
    QMessageBox, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from ...mining.analysis import analyse, check_soundness, check_workflow_net
from ...mining.footprint import footprint_of_net
from ...mining.petrinet import Marking
from ...mining.pnml import write_pnml
from ...model.net import Arc, Place, Transition
from ...model.plain import to_petri_net, token_count, tokens_text, weight_of
from .cpn_page import CpnPage
from .documents import ModelDocument
from .widgets import (
    Card, Verdict, button, flow, footprint_table, hbox, label, status_for,
)
from .workers import run_in_background


class PetriNetPage(CpnPage):
    """Draw, play and analyse a plain Petri net (see the module docstring)."""

    #: The net as a model for conformance checking / the model views.
    open_model = Signal(object)

    INSPECTOR = ["Simulation", "Element", "Analysis"]
    KIND = "Petri net"

    def __init__(self, document, parent=None) -> None:
        self._analysis_stale = True
        super().__init__(document, parent)
        # No colour sets, declarations or pages to manage.
        self.structure_toggle.hide()
        self._toggle_structure(False)
        self.values_button.hide()
        self.export_log_button.setText("Generate event log…")
        self.export_log_button.setToolTip("Play the net out many times (random choices) and "
                                          "open the traces as an event log")
        self.inspector_tabs.changed.connect(self._inspector_tab_changed)
        # Plain nets have no variables and no clock.
        self.bindings_card.title_label.setText("Enabled transitions")
        self.bindings_card.caption_label.setText("Double-click one to fire it (or click it on "
                                                 "the net).")
        self.binding_filter.hide()
        self.time_tile.hide()

    def _mode_changed(self, index: int) -> None:
        super()._mode_changed(index)
        if index == 1:
            self.sim_hint.setText("Green = enabled. Click a green transition to fire it; Back "
                                  "undoes, Reset returns to the initial marking. Trace lights up "
                                  "the path so far.")
        elif index == 2:
            self.sim_hint.setText("Play fires enabled transitions at random (blue halo = fired "
                                  "last). Generate event log (Simulation tab) plays many runs "
                                  "and opens them as a log.")

    def refresh_simulation(self, light: bool = False) -> None:
        super().refresh_simulation(light)
        count = len(getattr(self, "enabled_elements", []))
        self.enabled_tile.set(f"{count}", f"transition{'s' * (count != 1)}")

    def _fill_marking(self) -> None:
        """The marking as counts and dots, not CPN multisets."""
        from PySide6.QtWidgets import QTableWidgetItem
        rows = []
        for place in self.net.all_places():
            count = self._marking_for(place.id)[0]
            if count or not self.only_marked.isChecked():
                rows.append((place, count))
        self.marking_table.setRowCount(len(rows))
        for row, (place, count) in enumerate(rows):
            name = QTableWidgetItem(place.name)
            name.setData(Qt.UserRole, place.id)
            number = QTableWidgetItem(f"{count:,}")
            number.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            dots = QTableWidgetItem("●" * count if count <= 12 else f"{count} tokens")
            self.marking_table.setItem(row, 0, name)
            self.marking_table.setItem(row, 1, number)
            self.marking_table.setItem(row, 2, dots)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._toggle_structure(False)

    # =====================================================================
    # Inspector
    # =====================================================================
    def _build_inspector(self) -> QWidget:
        from PySide6.QtWidgets import QStackedWidget
        from .widgets import SegmentedControl, scroll
        host = QWidget()
        self.inspector_panel = host
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.inspector_tabs = SegmentedControl(self.INSPECTOR, compact=True)
        host.setMinimumWidth(max(360, self.inspector_tabs.sizeHint().width() + 24))
        layout.addLayout(hbox(self.inspector_tabs, None))
        self.inspector_stack = QStackedWidget()
        for build in (self._build_simulation_tab, self._build_element_tab,
                      self._build_analysis_tab):
            self.inspector_stack.addWidget(scroll(build()))
        self.inspector_tabs.changed.connect(self.inspector_stack.setCurrentIndex)
        layout.addWidget(self.inspector_stack, 1)
        # The coloured-net page's problems list is not needed here.
        self.problems_card = Card()
        return host

    # -- element form -------------------------------------------------------------------
    def _build_element_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 4, 0)
        self.element_card = Card("Nothing selected")
        self.element_hint = label(
            "Click a place, transition or arc to edit it. Double-click a place or "
            "transition on the canvas to rename it.", "muted", wrap=True)
        self.element_card.add(self.element_hint)
        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.form.setHorizontalSpacing(12)
        self.form.setVerticalSpacing(10)
        self.name_edit = QLineEdit()
        self.name_edit.editingFinished.connect(self._commit_element)
        self.tokens_spin = QSpinBox()
        self.tokens_spin.setRange(0, 999)
        self.tokens_spin.setToolTip("Tokens in this place in the initial marking")
        self.tokens_spin.valueChanged.connect(lambda _v: self._commit_element())
        self.silent_box = QCheckBox("Silent (τ) — invisible in traces")
        self.silent_box.toggled.connect(lambda _v: self._commit_element())
        self.weight_spin = QSpinBox()
        self.weight_spin.setRange(1, 99)
        self.weight_spin.setToolTip("How many tokens the arc moves at once")
        self.weight_spin.valueChanged.connect(lambda _v: self._commit_element())
        self.orientation_box = QComboBox()
        self.orientation_box.addItems(["Place → Transition", "Transition → Place",
                                       "Both directions"])
        self.orientation_box.activated.connect(lambda _i: self._commit_element())
        self.rows = {}
        for key, caption, widget in (("name", "Name", self.name_edit),
                                     ("tokens", "Tokens", self.tokens_spin),
                                     ("silent", "", self.silent_box),
                                     ("weight", "Weight", self.weight_spin),
                                     ("orientation", "Direction", self.orientation_box)):
            caption_label = label(caption, "muted")
            self.form.addRow(caption_label, widget)
            self.rows[key] = (caption_label, widget)
        self.element_card.add(self.form)
        self.element_info = label("", "muted", wrap=True, selectable=True)
        self.element_card.add(self.element_info)
        from PySide6.QtWidgets import QVBoxLayout as _V
        self.element_problems = _V()
        layout.addWidget(self.element_card)
        layout.addStretch(1)
        self._show_element(None)
        return page

    def _show_element(self, element) -> None:
        self.element = element
        self.element_info.setText("")
        self.element_hint.setVisible(element is None)
        widgets = (self.name_edit, self.tokens_spin, self.silent_box, self.weight_spin,
                   self.orientation_box)
        for widget in widgets:
            widget.blockSignals(True)
        try:
            if element is None:
                self.element_card.title_label.setText("Nothing selected")
                self._set_rows(set())
            elif isinstance(element, Place):
                self.element_card.title_label.setText(f"Place · {element.name}")
                self.name_edit.setText(element.name)
                self.tokens_spin.setValue(token_count(element.initial_marking_text))
                self._set_rows({"name", "tokens"})
                now = self._marking_for(element.id)[0]
                self.element_info.setText(f"Now: {now} token(s).")
            elif isinstance(element, Transition):
                kind = "Silent transition" if element.silent else "Transition"
                self.element_card.title_label.setText(f"{kind} · {element.name or 'τ'}")
                self.name_edit.setText(element.name)
                self.silent_box.setChecked(element.silent)
                self._set_rows({"name", "silent"})
                enabled = bool(self.simulator.enabled_bindings(element))
                self.element_info.setText("Enabled now." if enabled else "Not enabled now.")
            elif isinstance(element, Arc):
                place = self.net.find_place(element.place_id)
                transition = self.net.find_transition(element.transition_id)
                self.element_card.title_label.setText("Arc")
                self.weight_spin.setValue(weight_of(element))
                self.orientation_box.setCurrentIndex(
                    {"PtoT": 0, "TtoP": 1, "BOTHDIR": 2}.get(element.orientation, 0))
                self._set_rows({"weight", "orientation"})
                self.element_info.setText(
                    f"Between place “{place.name if place else '?'}” and transition "
                    f"“{transition.name if transition else '?'}”.")
        finally:
            for widget in widgets:
                widget.blockSignals(False)

    def _commit_element(self) -> None:
        element = self.element
        if element is None:
            return
        before = self._element_state(element)
        snapshot = self._snapshot()
        if isinstance(element, Place):
            element.name = self.name_edit.text().strip() or element.name
            element.initial_marking_text = tokens_text(self.tokens_spin.value())
        elif isinstance(element, Transition):
            element.name = self.name_edit.text().strip()
            element.silent = self.silent_box.isChecked()
        elif isinstance(element, Arc):
            weight = self.weight_spin.value()
            element.expression_text = "" if weight == 1 else tokens_text(weight)
            element.orientation = ["PtoT", "TtoP", "BOTHDIR"][self.orientation_box.currentIndex()]
        if self._element_state(element) != before:
            self._push_undo(snapshot)
            self._edited()
            self._show_element(element)

    @staticmethod
    def _element_state(element) -> tuple:
        return tuple(getattr(element, name, None) for name in (
            "name", "initial_marking_text", "silent", "expression_text", "orientation"))

    # -- analysis --------------------------------------------------------------------------
    def _build_analysis_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(12)
        self.analysis_button = button("Check again", self.run_analysis, kind="primary",
                                      tooltip="The analysis also runs by itself whenever "
                                              "you open this tab after an edit")
        layout.addLayout(hbox(label("Updated after every edit.", "muted"), None,
                              self.analysis_button))
        self.soundness_card = Card("Soundness", "Definition 12 of the paper: from one token "
                                   "in i, (i) every run can still reach [o], (ii) [o] is the "
                                   "only marking with a token in o, (iii) every transition "
                                   "can fire.")
        self.theorem_card = Card("Short-circuited net N̄ (Theorem 1)",
                                 "N̄ is the net plus a transition t* from o back to i. "
                                 "Theorem 1: the WF-net is sound iff (N̄, [i]) is live and "
                                 "bounded.")
        self.structure_card = Card("Structure (§6)", "Properties of the drawing alone. They "
                                   "point at the construct behind a problem.")
        self.properties_card = Card("Behavioural properties", "Of the net as drawn, from "
                                    "its initial marking.")
        self.footprint_card = Card("Footprint", "The ordering relations of the net's "
                                   "behaviour: which transition can directly follow which.")
        self.more_card = Card("More")
        self.more_card.add(label("Look at every reachable marking, or replay an event log "
                                 "on this net (token replay, alignments).", "muted",
                                 wrap=True))
        self.more_card.add(flow(button("Reachability graph…", self.show_reachability_graph),
                                button("Conformance with a log…", self.open_as_model)))
        for card in (self.soundness_card, self.theorem_card, self.structure_card,
                     self.properties_card, self.footprint_card, self.more_card):
            layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _inspector_tab_changed(self, index: int) -> None:
        if index == 2 and self._analysis_stale:
            self.run_analysis()

    def _edited(self) -> None:
        super()._edited()
        self._analysis_stale = True
        if getattr(self, "inspector_tabs", None) is not None and self.inspector_tabs.index() == 2:
            QTimer.singleShot(0, self.run_analysis)

    def petri_net(self):
        """The drawing as a :class:`~cpnpy.mining.petrinet.PetriNet`."""
        return to_petri_net(self.net)

    def run_analysis(self) -> None:
        self._analysis_stale = False
        petri = self.petri_net()
        for card in self._result_cards():
            card.clear()
        self.soundness_card.add(label("Checking…", "muted"))

        def compute():
            soundness = check_soundness(petri, max_states=100_000)
            drawn = petri
            if not petri.initial_marking and soundness.workflow.is_workflow_net:
                # Nothing drawn in the net yet: analyse from [source].
                drawn = petri.copy()
                drawn.initial_marking = Marking({soundness.workflow.source: 1})
            properties = analyse(drawn, max_states=50_000)
            try:
                footprint = footprint_of_net(drawn)
                footprint_error = None
            except ValueError as error:
                footprint, footprint_error = None, str(error)
            return soundness, properties, footprint, footprint_error, drawn is not petri

        run_in_background(compute, self._show_analysis,
                          lambda message: self.soundness_card.add(
                              Verdict("Analysis failed", "critical", message)))

    def _result_cards(self) -> tuple:
        return (self.soundness_card, self.theorem_card, self.structure_card,
                self.properties_card, self.footprint_card)

    def _finding(self, card: Card, text: str, path: list[str] | None = None,
                 source: str | None = None) -> None:
        """A bullet with, when there is a firing sequence, a Show ▶ button."""
        row = QWidget()
        row_layout = hbox(spacing=6)
        row_layout.addWidget(label("• " + text, "muted", wrap=True, selectable=True), 1)
        if path:
            show = button("Show ▶", lambda _=False, p=path, s=source: self.replay(p, s),
                          kind="ghost", tooltip="Fire this sequence on the net in the "
                                                "token game")
            show.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            row_layout.addWidget(show, 0, Qt.AlignTop)
        row.setLayout(row_layout)
        card.add(row)

    def _show_analysis(self, result) -> None:
        soundness, properties, footprint, footprint_error, from_source = result
        for card in self._result_cards():
            card.clear()
        workflow = soundness.workflow
        card = self.soundness_card
        card.add(Verdict("WF-net (Definition 11)", status_for(workflow.is_workflow_net),
                         f"source i = {self._name(workflow.source)}, sink o = "
                         f"{self._name(workflow.sink)}" if workflow.is_workflow_net else
                         "needs one source place i, one sink place o, and every node on a "
                         "path from i to o"))
        if workflow.is_workflow_net:
            verdict = soundness.sound
            card.add(Verdict("Sound" if verdict else ("Not sound" if verdict is False
                                                      else "Undecided"),
                             status_for(verdict),
                             "every case can complete properly and every transition can fire"
                             if verdict else ""))
            for name, value in (("(i) Option to complete", soundness.option_to_complete),
                                ("(ii) Proper completion", soundness.proper_completion),
                                ("(iii) No dead transitions", soundness.no_dead_transitions)):
                card.add(Verdict(name, status_for(value), ""))
        for finding, path in zip(soundness.findings, soundness.paths):
            self._finding(card, finding, path, workflow.source)
        self._show_theorem(soundness)
        self._show_structure(soundness)

        if from_source:
            self.properties_card.add(label("The net has no tokens yet, so this is from one "
                                           "token in the source place.", "muted", wrap=True))
        final = Marking({workflow.sink: 1}) if workflow.is_workflow_net else None
        only_final = final is not None and properties.dead_markings and all(
            properties.graph.states[s] == final for s in properties.dead_markings)
        for name, value, detail in properties.lines():
            if name == "Deadlock-free" and only_final:
                # A WF-net always stops in [o]: that is the case finishing.
                self.properties_card.add(Verdict(
                    name, "info", f"the only dead marking is [{self._plain(workflow.sink)}]: "
                    "the case has finished. Every WF-net stops there, so this is expected; "
                    "N̄ above shows whether it can get stuck anywhere else."))
                continue
            self.properties_card.add(Verdict(name, status_for(value), detail))
        self.properties_card.add(label(
            f"{len(properties.graph.states):,} reachable markings "
            f"({properties.graph.kind} graph).", "muted", wrap=True))

        if footprint is None:
            self.footprint_card.add(label(footprint_error or "", "muted", wrap=True))
        elif not footprint.activities:
            self.footprint_card.add(label("No visible transitions yet.", "muted"))
        else:
            table = footprint_table(footprint, compact=True)
            rows = len(footprint.activities)
            table.setMinimumHeight(min(440, 36 + 30 * rows))
            self.footprint_card.add(table)
            abbreviated = any(len(a) > 3 for a in footprint.activities)
            self.footprint_card.add(label(
                ("Columns use initials (hover for the name). " if abbreviated else "")
                + "→ causality  ← inverse  ‖ parallel  # choice. Start: "
                f"{', '.join(sorted(footprint.start)) or '–'} · end: "
                f"{', '.join(sorted(footprint.end)) or '–'}", "muted", wrap=True))

    def _name(self, node_id: str | None) -> str:
        if node_id is None:
            return "?"
        node = self.net.find_place(node_id) or self.net.find_transition(node_id)
        return f"“{node.name}”" if node is not None else node_id

    def _plain(self, node_id: str | None) -> str:
        node = node_id and (self.net.find_place(node_id) or self.net.find_transition(node_id))
        return node.name if node else (node_id or "?")

    def _show_theorem(self, soundness) -> None:
        """Theorem 1: (N̄, [i]) live and bounded ⇔ sound."""
        card = self.theorem_card
        closed = soundness.short_circuit
        if closed is None:
            card.add(label("Only for WF-nets.", "muted"))
            return
        graph = closed.properties.graph
        net = closed.net
        live = closed.live
        not_live = [net.node_name(t) for t in closed.not_live]
        card.add(Verdict("Live", status_for(live),
                         "from every reachable marking, every transition (t* too) can "
                         "fire again" if live else
                         ("not decided: N̄ is unbounded or too big" if live is None else
                          "can never fire again at some point: " + ", ".join(not_live))))
        card.add(Verdict("Bounded", status_for(closed.bounded),
                         f"at most {int(closed.properties.bound)} token(s) per place"
                         if closed.bounded else
                         "tokens can pile up: a case can finish with tokens left behind, "
                         "and t* then starts the next case on top of them"))
        theorem = closed.sound
        card.add(Verdict("Live and bounded ⇒ sound" if theorem else
                         ("Unbounded ⇒ not sound" if not closed.bounded else
                          "Not live ⇒ not sound" if theorem is False else "Undecided"),
                         status_for(theorem),
                         "the same verdict as Definition 12 above" if theorem ==
                         soundness.sound else "differs from Definition 12 (a state-space "
                         "limit was hit)"))
        card.add(Verdict("Safe", "good" if closed.safe else "info",
                         "at most one token per place (Lemmas 1 and 3: a sound free-choice "
                         "or well-structured net is always safe)" if closed.safe else
                         "some place can hold two or more tokens"))
        dead = closed.properties.dead_markings
        card.add(Verdict("Deadlock-free", "good" if not dead else "info",
                         "no marking where nothing can fire. Weaker than live: a net can "
                         "keep going while some transition is dead, so Theorem 1 asks for "
                         "live" if not dead else
                         f"stuck in {graph.states[dead[0]].describe(net)}; a deadlock is "
                         "never live, so this alone already means not sound"))
        for transition, state in list(closed.not_live.items())[:4]:
            path = graph.path_to(state)
            usable = "t_star" not in path
            self._finding(card, f"{net.node_name(transition)} can never fire again after "
                          f"{graph.describe_path(state)} (marking "
                          f"{graph.states[state].describe(net)}).",
                          path if usable else None, soundness.workflow.source)
        card.add(flow(button("Open N̄ as a new net", self._open_short_circuited,
                             tooltip="Draw the short-circuited net in a new tab")))

    def _open_short_circuited(self) -> None:
        from ...mining.analysis import short_circuit
        from ...model.plain import from_petri_net
        from .documents import CpnDocument
        petri = self.petri_net()
        workflow = check_workflow_net(petri)
        if not workflow.is_workflow_net:
            return
        closed = short_circuit(petri, workflow.source, workflow.sink)
        closed.name = f"{self.net.name} — short-circuited"
        self.open_model.emit(CpnDocument(from_petri_net(closed)))

    def _show_structure(self, soundness) -> None:
        """§6: free-choice, well-structured, S-coverable (+ Lemma 4)."""
        card = self.structure_card
        report = soundness.structure
        if report is None:
            card.add(label("Only for WF-nets.", "muted"))
            return
        name = self._plain

        def node(prefixed: str) -> str:
            return "t*" if prefixed == "t:t_star" else name(prefixed[2:])

        if report.is_free_choice:
            detail = ("transitions that share an input place have the same input places, "
                      "so every choice is free (Corollary 1)")
        else:
            t1, t2, p = report.free_choice[0]
            detail = (f"{name(t1)} and {name(t2)} share {name(p)} but need different input "
                      "places, so the choice between them depends on what happened "
                      "elsewhere (Definition 7)")
        card.add(Verdict("Free-choice", "good" if report.is_free_choice else "info", detail))

        well = report.well_structured
        if well is None:
            detail = "not checked (the net is very large)"
        elif well:
            detail = ("N̄ has no handles: every AND-split is closed by an AND-join and every "
                      "OR-split by an OR-join (Definition 14)")
        else:
            handle = report.handles[0]
            kind = ("an OR-split (place) later synchronised by an AND-join (transition)"
                    if handle.kind == "PT" else
                    "an AND-split (transition) later merged by an OR-join (place)")
            detail = (f"{handle.kind}-handle from {node(handle.start)} to "
                      f"{node(handle.end)}: {kind}. Paths "
                      + " and ".join("⟨" + ", ".join(node(n) for n in path) + "⟩"
                                     for path in handle.paths))
        card.add(Verdict("Well-structured", "unknown" if well is None else
                         ("good" if well else "info"), detail))

        cover = report.s_coverable
        if cover is None:
            detail = "not decided (search limit reached)"
        elif cover:
            detail = (f"{len(report.coverage.components)} S-component(s) cover N̄: each is "
                      "a 'thread' that is always in exactly one place (Definition 16)")
        else:
            missing = ", ".join("t*" if n == "t_star" else name(n)
                                for n in report.coverage.uncovered[:6])
            detail = (f"no S-component contains {missing}. In the paper every WF-net that is "
                      "not S-coverable is unsound — worth a close look (§6.3)")
        card.add(Verdict("S-coverable", "unknown" if cover is None else
                         ("good" if cover else "warning"), detail))
        for transition in report.lemma4:
            self._finding(card, f"Lemma 4: {name(transition)} needs i or o together with "
                          "another place, which never happens in a sound net — it is dead.")
        if soundness.sound and (report.is_free_choice or well):
            self._finding(card, "Sound and " + ("free-choice" if report.is_free_choice
                                                else "well-structured")
                          + ", so the net is safe (Lemma " + ("1" if report.is_free_choice
                                                             else "3") + ").")

    # -- counterexamples in the token game --------------------------------------------------
    def replay(self, path: list[str], source: str | None = None) -> None:
        """Fire ``path`` (transition ids) from the start, in Step through mode."""
        if source is not None:
            place = self.net.find_place(source)
            wanted = {p.id: (1 if p.id == source else 0) for p in self.net.all_places()}
            drawn = {p.id: token_count(p.initial_marking_text) for p in self.net.all_places()}
            if place is not None and drawn != wanted:
                # Soundness is about one token in the source: start there.
                self._push_undo(self._snapshot())
                for other in self.net.all_places():
                    other.initial_marking_text = tokens_text(wanted[other.id])
                self._edited()
                self.status.emit(f"Initial marking set to one token in {place.name} to "
                                 f"replay the counterexample (undo brings yours back)")
        self.mode_switch.set_index(1)
        self.simulator.reset()
        names = []
        for transition_id in path:
            transition = self.net.find_transition(transition_id)
            elements = self.simulator.enabled_bindings(transition) if transition else []
            if not elements:
                break
            self.simulator.step(elements[0])
            names.append(transition.name or "τ")
        self.refresh_simulation()
        self.inspector_tabs.set_index(0)
        self.status.emit("Counterexample: " + (" → ".join(names) or "(initial marking)")
                         + " — this is the problem marking")

    # -- more ------------------------------------------------------------------------------
    def show_reachability_graph(self) -> None:
        from ...mining.analysis import coverability_graph, reachability_graph
        from .graph_builders import state_graph_specs
        from .graph_view import GraphView
        petri = self.petri_net()
        if not petri.initial_marking:
            workflow = check_workflow_net(petri)
            if workflow.is_workflow_net:
                petri.initial_marking = Marking({workflow.source: 1})
        graph = reachability_graph(petri, max_states=5_000)
        if graph.has_omega:
            graph = coverability_graph(petri, max_states=5_000)
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Reachability graph — {self.net.name}")
        dialog.resize(900, 640)
        layout = QVBoxLayout(dialog)
        kind = "Coverability graph (ω = unbounded)" if graph.kind == "coverability" \
            else "Reachability graph"
        layout.addWidget(label(f"{kind}: {len(graph.states):,} markings, "
                               f"{len(graph.edges):,} steps"
                               + (" (stopped at 5,000)" if graph.truncated else "")
                               + ". The initial marking is shaded; red = dead.", "muted",
                               wrap=True))
        view = GraphView()
        nodes, edges = state_graph_specs(graph)
        view.graph.populate(nodes, edges, layer_gap=120)
        layout.addWidget(view, 1)
        QTimer.singleShot(0, view.fit)
        dialog.exec()

    def open_as_model(self) -> None:
        """Open the net next to the logs, where conformance checking lives."""
        petri = self.petri_net()
        self.open_model.emit(ModelDocument(petri, origin=f"Drawn in {self.net.name}"))

    def _export_log(self) -> None:
        """Play the net out: each run from the initial marking is one case."""
        from ...mining.playout import play_out
        count, ok = QInputDialog.getInt(self, "Generate event log",
                                        "Number of cases to simulate:", 100, 1, 100_000, 50)
        if not ok:
            return
        petri = self.petri_net()
        if not petri.initial_marking:
            workflow = check_workflow_net(petri)
            if workflow.is_workflow_net:
                petri.initial_marking = Marking({workflow.source: 1})

        def done(result) -> None:
            self.status.emit(f"Generated {len(result.log):,} cases: {result.completed:,} "
                             f"completed, {result.deadlocked:,} deadlocked")
            self.log_generated.emit(result.log)

        run_in_background(lambda: play_out(petri, traces=count,
                                           name=f"Play-out · {self.net.name}"),
                          done, lambda m: self.status.emit(f"Play-out failed: {m}"))

    # =====================================================================
    # Status, titles, files
    # =====================================================================
    def _fill_problems(self) -> None:
        pass

    def _update_sim_status(self) -> None:
        if not self.simulating:
            workflow = check_workflow_net(self.petri_net())
            self.sim_status.setText("WF-net ✓" if workflow.is_workflow_net else
                                    "not (yet) a WF-net")
            return
        enabled = len(getattr(self, "enabled_elements", []))
        state = f"{enabled} enabled" if enabled else "✕ dead: nothing is enabled"
        self.sim_status.setText(f"Step {self.simulator.step_count:,} · {state}")
        self.back_button.setEnabled(bool(self.simulator.log))
        self.step_button.setEnabled(bool(enabled))

    def _subtitle(self) -> str:
        places = sum(1 for _ in self.net.all_places())
        transitions = sum(1 for _ in self.net.all_transitions())
        where = Path(self.document.path).name if self.document.path else "not saved yet"
        state = " · edited" if self.document.dirty else ""
        return (f"Petri net · {places} places · {transitions} transitions · "
                f"{where}{state}")

    def export(self) -> bool:
        suggested = self.document.path or f"{self.net.name}.pnml"
        if suggested.lower().endswith(".cpn"):
            suggested = suggested[:-4] + ".pnml"
        path, chosen = QFileDialog.getSaveFileName(
            self, "Save Petri net", suggested,
            "PNML Petri net (*.pnml);;CPN Tools model (*.cpn)")
        if not path:
            return False
        if not path.lower().endswith((".pnml", ".cpn")):
            path += ".cpn" if "cpn" in chosen.lower() and "pnml" not in chosen.lower() \
                else ".pnml"
        return self._write(Path(path))

    def _write(self, path: Path) -> bool:
        if path.suffix.lower() == ".cpn":
            return super()._write(path)
        try:
            write_pnml(self.petri_net(), path)
        except Exception as error:  # noqa: BLE001
            QMessageBox.critical(self, "Could not save the net", str(error))
            return False
        self.document.path = str(path)
        self.set_dirty(False)
        self.status.emit(f"Saved {path.name}")
        self.saved.emit()
        return True
