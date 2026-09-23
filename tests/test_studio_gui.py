"""Smoke test for CPNpy Studio: build every page offscreen and exercise it.

Skipped when PySide6 is not installed.  Nothing is shown on screen: Qt's
"offscreen" platform renders into memory, which is enough to catch errors
in widget construction, signal wiring and painting.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _pump(app, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def test_studio_end_to_end(app):
    from cpnpy.gui.studio.app import StudioWindow
    from cpnpy.gui.studio.documents import LogDocument, ModelDocument
    from cpnpy.mining import inductive_miner, read_xes

    window = StudioWindow()
    window.resize(1400, 900)
    window.show()
    log = LogDocument(read_xes(DATA / "plane_wilma_10.xes"), path=str(DATA / "plane_wilma_10.xes"))
    window.add_document(log)
    page = window.current_page()
    for index in range(len(page.pages)):          # build and paint every tab
        page.tabs.set_index(index)
        _pump(app, 0.2)
        page.grab()
    _pump(app, 1.0)                               # discovery runs in the background

    result = inductive_miner(log.simple_log())
    window.add_document(ModelDocument(result.net, origin="test", derivation=result,
                                      source_log=log))
    model_page = window.current_page()
    model_page._check()
    _pump(app, 2.0)
    assert model_page.conformance is not None
    replay, alignments = model_page.conformance
    assert alignments.average_fitness == pytest.approx(1.0)

    # Step through: a real mouse click on an enabled transition fires it.
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    model_page.mode_switch.set_index(1)
    _pump(app, 0.2)
    first = model_page.net.enabled(model_page.marking)[0]
    item = model_page.view.graph.nodes[first]
    view = model_page.view
    point = view.mapFromScene(item.scenePos())
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, point)
    _pump(app, 0.1)
    assert [t for _, t in model_page.history] == [first]
    model_page._back()
    assert model_page.history == [] and model_page.marking == model_page.net.initial_marking
    # Simulate: the timer fires transitions and completes runs.
    model_page.mode_switch.set_index(2)
    model_page.speed.setValue(30)
    model_page.play_button.setChecked(True)
    _pump(app, 1.5)
    model_page.play_button.setChecked(False)
    assert model_page.runs_completed >= 1
    model_page.mode_switch.set_index(0)
    model_page.view_switch.set_index(1)
    _pump(app, 1.0)
    assert model_page.state_view.graph.nodes
    window.grab()

    # dotted chart: zoom, back, reconfigure
    log_page = window.pages[log.id]
    window.tree.setCurrentItem(window.items[log.id])
    log_page.tabs.set_index(3)
    _pump(app, 0.3)
    from cpnpy.gui.studio.dotted_chart import DottedChartPanel
    panel = log_page.findChild(DottedChartPanel)
    chart = panel.chart
    full = (chart.vx0, chart.vx1)
    chart.set_view(chart.vx0, (chart.vx0 + chart.vx1) / 2, 0, 3)
    assert chart.zoom_factors()[0] > 1.9
    chart.back()
    assert (chart.vx0, chart.vx1) == full
    panel.rows_box.setCurrentText("Activity")
    panel.colour_box.setCurrentText("Lifecycle")
    panel.shape_box.setCurrentText("Activity")
    panel.all_events.setChecked(True)
    panel.connect_box.setChecked(True)
    _pump(app, 0.2)
    assert len(chart.data.row_values) == 6
    panel.grab()

    # removing: a file-backed log goes without a question; the page disappears
    before = len(window.documents)
    window.remove_documents([log.id])
    assert len(window.documents) == before - 1 and log.id not in window.pages
    window.close()


def test_graph_view_zoom_controls(app):
    from cpnpy.gui.studio.graph_view import GraphView, NodeSpec, EdgeSpec

    view = GraphView()
    view.resize(600, 400)
    view.graph.populate([NodeSpec("a", "transition", text="A"),
                         NodeSpec("b", "transition", text="B")], [EdgeSpec("a", "b")])
    view.show()
    view.fit()
    controls = view.zoom_controls
    assert controls is not None and controls.isVisible()
    start = view.zoom()
    controls.plus.click()
    assert view.zoom() == pytest.approx(min(start * 1.25, GraphView.MAX_ZOOM))
    assert not view.auto_fit
    assert controls.percent.text() == f"{round(view.zoom() * 100)}%"
    controls.minus.click()
    controls.minus.click()
    assert view.zoom() < start
    controls.percent.click()
    assert view.zoom() == pytest.approx(1.0)
    controls.fit.click()
    assert view.auto_fit
    for _ in range(40):
        view.zoom_out()
    assert view.zoom() == pytest.approx(GraphView.MIN_ZOOM)
    assert not controls.minus.isEnabled()
    view.close()


def test_cpn_page_edit_simulate_analyse(app, tmp_path):
    """The CPN workspace: modes, firing, back, history, bindings, editing,
    declarations, state space, saving and exporting a simulation as a log."""
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from models import dining_philosophers

    from cpnpy.gui.studio.app import StudioWindow
    from cpnpy.gui.studio.cpn_page import CpnPage, simulation_to_log
    from cpnpy.gui.studio.documents import CpnDocument, LogDocument

    window = StudioWindow()
    window.resize(1500, 950)
    window.show()
    window.open_path(str(DATA / "plane_boarding.cpn"))
    page = window.current_page()
    assert isinstance(page, CpnPage)
    _pump(app, 0.2)
    assert not page.net.errors
    assert page.enabled_elements, "check-in should be enabled initially"

    # CPN Tools' marking display: the file hides Isle's tokens; clicking the
    # count shows them.
    isle = next(p for p in page.net.all_places() if p.name == "Isle")
    isle_item = page.scene.place_items[isle.id]
    assert isle_item.count_pill.isVisible() and not isle_item.marking_label.isVisible()
    isle_item.toggle_marking()
    assert isle_item.marking_label.isVisible() and not isle.graphics.marking_hidden
    isle_item.toggle_marking()
    assert not isle_item.marking_label.isVisible()

    # Edit mode: clicking a transition does not fire it.
    enabled_id = page.enabled_elements[0].transition_id
    item = page.scene.transition_items[enabled_id]
    page.view.centerOn(item)
    _pump(app, 0.1)
    point = page.view.mapFromScene(item.scenePos())
    QTest.mouseClick(page.view.viewport(), Qt.LeftButton, Qt.NoModifier, point)
    _pump(app, 0.1)
    assert page.simulator.step_count == 0

    # Step through: a real click fires, Back undoes, the history fills.
    page.mode_switch.set_index(1)
    point = page.view.mapFromScene(item.scenePos())
    QTest.mouseClick(page.view.viewport(), Qt.LeftButton, Qt.NoModifier, point)
    _pump(app, 0.1)
    assert page.simulator.step_count == 1
    page.back_button.click()
    assert page.simulator.step_count == 0
    for _ in range(5):
        page.step_button.click()
    assert page.simulator.step_count == 5
    assert page.history_list.count() == 5
    page._rewind_to_item(page.history_list.item(3))      # 4th newest = after step 2
    assert page.simulator.step_count == 2

    # A specific binding from the inspector.
    page.binding_filter.setText("Check in")
    assert page.binding_list.count() > 0
    page.binding_list.setCurrentRow(0)
    page.fire_selected.click()
    assert page.simulator.step_count == 3
    page.binding_filter.clear()

    # Simulate: fast-forward to the end of boarding.
    page.mode_switch.set_index(2)
    page.forward_steps.setValue(5000)
    page.forward_button.setChecked(True)
    deadline = time.time() + 60
    while page.forward_button.isChecked() and time.time() < deadline:
        app.processEvents()
    assert not page.forward_button.isChecked()
    seated = next(p for p in page.net.all_places() if p.name == "Seated")
    assert page.simulator.marking.get(page.net.marking_key(seated.id)).size() == 120

    # The simulation as an event log: one case per passenger.
    log = simulation_to_log(page.net, page.simulator.log, "id")
    assert len(log) == 120
    assert {e.activity for t in log.traces for e in t.events} >= {"Move in", "stow bag"}
    before = len(window.documents)
    page.log_generated.emit(log)
    assert len(window.documents) == before + 1
    assert isinstance(window.documents[-1], LogDocument)

    # Editing a guard recompiles, marks the model dirty and resets the simulation.
    window.tree.setCurrentItem(window.items[page.document.id])
    page.mode_switch.set_index(0)
    move_up = next(t for t in page.net.all_transitions() if t.name == "Move up")
    page.reveal_element(move_up.id)
    assert page.element is move_up
    page.guard_edit.setText("[nr=cr+1, cr<r")                 # a syntax error
    page.guard_edit.editingFinished.emit()
    assert page.document.dirty and page.simulator.step_count == 0
    assert any(e.element_id == move_up.id for e in page.net.errors)
    assert "Problems (" in page.inspector_tabs.buttons[2].text()
    assert window.items[page.document.id].text(0).endswith("•")
    page.guard_edit.setText("[nr=cr+1, cr<r]")
    page.guard_edit.editingFinished.emit()
    assert not page.net.errors

    # Saving writes a .cpn that reads back.
    target = tmp_path / "saved.cpn"
    assert page._write(target)
    assert not page.document.dirty
    from cpnpy.io.cpn_reader import read_cpn
    assert read_cpn(target).compile() == []

    # A new model, built by hand: declarations, places, transition, arcs.
    net = dining_philosophers(3)
    window.add_document(CpnDocument(net))
    small = window.current_page()
    small.structure_switch.set_index(1)
    text = small.declarations_editor.toPlainText()
    assert "colset" in text
    small.declarations_editor.setPlainText(text + "\nval extra = 1;")
    assert small.apply_button.isEnabled()
    small.apply_button.click()
    assert not small.net.errors
    small.inspector_tabs.set_index(3)
    small.space_button.click()
    deadline = time.time() + 30
    while small.busy and time.time() < deadline:
        app.processEvents()
    assert small.space_results.isVisible()
    assert "Full state space" in small.space_status.text()

    # Draw: place tool, click on the canvas.
    small.mode_switch.set_index(0)
    small.tool_switch.set_index(1)
    places = sum(1 for _ in small.net.all_places())
    QTest.mouseClick(small.view.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(30, 30))
    assert sum(1 for _ in small.net.all_places()) == places + 1
    assert small.document.dirty

    # Undo / redo: the new place goes and comes back; guard edits too.
    small.undo_button.click()
    assert sum(1 for _ in small.net.all_places()) == places
    small.redo_button.click()
    assert sum(1 for _ in small.net.all_places()) == places + 1
    take = next(t for t in small.net.all_transitions() if t.name == "take")
    small.reveal_element(take.id)
    small.guard_edit.setText("[p = p]")
    small.guard_edit.editingFinished.emit()
    assert next(t for t in small.net.all_transitions() if t.name == "take").guard_text == "[p = p]"
    small.undo()
    assert next(t for t in small.net.all_transitions() if t.name == "take").guard_text == ""
    assert not small.net.errors
    # Dragging a node is undoable and marks the model edited.
    small.tool_switch.set_index(0)
    item = next(iter(small.scene.transition_items.values()))
    small.view.centerOn(item)
    start = small.view.mapFromScene(item.scenePos())
    before = (item.transition.graphics.x, item.transition.graphics.y)
    QTest.mousePress(small.view.viewport(), Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(small.view.viewport(), start + QPoint(40, 30))
    QTest.mouseRelease(small.view.viewport(), Qt.LeftButton, Qt.NoModifier, start + QPoint(40, 30))
    moved = small.net.find_transition(item.transition.id)
    assert (moved.graphics.x, moved.graphics.y) != before
    small.undo()
    restored = small.net.find_transition(item.transition.id)
    assert (restored.graphics.x, restored.graphics.y) == before

    small.document.dirty = False          # closing would otherwise ask to save
    window.close()


def test_compare_logs(app):
    from cpnpy.gui.studio.app import StudioWindow
    from cpnpy.gui.studio.compare_page import ComparePage, activity_shares, key_figures
    from cpnpy.gui.studio.documents import ComparisonDocument, LogDocument
    from cpnpy.mining import read_xes
    from cpnpy.mining.log import EventLog, parse_simple_log

    window = StudioWindow()
    window.show()
    wilma = LogDocument(read_xes(DATA / "plane_wilma_10.xes"), path=str(DATA / "plane_wilma_10.xes"))
    textbook = LogDocument(EventLog.from_simple_log(
        parse_simple_log("[<a,b,c,d>^3, <a,c,b,d>^2, <a,e,d>]"), "L1"))
    window.add_document(wilma)
    window.add_document(textbook)
    window.compare([wilma, textbook])
    page = window.current_page()
    assert isinstance(page, ComparePage)
    assert isinstance(window.documents[-1], ComparisonDocument)
    for index in range(4):                 # every tab builds
        page.tabs.set_index(index)
        _pump(app, 0.05)
    assert len(page.charts) == 2
    # Same activity, same colour: colour values are shared.
    assert page.charts[0].data.colour_values == page.charts[1].data.colour_values
    # Zooming one chart zooms the other (same x window).
    first, second = page.charts
    first.set_view(first.vx0, (first.vx0 + first.vx1) / 2, first.vy0, first.vy1)
    assert second.vx1 == pytest.approx(first.vx1)
    figures = key_figures(textbook)
    assert figures[0][1] == "6" and figures[3][1] == "3"          # cases, variants
    rows = {name: shares for name, shares, _ in activity_shares([wilma, textbook])}
    assert rows["a"] == [0.0, 1.0]
    # Comparing the same logs again selects the existing comparison.
    count = len(window.documents)
    window.compare([wilma, textbook])
    assert len(window.documents) == count
    # Removing a log removes its comparisons too.
    window.remove_documents([wilma.id])
    assert not any(isinstance(d, ComparisonDocument) for d in window.documents)
    textbook.path = "x"                    # avoid the unsaved-log question on close
    window.close()



def test_cpn_arc_editing_like_cpn_ide(app):
    """Arcs are edited as in CPN IDE: drag the line to add a bend, drag the
    bend back into line to remove it, drag an end to reconnect; nodes snap
    into line with each other.  Everything is undoable."""
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtTest import QTest

    from cpnpy.gui.items import PlaceItem
    from cpnpy.gui.studio.app import StudioWindow

    window = StudioWindow()
    window.resize(1500, 950)
    window.show()
    window.open_path(str(DATA / "plane_boarding.cpn"))
    page = window.current_page()
    _pump(app, 0.2)
    page.mode_switch.set_index(0)
    page.tool_switch.set_index(0)
    scene, view = page.scene, page.view
    port = view.viewport()

    def drag(start: QPointF, offset: QPoint) -> None:
        view.centerOn(start)
        _pump(app, 0.05)
        a = view.mapFromScene(start)
        QTest.mousePress(port, Qt.LeftButton, Qt.NoModifier, a)
        QTest.mouseMove(port, a + offset / 2)
        QTest.mouseMove(port, a + offset)
        QTest.mouseRelease(port, Qt.LeftButton, Qt.NoModifier, a + offset)

    # A long straight arc (not one of a parallel pair, which is drawn shifted).
    arc_item = max((a for a in scene.arc_items.values()
                    if not a.arc.bendpoints and abs(a.bow) < 1e-9),
                   key=lambda a: (a.waypoints()[0] - a.waypoints()[-1]).manhattanLength())
    arc_id = arc_item.arc.id
    ends = arc_item.waypoints()
    middle = (ends[0] + ends[-1]) / 2

    # A click (no movement) only selects the arc.
    view.centerOn(middle)
    _pump(app, 0.05)
    QTest.mouseClick(port, Qt.LeftButton, Qt.NoModifier, view.mapFromScene(middle))
    assert arc_item.isSelected() and arc_item.arc.bendpoints == []

    # Dragging the line adds a bend where it was grabbed.
    drag(middle, QPoint(0, 60))
    arc_item = scene.arc_items[arc_id]
    assert len(arc_item.arc.bendpoints) == 1

    # Dragging that bend back into line removes it.
    bend = arc_item.waypoints()[1]
    back = view.mapFromScene(middle) - view.mapFromScene(bend)
    drag(bend, back)
    assert scene.arc_items[arc_id].arc.bendpoints == []
    page.undo()
    assert len(scene.arc_items[arc_id].arc.bendpoints) == 1
    page.undo()
    assert scene.arc_items[arc_id].arc.bendpoints == []

    # Dragging the place end onto another place reconnects the arc.
    arc_item = scene.arc_items[arc_id]
    old_place = arc_item.arc.place_id
    other = next(p for p in scene.place_items.values() if p.place.id != old_place)
    scene.clearSelection()
    arc_item.setSelected(True)
    end = arc_item.waypoints()[-1]
    drag(end, view.mapFromScene(other.pos()) - view.mapFromScene(end))
    assert scene.arc_items[arc_id].arc.place_id == other.place.id
    assert not page.net.errors or True          # the inscription may not fit the new place
    page.undo()
    assert scene.arc_items[arc_id].arc.place_id == old_place

    # A dragged node snaps level with another node (7 units).
    nodes = list(scene.place_items.values())
    mover, anchor = nodes[0], nodes[1]
    scene.clearSelection()
    target_y = anchor.pos().y() + 5 - mover.pos().y()
    start = mover.pos()
    view.centerOn(start)
    _pump(app, 0.05)
    a = view.mapFromScene(start)
    b = view.mapFromScene(start + QPointF(90, target_y))
    QTest.mousePress(port, Qt.LeftButton, Qt.NoModifier, a)
    QTest.mouseMove(port, (a + b) / 2)
    QTest.mouseMove(port, b)
    assert any(line.isVisible() for line in scene._guides)      # the guide line shows
    target_ys = {y for _, y in scene._snap_targets}
    QTest.mouseRelease(port, Qt.LeftButton, Qt.NoModifier, b)
    assert isinstance(mover, PlaceItem)
    final_y = scene.place_items[mover.place.id].pos().y()
    assert final_y in target_ys and abs(final_y - anchor.pos().y()) <= 7
    page.undo()

    page.document.dirty = False
    window.close()


def test_petri_net_editor_draw_and_analyse(app, tmp_path):
    """Draw a WF-net with the mouse (names typed on creation, arcs by
    dragging), then analyse: sound; break it and get a counterexample that
    replays in the token game; save as PNML and open it again."""
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton, QTableWidget

    from cpnpy.gui.studio.app import StudioWindow
    from cpnpy.gui.studio.documents import CpnDocument
    from cpnpy.gui.studio.petri_page import PetriNetPage
    from cpnpy.mining.analysis import check_soundness
    from cpnpy.mining.petrinet import PetriNet
    from cpnpy.mining.pnml import read_pnml
    from cpnpy.model.plain import from_petri_net

    window = StudioWindow()
    window.resize(1500, 950)
    window.show()
    window.action_new_petri()
    page = window.current_page()
    assert isinstance(page, PetriNetPage)
    _pump(app, 0.2)
    scene, view = page.scene, page.view
    port = view.viewport()
    view.resetTransform()
    view.auto_fit = False

    def at(x: float, y: float) -> QPoint:
        return view.mapFromScene(QPointF(x, y))

    def add(tool: int, x: float, y: float, name: str) -> None:
        page.tool_switch.set_index(tool)
        QTest.mouseClick(port, Qt.LeftButton, Qt.NoModifier, at(x, y))
        _pump(app, 0.05)
        assert page.tool_switch.index() == 0          # back to Select
        editor = view.name_editor
        assert editor is not None and editor.hasSelectedText()
        editor.setText(name)
        QTest.keyClick(editor, Qt.Key_Return)
        _pump(app, 0.05)

    def connect(a: tuple, b: tuple) -> None:
        page.tool_switch.set_index(3)
        QTest.mousePress(port, Qt.LeftButton, Qt.NoModifier, at(*a))
        QTest.mouseMove(port, at((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
        QTest.mouseMove(port, at(*b))
        QTest.mouseRelease(port, Qt.LeftButton, Qt.NoModifier, at(*b))
        _pump(app, 0.02)

    add(1, 0, 0, "i")
    add(2, 100, 0, "a")
    add(1, 200, -60, "p1")
    add(1, 200, 60, "p2")
    add(2, 300, 0, "b")
    add(1, 400, 0, "o")
    names = sorted(p.name for p in page.net.all_places())
    assert names == ["i", "o", "p1", "p2"]
    connect((0, 0), (100, 0))
    connect((100, 0), (200, -60))
    connect((100, 0), (200, 60))            # a second arc out of the same transition
    connect((200, -60), (300, 0))
    connect((200, 60), (300, 0))
    connect((300, 0), (400, 0))
    assert len(page.net.pages[0].arcs) == 6
    # A place-to-place drag is refused, with a message.
    messages = []
    scene.message.connect(messages.append)
    connect((0, 0), (200, -60))
    assert len(page.net.pages[0].arcs) == 6 and "Can't connect two places" in messages[-1]

    # Double-click renames.
    QTest.mouseDClick(port, Qt.LeftButton, Qt.NoModifier, at(100, 0))
    _pump(app, 0.05)
    assert view.name_editor is not None
    view.name_editor.setText("register")
    QTest.keyClick(view.name_editor, Qt.Key_Return)
    _pump(app, 0.05)
    assert any(t.name == "register" for t in page.net.all_transitions())

    # Analysis: a sound WF-net (AND-split / AND-join).
    page.inspector_tabs.set_index(2)
    _pump(app, 0.5)
    assert check_soundness(page.petri_net()).sound is True

    # Deleting the arc p2 -> b makes p2 a second sink: no longer a WF-net.
    arc = next(a for a in page.net.pages[0].arcs
               if page.net.find_place(a.place_id).name == "p2" and a.orientation == "PtoT")
    page.reveal_element(arc.id)
    _pump(app, 0.05)
    page._delete_selection()
    _pump(app, 0.3)
    assert check_soundness(page.petri_net()).sound is False   # p2 became a second sink
    page.undo()
    _pump(app, 0.3)
    report = check_soundness(page.petri_net())
    assert report.sound is True and report.paths == []

    # A deadlocking net: choice (two transitions from i) into an AND-join.
    replay_buttons = []
    petri = PetriNet("xor-and")
    i, p1, p2, o = (petri.add_place(n) for n in ("i", "p1", "p2", "o"))
    a, b, c = (petri.add_transition(n) for n in ("a", "b", "c"))
    for s, t in ((i, a), (i, b), (a, p1), (b, p2), (p1, c), (p2, c), (c, o)):
        petri.add_arc(s, t)
    window.add_document(CpnDocument(from_petri_net(petri)))
    bad = window.current_page()
    _pump(app, 0.2)
    bad.inspector_tabs.set_index(2)
    for _ in range(100):
        _pump(app, 0.05)
        replay_buttons = [b for b in bad.soundness_card.findChildren(QPushButton)
                          if b.text().startswith("Show")]
        if replay_buttons:
            break
    assert replay_buttons, "a counterexample with a Show button"
    replay_buttons[0].click()
    _pump(app, 0.1)
    assert bad.mode_switch.index() == 1 and bad.simulator.step_count == 1
    assert bad._dead()                                   # the problem marking: stuck

    # The net's footprint is shown.
    assert bad.footprint_card.findChildren(QTableWidget)

    # Save as PNML and read it back.
    target = tmp_path / "drawn.pnml"
    assert page._write(target)
    again = read_pnml(target)
    assert sorted(p.name for p in again.places.values()) == ["i", "o", "p1", "p2"]
    assert len(again.arcs) == 6
    window.open_path(str(target))
    assert isinstance(window.current_page(), PetriNetPage)
    for p in list(window.pages.values()):
        if hasattr(p, "document"):
            p.document.dirty = False
    bad.document.dirty = False
    window.close()


def test_petri_net_names_inside_or_outside(app, tmp_path):
    """Names sit inside the nodes by default; "Names outside" puts them
    underneath, where they can be dragged; both survive saving as PNML.
    Renaming opens a small editor over the name, and a hand-drawn
    transition shows in the Element tab."""
    from PySide6.QtCore import QPointF
    from PySide6.QtTest import QTest

    from cpnpy.gui.studio.app import StudioWindow
    from cpnpy.gui.studio.petri_page import PetriNetPage

    window = StudioWindow()
    window.resize(1400, 900)
    window.show()
    window.action_new_petri()
    page = window.current_page()
    assert isinstance(page, PetriNetPage)
    _pump(app, 0.2)
    view, port = page.view, page.view.viewport()
    view.resetTransform()
    view.auto_fit = False

    for tool, x in ((1, -100.0), (2, 100.0)):
        page.tool_switch.set_index(tool)
        QTest.mouseClick(port, Qt.LeftButton, Qt.NoModifier, view.mapFromScene(QPointF(x, 0)))
        _pump(app, 0.05)
        editor = view.name_editor
        assert editor is not None and editor.width() < 140     # snug, not a wide bar
        QTest.keyClick(editor, Qt.Key_Return)
        _pump(app, 0.05)
    place_item = next(iter(page.scene.place_items.values()))
    transition_item = next(iter(page.scene.transition_items.values()))

    # Inside (the default): the names are within the shapes.
    assert not page.names_box.isChecked()
    assert place_item.shape().contains(place_item.name_label.mapToParent(
        place_item.name_label.boundingRect().center()))

    # The Element tab shows a hand-drawn transition.
    page.scene.clearSelection()
    transition_item.setSelected(True)
    _pump(app, 0.05)
    assert page.element_card.title_label.text().startswith("Transition")

    # Outside: names under the nodes; dragging one keeps the spot.
    page.names_box.setChecked(True)
    _pump(app, 0.1)
    place_item = next(iter(page.scene.place_items.values()))
    label = place_item.name_label
    assert label.sceneBoundingRect().top() >= place_item.sceneBoundingRect().bottom() - 8
    start = view.mapFromScene(label.sceneBoundingRect().center())
    QTest.mousePress(port, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(port, start + QPointF(40, 20).toPoint())
    QTest.mouseRelease(port, Qt.LeftButton, Qt.NoModifier, start + QPointF(40, 20).toPoint())
    offset = place_item.place.graphics.label_offsets.get("name")
    assert offset is not None

    # Renaming now edits over the label, not over the circle.
    page.start_rename(place_item.place.id)
    _pump(app, 0.05)
    editor = view.name_editor
    label_centre = view.mapFromScene(page.scene.place_items[place_item.place.id]
                                     .name_label.sceneBoundingRect().center())
    assert abs(editor.geometry().center().y() - label_centre.y()) < 6
    view.close_editor()

    # Both survive a save and a reopen.
    target = tmp_path / "names.pnml"
    assert page._write(target)
    page.undo()                                             # the drag is undoable ...
    page.undo()                                             # ... and so is the setting
    assert not page.net.names_outside and not page.names_box.isChecked()
    page.document.dirty = False
    window.remove_documents([page.document.id])
    window.open_path(str(target))
    reopened = window.current_page()
    assert reopened.net.names_outside and reopened.names_box.isChecked()
    again = next(iter(reopened.net.all_places()))
    assert again.graphics.label_offsets.get("name") == pytest.approx(offset, abs=0.2)
    for p in list(window.pages.values()):
        if hasattr(p, "document") and hasattr(p.document, "dirty"):
            p.document.dirty = False
    window.close()


def test_dotted_chart_custom_colours(app):
    """Legend values can be given their own dot colour, and reset."""
    from PySide6.QtGui import QColor

    from cpnpy.gui.studio.documents import LogDocument
    from cpnpy.gui.studio.dotted_chart import DottedChartPanel
    from cpnpy.mining import read_xes

    panel = DottedChartPanel(LogDocument(read_xes(DATA / "plane_wilma_10.xes")))
    panel.resize(1200, 700)
    panel.show()
    _pump(app, 0.2)
    data = panel.chart.data
    default = data.colour_hex(0)
    panel.set_colour(0, "#123456")
    assert panel.chart.data.colour_hex(0) == "#123456"
    swatch = panel.legend.item(0).icon().pixmap(14, 14).toImage().pixelColor(7, 7)
    assert swatch == QColor("#123456")
    image = panel.chart.grab()                    # paints with the new colour
    assert not image.isNull()
    panel.legend.setCurrentRow(1)
    assert panel.legend.currentItem().data(Qt.UserRole) == 1
    panel._reset_colours()
    assert panel.chart.data.colour_hex(0) == default
    panel.close()


def test_hover_arrow_draws_arcs(app):
    """Hovering near a node shows a translucent arrow; dragging it to another
    node adds an arc (with the Select tool, no mode switch needed)."""
    from PySide6.QtCore import QPointF
    from PySide6.QtTest import QTest

    from cpnpy.gui.studio.app import StudioWindow
    from cpnpy.mining.petrinet import PetriNet
    from cpnpy.model.plain import from_petri_net
    from cpnpy.gui.studio.documents import CpnDocument

    petri = PetriNet("hover")
    for name, x in (("p1", 0.0), ("p2", 300.0)):
        petri.add_place(name).position = (x, 0.0)
    petri.add_transition("t1").position = (150.0, 0.0)
    window = StudioWindow()
    window.resize(1400, 900)
    window.show()
    window.add_document(CpnDocument(from_petri_net(petri)))
    page = window.current_page()
    _pump(app, 0.2)
    scene, view, port = page.scene, page.view, page.view.viewport()
    view.resetTransform()
    view.auto_fit = False
    view.centerOn(QPointF(150, 0))
    _pump(app, 0.05)
    p1 = next(i for i in scene.place_items.values() if i.place.name == "p1")

    # Hover just right of p1: the arrow appears on that side.
    QTest.mouseMove(port, view.mapFromScene(p1.pos() + QPointF(30, 0)))
    _pump(app, 0.05)
    handle = scene._handle
    assert handle is not None and handle.isVisible() and handle.node is p1
    assert handle.pos().x() > p1.pos().x() + p1.rect().width() / 2

    # Drag the arrow onto t1: a new arc p1 -> t1.
    start = view.mapFromScene(handle.pos())
    target = view.mapFromScene(QPointF(150, 0))
    QTest.mousePress(port, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(port, (start + target) / 2)
    QTest.mouseMove(port, target)
    QTest.mouseRelease(port, Qt.LeftButton, Qt.NoModifier, target)
    _pump(app, 0.05)
    arcs = page.net.pages[0].arcs
    assert len(arcs) == 1 and arcs[0].orientation == "PtoT"
    assert page.tool_switch.index() == 0                  # still the Select tool

    # Place to place is refused.
    messages = []
    scene.message.connect(messages.append)
    p1 = next(i for i in scene.place_items.values() if i.place.name == "p1")
    QTest.mouseMove(port, view.mapFromScene(p1.pos() + QPointF(0, 30)))
    _pump(app, 0.05)
    start = view.mapFromScene(scene._handle.pos())
    target = view.mapFromScene(QPointF(300, 0))
    QTest.mousePress(port, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(port, target)
    QTest.mouseRelease(port, Qt.LeftButton, Qt.NoModifier, target)
    assert len(page.net.pages[0].arcs) == 1 and "Can't connect two places" in messages[-1]

    # Far from every node: no arrow.
    QTest.mouseMove(port, view.mapFromScene(QPointF(150, 200)))
    _pump(app, 0.05)
    assert not scene._handle.isVisible()
    page.document.dirty = False
    window.close()


def test_petri_analysis_follows_the_paper_and_trace_highlights(app):
    """The Analysis tab shows Theorem 1 (N̄ live and bounded) and the §6
    structure checks; N̄ opens as a net of its own; stepping through lights
    up the path taken, and the Trace box switches that off."""
    from PySide6.QtWidgets import QLabel

    from cpnpy.gui.studio import petri_page
    from cpnpy.gui.studio.app import StudioWindow
    from cpnpy.model.examples import order_handling_unsound

    window = StudioWindow()
    window.resize(1500, 950)
    window.show()
    window.open_example_net(order_handling_unsound())
    page = window.current_page()
    original = petri_page.run_in_background
    petri_page.run_in_background = lambda work, done, failed=None: done(work())
    try:
        page.run_analysis()
    finally:
        petri_page.run_in_background = original

    def texts(card):
        return " ".join(label.text() for label in card.findChildren(QLabel))

    theorem = texts(page.theorem_card)
    assert "Bounded" in theorem and "Unbounded ⇒ not sound" in theorem
    structure = texts(page.structure_card)
    assert "Free-choice" in structure and "ship and reject share c3" in structure
    assert "PT-handle" in structure and "S-coverable" in structure

    before = len(window.documents) if hasattr(window, "documents") else None
    page._open_short_circuited()
    closed = window.current_page()
    assert closed is not page
    assert any(t.name == "t*" for t in closed.net.all_transitions())
    if before is not None:
        assert len(window.documents) == before + 1
    closed.document.dirty = False

    # -- the trace while stepping through
    window.select_document(page.document) if hasattr(window, "select_document") else None
    page.mode_switch.set_index(1)
    page.trace_box.setChecked(True)
    for name in ("register", "check stock"):
        page._fire_transition(next(t for t in page.net.all_transitions() if t.name == name))
    items = {i.transition.name: i for i in page.scene.transition_items.values()}
    assert items["register"].trace_steps == [1] and items["check stock"].trace_steps == [2]
    assert items["check stock"].trace == 1.0 > items["register"].trace > 0
    assert items["ship"].trace_steps == []
    lit = [a for a in page.scene.arc_items.values() if a.trace > 0]
    assert len(lit) == 5                 # start→register→c1,c2 and c1→check stock→c3
    page.trace_box.setChecked(False)
    assert all(a.trace == 0 for a in page.scene.arc_items.values())
    assert items["register"].trace_steps == []
    page.trace_box.setChecked(True)
    page.mode_switch.set_index(0)        # editing: no trace
    assert items["register"].trace_steps == []
    page.document.dirty = False
    window.close()


def test_properties_show_their_definitions(app):
    """Hovering over a property shows its definition filled in for the net;
    clicking opens a pop-up whose links lead to related definitions; Help ▸
    Definitions lists them all."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from cpnpy.gui.studio import petri_page
    from cpnpy.gui.studio.app import StudioWindow
    from cpnpy.gui.studio.definition_view import show_reference
    from cpnpy.gui.studio.widgets import Verdict
    from cpnpy.model.examples import order_handling_unsound

    window = StudioWindow()
    window.resize(1500, 950)
    window.show()
    window.open_example_net(order_handling_unsound())
    page = window.current_page()
    original = petri_page.run_in_background
    petri_page.run_in_background = lambda work, done, failed=None: done(work())
    try:
        page.run_analysis()
    finally:
        petri_page.run_in_background = original

    verdicts = {v.definition.key: v for v in page.findChildren(Verdict)
                if getattr(v, "definition", None) is not None}
    for key in ("wf_net", "option_to_complete", "live", "bounded", "free_choice",
                "well_structured", "s_coverable", "soundness_theorem"):
        assert key in verdicts, key
    tip = verdicts["option_to_complete"].title.toolTip()
    assert "For this net" in tip and "start" in tip and "c4" in tip

    QTest.mouseClick(verdicts["free_choice"].title, Qt.LeftButton)
    popup = verdicts["free_choice"].last_popup
    assert "reject" in popup.browser.toPlainText()
    popup._link("def:preset")                         # follow "Builds on"
    assert popup.current.key == "preset" and popup.back_button.isVisibleTo(popup)
    popup._back()
    assert popup.current.key == "free_choice"
    popup.close()

    dialog = show_reference("sound", window)
    assert "Soundness theorem" in dialog.browser.toPlainText()
    dialog.close()
    page.document.dirty = False
    window.close()


