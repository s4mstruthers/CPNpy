"""CPNpy became OpenProcess in 0.7: the old name keeps working."""

from __future__ import annotations

import importlib
import json
import sys
import warnings


def test_cpnpy_is_openprocess_under_its_old_name():
    for name in [m for m in sys.modules if m == "cpnpy" or m.startswith("cpnpy.")]:
        del sys.modules[name]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cpnpy = importlib.import_module("cpnpy")
    assert any("openprocess" in str(w.message) for w in caught)
    import openprocess
    from cpnpy.flow import box as old_box
    from openprocess.flow import box as new_box
    assert old_box is new_box and cpnpy.__version__ == openprocess.__version__
    checks = importlib.import_module("cpnpy.learn.checks")
    assert checks.__name__ == "openprocess.learn.checks"
    from cpnpy.mining.discovery.alpha import alpha_miner
    assert alpha_miner.__module__ == "openprocess.mining.discovery.alpha"


def test_a_folder_last_opened_by_cpnpy_keeps_its_state_and_notes(tmp_path):
    from openprocess.gui.studio.workspace import NOTES_FILE, STATE_FILE, Workspace
    (tmp_path / ".cpnpy").write_text(json.dumps({"open": [], "view": "folder"}))
    (tmp_path / ".cpnpy notes.md").write_text("my notes")
    workspace = Workspace(tmp_path)
    assert (tmp_path / STATE_FILE).exists() and not (tmp_path / ".cpnpy").exists()
    assert workspace.load_notes() == "my notes" and (tmp_path / NOTES_FILE).exists()
    # Never over an existing file of the new name.
    (tmp_path / ".cpnpy notes.md").write_text("older notes")
    Workspace(tmp_path)
    assert workspace.load_notes() == "my notes" and (tmp_path / ".cpnpy notes.md").exists()


def test_the_datasets_cache_is_found_under_either_name(tmp_path, monkeypatch):
    from openprocess.flow import datasets
    monkeypatch.delenv("OPENPROCESS_DATASETS", raising=False)
    monkeypatch.delenv("CPNPY_DATASETS", raising=False)
    monkeypatch.setattr(datasets.Path, "home", classmethod(lambda cls: tmp_path))
    assert datasets.cache_dir() == tmp_path / ".openprocess" / "datasets"
    (tmp_path / ".openprocess").rename(tmp_path / ".cpnpy")      # a cache CPNpy filled
    assert datasets.cache_dir() == tmp_path / ".cpnpy" / "datasets"
    monkeypatch.setenv("CPNPY_DATASETS", str(tmp_path / "elsewhere"))
    assert datasets.cache_dir() == tmp_path / "elsewhere"
