"""Checking answers.

Each answer block is checked by :func:`check` against what the block says
is right.  The right answer can be written into the block (``answer: {a,
b}``) or *computed* from the exercise's own files (``compute: alpha.T_I``),
so an exercise about a log does not need its answers worked out by hand,
and changing the log changes the answers with it.

Computed values (:data:`COMPUTED`)
----------------------------------
Of the exercise's log (``log.txt`` / ``log.xes`` / ``log.csv``):
``activities`` (T_L), ``start activities`` (T_I), ``end activities``
(T_O), ``alpha.T_L``, ``alpha.T_I``, ``alpha.T_O``, ``alpha.X_L``,
``alpha.Y_L`` (the steps of the α-algorithm).

Of the exercise's net (``net.pnml``, or the file given with ``of:``):
``wf-net``, ``sound``, ``option to complete``, ``proper completion``,
``no dead transitions``, ``dead transitions`` (their labels), ``bounded``,
``safe``, ``live``, ``deadlock-free``, ``reversible``, ``free-choice``,
``well-structured``, ``s-coverable``, ``fitness`` (token-based replay of the
log on the net).

Of the exercise's transition system (``ts.txt``):
``regions``, ``minimal regions``, ``ger(e)``, ``pre-regions(e)``,
``post-regions(e)`` (the minimal ones), ``region({s1, s3})`` (yes or no),
``elementary``, ``state separation``, ``forward closure``.

A check returns a :class:`Result`: right or not, a sentence that says why
without giving the answer away, and for a footprint the cells that are wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from . import answers
from .answers import AnswerSyntaxError
from .pack import Exercise
from .sheet import Task

CORRECT, INCORRECT, PARTIAL, UNKNOWN = "correct", "incorrect", "partial", "unknown"

YES = {"yes", "y", "true", "ja", "1"}
NO = {"no", "n", "false", "nee", "0"}


@dataclass
class Result:
    status: str
    message: str
    #: Footprint cells that are wrong, as (row activity, column activity).
    wrong_cells: list[tuple[str, str]] = field(default_factory=list)
    #: For a net: the comparison with the model answer (cpnpy.mining.compare_nets).
    comparison: object | None = None

    @property
    def correct(self) -> bool:
        return self.status == CORRECT


class TaskError(ValueError):
    """The answer block cannot be checked (a missing file, an unknown compute)."""


# ---------------------------------------------------------------------------
# What the exercise gives
# ---------------------------------------------------------------------------
class Context:
    """The exercise's files, read once and only when a check needs them."""

    def __init__(self, exercise: Exercise) -> None:
        self.exercise = exercise
        self.files = exercise.files

    def path(self, name: str | None, default: Path | None, what: str) -> Path:
        if name:
            path = self.files.file(name)
            if path is None:
                raise TaskError(f"the exercise has no file “{name}”")
            return path
        if default is None:
            raise TaskError(f"the exercise has no {what}")
        return default

    def simple_log(self, name: str | None = None):
        from ..mining.csv_import import guess_mapping, read_csv, sniff
        from ..mining.log import parse_simple_log
        from ..mining.xes import read_xes
        path = self.path(name, self.files.log, "log (log.txt, log.xes or log.csv)")
        lower = path.name.lower()
        if lower.endswith(".txt"):
            return parse_simple_log(path.read_text(encoding="utf-8", errors="replace"))
        if lower.endswith(".csv"):
            log = read_csv(str(path), guess_mapping(sniff(str(path))[1]))
        else:
            log = read_xes(str(path))
        return log.simple_log()

    def net(self, name: str | None = None):
        from ..mining.pnml import read_pnml
        return read_pnml(str(self.path(name, self.files.net, "net (net.pnml)")))

    def ts(self, name: str | None = None):
        from ..mining.transition_system import parse_transition_system
        path = self.path(name, self.files.ts, "transition system (ts.txt)")
        return parse_transition_system(path.read_text(encoding="utf-8", errors="replace"))

    @cached_property
    def alpha(self):
        from ..mining.discovery.alpha import alpha_miner
        return alpha_miner(self.simple_log())


