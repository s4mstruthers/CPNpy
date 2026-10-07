"""Exercises, transition systems and regions, and Compare nets… in CPNpy Studio.

Rendered offscreen, like the other GUI tests.  The demo exercises that ship
with the app (``cpnpy/exercises``) are copied to a temporary folder first,
because an exercise saves your work into its folder.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DEMO = Path(__file__).resolve().parents[1] / "cpnpy" / "exercises"


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _pump(app, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def wait_for(app, condition, seconds: float = 8.0) -> bool:
    for _ in range(int(seconds / 0.02)):
        if condition():
            return True
        _pump(app, 0.02)
    return condition()


@pytest.fixture
def demo(tmp_path):
    target = tmp_path / "Exercises"
    shutil.copytree(DEMO, target)
    return target


def _window():
    from cpnpy.gui.studio.app import StudioWindow
    window = StudioWindow()
    window.resize(1500, 950)
    window.show()
    return window


def test_every_demo_folder_is_an_exercise():
    from cpnpy.gui.studio.workspace import exercise_files
    folders = [p for p in DEMO.glob("*/*") if p.is_dir()]
    assert len(folders) == 4
    for folder in folders:
        files = exercise_files(folder)
        assert files is not None, folder
        assert files.answer_net is not None or files.answer_text is not None


def test_modelling_exercise_checks_your_net(app, demo):
    """A blank net that becomes "my answer.pnml" on the first edit; Check finds an
    XOR where the answer has an AND, with a trace to replay, and accepts an
    equivalent net drawn differently."""
    from cpnpy.gui.studio.app import EXERCISE_ROLE
    from cpnpy.gui.studio.petri_page import PetriNetPage
    from cpnpy.mining.pnml import read_pnml, write_pnml

    folder = demo / "1 Petri nets" / "Exercise 1.1 Order handling"
    window = _window()
    window.open_exercise(str(folder))
    assert window.exercise is not None and not window.exercise_panel.isHidden()
    assert "Order handling" in window.exercise_panel.question.toPlainText()
    # The exercise folder is a row of its own; the answer is not listed.
    rows = [i for i in window._all_rows() if i.data(0, EXERCISE_ROLE)]
    assert len(rows) == 1 and rows[0].text(0) == folder.name   # its parent was opened
    from cpnpy.gui.studio.sidebar import FILE_ROLE
    assert not any(str(i.data(0, FILE_ROLE) or "").endswith("/answer.pnml")
                   for i in window._all_rows())

    # A blank net, not saved until you edit it.
    page = window.current_page()
    assert isinstance(page, PetriNetPage)
    assert page.document.path is None and not (folder / "my answer.pnml").exists()
    page._edited()
    assert page.document.path == str(folder / "my answer.pnml")
    assert (folder / "my answer.pnml").exists()

    # Your net: an XOR where the answer has an AND.  Written as your file and
    # reopened, as if you had drawn it.
    answer = read_pnml(str(folder / "answer.pnml"))
    xor = answer.copy()
    for place in ("p2", "p4"):
        xor.remove_place(place)
    xor.add_arc("p1", "t_ship")
    xor.add_arc("t_ship", "p3")
    write_pnml(xor, str(folder / "my answer.pnml"))
    window.close_exercise()
    window.remove_documents([d.id for d in window.documents], confirm=False)
    window.open_exercise(str(folder))
    mine = window.current_page()
    assert mine.document.path == str(folder / "my answer.pnml")

    window.check_exercise()
    assert wait_for(app, lambda: getattr(window, "last_comparison", None) is not None)
    view = window.last_comparison
    assert not view.comparison.equivalent
    assert view.comparison.only_second == [("receive", "pay", "ship", "close")]
    assert ("receive", "pay", "close") in view.comparison.only_first
    # Replay: the net does what it can of the answer's trace, then stops.
    view.replay_buttons[0].click()
    assert mine.simulator.step_count == 2
    assert "differs" in window.statusBar().currentMessage()

    # The same behaviour, drawn differently (other place names, a silent step).
    same = answer.copy()
    for place in list(same.places.values()):
        place.name = "q" + place.name
    write_pnml(same, str(folder / "my answer.pnml"))
    window.close_exercise()
    window.remove_documents([d.id for d in window.documents], confirm=False)
    window.last_comparison = None
    window.open_exercise(str(folder))
    window.check_exercise()
    assert wait_for(app, lambda: window.last_comparison is not None)
    assert window.last_comparison.comparison.equivalent
    window.close()


def test_soundness_exercise_hides_results_and_keeps_the_given_net(app, demo):
    from cpnpy.gui.studio import petri_page

    folder = demo / "2 Soundness" / "Exercise 2.1 Spot the flaw"
    given = (folder / "net.pnml").read_bytes()
    window = _window()
    window.open_exercise(str(folder))
    page = window.current_page()
    assert page.document.path == str(folder / "net.pnml")
    assert not page.document.autosave             # the given net is never saved over

    original = petri_page.run_in_background
    petri_page.run_in_background = lambda work, done, failed=None: done(work())
    try:
        page.run_analysis()
    finally:
        petri_page.run_in_background = original
    # Hidden in the exercise, one card at a time or all at once.
    assert page.soundness_card.concealed and page.footprint_card.concealed
    assert not page.soundness_card.reveal_row.isHidden()
    page.soundness_card.reveal_button.click()
    assert not page.soundness_card.concealed and page.footprint_card.concealed
    window.exercise_panel.reveal_button.click()
    assert not page.footprint_card.concealed
    assert not window.exercise_panel.reveal_button.isEnabled()

    # The first edit moves your work to "my answer.pnml".
    page._edited()
    assert page.document.path == str(folder / "my answer.pnml")
    assert (folder / "net.pnml").read_bytes() == given

    # No answer.pnml: Check shows the worked answer.
    assert window.exercise_panel.check_button.text() == "Show answer"
    window.exercise_panel.check_button.click()
    assert "PT-handle" in window.exercise_panel.answer_browser.toPlainText()

    # Closing the exercise: nothing is hidden any more, and the question goes.
    window.close_exercise()
    assert page.concealment is None and window.exercise_panel.isHidden()
    window.close()


def test_log_exercise_opens_textbook_notation_and_hides_the_footprint(app, demo):
    from cpnpy.gui.studio.documents import LogDocument
    from cpnpy.gui.studio.log_page import LogPage

    folder = demo / "3 Discovery" / "Exercise 3.1 The alpha-algorithm"
    window = _window()
    window.open_exercise(str(folder))
    logs = [d for d in window.documents if isinstance(d, LogDocument)]
    assert len(logs) == 1 and len(logs[0].log) == 7
    assert logs[0].path == str(folder / "log.txt")
    page = window.pages[logs[0].id]
    assert isinstance(page, LogPage)
    page.tabs.set_index(5)                       # Footprint
    footprint = [c for c, key in page._concealed_cards if key == "footprint"][0]
    assert footprint.concealed
    window.close_exercise()
    assert not footprint.concealed               # outside an exercise: as before
    window.close()


def test_regions_exercise_and_transition_system_page(app, demo):
    from cpnpy.gui.studio.documents import TransitionSystemDocument
    from cpnpy.gui.studio.regions_view import TransitionSystemPage

    folder = demo / "4 Regions" / "Exercise 4.1 Regions of a transition system"
    window = _window()
    window.open_exercise(str(folder))
    systems = [d for d in window.documents if isinstance(d, TransitionSystemDocument)]
    assert len(systems) == 1 and len(systems[0].ts.states) == 7
    page = window.pages[systems[0].id]
    assert isinstance(page, TransitionSystemPage)
    assert wait_for(app, lambda: page.panel is not None)
    panel = page.panel
    # The checker works in the exercise; the analysis is hidden.
    panel.region_edit.setText("s1, s3")
    panel.check_region()
    assert panel.last_check.is_region
    panel.system_view._clicked(panel.system_view.ids["s4"])     # click a state: {s1, s3, s4}
    assert panel.region_edit.text() == "s1, s3, s4" and not panel.last_check.is_region
    hidden = [card for card, _ in panel._concealed_cards]
    assert hidden and all(card.concealed for card in hidden)
    window.exercise_panel.reveal_button.click()
    assert not any(card.concealed for card in hidden)
    assert panel.result.analysis.state_separation is False

    # Editing the text recomputes and saves the file.
    page.editor.setPlainText("s0 -a-> s1, s1 -b-> s2")
    page.apply()
    assert wait_for(app, lambda: page.panel is not None and len(page.panel.ts.states) == 3)
    assert "s1 -b-> s2" in (folder / "ts.txt").read_text()
    window.close()


def test_discover_with_state_based_regions(app):
    from cpnpy.gui.studio.documents import LogDocument
    from cpnpy.gui.studio.regions_view import RegionsPanel
    from cpnpy.mining import EventLog, parse_simple_log

    window = _window()
    log = EventLog.from_simple_log(parse_simple_log("[<a,b,c,d>^3, <a,c,b,d>^2, <a,e,d>]"),
                                   "L")
    window.add_document(LogDocument(log))
    page = window.current_page()
    page.tabs.set_index(6)                       # Discover
    from PySide6.QtWidgets import QComboBox
    chooser = next(box for box in page.findChildren(QComboBox)
                   if box.findData("regions") >= 0)
    chooser.setCurrentIndex(chooser.findData("regions"))
    assert wait_for(app, lambda: page.findChildren(RegionsPanel))
    panel = page.findChildren(RegionsPanel)[-1]
    assert panel.result.analysis.elementary and panel.result.synthesis.isomorphic
    # The state function: a sequence with no horizon is a tree, not elementary.
    direction, representation, horizon = page.region_controls
    representation.setCurrentIndex(representation.findData("sequence"))
    assert wait_for(app, lambda: any(p.result.ts.states[0] == "⟨⟩"
                                     for p in page.findChildren(RegionsPanel)))
    window.close()


def test_compare_nets_outside_an_exercise(app):
    from cpnpy.gui.studio.documents import ModelDocument
    from cpnpy.model.examples import order_handling_sound, order_handling_unsound

    window = _window()
    window.add_document(ModelDocument(order_handling_sound(), origin="test"))
    window.add_document(ModelDocument(order_handling_unsound(), origin="test"))
    first, second = window.documents
    window.compare_nets(first, second)
    assert wait_for(app, lambda: getattr(window, "net_comparison_dialog", None) is not None)
    from cpnpy.gui.studio.exercise_panel import NetComparisonView
    view = window.net_comparison_dialog.findChildren(NetComparisonView)[0]
    assert isinstance(view.comparison.equivalent, bool)
    window.net_comparison_dialog.close()
    window.close()


def test_question_markdown_has_maths_and_tables():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from cpnpy.gui.studio.exercise_panel import markdown_html
    html = markdown_html("| a | b |\n|---|---|\n| 1 | 2 |\n\nInline $s_{in} \\in S$ and\n\n"
                         "$$\\bigcap_{R} R$$\n\nand $\\frobnicate$ stays as written.")
    assert "<table" in html and "<sub>" in html and "⋂" in html
    assert "frobnicate" in html and "MATHX" not in html
