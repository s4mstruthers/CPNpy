"""Transition systems: the first phase of two-phase discovery.

A **transition system** is ``TS = (S, E, T, s_in)``: states ``S``, events
``E``, transitions ``T ⊆ S × E × S`` and an initial state ``s_in``.  It is the
simplest model of a process: the states are drawn as circles, every
transition as an arrow labelled with its event.  It has no concurrency, so a
process where *a* and *b* can happen in either order needs a diamond.

From an event log (van der Aalst, *Process Mining*, Section 7.4.1)
-----------------------------------------------------------------
Each event in a trace happens in a *state*, and the **state function**
decides what that state is.  It looks at the events before it (the
*prefix*), the events still to come (the *postfix*), or both, and abstracts
them in two steps:

1. the **horizon** ``k`` keeps only the last ``k`` events of the prefix (the
   first ``k`` of the postfix), or all of them;
2. the **representation** turns that into a state: the **sequence** itself
   (``⟨a,d⟩``), the **multiset** (``[a, d^2]``, order forgotten) or the
   **set** (``{a,d}``, order and frequency forgotten).

Every trace then walks from state to state, one event at a time, and the
transition system is the union of those walks.  Coarser abstractions (a
set, a short horizon) give fewer states and generalise more; the sequence
with no horizon gives a tree that allows exactly the log.

The prefix of the first event is empty, so with the prefix every trace starts
in the same state.  The postfix of the first event is the whole trace, so
the postfix gives each distinct trace its own start state.

Typed transition systems
------------------------
Exercises often start from a transition system rather than a log.
:func:`parse_transition_system` reads one written as text::

    s0 -a-> s1, s0 -b-> s2
    s1 -c-> s3
    initial: s0

Everything here is pure standard library, like the rest of
:mod:`openprocess.mining`.
"""

from __future__ import annotations

import re
from collections import Counter, deque
from dataclasses import dataclass, field

from .log import SimpleLog

#: The parts of a trace the state function can look at.
DIRECTIONS = ("prefix", "postfix", "both")
#: How the events in view become a state.
REPRESENTATIONS = ("sequence", "multiset", "set")


@dataclass
class TransitionSystem:
    """``(S, E, T, s_in)`` with states named by strings.

    ``initial`` is a list because a transition system built from the
    postfix of a log has one start state per distinct trace; region theory
    needs exactly one (:attr:`initial_state`).  ``final`` lists the states
    in which a trace of the log ended (empty for a typed system unless given).
    """

    states: list[str] = field(default_factory=list)
    transitions: list[tuple[str, str, str]] = field(default_factory=list)
    initial: list[str] = field(default_factory=list)
    final: list[str] = field(default_factory=list)
    name: str = "Transition system"
    #: For a transition system built from a log: each variant (sequence,
    #: number of cases) with the states it passes through, in order.
    traces: list[tuple[tuple[str, ...], int, list[str]]] = field(default_factory=list)
    #: How it was made, e.g. ``"set of the prefix, last 2 events"``.
    abstraction: str = ""

    # -- construction --------------------------------------------------------------------
    def add_state(self, state: str) -> str:
        if state not in self._state_set():
            self.states.append(state)
            self._states_cache.add(state)
        return state

    def add_transition(self, source: str, event: str, target: str) -> None:
        self.add_state(source)
        self.add_state(target)
        step = (source, event, target)
        if step not in self._transition_set():
            self.transitions.append(step)
            self._transitions_cache.add(step)

    def _state_set(self) -> set[str]:
        cache = getattr(self, "_states_cache", None)
        if cache is None or len(cache) != len(self.states):
            self._states_cache = set(self.states)
        return self._states_cache

    def _transition_set(self) -> set[tuple[str, str, str]]:
        cache = getattr(self, "_transitions_cache", None)
        if cache is None or len(cache) != len(self.transitions):
            self._transitions_cache = set(self.transitions)
        return self._transitions_cache

    # -- queries -------------------------------------------------------------------------
    @property
    def events(self) -> list[str]:
        """The events, in the order they first appear."""
        seen: dict[str, None] = {}
        for _, event, _ in self.transitions:
            seen.setdefault(event, None)
        return list(seen)

    @property
    def initial_state(self) -> str | None:
        """``s_in``, when there is exactly one initial state."""
        return self.initial[0] if len(self.initial) == 1 else None

    def transitions_of(self, event: str) -> list[tuple[str, str]]:
        """``(source, target)`` of every transition labelled ``event``."""
        return [(s, t) for s, e, t in self.transitions if e == event]

    def successors(self, state: str) -> list[tuple[str, str]]:
        return [(e, t) for s, e, t in self.transitions if s == state]

    def reachable(self) -> set[str]:
        """The states reachable from the initial state(s)."""
        seen = set(self.initial)
        queue = deque(self.initial)
        outgoing: dict[str, list[str]] = {}
        for s, _, t in self.transitions:
            outgoing.setdefault(s, []).append(t)
        while queue:
            state = queue.popleft()
            for target in outgoing.get(state, []):
                if target not in seen:
                    seen.add(target)
                    queue.append(target)
        return seen

    def summary(self) -> str:
        def count(number: int, noun: str) -> str:
            return f"{number} {noun}{'' if number == 1 else 's'}"
        return (f"{count(len(self.states), 'state')}, {count(len(self.events), 'event')}, "
                f"{count(len(self.transitions), 'transition')}")

    def to_text(self) -> str:
        """The notation :func:`parse_transition_system` reads."""
        lines = [f"{s} -{e}-> {t}" for s, e, t in self.transitions]
        lonely = [s for s in self.states
                  if not any(s in (a, b) for a, _, b in self.transitions)]
        if lonely:
            lines.append("states: " + ", ".join(lonely))
        if self.initial:
            lines.append("initial: " + ", ".join(self.initial))
        if self.final:
            lines.append("final: " + ", ".join(self.final))
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"<TransitionSystem {self.name!r}: {self.summary()}>"