def _soundness(net):
    from ..mining.analysis import check_soundness
    return check_soundness(net, max_states=50_000)


def _structure(net):
    from ..mining.analysis import check_workflow_net
    from ..mining.structure import check_structure
    workflow = check_workflow_net(net)
    if not workflow.is_workflow_net:
        raise TaskError("the net is not a WF-net, so this structural property is not defined")
    return check_structure(net, workflow.source, workflow.sink)


def _properties(net):
    from ..mining.analysis import analyse, check_workflow_net
    from ..mining.petrinet import Marking
    if not net.initial_marking:
        workflow = check_workflow_net(net)
        if workflow.is_workflow_net:
            net = net.copy()
            net.initial_marking = Marking({workflow.source: 1})
    return analyse(net, max_states=50_000)


def _labels(net, ids) -> frozenset:
    return frozenset(net.transitions[t].label or net.transitions[t].name or t for t in ids)


def _regions(ts):
    from ..mining.regions import analyse_regions
    return analyse_regions(ts)


def _event_regions(ts, event: str):
    analysis = _regions(ts)
    for key, regions in analysis.by_event.items():
        if answers.name(key) == answers.name(event):
            return regions
    raise TaskError(f"the transition system has no event “{event}”")


#: compute name -> function(context, argument, task) -> bool | number | set
COMPUTED = {
    "activities": lambda c, a, t: frozenset(c.alpha.T_L),
    "start activities": lambda c, a, t: frozenset(c.alpha.T_I),
    "end activities": lambda c, a, t: frozenset(c.alpha.T_O),
    "alpha.t_l": lambda c, a, t: frozenset(c.alpha.T_L),
    "alpha.t_i": lambda c, a, t: frozenset(c.alpha.T_I),
    "alpha.t_o": lambda c, a, t: frozenset(c.alpha.T_O),
    "alpha.x_l": lambda c, a, t: frozenset(c.alpha.X_L),
    "alpha.y_l": lambda c, a, t: frozenset(c.alpha.Y_L),
    "wf-net": lambda c, a, t: _wf(c.net(t.get("of"))),
    "sound": lambda c, a, t: _soundness(c.net(t.get("of"))).sound,
    "option to complete": lambda c, a, t: _soundness(c.net(t.get("of"))).option_to_complete,
    "proper completion": lambda c, a, t: _soundness(c.net(t.get("of"))).proper_completion,
    "no dead transitions": lambda c, a, t: _soundness(c.net(t.get("of"))).no_dead_transitions,
    "dead transitions": lambda c, a, t: _dead(c.net(t.get("of"))),
    "bounded": lambda c, a, t: _properties(c.net(t.get("of"))).bounded,
    "safe": lambda c, a, t: _properties(c.net(t.get("of"))).safe,
    "deadlock-free": lambda c, a, t: _properties(c.net(t.get("of"))).deadlock_free,
    "live": lambda c, a, t: _live(c.net(t.get("of"))),
    "reversible": lambda c, a, t: _properties(c.net(t.get("of"))).reversible,
    "free-choice": lambda c, a, t: _free_choice(c.net(t.get("of"))),
    "well-structured": lambda c, a, t: _structure(c.net(t.get("of"))).well_structured,
    "s-coverable": lambda c, a, t: _structure(c.net(t.get("of"))).s_coverable,
    "fitness": lambda c, a, t: _fitness(c, t),
    "regions": lambda c, a, t: frozenset(_regions(c.ts(t.get("of"))).regions),
    "minimal regions": lambda c, a, t: frozenset(_regions(c.ts(t.get("of"))).minimal),
    "ger": lambda c, a, t: _event_regions(c.ts(t.get("of")), a).ger,
    "pre-regions": lambda c, a, t: frozenset(
        _event_regions(c.ts(t.get("of")), a).minimal_pre),
    "post-regions": lambda c, a, t: frozenset(
        _event_regions(c.ts(t.get("of")), a).minimal_post),
    "region": lambda c, a, t: _is_region(c.ts(t.get("of")), a),
    "elementary": lambda c, a, t: _regions(c.ts(t.get("of"))).elementary,
    "state separation": lambda c, a, t: _regions(c.ts(t.get("of"))).state_separation,
    "forward closure": lambda c, a, t: _regions(c.ts(t.get("of"))).forward_closure,
}


