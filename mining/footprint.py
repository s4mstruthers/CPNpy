"""Ordering relations and footprint matrices (van der Aalst, ch. 6.2 and 8.4).

From the directly-follows relation ``>_L`` four *log-based ordering
relations* are derived, for every pair of activities a, b:

====================  ===========================================  =========
relation              definition                                   symbol
====================  ===========================================  =========
causality             ``a > b`` and **not** ``b > a``              ``→``
inverse causality     ``b > a`` and **not** ``a > b``              ``←``
parallel              ``a > b`` **and** ``b > a``                  ``‖``
choice / unrelated    **neither** ``a > b`` nor ``b > a``          ``#``
====================  ===========================================  =========

Exactly one of the four holds for each ordered pair, so the relations can be
tabulated as the **footprint matrix**.  Note the diagonal: ``a # a`` unless
``a`` directly follows itself (a length-one loop), in which case ``a ‖ a``.

Frequencies play no role: a pair that directly follows once counts the same
as one that follows a thousand times.  That is exactly why the α-algorithm is
sensitive to noise.

Conformance via footprints (ch. 8.4)
------------------------------------
A model has a footprint too (computed from its behaviour).  Comparing the log
footprint with the model footprint cell by cell gives a simple conformance
measure::

    fitness_footprint = 1 - (number of differing cells) / (total cells)
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .dfg import DFG, dfg_from_simple_log
from .log import SimpleLog
from .petrinet import PetriNet

CAUSAL = "→"
INVERSE = "←"
PARALLEL = "‖"
CHOICE = "#"


@dataclass
class Footprint:
    activities: list[str]
    directly_follows: set[tuple[str, str]]
    start: set[str]
    end: set[str]

    def relation(self, a: str, b: str) -> str:
        forward = (a, b) in self.directly_follows
        backward = (b, a) in self.directly_follows
        if forward and backward:
            return PARALLEL
        if forward:
            return CAUSAL
        if backward:
            return INVERSE
        return CHOICE

    # Convenience predicates with the textbook names -----------------------
    def causal(self, a: str, b: str) -> bool:
        return self.relation(a, b) == CAUSAL

    def parallel(self, a: str, b: str) -> bool:
        return self.relation(a, b) == PARALLEL

    def choice(self, a: str, b: str) -> bool:
        return self.relation(a, b) == CHOICE

    def matrix(self) -> list[list[str]]:
        return [[self.relation(a, b) for b in self.activities] for a in self.activities]

    def as_text(self) -> str:
        width = max([len(a) for a in self.activities] + [1])
        header = " " * (width + 1) + " ".join(a.rjust(width) for a in self.activities)
        rows = [header]
        for a, row in zip(self.activities, self.matrix()):
            rows.append(a.rjust(width) + " " + " ".join(cell.rjust(width) for cell in row))
        return "\n".join(rows)


def footprint_from_dfg(dfg: DFG) -> Footprint:
    return Footprint(sorted(dfg.activities), set(dfg.edges), set(dfg.start), set(dfg.end))


def footprint_of_log(log: SimpleLog) -> Footprint:
    return footprint_from_dfg(dfg_from_simple_log(log))


def footprint_of_net(net: PetriNet, max_states: int = 50_000) -> Footprint:
    """The footprint of a model's behaviour.

    ``a > b`` holds in the model iff some reachable marking allows ``a`` and
    then ``b`` with only silent transitions in between.  Computed from the
    reachability graph, so the net must be bounded.
    """
    from .analysis import reachability_graph

    graph = reachability_graph(net, max_states=max_states)
    if graph.has_omega or graph.truncated:
        raise ValueError("The model's state space is unbounded or too large to "
                         "compute its footprint.")

    def visible_next(state: int) -> set[str]:
        """Labels that can occur next from ``state``, skipping silent steps."""
        seen, result = {state}, set()
        queue = deque([state])
        while queue:
            current = queue.popleft()
            for transition, target in graph.successors(current):
                label = net.transitions[transition].label
                if label is None:
                    if target not in seen:
                        seen.add(target)
                        queue.append(target)
                else:
                    result.add(label)
        return result

    follows: set[tuple[str, str]] = set()
    for source, transition, target in graph.edges:
        label = net.transitions[transition].label
        if label is None:
            continue
        for successor in visible_next(target):
            follows.add((label, successor))
    start = visible_next(0)
    final_states = [i for i, m in enumerate(graph.states) if m == net.final_marking]
    end: set[str] = set()
    for source, transition, target in graph.edges:
        label = net.transitions[transition].label
        if label is not None and _silently_reaches(graph, net, target, set(final_states)):
            end.add(label)
    return Footprint(sorted(net.labels()), follows, start, end)


def _silently_reaches(graph, net, state: int, targets: set[int]) -> bool:
    seen = {state}
    queue = deque([state])
    while queue:
        current = queue.popleft()
        if current in targets:
            return True
        for transition, target in graph.successors(current):
            if net.transitions[transition].label is None and target not in seen:
                seen.add(target)
                queue.append(target)
    return False


@dataclass
class FootprintComparison:
    activities: list[str]
    log_matrix: list[list[str]]
    model_matrix: list[list[str]]

    @property
    def differences(self) -> list[tuple[str, str, str, str]]:
        """(a, b, log relation, model relation) for every differing cell."""
        result = []
        for i, a in enumerate(self.activities):
            for j, b in enumerate(self.activities):
                if self.log_matrix[i][j] != self.model_matrix[i][j]:
                    result.append((a, b, self.log_matrix[i][j], self.model_matrix[i][j]))
        return result

    @property
    def fitness(self) -> float:
        cells = len(self.activities) ** 2
        return 1.0 if cells == 0 else 1 - len(self.differences) / cells


def compare_footprints(log_fp: Footprint, model_fp: Footprint) -> FootprintComparison:
    """Cell-by-cell comparison over the union of both alphabets."""
    activities = sorted(set(log_fp.activities) | set(model_fp.activities))
    log_matrix = [[log_fp.relation(a, b) for b in activities] for a in activities]
    model_matrix = [[model_fp.relation(a, b) for b in activities] for a in activities]
    return FootprintComparison(activities, log_matrix, model_matrix)
