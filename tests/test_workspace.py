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


def test_tree_lists_folders_first_including_empty_ones(tmp_path):
    from cpnpy.gui.studio.workspace import WorkspaceFolder

    _touch(tmp_path / "b.pnml")
    _touch(tmp_path / "A.xes")
    _touch(tmp_path / "models" / "order.pnml")
    _touch(tmp_path / "models" / "notes.txt")
    (tmp_path / "empty").mkdir()
    _touch(tmp_path / "logs" / "2024" / "boarding.xes")
    _touch(tmp_path / ".git" / "x.pnml")

    tree = Workspace(tmp_path).tree()
    assert isinstance(tree, WorkspaceFolder) and tree.relative == "" and not tree.truncated
    assert [f.relative for f in tree.folders] == ["empty", "logs", "models"]
    assert [f.relative for f in tree.files] == ["A.xes", "b.pnml"]
    logs = tree.folders[1]
    assert [f.relative for f in logs.folders] == ["logs/2024"]
    assert [f.relative for f in logs.folders[0].files] == ["logs/2024/boarding.xes"]
    assert [f.relative for f in tree.folders[2].files] == ["models/order.pnml"]
    assert [f.relative for f in tree.walk()] == ["", "empty", "logs", "logs/2024", "models"]
    assert Workspace(tmp_path).directories() == [tmp_path.resolve() / r for r in
                                                 ("", "empty", "logs", "logs/2024", "models")]


def test_tree_says_when_it_stopped_listing(tmp_path, monkeypatch):
    from cpnpy.gui.studio import workspace as module

    monkeypatch.setattr(module, "MAX_FILES", 3)
    for index in range(5):
        _touch(tmp_path / f"net {index}.pnml")
    tree = Workspace(tmp_path).tree()
    assert len(tree.files) == 3 and tree.truncated


def test_icloud_placeholders_are_listed_as_in_the_cloud(tmp_path):
    _touch(tmp_path / ".Week 2.xes.icloud")          # only in iCloud
    _touch(tmp_path / "here.pnml")
    _touch(tmp_path / ".here.pnml.icloud")           # stale placeholder: the file is here
    _touch(tmp_path / ".notes.txt.icloud")           # not something the app opens
    tree = Workspace(tmp_path).tree()
    assert [(f.relative, f.in_cloud) for f in tree.files] == [("here.pnml", False),
                                                            ("Week 2.xes", True)]
    cloud = tree.files[1]
    assert cloud.path == tmp_path.resolve() / "Week 2.xes"
    assert cloud.cloud_placeholder == tmp_path.resolve() / ".Week 2.xes.icloud"
    # files() is what can be opened right now.
    assert [f.relative for f in Workspace(tmp_path).files()] == ["here.pnml"]


def test_settings_live_next_to_the_open_files(tmp_path):
    net = _touch(tmp_path / "order.pnml")
    workspace = Workspace(tmp_path)
    assert workspace.settings() == {}
    workspace.update_settings(view="kind", expanded=["logs"])
    workspace.save_state([{"path": str(net)}], str(net))
    assert workspace.settings() == {"view": "kind", "expanded": ["logs"]}
    assert [e["path"] for e in workspace.load_state()["open"]] == [str(net)]
    workspace.update_settings(view=None, expanded=["logs", "models"])
    assert workspace.settings() == {"expanded": ["logs", "models"]}
    assert workspace.load_state()["selected"] == str(net)


def test_unique_names_and_safe_names(tmp_path):
    from cpnpy.gui.studio.workspace import file_stem, file_suffix, safe_file_name, unique_path

    assert unique_path(tmp_path, "Wilma 50.xes") == tmp_path / "Wilma 50.xes"
    _touch(tmp_path / "Wilma 50.xes")
    _touch(tmp_path / ".Wilma 50 2.xes.icloud")       # taken too, by a file in iCloud
    assert unique_path(tmp_path, "Wilma 50.xes") == tmp_path / "Wilma 50 3.xes"
    _touch(tmp_path / "log.xes.gz")
    assert unique_path(tmp_path, "log.xes.gz") == tmp_path / "log 2.xes.gz"
    assert (file_stem("log.xes.gz"), file_suffix("log.xes.gz")) == ("log", ".xes.gz")
    assert safe_file_name("α · a/b: c?") == "α · a-b- c-"
    assert safe_file_name("  ..  ") == "Untitled"


def test_atomic_write_never_leaves_half_a_file(tmp_path):
    import pytest
    from cpnpy.gui.studio.workspace import atomic_write, made_by_cpnpy

    target = _touch(tmp_path / "model.pnml", "old")
    atomic_write(target, lambda path: path.write_text("new"))
    assert target.read_text() == "new"

    def broken(path):
        path.write_text("half")
        raise RuntimeError("disk full")
    with pytest.raises(RuntimeError):
        atomic_write(target, broken)
    assert target.read_text() == "new"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["model.pnml"]   # no leftovers

    assert made_by_cpnpy(_touch(tmp_path / "a.cpn", '<generator tool="CPNpy" version="0.2.0"/>'))
    assert not made_by_cpnpy(_touch(tmp_path / "b.cpn", '<generator tool="CPN Tools"/>'))
    assert not made_by_cpnpy(tmp_path / "missing.cpn")