# ---------------------------------------------------------------------------
# From an event log
# ---------------------------------------------------------------------------
def describe_abstraction(direction: str = "prefix", representation: str = "sequence",
                         horizon: int | None = None) -> str:
    """Words for a state function, e.g. ``"set of the prefix, last 2 events"``."""
    if direction == "both":
        part = "prefix and postfix"
    else:
        part = direction
    if horizon is None:
        window = "no horizon"
    else:
        noun = "event" if horizon == 1 else "events"
        window = (f"last {horizon} {noun}" if direction == "prefix" else
                  f"next {horizon} {noun}" if direction == "postfix" else
                  f"{horizon} {noun} each way")
    return f"{representation} of the {part}, {window}"


def state_label(events: tuple[str, ...], representation: str) -> str:
    """How a state is written: ``⟨a,d⟩``, ``[a,d^2]`` or ``{a,d}``."""
    if representation == "sequence":
        return "⟨" + ",".join(events) + "⟩"
    if representation == "multiset":
        counts = Counter(events)
        return "[" + ",".join(a if counts[a] == 1 else f"{a}^{counts[a]}"
                              for a in sorted(counts)) + "]"
    if representation == "set":
        return "{" + ",".join(sorted(set(events))) + "}"
    raise ValueError(f"unknown representation {representation!r}; use one of "
                     + ", ".join(REPRESENTATIONS))


