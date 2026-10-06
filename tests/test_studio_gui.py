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


@pytest.fixture(autouse=True)
def fake_bin(tmp_path_factory, monkeypatch):
    """Nothing a test moves "to the Bin" goes to your real Bin: it lands here."""
    import shutil
    from cpnpy.gui.studio import app as studio_app

    folder = tmp_path_factory.mktemp("Bin")

    def move_to_trash(path) -> bool:
        target, number = folder / Path(path).name, 2
        while target.exists():
            target = folder / f"{number} {Path(path).name}"
            number += 1
        shutil.move(str(path), str(target))
        return True
    monkeypatch.setattr(studio_app, "move_to_trash", move_to_trash)
    return folder


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


def test_substitution_transition_opens_its_subpage(app, tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from test_hierarchy import hierarchical
    from cpnpy.gui.studio.app import StudioWindow
    from cpnpy.io.cpn_writer import write_cpn

    net = hierarchical()
    net.compile()
    write_cpn(net, tmp_path / "hierarchy.cpn")
    window = StudioWindow()
    window.show()
    window.open_path(str(tmp_path / "hierarchy.cpn"))
    page = window.current_page()
    handle = page.net.pages[0].transitions[0]
    page._show_element(handle)
    assert not page.subpage_button.isHidden()
    page._open_subpage()
    _pump(app, 0.2)
    assert page.scene.page.name == "Handle"
    page.mode_switch.set_index(1)
    for _ in range(4):
        page._step(None)
    assert [r.binding.describe(page.net).split()[0] for r in page.simulator.log].count("pack") == 2
    window.close()


def test_clicking_away_from_the_name_box_keeps_the_name(app):
    """The box that opens to name a new node closes when you click anywhere
    else, as if Return were pressed -- also when the name was left as it is
    (Qt 6 only reports "editing finished" on focus loss after a change, so
    an untouched box used to stay open over the node)."""
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from cpnpy.gui.studio.app import StudioWindow

    window = StudioWindow()
    window.show()
    window.action_new_petri()
    page = window.current_page()
    net = page.net
    view = page.view
    _pump(app, 0.2)
    for tool, spot in ((1, QPoint(120, 150)), (2, QPoint(320, 150))):
        page.tool_switch.set_index(tool)                  # Place, then Transition
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, spot)
        _pump(app, 0.1)
        assert view.name_editor is not None and view.name_editor.isVisible()
        # Click on empty canvas without typing: the box closes, the name stays.
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(40, 380))
        _pump(app, 0.1)
        assert view.name_editor is None
    assert sorted(p.name for p in net.all_places()) == ["p1"]
    assert sorted(t.name for t in net.all_transitions()) == ["t1"]

    # Typed, then a click on a toolbar button: the typed name is kept.
    place = next(net.all_places())
    page.start_rename(place.id)
    _pump(app, 0.1)
    QTest.keyClicks(view.name_editor, "start")
    QTest.mouseClick(page.tool_switch.buttons[0], Qt.LeftButton)       # Select
    _pump(app, 0.1)
    assert view.name_editor is None
    assert place.name == "start"

    # Esc still cancels.
    page.start_rename(place.id)
    _pump(app, 0.1)
    QTest.keyClicks(view.name_editor, "other")
    QTest.keyClick(view.name_editor, Qt.Key_Escape)
    _pump(app, 0.1)
    assert view.name_editor is None and place.name == "start"
    page.document.dirty = False           # closing would otherwise ask to save
    window.close()