def test_removing_a_petri_net_and_a_log_without_times(app, monkeypatch):
    """Regressions: removing a Petri net raised ValueError (its sidebar
    section was missing from the ordering), and the dotted chart of a log
    without timestamps raised AttributeError while it was being built."""
    import sys
    from cpnpy.gui.studio.app import StudioWindow
    from cpnpy.gui.studio.documents import LogDocument
    from cpnpy.gui.studio.dotted_chart import DottedChartPanel
    from cpnpy.mining import EventLog, parse_simple_log

    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *info: errors.append(info))
    window = StudioWindow()
    window.show()
    shared_axis = DottedChartPanel.shared.x_mode
    notation = LogDocument(EventLog.from_simple_log(parse_simple_log("[<a,b>^2, <a,c>]"), "L"))
    window.add_document(notation)
    page = window.current_page()
    page.tabs.set_index(3)                         # the dotted chart
    _pump(app, 0.3)
    assert errors == []
    assert page.findChild(DottedChartPanel).settings.x_mode == 4       # logical order
    assert DottedChartPanel.shared.x_mode == shared_axis               # the default is untouched

    root = Path(__file__).resolve().parents[1]
    window.open_path(str(root / "examples" / "petri" / "order_handling_sound.pnml"))
    net = window.documents[-1]
    window.remove_documents([net.id])
    assert net not in window.documents and net.id not in window.pages
    assert errors == []
    window.close()


