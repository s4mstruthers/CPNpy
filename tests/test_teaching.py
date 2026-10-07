"""Exercise packs without the GUI: worksheets, reading answers, checking them."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from cpnpy.teaching import answers
from cpnpy.teaching.checks import (
    CORRECT, INCORRECT, PARTIAL, UNKNOWN, Context, check, model_answer_text, validate,
)
from cpnpy.teaching.pack import Exercise, load_pack, natural_key, pack_root
from cpnpy.teaching.sheet import SheetError, parse_sheet

DEMO = Path(__file__).resolve().parents[1] / "cpnpy" / "exercises"
ORDERS = DEMO / "1 Petri nets" / "Exercise 1.1 Order handling"
FLAW = DEMO / "2 Soundness" / "Exercise 2.1 Spot the flaw"
ALPHA = DEMO / "3 Discovery" / "Exercise 3.1 The alpha-algorithm"
REGIONS = DEMO / "4 Regions" / "Exercise 4.1 Regions of a transition system"


# -- reading answers -----------------------------------------------------------------
@pytest.mark.parametrize("typed, expected", [
    ("a, b, c", frozenset("abc")),
    ("{a,b, c}", frozenset("abc")),
    ("$\\{a, b, c\\}$", frozenset("abc")),
    ("{ A , B }", frozenset("ab")),
    ("∅", frozenset()),
])
def test_sets_are_read_leniently(typed, expected):
    assert expected in answers.readings(typed)


def test_nested_answers():
    assert answers.readings("{s1,s3}, {s2,s3}")[0] == frozenset(
        {frozenset({"s1", "s3"}), frozenset({"s2", "s3"})})
    assert frozenset({frozenset({"s1", "s3"}), frozenset({"s2", "s3"})}) in \
        answers.readings("{{s_1, s_3}, {s_{2}, s3}}")
    pairs = answers.readings("({a},{b,d}), ({b, d}, {e})")[0]
    assert (frozenset("a"), frozenset("bd")) in pairs
    assert answers.trace("⟨register, Send letter⟩") == ["register", "send letter"]
    assert answers.number("3/4") == 0.75 and answers.number("75%") == 0.75
    with pytest.raises(answers.AnswerSyntaxError):
        answers.parse("{a, b")
    with pytest.raises(answers.AnswerSyntaxError):
        answers.parse("{a} {b}")


def test_natural_order():
    names = ["Exercise 10", "Exercise 2", "exercise 1"]
    assert sorted(names, key=natural_key) == ["exercise 1", "Exercise 2", "Exercise 10"]


# -- the worksheet format ----------------------------------------------------------------
SHEET = """# My exercise

Intro text.

a. Pick one.

```answer
type: choice
- [x] right
- [ ] wrong
solution: Because
  it is right.
```

b. Name it.