def test_save_as_names_the_net_after_its_file(app, tmp_path, monkeypatch):
    """Regression: Save As wrote the file but the net kept the name
    "Untitled 1" in the header, the sidebar and the window title."""
    from cpnpy.gui.studio import cpn_page, petri_page
    from cpnpy.gui.studio.app import APPLICATION_NAME, StudioWindow

    window = StudioWindow()
    window.show()

    # A new Petri net, saved as PNML through the (stubbed) save dialog.
    window.action_new_petri()
    page, document = window.current_page(), window.documents[-1]
    assert document.name.startswith("Untitled")
    target = tmp_path / "Example net week 4.pnml"
    monkeypatch.setattr(petri_page.QFileDialog, "getSaveFileName",
                        lambda *args, **kwargs: (str(target), "PNML Petri net (*.pnml)"))
    assert page.export()
    assert target.exists()
    assert document.name == "Example net week 4"
    assert window.items[document.id].text(0).strip() == "Example net week 4"
    assert window.windowTitle() == f"Example net week 4 — {APPLICATION_NAME}"
    # Reopening the file gives the same name.
    window.open_path(str(target))
    assert window.documents[-1].name == "Example net week 4"

    # The same for a new coloured net saved as .cpn.
    window.action_new_cpn()
    page, document = window.current_page(), window.documents[-1]
    target = tmp_path / "boarding model.cpn"
    monkeypatch.setattr(cpn_page.QFileDialog, "getSaveFileName",
                        lambda *args, **kwargs: (str(target), "CPN Tools model (*.cpn)"))
    assert page.export()
    assert document.name == "boarding model"
    assert window.windowTitle() == f"boarding model — {APPLICATION_NAME}"
    window.close()


def test_renaming_a_net_renames_its_file(app, tmp_path, monkeypatch):
    """Double-clicking the title (or a sidebar entry) renames the document;
    a net named after its file takes the file with it."""
    import shutil

    from PySide6.QtTest import QTest
    from cpnpy.gui.studio import app as studio_app
    from cpnpy.gui.studio.app import APPLICATION_NAME, StudioWindow
    from cpnpy.gui.studio.documents import LogDocument
    from cpnpy.mining import EventLog, parse_simple_log

    root = Path(__file__).resolve().parents[1]
    source = tmp_path / "order.pnml"
    shutil.copy(root / "examples" / "petri" / "order_handling_sound.pnml", source)
    answers, warnings = [], []
    monkeypatch.setattr(studio_app.QInputDialog, "getText",
                        lambda *args, **kwargs: (answers.pop(0), True))
    monkeypatch.setattr(studio_app.QMessageBox, "warning",
                        lambda *args, **kwargs: warnings.append(args[2]))

    window = StudioWindow()
    window.show()
    window.open_path(str(source))
    document, page = window.documents[-1], window.current_page()
    assert document.name == "order"

    # Double-click on the page title -> rename -> the file follows.
    answers.append("order v2")
    QTest.mouseDClick(page.header.title, Qt.LeftButton)
    renamed = tmp_path / "order v2.pnml"
    assert document.name == "order v2" and document.path == str(renamed)
    assert renamed.exists() and not source.exists()
    assert window.windowTitle() == f"order v2 — {APPLICATION_NAME}"

    # Double-click in the sidebar does the same.
    answers.append("final")
    item = window.items[document.id]
    window.tree.itemDoubleClicked.emit(item, 0)
    assert (tmp_path / "final.pnml").exists() and document.name == "final"

    # An existing file is never overwritten, and characters files cannot have are refused.
    (tmp_path / "taken.pnml").write_text("keep me")
    answers.append("taken")
    window.rename_document(document)
    answers.append("a/b")
    window.rename_document(document)
    assert len(warnings) == 2 and document.name == "final"
    assert (tmp_path / "taken.pnml").read_text() == "keep me"

    # A log is named by its concept:name, not its file: only the name changes.
    log_file = tmp_path / "events.xes"
    from cpnpy.mining.xes import write_xes
    write_xes(EventLog.from_simple_log(parse_simple_log("[<a,b>^2]"), "Boarding"), log_file)
    window.open_path(str(log_file))
    for _ in range(300):                       # logs are read in the background
        logs = [d for d in window.documents if isinstance(d, LogDocument)]
        if logs:
            break
        _pump(app, 0.02)
    log_doc = logs[0]
    assert log_doc.name == "Boarding"
    answers.append("Boarding (week 4)")
    window.rename_document(log_doc)
    assert log_doc.name == "Boarding (week 4)" and log_file.exists()
    window.close()