def _wf(net) -> bool:
    from ..mining.analysis import check_workflow_net
    return check_workflow_net(net).is_workflow_net


def _dead(net) -> frozenset:
    """Transitions that never fire from the net's marking (a WF-net: from [i])."""
    return _labels(net, _properties(net).dead_transitions)


def _free_choice(net) -> bool:
    """Structural, so any net (not only a WF-net) has an answer."""
    from ..mining.structure import free_choice_violations
    return not free_choice_violations(net)


def _live(net):
    report = _properties(net)
    if report.live_transitions is None:
        return None
    return set(report.live_transitions) == set(net.transitions)


def _fitness(context: Context, task: Task) -> float:
    from ..mining.conformance.token_replay import token_replay
    return token_replay(context.net(task.get("of")), context.simple_log(task.get("log"))).fitness


def _is_region(ts, argument: str) -> bool:
    from ..mining.regions import check_region
    states = answers.readings(argument)[-1]
    known = {answers.name(s): s for s in ts.states}
    unknown = [s for s in states if s not in known]
    if unknown:
        raise TaskError("not states of the transition system: " + ", ".join(sorted(unknown)))
    return check_region(ts, {known[s] for s in states}).is_region


_CALL = re.compile(r"^([\w.\- ]+?)\s*\((.*)\)\s*$")


def compute(context: Context, task: Task):
    """The value of the block's ``compute:``."""
    expression = task.get("compute", "").strip()
    match = _CALL.match(expression)
    key, argument = (match.group(1), match.group(2)) if match else (expression, "")
    key = " ".join(key.split()).casefold()
    if key not in COMPUTED:
        raise TaskError(f"unknown compute “{expression}” (known: "
                        + ", ".join(sorted(COMPUTED)) + ")")
    value = COMPUTED[key](context, argument, task)
    if value is None:
        raise TaskError(f"“{expression}” could not be decided for this exercise "
                        "(the state space is too large)")
    return value


def expected(context: Context, task: Task):
    """The right answer of a set, number or yes/no block, from ``answer`` or ``compute``."""
    if "compute" in task.settings:
        return compute(context, task)
    if "answer" not in task.settings:
        raise TaskError("the block has neither an answer nor a compute")
    return task.settings["answer"]


def _yes_no(value) -> bool:
    if isinstance(value, bool):
        return value
    text = answers.name(str(value))
    if text in YES:
        return True
    if text in NO:
        return False
    raise TaskError(f"“{value}” is not yes or no")


# ---------------------------------------------------------------------------
# The checks, one per type
# ---------------------------------------------------------------------------
def check(exercise: Exercise, task: Task, answer, context: Context | None = None) -> Result:
    """Is ``answer`` (as the answer box stores it) right for ``task``?"""
    context = context or Context(exercise)
    checker = {"set": _check_set, "number": _check_number, "yesno": _check_yesno,
               "choice": _check_choice, "text": _check_text, "footprint": _check_footprint,
               "trace": _check_trace, "net": _check_net}.get(task.type)
    if checker is None:
        return Result(UNKNOWN, "Compare your answer with the model answer.")
    if answer in (None, "", [], {}):
        return Result(UNKNOWN, "Answer first, then check.")
    try:
        return checker(context, task, answer)
    except AnswerSyntaxError as error:
        return Result(UNKNOWN, f"Could not read your answer: {error}.")