def transition_system_from_log(log: SimpleLog, direction: str = "prefix",
                               representation: str = "sequence",
                               horizon: int | None = None,
                               name: str = "Transition system") -> TransitionSystem:
    """Build a transition system from a simple log with a state function.

    ``direction`` is ``"prefix"``, ``"postfix"`` or ``"both"``;
    ``representation`` is ``"sequence"``, ``"multiset"`` or ``"set"``;
    ``horizon`` is how many events to keep (``None``: all).
    """
    if direction not in DIRECTIONS:
        raise ValueError(f"unknown direction {direction!r}; use one of {', '.join(DIRECTIONS)}")
    if horizon is not None and horizon < 1:
        horizon = None

    def view(trace: tuple[str, ...], position: int) -> str:
        before, after = trace[:position], trace[position:]
        if horizon is not None:
            before, after = before[-horizon:] if horizon else (), after[:horizon]
        if direction == "prefix":
            return state_label(before, representation)
        if direction == "postfix":
            return state_label(after, representation)
        return f"({state_label(before, representation)}, {state_label(after, representation)})"

    ts = TransitionSystem(name=name, abstraction=describe_abstraction(direction, representation,
                                                                      horizon))
    variants = sorted(log.items(), key=lambda item: (-item[1], item[0]))
    for trace, count in variants:
        walk = [view(trace, position) for position in range(len(trace) + 1)]
        if walk[0] not in ts.initial:
            ts.initial.append(walk[0])
        ts.add_state(walk[0])
        for position, event in enumerate(trace):
            ts.add_transition(walk[position], event, walk[position + 1])
        if walk[-1] not in ts.final:
            ts.final.append(walk[-1])
        ts.traces.append((trace, count, walk))
    return ts


# ---------------------------------------------------------------------------
# Typed transition systems
# ---------------------------------------------------------------------------
# A state is a word, or a bracketed abstraction such as {a,d}, [a^2,b] or ⟨a,b⟩.
_STATE = r"(\{[^{}]*\}|\[[^\[\]]*\]|⟨[^⟨⟩]*⟩|\([^()]*\)|[^\s,;{}\[\]⟨⟩()]+)"
_EVENT = r"([^\s,;\-–—→>]+(?:\s+[^\s,;\-–—→>]+)*?)"
_ARROW = re.compile(_STATE + r"\s*(?:-+|–|—)\s*" + _EVENT + r"\s*(?:-+>|→|–>|—>)\s*" + _STATE)
_LATEX = re.compile(_STATE + r"\s*\\xrightarrow\{([^{}]+)\}\s*" + _STATE)
_ROLE = re.compile(r"^\s*(initial|init|start|final|end|states?)\s*[:=]\s*(.*)$", re.IGNORECASE)


def _clean_state(text: str) -> str:
    # s_0 and s_{0} (LaTeX) are both s0.
    text = text.strip()
    match = re.fullmatch(r"([A-Za-z]+)_\{?(\w+)\}?", text)
    return match.group(1) + match.group(2) if match else text


def parse_states(text: str) -> list[str]:
    """States written as a list: ``s0, s2`` or ``{a}, {a,d}`` (braces kept together)."""
    return [_clean_state(m.group(0)) for m in re.finditer(_STATE, text)]


_state_list = parse_states


def parse_transition_system(text: str, name: str = "Transition system") -> TransitionSystem:
    """Read a transition system written as text.

    Transitions are written ``source -event-> target`` (also ``--a-->``,
    ``–a→``, or LaTeX's ``s_0 \\xrightarrow{a} s_1``), separated by commas,
    semicolons or new lines.  States may be words (``s0``, ``s_1``) or
    abstractions as the log-based construction writes them (``{a,d}``,
    ``[a^2]``, ``⟨a,b⟩``).  Optional lines::

        initial: s0          (default: the source of the first transition)
        final: s7, s8
        states: s9           (states without transitions)

    Raises ``ValueError`` when no transition is found.
    """
    ts = TransitionSystem(name=name)
    initial: list[str] | None = None
    final: list[str] = []
    found = False
    for line in text.replace(";", "\n").splitlines():
        line = line.split("#", 1)[0] if not line.lstrip().startswith("#") else ""
        role = _ROLE.match(line)
        if role:
            word, states = role.group(1).lower(), _state_list(role.group(2))
            if word in ("initial", "init", "start"):
                initial = (initial or []) + states
            elif word in ("final", "end"):
                final += states
            else:
                for state in states:
                    ts.add_state(state)
            continue
        steps = list(_ARROW.finditer(line)) + list(_LATEX.finditer(line))
        steps.sort(key=lambda m: m.start())
        for step in steps:
            source, event, target = (_clean_state(step.group(1)), step.group(2).strip(),
                                     _clean_state(step.group(3)))
            ts.add_transition(source, event, target)
            found = True
    if not found:
        raise ValueError("No transitions found. Write them as  s0 -a-> s1, one per line or "
                         "separated by commas.")
    for state in (initial or []) + final:
        ts.add_state(state)
    ts.initial = initial if initial else [ts.transitions[0][0]]
    ts.final = final
    return ts