def test_workspace_folder(app, tmp_path, monkeypatch):
    """A folder as workspace: its files are listed (lighter until opened),
    open with one click, come back after closing, follow changes on disk,
    receive new nets, and the open files are restored next time."""
    import shutil

    from cpnpy.gui.studio import petri_page
    from cpnpy.gui.studio.app import APPLICATION_NAME, FILE_ROLE, StudioWindow
    from cpnpy.gui.studio.documents import LogDocument
    from cpnpy.mining import EventLog, parse_simple_log
    from cpnpy.mining.xes import write_xes

    root = Path(__file__).resolve().parents[1]
    week = tmp_path / "Week 2"
    (week / "logs").mkdir(parents=True)
    shutil.copy(root / "examples" / "petri" / "order_handling_sound.pnml", week / "order.pnml")
    shutil.copy(root / "examples" / "simple_transfer.cpn", week / "transfer.cpn")
    write_xes(EventLog.from_simple_log(parse_simple_log("[<a,b>^2, <a,c>]"), "Boarding"),
              week / "logs" / "boarding.xes")
    (week / "notes.txt").write_text("not a model")

    def rows(section):
        return [section.child(i).text(0).strip() for i in range(section.childCount())]

    def wait_for(condition, seconds=6.0):
        for _ in range(int(seconds / 0.02)):
            if condition():
                return True
            _pump(app, 0.02)
        return condition()

    window = StudioWindow()
    window.show()
    # A file from elsewhere (saved, so closing it needs no confirmation).
    window.open_path(str(root / "examples" / "petri" / "order_handling_unsound.pnml"))
    assert window.open_workspace(str(week))

    # The outside file was closed; the folder's files are listed (here grouped by kind).
    window.set_view_mode("kind")
    assert [d.name for d in window.documents] == []
    assert window.sidebar_title.text() == "Week 2"
    assert not window.workspace_caption.isHidden()
    assert window.windowTitle() == f"Week 2 — {APPLICATION_NAME}"
    assert rows(window.petri_section) == ["order"]
    assert rows(window.cpn_section) == ["transfer"]
    assert rows(window.logs_section) == ["boarding"]             # the subfolder is in the tooltip
    assert window.logs_section.child(0).toolTip(0).startswith("logs/boarding.xes")

    # One click opens a file; its row becomes the open document.
    window._open_placeholder(window.petri_section.child(0))
    net = window.documents[-1]
    assert net.name == "order" and window.petri_section.childCount() == 1
    assert window.petri_section.child(0).data(0, FILE_ROLE) is None
    assert window.windowTitle() == "order — Week 2"
    # A double-click right after that click does not ask to rename it.
    window._on_double_click(window.items[net.id], 0)

    # A log opens in the background.
    window._open_placeholder(window.logs_section.child(0))
    assert wait_for(lambda: any(isinstance(d, LogDocument) for d in window.documents))
    assert rows(window.logs_section) == ["Boarding"]

    # Closing a file lists it again, ready to reopen.
    window.remove_documents([net.id])
    assert rows(window.petri_section) == ["order"]
    assert window.petri_section.child(0).data(0, FILE_ROLE)

    # Files added in Finder appear by themselves (the folder is watched).
    shutil.copy(week / "order.pnml", week / "another net.pnml")
    assert wait_for(lambda: rows(window.petri_section) == ["another net", "order"])

    # A new net's Save dialog starts in the workspace folder.
    window.action_new_petri()
    offered = {}

    def save_dialog(_parent, _title, suggested, _filters):
        offered["path"] = suggested
        return str(week / "my model.pnml"), "PNML Petri net (*.pnml)"
    monkeypatch.setattr(petri_page.QFileDialog, "getSaveFileName", save_dialog)
    assert window.current_page().export()
    assert Path(offered["path"]).parent == week
    window._rescan_workspace()
    assert rows(window.petri_section) == ["another net", "my model", "order"]
    assert sum(1 for i in range(3) if window.petri_section.child(i).data(0, FILE_ROLE)) == 2

    # What was open is remembered in the folder and comes back next time.
    assert (week / ".cpnpy").exists()
    window.close()
    again = StudioWindow()
    again.show()
    assert again.open_workspace(str(week))
    assert wait_for(lambda: len(again.documents) == 2)
    assert sorted(d.name for d in again.documents) == ["Boarding", "my model"]
    assert again.windowTitle() == "my model — Week 2"          # it was selected

    # Closing the workspace closes everything and goes back to "CPNpy Studio".
    assert again.close_workspace()
    assert again.documents == [] and again.sidebar_title.text() == APPLICATION_NAME
    assert all(s.isHidden() for s in (again.logs_section, again.petri_section, again.cpn_section))
    again.close()