def _check_set(context, task, answer) -> Result:
    right = answers.normalised(expected(context, task))
    right = answers.as_set(right) if isinstance(right, str) else frozenset(right)
    options = answers.readings(str(answer))
    if right in options:
        return Result(CORRECT, f"Right: {len(right)} item{'s' * (len(right) != 1)}.")
    nested = all(isinstance(x, frozenset | tuple) for x in right)

    def fit(reading) -> tuple:
        same_kind = all(isinstance(x, frozenset | tuple) == nested for x in reading)
        return len(reading & right), same_kind
    mine = max(options, key=fit)
    hits, extra = len(mine & right), len(mine - right)
    missing = len(right - mine)
    parts = []
    if hits:
        parts.append(f"{hits} of your items {'is' if hits == 1 else 'are'} right")
    if extra:
        parts.append(f"{extra} {'does' if extra == 1 else 'do'} not belong")
    if missing:
        parts.append(f"{missing} {'is' if missing == 1 else 'are'} missing")
    return Result(PARTIAL if hits else INCORRECT, "Not yet: " + ", ".join(parts) + ".")


def _check_number(context, task, answer) -> Result:
    right = expected(context, task)
    right = float(right) if not isinstance(right, str) else answers.number(right)
    try:
        mine = answers.number(str(answer))
    except (ValueError, ZeroDivisionError):
        return Result(UNKNOWN, "That is not a number.")
    tolerance = float(task.get("tolerance") or 0) or max(1e-9, abs(right) * 1e-6)
    if task.get("tolerance") is None and "compute" in task.settings:
        tolerance = 0.005                       # a computed figure: two decimals will do
    if abs(mine - right) <= tolerance:
        return Result(CORRECT, "Right.")
    return Result(INCORRECT, "Not yet: " + ("too high." if mine > right else "too low."))


def _check_yesno(context, task, answer) -> Result:
    right = _yes_no(expected(context, task))
    if _yes_no(answer) == right:
        return Result(CORRECT, "Right.")
    return Result(INCORRECT, "Not right.")


def _check_choice(context, task, answer) -> Result:
    chosen = set(answer if isinstance(answer, list) else [answer])
    right = {i for i, option in enumerate(task.options) if option.correct}
    if chosen == right:
        return Result(CORRECT, "Right.")
    if len(right) > 1 and chosen & right:
        return Result(PARTIAL, f"Not yet: {len(chosen & right)} of the {len(right)} right "
                               "options, " + (f"and {len(chosen - right)} wrong one"
                                              f"{'s' * (len(chosen - right) != 1)}"
                                              if chosen - right else "but not all"))
    return Result(INCORRECT, "Not right.")


def _check_text(context, task, answer) -> Result:
    mine = answers.name(str(answer))
    pattern = task.get("pattern")
    if pattern and re.fullmatch(pattern, str(answer).strip(), re.I):
        return Result(CORRECT, "Right.")
    accepted = ([task.settings["answer"]] if "answer" in task.settings else []) \
        + task.alternatives
    if any(answers.name(a) == mine for a in accepted):
        return Result(CORRECT, "Right.")
    return Result(INCORRECT, "Not right.")


def footprint_of(context: Context, task: Task):
    """The footprint the block asks for: of the log, or of a net (``of: net.pnml``)."""
    from ..mining.footprint import footprint_of_log, footprint_of_net
    source = task.get("of")
    if source and source.lower().endswith(".pnml"):
        return footprint_of_net(context.net(source))
    return footprint_of_log(context.simple_log(source if source and source != "log" else None))


