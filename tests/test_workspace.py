"""Workspace folders: listing a folder's files and remembering what was open."""

from __future__ import annotations

import json
from pathlib import Path

from cpnpy.gui.studio.workspace import STATE_FILE, Workspace, display_name, file_kind


def _touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_file_kinds_and_display_names():
    assert file_kind(Path("a.xes")) == "log"
    assert file_kind(Path("a.XES.gz")) == "log"
    assert file_kind(Path("a.csv")) == "log"
    assert file_kind(Path("a.pnml")) == "petri"
    assert file_kind(Path("a.cpn")) == "cpn"
    assert file_kind(Path("a.gz")) is None and file_kind(Path("notes.txt")) is None
    assert display_name("order handling.pnml") == "order handling"
    assert display_name("logs/boarding.xes.gz") == "logs/boarding"


def test_lists_what_the_app_can_open(tmp_path):
    _touch(tmp_path / "order.pnml")
    _touch(tmp_path / "Wilma 50.xes")
    _touch(tmp_path / "logs" / "boarding.xes.gz")
    _touch(tmp_path / "model.cpn")
    _touch(tmp_path / "notes.txt")                      # not something the app opens
    _touch(tmp_path / ".hidden.pnml")                   # hidden, as in Finder
    _touch(tmp_path / ".git" / "x.pnml")                # inside a hidden folder
    _touch(tmp_path / "__pycache__" / "y.pnml")         # a tool's cache
    _touch(tmp_path / "a" / "b" / "c" / "d" / "deep.pnml")   # deeper than MAX_DEPTH

    files = Workspace(tmp_path).files()
    assert [f.relative for f in files] == [
        "model.cpn", "order.pnml", "Wilma 50.xes", "logs/boarding.xes.gz"]
    assert [f.kind for f in files] == ["cpn", "petri", "log", "log"]
    assert files[-1].name == "logs/boarding"


def test_state_round_trip_with_relative_paths(tmp_path):
    folder = tmp_path / "Week 2"
    net = _touch(folder / "order.pnml")
    log = _touch(folder / "events.csv")
    workspace = Workspace(folder)

    # Nothing open and no state yet: no file is created.
    workspace.save_state([], None)
    assert not (folder / STATE_FILE).exists()

    workspace.save_state([{"path": str(net)}, {"path": str(log), "csv_mapping": {"case": "id"}}],
                         str(net))
    stored = json.loads((folder / STATE_FILE).read_text())
    assert [e["path"] for e in stored["open"]] == ["order.pnml", "events.csv"]
    assert stored["selected"] == "order.pnml"

    # Moving the folder keeps the workspace working: paths are relative.
    moved = tmp_path / "Week 2 (moved)"
    folder.rename(moved)
    state = Workspace(moved).load_state()
    assert [Path(e["path"]) for e in state["open"]] == [moved / "order.pnml", moved / "events.csv"]
    assert state["open"][1]["csv_mapping"] == {"case": "id"}
    assert Path(state["selected"]) == moved / "order.pnml"


def test_unchanged_state_is_not_rewritten(tmp_path):
    net = _touch(tmp_path / "order.pnml")
    workspace = Workspace(tmp_path)
    workspace.save_state([{"path": str(net)}], None)
    before = (tmp_path / STATE_FILE).stat().st_mtime_ns
    workspace.save_state([{"path": str(net)}], None)
    assert (tmp_path / STATE_FILE).stat().st_mtime_ns == before


def test_broken_state_file_is_ignored(tmp_path):
    (tmp_path / STATE_FILE).write_text("{ not json")
    assert Workspace(tmp_path).load_state() == {"open": [], "selected": None}