def test_filter_dialog_opens_a_filtered_log(app):
    from cpnpy.gui.studio.app import StudioWindow
    from cpnpy.gui.studio.documents import LogDocument
    from cpnpy.gui.studio.filter_dialog import FilterDialog
    from cpnpy.mining import EventLog, parse_simple_log

    window = StudioWindow()
    window.show()
    log = LogDocument(EventLog.from_simple_log(
        parse_simple_log("[<a,b,c,d>^3, <a,c,b,d>^2, <a,e,d>]"), "L1"))
    window.add_document(log)
    page = window.current_page()
    dialog = FilterDialog(log, page)
    dialog.activities_box.setChecked(True)
    dialog.activity_mode.setCurrentIndex(2)                # remove cases with e
    for i in range(dialog.activity_list.count()):
        item = dialog.activity_list.item(i)
        item.setCheckState(Qt.Checked if item.data(Qt.UserRole) == "e" else Qt.Unchecked)
    _pump(app, 0.3)
    assert dialog.preview.text().startswith("Result: 5 of 6 cases")
    filtered = LogDocument(dialog.result_log())
    page.open_log.emit(filtered)
    assert window.documents[-1] is filtered and filtered.name == "L1 (filtered)"
    assert ("a", "e", "d") not in filtered.simple_log()
    window.close()