def _check_footprint(context, task, answer) -> Result:
    footprint = footprint_of(context, task)
    wrong, blank = [], 0
    for a in footprint.activities:
        for b in footprint.activities:
            mine = answer.get(f"{a}\t{b}") if isinstance(answer, dict) else None
            if not mine:
                blank += 1
                wrong.append((a, b))
            elif mine != footprint.relation(a, b):
                wrong.append((a, b))
    cells = len(footprint.activities) ** 2
    if not wrong:
        return Result(CORRECT, f"Right: all {cells} cells.")
    filled_wrong = len(wrong) - blank
    message = f"{cells - len(wrong)} of {cells} cells are right"
    if filled_wrong:
        message += f"; {filled_wrong} {'is' if filled_wrong == 1 else 'are'} wrong (marked)"
    if blank:
        message += f"; {blank} {'is' if blank == 1 else 'are'} still empty"
    return Result(PARTIAL if cells - len(wrong) else INCORRECT, message + ".",
                  wrong_cells=wrong)


def _check_trace(context, task, answer) -> Result:
    """A firing sequence of the net that ends as ``ends:`` says."""
    from ..mining.analysis import check_workflow_net, reachability_graph
    from ..mining.compare_nets import replayable_prefix
    from ..mining.petrinet import Marking
    steps = answers.trace(str(answer))
    net = context.net(task.get("net") or task.get("of"))
    if not net.initial_marking:
        workflow = check_workflow_net(net)
        if workflow.is_workflow_net:
            net.initial_marking = Marking({workflow.source: 1})
            net.final_marking = net.final_marking or Marking({workflow.sink: 1})
    path, done = replayable_prefix(net, steps)
    if done < len(steps):
        return Result(INCORRECT, f"The net can do the first {done} step"
                      f"{'s' * (done != 1)}, but then “{steps[done]}” is not enabled.")
    marking = net.initial_marking
    for transition in path:
        marking = net.fire(marking, transition)
    ends = (task.get("ends") or "any").lower()
    final = net.final_marking or None
    if ends == "any":
        ok, why = True, "it can be fired"
    elif ends == "final":
        ok, why = final is not None and marking == final, "it ends in the final marking"
    elif ends == "deadlock":
        ok = not net.enabled(marking) and marking != final
        why = "nothing is enabled at its end and the case has not completed"
    elif ends in ("stuck", "no completion", "cannot complete"):
        graph = reachability_graph(net, marking, max_states=50_000)
        ok = final is not None and final not in graph.states and not graph.truncated
        why = "after it, the final marking can no longer be reached"
    elif ends in ("improper", "improper completion"):
        ok = final is not None and all(marking[p] >= n for p, n in final.items()) \
            and marking != final
        why = "it puts a token in the sink while other tokens are left behind"
    else:
        raise TaskError(f"unknown “ends: {ends}” (use any, final, deadlock, stuck or "
                        "improper)")
    if ok:
        return Result(CORRECT, f"Right: {why}.")
    return Result(INCORRECT, f"The net can fire it, but it is not what is asked: {why} "
                             "does not hold at its end.")


def _check_net(context, task, answer) -> Result:
    """``answer`` is the student's net (a PetriNet)."""
    from ..mining.compare_nets import compare_nets
    net = answer
    problems: list[str] = []
    comparison = None
    if task.get("sound") is not None and _yes_no(task.get("sound")):
        report = _soundness(net)
        if not report.workflow.is_workflow_net:
            problems.append("it is not a WF-net (" + "; ".join(report.workflow.problems[:1])
                            + ")")
        elif report.sound is False:
            problems.append("it is not sound: " + (report.findings[0] if report.findings
                                                   else "a soundness condition fails"))
        elif report.sound is None:
            problems.append("its soundness could not be decided (too many states)")
    if task.get("fits") is not None:
        from ..mining.conformance.token_replay import token_replay
        source = task.get("fits")
        log = context.simple_log(None if source.lower() in ("log", "yes", "") else source)
        replay = token_replay(_with_start(net), log)
        if replay.fitting_traces < replay.trace_count:
            problems.append(f"it replays {replay.fitting_traces} of the "
                            f"{replay.trace_count} traces of the log without problems")
    target = task.get("answer")
    if target:
        model = _model_answer(context, target)
        comparison = compare_nets(net, model)
        if not comparison.equivalent:
            problems.append("it does not allow the same complete traces as the model answer")
    if not any(task.get(k) for k in ("sound", "fits", "answer")):
        return Result(UNKNOWN, "Nothing to check this net against: compare it with the "
                               "model answer yourself.")
    if problems:
        return Result(INCORRECT, "Not yet: " + "; ".join(problems) + ".",
                      comparison=comparison)
    good = []
    if target:
        good.append("same behaviour as the model answer")
    if task.get("sound"):
        good.append("sound")
    if task.get("fits"):
        good.append("replays every trace of the log")
    return Result(CORRECT, "Right: " + ", ".join(good) + ".", comparison=comparison)