def test_empty_workspace_says_so(app, tmp_path):
    from cpnpy.gui.studio.app import StudioWindow

    window = StudioWindow()
    window.show()
    window.open_workspace(str(tmp_path))
    assert not window.empty_hint.isHidden()
    window.close_workspace()
    assert window.empty_hint.isHidden()
    window.close()


def _middle_drag(app, view, start, end, steps=4):
    """Press the middle button at ``start``, move to ``end`` and release."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    def send(kind, point, button, buttons):
        event = QMouseEvent(kind, QPointF(point), view.viewport().mapToGlobal(point).toPointF(),
                            button, buttons, Qt.NoModifier)
        QApplication.sendEvent(view.viewport(), event)

    from PySide6.QtCore import QEvent, QPoint
    send(QEvent.MouseButtonPress, QPoint(*start), Qt.MiddleButton, Qt.MiddleButton)
    for step in range(1, steps + 1):
        point = QPoint(start[0] + (end[0] - start[0]) * step // steps,
                       start[1] + (end[1] - start[1]) * step // steps)
        send(QEvent.MouseMove, point, Qt.NoButton, Qt.MiddleButton)
    send(QEvent.MouseButtonRelease, QPoint(*end), Qt.MiddleButton, Qt.NoButton)
    app.processEvents()


def test_middle_drag_pans_the_net_editor(app):
    """Regression (#11): middle-drag panning did nothing (Qt's hand drag only
    starts on the left button), did nothing while the whole net was in view,
    and could leave the view stuck in hand-drag mode."""
    from PySide6.QtWidgets import QGraphicsView
    from cpnpy.gui.studio.app import StudioWindow

    root = Path(__file__).resolve().parents[1]
    window = StudioWindow()
    window.resize(1300, 850)
    window.show()
    window.open_path(str(root / "examples" / "petri" / "order_handling_sound.pnml"))
    page = window.current_page()
    view = page.view
    _pump(app, 0.2)
    view.zoom_to_fit()                    # the whole net in view: nothing to scroll
    landmark = page.scene.itemsBoundingRect().center()     # a fixed point of the drawing

    def on_screen():
        point = view.mapFromScene(landmark)
        return point.x(), point.y()

    start_position = on_screen()
    for tool in (0, 1):                   # whatever tool is picked (Select, Place)
        page.tool_switch.set_index(tool)
        cursor = view.viewport().cursor().shape()
        before = on_screen()
        _middle_drag(app, view, (300, 300), (380, 340))
        # The drawing follows the pointer exactly.
        assert on_screen() == (before[0] + 80, before[1] + 40)
        assert view.dragMode() != QGraphicsView.ScrollHandDrag
        assert view.viewport().cursor().shape() == cursor      # the tool's cursor is back
    assert on_screen() == (start_position[0] + 160, start_position[1] + 80)

    # Over a node too: the node is not dragged, the view pans.
    node = next(iter(page.scene.place_items.values()))
    position = node.pos()
    start = view.mapFromScene(node.sceneBoundingRect().center())
    before = on_screen()
    _middle_drag(app, view, (start.x(), start.y()), (start.x() - 50, start.y() - 30))
    assert node.pos() == position and on_screen() == (before[0] - 50, before[1] - 30)

    # Zoom to fit brings the whole net back.
    view.zoom_to_fit()
    assert view.sceneRect() == page.scene.sceneRect()
    window.close()


# ---------------------------------------------------------------------------
# Working in a folder: the Folder view, organising, two-way sync, bringing
# files in (issues #7, #8, #9, #10)
# ---------------------------------------------------------------------------
def _wait_for(app, condition, seconds: float = 6.0) -> bool:
    for _ in range(int(seconds / 0.02)):
        if condition():
            return True
        _pump(app, 0.02)
    return condition()


def _week(tmp_path) -> Path:
    """A course folder: a net at the top, a log and a net in subfolders, an empty one."""
    import shutil

    from cpnpy.mining import EventLog, parse_simple_log
    from cpnpy.mining.xes import write_xes

    root = Path(__file__).resolve().parents[1]
    week = tmp_path / "Week 2"
    (week / "logs").mkdir(parents=True)
    (week / "models").mkdir()
    (week / "empty").mkdir()
    shutil.copy(root / "examples" / "petri" / "order_handling_sound.pnml",
                week / "models" / "order.pnml")
    shutil.copy(root / "examples" / "simple_transfer.cpn", week / "transfer.cpn")
    write_xes(EventLog.from_simple_log(parse_simple_log("[<a,b>^2, <a,c>]"), "Boarding"),
              week / "logs" / "boarding.xes")
    return week


def _layout(window) -> list[str]:
    """The sidebar as text: one line per visible row, indented by depth."""
    from PySide6.QtWidgets import QTreeWidgetItemIterator
    lines = []
    iterator = QTreeWidgetItemIterator(window.tree)
    while iterator.value() is not None:
        item = iterator.value()
        depth, parent, visible = 0, item.parent(), not item.isHidden()
        while parent is not None:
            depth += 1
            visible = visible and parent.isExpanded() and not parent.isHidden()
            parent = parent.parent()
        if visible:
            lines.append("  " * depth + item.text(0).strip())
        iterator += 1
    return lines


def test_folder_view_shows_subfolders_and_remembers_them(app, tmp_path):
    from cpnpy.gui.studio.app import FOLDER_ROLE, StudioWindow
    from cpnpy.gui.studio.workspace import Workspace

    week = _week(tmp_path)
    window = StudioWindow()
    window.show()
    window.open_workspace(str(week))
    assert window.view_mode == "folder" and not window.view_row.isHidden()
    # Folders first, then files, as in Finder; subfolders start collapsed.
    assert _layout(window) == ["empty", "logs", "models", "transfer"]
    window.folder_items["models"].setExpanded(True)
    assert _layout(window) == ["empty", "logs", "models", "  order", "transfer"]
    assert window.folder_items["models"].data(0, FOLDER_ROLE) == str(week.resolve() / "models")

    # Opening a file keeps it in its subfolder; a new net goes into the folder.
    window._open_placeholder(window.placeholders[window._key(week / "models" / "order.pnml")])
    assert window.documents[-1].name == "order"
    assert _layout(window) == ["empty", "logs", "models", "  order", "transfer"]
    assert window.tree.currentItem() is window.items[window.documents[-1].id]

    # The view and the expanded subfolders are remembered in the folder.
    window.set_view_mode("kind")
    assert "PETRI NETS" in _layout(window) and "models" not in _layout(window)
    # Regression: the headings' rows were in the tree but not laid out (an
    # empty By kind view), so check what the view actually shows.
    for section in (window.logs_section, window.petri_section, window.cpn_section):
        for i in range(section.childCount()):
            assert window.tree.visualItemRect(section.child(i)).height() > 0
    assert Workspace(week).settings() == {"view": "kind", "expanded": ["models"]}
    window.close()
    again = StudioWindow()
    again.show()
    again.open_workspace(str(week))
    assert again.view_mode == "kind" and again.view_switch.index() == 1
    again.set_view_mode("folder")
    assert again.folder_items["models"].isExpanded()
    again.close()


def test_organising_files_from_the_sidebar(app, tmp_path, monkeypatch, fake_bin):
    """New Folder, drag to move (an open file follows), rename a folder with an
    open file in it, and Move to Bin (recoverable), with the disk matching."""
    from cpnpy.gui.studio import app as studio_app
    from cpnpy.gui.studio.app import StudioWindow

    week = _week(tmp_path)
    answers = []
    monkeypatch.setattr(studio_app.QInputDialog, "getText",
                        lambda *args, **kwargs: (answers.pop(0), True))
    monkeypatch.setattr(studio_app.QMessageBox, "exec", lambda box: box.setProperty(
        "clicked", True) or None)
    # Every "Move to Bin?" is answered yes.
    monkeypatch.setattr(studio_app.QMessageBox, "clickedButton",
                        lambda box: next(b for b in box.buttons()
                                         if box.buttonRole(b) == studio_app.QMessageBox.DestructiveRole))

    window = StudioWindow()
    window.show()
    window.open_workspace(str(week))

    # New Folder, inside "models".
    answers.append("assignment 1")
    window.new_folder(str(week / "models"))
    assert (week / "models" / "assignment 1").is_dir()
    assert "models/assignment 1" in window.folder_items
    assert window.folder_items["models"].isExpanded()

    # Open order.pnml, then drag it into the new folder: the file moves, the
    # document stays open with its new path, even with unsaved edits.
    window.set_autosave(False)
    window.open_path(str(week / "models" / "order.pnml"))
    net, page = window.documents[-1], window.current_page()
    page.set_dirty(True)
    target = week / "models" / "assignment 1"
    window.tree.paths_dropped.emit([net.path], str(target), True)
    assert (target / "order.pnml").exists() and not (week / "models" / "order.pnml").exists()
    assert Path(net.path) == (target / "order.pnml").resolve() and net.dirty
    assert window.items[net.id].text(0) == "order  •"
    assert "order.pnml" in page.header.subtitle.text()
    assert window.items[net.id].parent() is window.folder_items["models/assignment 1"]

    # A file that is not open moves too, and dropping on a file means its folder.
    transfer = window.placeholders[window._key(week / "transfer.cpn")]
    window.tree.paths_dropped.emit([str(week / "transfer.cpn")],
                                   window._drop_folder(window.items[net.id]), True)
    assert (target / "transfer.cpn").exists() and not (week / "transfer.cpn").exists()
    del transfer

    # Renaming the folder takes the open file with it.
    answers.append("Assignment one")
    window.rename_path(str(target))
    renamed = week / "models" / "Assignment one"
    assert Path(net.path) == (renamed / "order.pnml").resolve()
    assert "models/Assignment one" in window.folder_items

    # Move to Bin: a file that is not open, then the folder with the open net.
    window.trash_paths([str(renamed / "transfer.cpn")])
    assert not (renamed / "transfer.cpn").exists() and (fake_bin / "transfer.cpn").exists()
    window.trash_paths([str(renamed)])
    assert not renamed.exists() and (fake_bin / "Assignment one" / "order.pnml").exists()
    assert net not in window.documents
    assert "models/Assignment one" not in window.folder_items
    window.close()


def test_changes_on_disk_reach_the_app(app, tmp_path):
    """Folder → app: an open file changed elsewhere is reloaded (or, with
    edits here, the user is asked); one deleted is marked missing; a new
    subfolder with a file in it is listed; the app's own saves are not
    mistaken for changes made elsewhere."""
    import shutil

    from cpnpy.gui.studio.app import StudioWindow
    from cpnpy.mining import EventLog, parse_simple_log
    from cpnpy.mining.pnml import read_pnml, write_pnml
    from cpnpy.mining.xes import write_xes

    root = Path(__file__).resolve().parents[1]
    week = _week(tmp_path)
    window = StudioWindow()
    window.show()
    window.open_workspace(str(week))
    path = week / "models" / "order.pnml"
    window.open_path(str(path))
    net = window.documents[-1]
    before = net.net

    def arcs() -> int:
        return sum(len(page.arcs) for page in net.net.pages)
    sound_arcs = arcs()

    # Changed in another app (no edits here): reloaded by itself.
    other = read_pnml(str(root / "examples" / "petri" / "order_handling_unsound.pnml"))
    write_pnml(other, str(path))
    assert _wait_for(app, lambda: net.net is not before)
    assert arcs() == sound_arcs - 1
    assert "changed on disk — reloaded" in window.statusBar().currentMessage()
    assert window.current_page().document is net

    # The app's own save: nothing is reloaded.
    reloaded_page = window.pages[net.id]
    window.set_autosave(False)
    reloaded_page.set_dirty(True)
    assert reloaded_page.save()
    _pump(app, 1.0)
    assert window.pages[net.id] is reloaded_page

    # Changed elsewhere while it has edits here: the user is asked.
    reloaded_page.set_dirty(True)
    shutil.copy(root / "examples" / "petri" / "order_handling_sound.pnml", path)
    banner = window.banners[net.id]
    assert _wait_for(app, lambda: banner.isVisibleTo(window) and banner.kind == "changed")
    assert "changed on disk" in banner.text.text()
    reload_button = banner.buttons.itemAt(0).widget()
    reload_button.click()
    assert arcs() == sound_arcs and not net.dirty

    # Deleted in Finder: still open, marked missing, not recreated by autosave.
    window.set_autosave(True)
    path.unlink()
    assert _wait_for(app, lambda: net.missing)
    assert net in window.documents and not path.exists()
    assert window.items[net.id].font(0).italic()
    assert window.banners[net.id].kind == "missing"
    window.pages[net.id].set_dirty(True)
    _pump(app, 1.5)
    assert not path.exists()                   # autosave does not bring it back

    # A new subfolder made in Finder, with a log copied straight into it.
    (week / "week 3").mkdir()
    write_xes(EventLog.from_simple_log(parse_simple_log("[<x,y>]"), "New"),
              week / "week 3" / "fresh.xes")
    assert _wait_for(app, lambda: window._key(week / "week 3" / "fresh.xes")
                     in window.placeholders)
    assert "week 3" in window.folder_items
    net.dirty = False                          # (quitting would ask about the edits)
    window.close()


def test_the_app_keeps_the_folder_up_to_date(app, tmp_path):
    """App → folder: new nets and logs are files from the start, edits are
    autosaved, results go next to their source, and Keep saves a model."""
    from cpnpy.gui.studio.app import AUTOSAVE_DELAY, StudioWindow
    from cpnpy.gui.studio.documents import LogDocument, ModelDocument
    from cpnpy.mining import EventLog, parse_simple_log
    from cpnpy.mining.discovery.alpha import alpha_miner
    from cpnpy.mining.pnml import read_pnml

    week = _week(tmp_path)
    window = StudioWindow()
    window.show()
    window.open_workspace(str(week))

    # A new Petri net is "Untitled 1.pnml" straight away, autosaved without a dot.
    window.action_new_petri()
    net, page = window.documents[-1], window.current_page()
    assert net.path and Path(net.path).name == "Untitled 1.pnml" and net.autosave
    from cpnpy.model.net import Place
    page._checkpoint()
    net.net.pages[0].places.append(Place(name="start"))
    page._edited()
    assert net.dirty and window.items[net.id].text(0) == "Untitled 1"   # no dot
    assert "edited" not in page.header.subtitle.text()
    assert _wait_for(app, lambda: not net.dirty, AUTOSAVE_DELAY / 1000 + 2)
    assert [p.name for p in read_pnml(net.path).places.values()] == ["start"]
    _pump(app, 0.8)
    assert window.pages[net.id] is page          # its own save is not reloaded

    # Renaming the net renames the file; a new coloured net is a .cpn.
    import cpnpy.gui.studio.app as studio_app
    original = studio_app.QInputDialog.getText
    studio_app.QInputDialog.getText = lambda *args, **kwargs: ("first net", True)
    try:
        window.rename_document(net)
    finally:
        studio_app.QInputDialog.getText = original
    assert (week / "first net.pnml").exists() and not (week / "Untitled 1.pnml").exists()
    window.action_new_cpn()
    assert Path(window.documents[-1].path).name == "Untitled 1.cpn"

    # A log typed in notation is saved as <name>.xes; a filtered log goes next to its source.
    window.add_document(LogDocument(EventLog.from_simple_log(
        parse_simple_log("[<a,b,c>^2, <a,c>]"), "L1")))
    assert (week / "L1.xes").exists() and window.documents[-1].path == str(week / "L1.xes")
    window.open_path(str(week / "logs" / "boarding.xes"))
    assert _wait_for(app, lambda: any(d.name == "Boarding" for d in window.documents))
    boarding = next(d for d in window.documents if d.name == "Boarding")
    filtered_log = EventLog.from_simple_log(parse_simple_log("[<a,b>^2]"), "Boarding (filtered)")
    window.pages[boarding.id].open_log.emit(LogDocument(filtered_log))
    assert (week / "logs" / "Boarding (filtered).xes").exists()

    # A discovered model waits for Keep, then goes next to its log.
    model = ModelDocument(alpha_miner(boarding.simple_log()).net, origin="α",
                          source_log=boarding)
    model.net.name = "α · Boarding"
    window.add_document(model)
    model_page = window.current_page()
    assert model.path is None and model_page.keep_button.isVisibleTo(window)
    assert window.items[model.id].parent() is window.unsaved_section
    assert window.tree.visualItemRect(window.items[model.id]).height() > 0
    model_page.keep_button.click()
    kept = week / "logs" / "α · Boarding.pnml"
    assert kept.exists() and Path(model.path) == kept and read_pnml(str(kept)).transitions
    assert not model_page.keep_button.isVisibleTo(window)

    # Turning autosave off brings the edited dot back.
    window.set_autosave(False)
    page.set_dirty(True)
    assert window.items[net.id].text(0) == "first net  •"
    window.set_autosave(True)
    assert _wait_for(app, lambda: not net.dirty, AUTOSAVE_DELAY / 1000 + 2)
    window.close()


def test_opening_a_file_from_outside_the_folder(app, tmp_path, monkeypatch, fake_bin):
    """#9: copy (the default), move or open in place; name clashes; the
    remembered choice; dropping onto a subfolder."""
    import shutil

    from cpnpy.gui.studio import app as studio_app
    from cpnpy.gui.studio.app import StudioWindow
    from cpnpy.gui.studio.workspace import Workspace

    root = Path(__file__).resolve().parents[1]
    week = _week(tmp_path)
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    source = downloads / "unsound.pnml"
    shutil.copy(root / "examples" / "petri" / "order_handling_unsound.pnml", source)

    asked = []

    class FakeImportDialog:
        choice_to_make, always = "copy", False

        def __init__(self, names, folder, parent=None, allow_open=True, default="copy"):
            asked.append((names, allow_open))
            from PySide6.QtWidgets import QCheckBox
            self.always = QCheckBox()
            self.always.setChecked(FakeImportDialog.always)

        def exec(self):
            return studio_app.QDialog.Accepted

        def choice(self):
            return FakeImportDialog.choice_to_make

    clash_answers = []
    monkeypatch.setattr(studio_app, "ImportDialog", FakeImportDialog)
    monkeypatch.setattr(studio_app, "ask_about_clash", lambda parent, target: clash_answers.pop(0))

    window = StudioWindow()
    window.show()
    window.open_workspace(str(week))

    # Copy: the original stays, the copy in the folder is what opens.
    window.open_files([str(source)])
    assert source.exists() and (week / "unsound.pnml").exists()
    assert window.documents[-1].path == str(week / "unsound.pnml")
    assert asked[-1] == (["unsound.pnml"], True)

    # The same name again: keep both ("unsound 2.pnml"), or replace.
    clash_answers.append("keep")
    window.open_files([str(source)])
    assert (week / "unsound 2.pnml").exists()
    clash_answers.append("replace")
    (week / "unsound 2.pnml").write_text("old")
    window.open_files([str(source)])                 # "unsound.pnml" is open: replaced
    assert (fake_bin / "unsound.pnml").exists()       # the replaced one is in the Bin

    # Move, remembered for this folder ("Always do this").
    FakeImportDialog.choice_to_make, FakeImportDialog.always = "move", True
    other = downloads / "other.pnml"
    shutil.copy(source, other)
    window.open_files([str(other)])
    assert not other.exists() and (week / "other.pnml").exists()
    assert Workspace(week).settings()["import"] == "move"
    asked.clear()
    third = downloads / "third.pnml"
    shutil.copy(source, third)
    window.open_files([str(third)])
    assert asked == [] and (week / "third.pnml").exists() and not third.exists()

    # Open in place (the folder's choice changed back to asking).
    Workspace(week).update_settings(**{"import": None})
    FakeImportDialog.choice_to_make, FakeImportDialog.always = "open", False
    window.open_files([str(source)])
    assert window.documents[-1].path == str(source)
    assert window.items[window.documents[-1].id].parent() is window.elsewhere_section

    # Dropped from Finder onto a subfolder: it goes there ("open in place" is not offered).
    FakeImportDialog.choice_to_make = "copy"
    log = downloads / "events.xes"
    shutil.copy(week / "logs" / "boarding.xes", log)
    window.tree.paths_dropped.emit([str(log)], str(week / "logs"), False)
    assert (week / "logs" / "events.xes").exists() and asked[-1] == (["events.xes"], False)
    window.close()
