"""Editing logs inside the app: back to the notation, and case by case."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DATA = Path(__file__).resolve().parent / "data"


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def fake_bin(tmp_path_factory, monkeypatch):
    from openprocess.gui.studio import app as studio_app
    monkeypatch.setattr(studio_app, "move_to_trash", lambda path: True)


def _pump(app, seconds: float = 0.1) -> None:
    import time
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()


def _wait_for(app, condition, seconds: float = 6.0) -> bool:
    import time
    end = time.time() + seconds
    while time.time() < end:
        if condition():
            return True
        app.processEvents()
        time.sleep(0.01)
    return condition()


def test_a_notation_log_goes_back_to_its_notation(app, tmp_path):
    """Typed in notation, kept as a .log.txt in the folder, and Edit… shows the
    very text you typed; changing it rewrites the file and the page."""
    from openprocess.gui.studio.app import StudioWindow
    from openprocess.gui.studio.documents import LogDocument
    from openprocess.gui.studio.log_editor import LogEditorDialog, log_from_notation

    window = StudioWindow()
    window.show()
    window.open_workspace(str(tmp_path))
    text = "[<register, pay>^3, <register,cancel>]"        # spacing as typed
    window.add_document(LogDocument(log_from_notation(text, "Orders"), notation=text))
    document = window.logs()[0]
    assert document.path.endswith("Orders.log.txt")
    assert Path(document.path).read_text().strip() == text

    dialog = LogEditorDialog(document, window)
    assert dialog.mode == dialog.NOTATION
    assert dialog.notation.text() == text                  # exactly as typed
    dialog.notation.set_text("[<register, pay>^3, <register, cancel>^2, <register>]")
    assert dialog.buttons.button(dialog.buttons.StandardButton.Save).isEnabled()
    dialog._accept()
    window.pages[document.id].apply_edit(dialog.new_log, dialog.new_notation)
    _pump(app)
    assert sum(document.simple_log().values()) == 6
    assert "<register>" in Path(document.path).read_text()
    assert "6 cases" in window.pages[document.id].header.subtitle.text()

    # Invalid notation cannot be saved.
    dialog = LogEditorDialog(document, window)
    dialog.notation.set_text("register, pay")
    assert not dialog.buttons.button(dialog.buttons.StandardButton.Save).isEnabled()
    window.close()


def test_editing_cases_and_events_keeps_the_other_attributes(app, tmp_path):
    from openprocess.gui.studio.app import StudioWindow
    from openprocess.gui.studio.log_editor import LogEditorDialog
    from openprocess.mining import read_xes
    from openprocess.mining.log import KEY_RESOURCE, KEY_TIME

    source = tmp_path / "wilma.xes"
    shutil.copy(DATA / "plane_wilma_10.xes", source)
    window = StudioWindow()
    window.show()
    window.open_workspace(str(tmp_path))
    window.open_path(str(source))
    assert _wait_for(app, lambda: window.logs())
    document = window.logs()[0]
    cases_before = len(document.log)

    dialog = LogEditorDialog(document, window)
    assert dialog.mode == dialog.EVENTS                      # timestamps: case by case
    assert not dialog.notation_warning.isHidden()            # notation would lose them
    editor = dialog.cases
    headings = [h for _, h in editor.columns]
    assert "Timestamp" in headings and "Activity" in headings
    trace = editor.current_trace()
    first_activity = trace.events[0].activity
    length = len(trace.events)

    # A bad timestamp blocks saving until it is fixed.
    time_column = headings.index("Timestamp")
    editor.events.item(0, time_column).setText("not a date")
    assert not editor.valid
    assert not dialog.buttons.button(dialog.buttons.StandardButton.Save).isEnabled()
    editor.events.item(0, time_column).setText("2024-03-01 09:30:00")
    assert editor.valid

    # Delete the last event, add one, rename an activity everywhere.
    editor.events.selectRow(length - 1)
    editor.delete_event()
    assert len(trace.events) == length - 1
    editor.events.selectRow(0)
    editor.add_event()
    assert trace.events[1].activity == "new activity"
    editor.events.item(1, 0).setText("Check ticket")
    editor.duplicate_case()
    for t in editor.log.traces:
        for e in t.events:
            if e.activity == first_activity:
                e.attributes["concept:name"] = "Renamed"
    dialog._accept()
    assert dialog.new_notation is None                       # still a rich log
    window.pages[document.id].apply_edit(dialog.new_log, dialog.new_notation)
    _pump(app, 0.3)

    again = read_xes(str(source))
    assert len(again) == cases_before + 1
    edited = again.traces[0]
    assert edited.events[1].activity == "Check ticket"
    assert edited.events[0].timestamp.isoformat(sep=" ").startswith("2024-03-01 09:30:00")
    assert edited.events[0].resource == document.log.traces[0].events[0].attributes.get(
        KEY_RESOURCE)
    assert "Renamed" in {e.activity for e in edited.events}
    assert any(KEY_TIME in e.attributes for e in edited.events)
    window.close()


def test_a_plain_log_can_be_edited_both_ways(app):
    """Switching between the tabs carries the edits over."""
    from openprocess.gui.studio.documents import LogDocument
    from openprocess.gui.studio.log_editor import LogEditorDialog, log_from_notation

    document = LogDocument(log_from_notation("[<a,b>^2]", "L"), notation="[<a,b>^2]")
    dialog = LogEditorDialog(document)
    dialog.notation.set_text("[<a,b>^2, <a,c>]")
    dialog.modes.set_index(dialog.EVENTS)
    assert len(dialog.cases.log.traces) == 3
    assert [h for _, h in dialog.cases.columns] == ["Activity"]
    dialog.cases.cases.setCurrentRow(2)
    dialog.cases.delete_case()
    dialog.modes.set_index(dialog.NOTATION)
    assert dialog.notation.text() == "[<a,b>^2]"
    dialog.cases.add_case()
    dialog._accept()
    assert dialog.new_log is not None


def test_new_log_from_notation_remembers_the_text(app):
    from openprocess.gui.studio.app import StudioWindow
    from openprocess.gui.studio.log_editor import NotationDialog

    window = StudioWindow()
    dialog = NotationDialog(window, text="[<x,y>^2]", name="Mine")
    assert dialog.ok.isEnabled()
    from openprocess.gui.studio.documents import LogDocument
    window.add_document(LogDocument(dialog.log(), notation=dialog.text()))
    assert window.logs()[0].notation == "[<x,y>^2]"
    assert window.pages[window.logs()[0].id].edit_button.isEnabled()
    window.close()