def _with_start(net):
    from ..mining.analysis import check_workflow_net
    from ..mining.petrinet import Marking
    if net.initial_marking:
        return net
    workflow = check_workflow_net(net)
    if workflow.is_workflow_net:
        net = net.copy()
        net.initial_marking = Marking({workflow.source: 1})
        net.final_marking = net.final_marking or Marking({workflow.sink: 1})
    return net


def _model_answer(context: Context, target: str):
    """``answer.pnml``, or a net discovered from the log (``alpha``, ``inductive``)."""
    kind = target.strip().casefold()
    if kind in ("alpha", "alpha(log)", "α"):
        return context.alpha.net
    if kind in ("inductive", "inductive(log)", "im"):
        from ..mining.discovery.inductive import inductive_miner
        return inductive_miner(context.simple_log()).net
    return context.net(target)


def model_answer_text(exercise: Exercise, task: Task, context: Context | None = None) -> str:
    """The right answer in words, for *Show answer* (the block's ``solution`` first)."""
    if task.solution:
        return task.solution
    context = context or Context(exercise)
    try:
        if task.type in ("set", "number", "yesno"):
            value = expected(context, task)
            if task.type == "yesno":
                return "Yes." if _yes_no(value) else "No."
            if task.type == "number":
                return f"{float(value):.3g}" if not isinstance(value, str) else value
            value = answers.normalised(value)
            value = answers.as_set(value) if isinstance(value, str) else frozenset(value)
            return answers.show_set(value)
        if task.type == "choice":
            return "; ".join(o.text for o in task.options if o.correct) + "."
        if task.type == "text":
            return task.settings.get("answer") or (task.alternatives[0] if task.alternatives
                                                   else "")
    except TaskError as error:
        return f"(The answer could not be worked out: {error}.)"
    return ""


def validate(exercise: Exercise) -> list[str]:
    """Problems with the exercise's answer blocks (for authors: ``cpnpy exercises check``)."""
    problems = []
    if exercise.error:
        problems.append(exercise.error)
    context = Context(exercise)
    for task in exercise.sheet.tasks:
        where = f"answer block “{task.id}” (line {task.line})" if task.line else \
            f"answer “{task.id}”"
        try:
            if task.type in ("set", "number", "yesno") and task.checkable:
                expected(context, task)
                if task.type == "yesno":
                    _yes_no(expected(context, task))
            elif task.type == "footprint":
                footprint_of(context, task)
            elif task.type == "trace":
                context.net(task.get("net") or task.get("of"))
            elif task.type == "net":
                if task.get("answer"):
                    _model_answer(context, task.get("answer"))
                if task.get("start") and task.get("start").lower() != "empty" \
                        and exercise.files.file(task.get("start")) is None:
                    raise TaskError(f"the exercise has no file “{task.get('start')}”")
            if not task.checkable and task.type not in ("open",) and not task.solution:
                problems.append(f"{where}: nothing to check against and no solution")
        except TaskError as error:
            problems.append(f"{where}: {error}")
        except Exception as error:  # noqa: BLE001 - report, do not crash the listing
            problems.append(f"{where}: {type(error).__name__}: {error}")
    return problems