```answer
id: name
answer: Alpha
- the alpha miner
```
"""


def test_a_sheet_is_markdown_with_answer_boxes():
    sheet = parse_sheet(SHEET)
    assert sheet.title == "My exercise"
    first, second = sheet.tasks
    assert first.type == "choice" and first.id == "q1" and [o.correct for o in
                                                             first.options] == [True, False]
    assert first.solution == "Because\nit is right."
    assert first.prompt == "a. Pick one."
    assert second.type == "text" and second.id == "name"
    assert second.alternatives == ["the alpha miner"]
    assert [type(b).__name__ for b in sheet.blocks] == ["str", "Task", "str", "Task"]


@pytest.mark.parametrize("block, message", [
    ("```answer\ntype: essay\n```", "needs a type"),
    ("```answer\ntype: set\ncolour: red\n```", "unknown key"),
    ("```answer\ntype: choice\n```", "needs options"),
    ("```answer\ntype: set\n", "not closed"),
    ("```answer\nid: x\ntype: open\n```\n```answer\nid: x\ntype: open\n```", "same id"),
])
def test_mistakes_in_a_sheet_are_reported(block, message):
    with pytest.raises(SheetError, match=message):
        parse_sheet(block)


# -- the demo pack --------------------------------------------------------------------------
def test_the_demo_pack():
    pack = load_pack(DEMO)
    assert pack.title == "CPNpy demo exercises"
    assert [e.folder.name for e in pack.exercises] == [
        ORDERS.name, FLAW.name, ALPHA.name, REGIONS.name]
    assert [name for name, _ in pack.chapters()] == [
        "1 Petri nets", "2 Soundness", "3 Discovery", "4 Regions"]
    assert pack_root(ALPHA) == DEMO.resolve()
    for exercise in pack.exercises:
        assert exercise.error is None
        assert validate(exercise) == [], exercise.title
        assert exercise.sheet.tasks


def test_computed_answers_are_checked():
    exercise = Exercise.at(ALPHA)
    tasks = {t.get("compute"): t for t in exercise.sheet.tasks if t.get("compute")}
    context = Context(exercise)
    assert check(exercise, tasks["alpha.T_I"], "a", context).status == CORRECT
    assert check(exercise, tasks["alpha.T_L"], "{a,b,c,d}", context).status == PARTIAL
    assert check(exercise, tasks["alpha.T_O"], "{x}", context).status == INCORRECT
    y_l = "({a},{b,d}), ({a},{c,d}), ({b,d},{e}), ({c,d},{e})"
    assert check(exercise, tasks["alpha.Y_L"], y_l, context).correct
    result = check(exercise, tasks["alpha.Y_L"], "({a},{b}), ({a},{c,d})", context)
    assert result.status == PARTIAL and "1 of your items is right" in result.message
    assert check(exercise, tasks["alpha.Y_L"], "", context).status == UNKNOWN
    assert "({a}, {b, d})" in model_answer_text(exercise, tasks["alpha.Y_L"], context)


def test_footprint_check_marks_the_wrong_cells():
    from cpnpy.mining import footprint_of_log, parse_simple_log
    exercise = Exercise.at(ALPHA)
    task = next(t for t in exercise.sheet.tasks if t.type == "footprint")
    footprint = footprint_of_log(parse_simple_log((ALPHA / "log.txt").read_text()))
    cells = {f"{a}\t{b}": footprint.relation(a, b) for a in footprint.activities
             for b in footprint.activities}
    assert check(exercise, task, cells).correct
    cells["b\tc"] = "→"
    del cells["e\te"]
    result = check(exercise, task, cells)
    assert result.status == PARTIAL
    assert set(result.wrong_cells) == {("b", "c"), ("e", "e")}
    assert "1 is wrong" in result.message and "1 is still empty" in result.message


def test_soundness_questions():
    exercise = Exercise.at(FLAW)
    wf, sound, conditions, deadlock, repair = exercise.sheet.tasks
    assert check(exercise, wf, "yes").correct and not check(exercise, sound, "yes").correct
    assert check(exercise, conditions, [0, 2]).correct
    assert check(exercise, conditions, [0]).status == PARTIAL
    assert check(exercise, deadlock, "register, send letter").correct
    result = check(exercise, deadlock, "register, archive")
    assert not result.correct and "“archive” is not enabled" in result.message
    assert not check(exercise, deadlock, "register").correct     # not a deadlock yet

    from cpnpy.mining.pnml import read_pnml
    given = read_pnml(str(FLAW / "net.pnml"))
    result = check(exercise, repair, given)
    assert result.status == INCORRECT and "not sound" in result.message
    assert check(exercise, repair, read_pnml(str(FLAW / "answer.pnml"))).correct


def test_a_net_against_a_discovered_model(tmp_path):
    exercise = Exercise.at(ALPHA)
    task = next(t for t in exercise.sheet.tasks if t.type == "net")
    from cpnpy.mining import alpha_miner, inductive_miner, parse_simple_log
    log = parse_simple_log((ALPHA / "log.txt").read_text())
    assert check(exercise, task, alpha_miner(log).net).correct
    sequence = inductive_miner(parse_simple_log("[<a,b,c,e>]")).net
    assert not check(exercise, task, sequence).correct


def test_regions_questions():
    exercise = Exercise.at(REGIONS)
    tasks = exercise.sheet.tasks
    assert check(exercise, tasks[0], "yes").correct           # {s1, s3} is a region
    assert check(exercise, tasks[1], "no").correct            # {s3, s4} is not
    assert check(exercise, tasks[2], "{s1,s3}, {s2, s3}").correct
    assert check(exercise, tasks[3], "{s4, s5}").correct      # one set: braces optional
    assert check(exercise, tasks[5], "no").correct            # state separation fails


def test_progress_is_kept_in_the_folder(tmp_path):
    folder = tmp_path / "ex"
    shutil.copytree(ALPHA, folder)
    exercise = Exercise.at(folder)
    assert exercise.summary().state == "new"
    first = exercise.sheet.tasks[1]
    exercise.save_progress({first.id: {"answer": "a, b", "status": "correct"}})
    again = Exercise.at(folder)
    assert again.load_progress()[first.id]["answer"] == "a, b"
    assert again.summary().state == "started" and again.summary().done == 1
    exercise.reset()
    assert not (folder / "my answers.json").exists()


def test_an_old_style_exercise_still_works(tmp_path):
    """No answer blocks: a net to draw against answer.pnml, or answer.md to compare with."""
    folder = tmp_path / "old"
    folder.mkdir()
    (folder / "question.md").write_text("# Old\n\nDraw it.")
    shutil.copy(ORDERS / "answer.pnml", folder / "answer.pnml")
    exercise = Exercise.at(folder)
    (task,) = exercise.sheet.tasks
    assert task.type == "net" and task.get("answer") == "answer.pnml"
    (folder / "answer.pnml").unlink()
    (folder / "answer.md").write_text("The answer.")
    (task,) = Exercise.at(folder).sheet.tasks
    assert task.type == "open" and task.solution == "The answer."


def test_comments_in_a_block():
    (task,) = parse_sheet("```answer\ntype: net\nstart: net.pnml   # where to begin\n```").tasks
    assert task.get("start") == "net.pnml"


def test_the_command_line_checks_a_pack(tmp_path, capsys):
    from cpnpy.cli import main
    assert main(["exercises", "check", str(DEMO), "--answers"]) == 0
    out = capsys.readouterr().out
    assert "No problems found." in out and "({a}, {b, d})" in out
    broken = tmp_path / "Ex"
    broken.mkdir()
    (broken / "question.md").write_text("```answer\ntype: set\ncompute: alpha.Q\n```\n")
    assert main(["exercises", "check", str(tmp_path)]) == 1
    assert "unknown compute" in capsys.readouterr().out