# ---------------------------------------------------------------------------
# Isomorphism
# ---------------------------------------------------------------------------
def isomorphic(first: TransitionSystem, second: TransitionSystem,
               reachable_only: bool = True) -> bool:
    """Are the two transition systems the same up to renaming states?

    Events must match exactly; initial states must map to initial states.
    With ``reachable_only`` only the parts reachable from the initial states
    are compared (what a net's reachability graph can show).
    """
    def prepare(ts: TransitionSystem):
        keep = ts.reachable() if reachable_only else set(ts.states)
        states = [s for s in ts.states if s in keep]
        edges = sorted({(s, e, t) for s, e, t in ts.transitions if s in keep})
        return states, edges, set(ts.initial)

    states1, edges1, init1 = prepare(first)
    states2, edges2, init2 = prepare(second)
    if len(states1) != len(states2) or len(edges1) != len(edges2) or len(init1) != len(init2):
        return False
    if Counter(e for _, e, _ in edges1) != Counter(e for _, e, _ in edges2):
        return False

    def refine(states, edges, init):
        """Colour refinement: states that cannot be told apart get one colour."""
        out: dict[str, list] = {s: [] for s in states}
        into: dict[str, list] = {s: [] for s in states}
        for s, e, t in edges:
            out[s].append((e, t))
            into[t].append((e, s))
        colour = {s: (s in init,) for s in states}
        for _ in range(len(states) + 1):
            new = {s: (colour[s], tuple(sorted((e, colour[t]) for e, t in out[s])),
                       tuple(sorted((e, colour[p]) for e, p in into[s]))) for s in states}
            if len(set(new.values())) == len(set(colour.values())):
                break
            colour = new
        return colour, out

    # Refine both together so the colours are comparable.
    joined_states = [("1", s) for s in states1] + [("2", s) for s in states2]
    joined_edges = [(("1", s), e, ("1", t)) for s, e, t in edges1] + \
        [(("2", s), e, ("2", t)) for s, e, t in edges2]
    joined_init = {("1", s) for s in init1} | {("2", s) for s in init2}
    colour, out = refine(joined_states, joined_edges, joined_init)
    if Counter(colour[("1", s)] for s in states1) != Counter(colour[("2", s)] for s in states2):
        return False
    edge_set2 = set(joined_edges)
    candidates = {s: [t for t in states2 if colour[("2", t)] == colour[("1", s)]] for s in states1}
    order = sorted(states1, key=lambda s: len(candidates[s]))
    mapping: dict[str, str] = {}
    used: set[str] = set()

    def consistent(s: str, t: str) -> bool:
        for e, s2 in out[("1", s)]:
            mapped = mapping.get(s2[1]) if s2[1] != s else t
            if mapped is not None and (("2", t), e, ("2", mapped)) not in edge_set2:
                return False
        return True

    def search(index: int) -> bool:
        if index == len(order):
            return all((("2", mapping[s]), e, ("2", mapping[t])) in edge_set2
                       for s, e, t in edges1)
        s = order[index]
        for t in candidates[s]:
            if t in used:
                continue
            mapping[s] = t
            used.add(t)
            if consistent(s, t) and search(index + 1):
                return True
            del mapping[s]
            used.discard(t)
        return False

    return search(0)


def transition_system_of_graph(graph, name: str | None = None) -> TransitionSystem:
    """A net's reachability graph as a transition system labelled by activities.

    States are named ``m0, m1, …`` (``m0`` the initial marking); silent
    transitions keep the label ``τ``.
    """
    net = graph.net
    ts = TransitionSystem(name=name or f"Reachability graph of {net.name}")
    for index in range(len(graph.states)):
        ts.add_state(f"m{index}")
    for source, transition, target in graph.edges:
        label = net.transitions[transition].label
        ts.add_transition(f"m{source}", label if label is not None else "τ", f"m{target}")
    ts.initial = ["m0"] if graph.states else []
    return ts
