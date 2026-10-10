"""Snapshots: every finished run kept, what changed, two compared, settings restored."""

from __future__ import annotations

from openprocess.flow import Runner, Workflow, standard_library
from openprocess.flow.boxes.check import soundness
from openprocess.flow.boxes.discover import inductive_miner
from openprocess.flow.boxes.input import typed_log
from openprocess.flow.record import load, save
from openprocess.flow.snapshots import LIMIT, History, Snapshot, compare, settings_to_apply, take


def _run(wf):
    run = Runner(standard_library()).run(wf)
    assert run.ok, [r.error for r in run.failed()]
    return run


def test_snapshots_say_what_changed_and_compare_box_by_box():
    wf = Workflow("Snaps")
    log = wf.add(typed_log, {"text": "[<a,b,c,d>^3, <a,c,b,d>^2, <a,e,d>]"})
    miner = wf.add(inductive_miner)
    wf.connect(log, miner)
    history = History()
    first = take(wf, _run(wf), None)
    assert first.label == "First run" and first.figures[log.id][0] == "6 cases" and history.add(first)
    assert not history.add(take(wf, _run(wf), history.latest))         # the same again: not kept
    wf.set(miner, noise=0.3)
    second = take(wf, _run(wf), history.latest)
    assert second.label == "Inductive Miner: noise 0.0 → 0.3" and history.add(second)
    by_title = {r.title: r for r in compare(first, second)}
    assert not by_title["Typed log"].changed
    assert by_title["Inductive Miner"].changes == ["Inductive Miner: noise 0.0 → 0.3"]
    assert settings_to_apply(first, miner.id)["noise"] == 0.0
    check = wf.add(soundness)
    wf.connect(miner, check)
    third = take(wf, _run(wf), history.latest)
    assert third.label == "+ Soundness"
    for _ in range(LIMIT + 5):
        history.add(Snapshot(f"t{_}", settings={"n": {"x": _}}))
    assert len(history.snapshots) == LIMIT


def test_the_history_travels_with_the_workflow_file(tmp_path):
    wf = Workflow("Kept")
    log = wf.add(typed_log, {"text": "[<a,b>^2]"})
    run = _run(wf)
    history = History()
    history.add(take(wf, run, None))
    path = tmp_path / "kept.cpnflow"
    save(wf, path, run, tmp_path, lock=False, history=history.to_dict())
    again, record = load(path, wf.library)
    restored = History.from_dict(record.history)
    assert len(restored.snapshots) == 1 and restored.latest.label == "First run"
    assert restored.latest.figures[log.id] == ("2 cases", "4 events")
