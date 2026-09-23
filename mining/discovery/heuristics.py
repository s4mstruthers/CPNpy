"""Heuristics Miner: frequency-aware dependency graphs (Weijters & van der Aalst).

Where the α-algorithm asks the yes/no question "does a ever directly precede
b?", the Heuristics Miner asks *how strongly* the log supports ``a`` causing
``b``, using counts ``|a >_L b|`` (how often b directly follows a):

Dependency measure, for ``a ≠ b``::

             |a > b| − |b > a|
    a ⇒ b = ───────────────────        value in (−1, 1)
             |a > b| + |b > a| + 1

It is close to 1 when b follows a often and a almost never follows b, close
to 0 when both orders are equally common (concurrency, or noise), negative
when the dependency is the other way round.  The ``+ 1`` damps small counts:
one occurrence gives only 0.5, a hundred give 0.99.

Length-one loop (``a`` directly followed by itself)::

    a ⇒ a = |a > a| / (|a > a| + 1)

Length-two loop (``a b a`` patterns, counted as ``|a >> b|``)::

    a ⇒2 b = (|a >> b| + |b >> a|) / (|a >> b| + |b >> a| + 1)

An edge ``a → b`` is kept when ``a ⇒ b`` reaches the *dependency threshold*
and ``|a > b|`` reaches the *positive observations* threshold.  With
*all tasks connected* on (the default), every activity additionally keeps its
single best incoming and outgoing edge, so no activity is left floating.

The output is a *dependency graph* (a heuristic net without split/join
semantics).  Converting it to a Petri net needs the AND/XOR split analysis of
causal nets; that conversion is offered through the optional PM4Py back end.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..dfg import DFG, dfg_from_simple_log
from ..log import SimpleLog


@dataclass
class DependencyGraph:
    activities: Counter
    #: (a, b) -> (dependency value, |a > b|) for every kept edge
    edges: dict[tuple[str, str], tuple[float, int]] = field(default_factory=dict)
    start: Counter = field(default_factory=Counter)
    end: Counter = field(default_factory=Counter)
    #: dependency value of every ordered pair that directly follows at least once
    all_dependencies: dict[tuple[str, str], float] = field(default_factory=dict)


def dependency(dfg: DFG, a: str, b: str) -> float:
    ab, ba = dfg.edges.get((a, b), 0), dfg.edges.get((b, a), 0)
    if a == b:
        return ab / (ab + 1)
    return (ab - ba) / (ab + ba + 1)


def heuristics_miner(log: SimpleLog, dependency_threshold: float = 0.5,
                     min_observations: int = 1, loop_two_threshold: float = 0.5,
                     all_tasks_connected: bool = True) -> DependencyGraph:
    dfg = dfg_from_simple_log(log)

    # |a >> b|: occurrences of the pattern a b a.
    two_loops: Counter = Counter()
    for trace, n in log.items():
        for i in range(len(trace) - 2):
            if trace[i] == trace[i + 2] and trace[i] != trace[i + 1]:
                two_loops[(trace[i], trace[i + 1])] += n

    graph = DependencyGraph(Counter(dfg.activities), start=Counter(dfg.start),
                            end=Counter(dfg.end))
    for (a, b), count in dfg.edges.items():
        value = dependency(dfg, a, b)
        graph.all_dependencies[(a, b)] = value
        if value >= dependency_threshold and count >= min_observations:
            graph.edges[(a, b)] = (value, count)

    # Length-two loops: a b a with both a⇒a and b⇒b weak (otherwise they are
    # already length-one loops) keeps both directions a→b and b→a.
    for (a, b), count in two_loops.items():
        mutual = count + two_loops.get((b, a), 0)
        value = mutual / (mutual + 1)
        if value >= loop_two_threshold:
            for x, y in ((a, b), (b, a)):
                if (x, y) in dfg.edges:
                    graph.edges[(x, y)] = (value, dfg.edges[(x, y)])

    if all_tasks_connected:
        for activity in dfg.activities:
            outgoing = [(dependency(dfg, activity, b), b) for (x, b) in dfg.edges
                        if x == activity and b != activity]
            incoming = [(dependency(dfg, a, activity), a) for (a, y) in dfg.edges
                        if y == activity and a != activity]
            if outgoing and activity not in dfg.end:
                value, best = max(outgoing)
                graph.edges.setdefault((activity, best), (value, dfg.edges[(activity, best)]))
            if incoming and activity not in dfg.start:
                value, best = max(incoming)
                graph.edges.setdefault((best, activity), (value, dfg.edges[(best, activity)]))
    return graph
