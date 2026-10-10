"""Structural properties of WF-nets (van der Aalst, *Workflow Verification*, §3 and §6).

These look only at the drawing -- places, transitions, arcs -- never at
markings, so they are quick and they point at the *construct* that causes a
problem instead of at a firing sequence.

Free-choice (Definition 7)
    Whenever two transitions share an input place, they have exactly the
    same input places: ``•t1 ∩ •t2 ≠ ∅  ⇒  •t1 = •t2``.  Every choice is then
    a "free" one, not influenced by what happened in parallel branches.
    (Corollary 1: soundness of a free-choice WF-net can be decided in
    polynomial time; Lemma 1: a sound free-choice WF-net is safe.)

Well-handled (Definition 13) and well-structured (Definition 14)
    A net is well-handled when there is no place/transition pair ``x, y``
    with two *different* elementary paths from ``x`` to ``y`` that share
    only ``x`` and ``y``.  Such a pair is a **handle**:

    * PT-handle -- ``x`` is a place, ``y`` a transition: a choice (OR-split)
      that is later synchronised (AND-join).
    * TP-handle -- ``x`` is a transition, ``y`` a place: parallel branches
      (AND-split) that are later merged as alternatives (OR-join).

    A WF-net is well-structured iff its short-circuited net ``N̄`` is
    well-handled (the extra transition ``t*`` catches handles that go
    "around" the net).  Corollary 2 / Lemma 3: soundness is polynomial and a
    sound well-structured WF-net is safe.

    Two paths sharing only their ends are two *internally vertex-disjoint*
    paths, so (Menger's theorem) a handle exists iff the maximum number of
    such paths from ``x`` to ``y`` is at least 2 -- a small max-flow problem
    with every inner node given capacity 1.

S-coverable (Definitions 8--10 and 16)
    An S-component is a strongly connected subnet that is a *state
    machine* (each transition has one input and one output place inside it)
    and takes along every arc of its places.  Think of it as one "document"
    or thread that is always in exactly one place.  A WF-net is S-coverable
    when every node of ``N̄`` lies in some S-component.  Sound free-choice
    and sound well-structured WF-nets are S-coverable (Corollaries 3, 4),
    and an S-coverable WF-net is safe.

Lemma 4 (a necessary condition for soundness)
    In a sound WF-net a transition that consumes from ``i`` consumes *only*
    from ``i``, and a transition that produces into ``o`` produces *only*
    into ``o`` -- otherwise it needs ``i`` (or ``o``) together with another
    marked place, which never happens.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .petrinet import PetriNet


# ---------------------------------------------------------------------------
# Free-choice
# ---------------------------------------------------------------------------
def free_choice_violations(net: PetriNet) -> list[tuple[str, str, str]]:
    """``(t1, t2, shared place)`` for every pair that breaks Definition 7."""
    violations = []
    transitions = list(net.transitions)
    for index, t1 in enumerate(transitions):
        inputs1 = net.preset(t1)
        for t2 in transitions[index + 1:]:
            inputs2 = net.preset(t2)
            shared = inputs1 & inputs2
            if shared and inputs1 != inputs2:
                violations.append((t1, t2, sorted(shared)[0]))
    return violations


# ---------------------------------------------------------------------------
# Handles (well-handledness)
# ---------------------------------------------------------------------------
@dataclass
class Handle:
    """Two elementary paths from ``start`` to ``end`` sharing only the ends."""

    start: str
    end: str
    paths: tuple[list[str], list[str]]

    @property
    def kind(self) -> str:
        return "PT" if self.start.startswith("p:") else "TP"


def _two_disjoint_paths(successors: dict[str, list[str]], start: str, end: str):
    """Two internally vertex-disjoint paths ``start → end``, or None.

    Max-flow with vertex splitting: node ``v`` becomes ``(v, 0) → (v, 1)``
    with capacity 1 (unlimited for ``start``/``end``); an arc ``u → v`` is
    ``(u, 1) → (v, 0)`` with capacity 1.  Two augmenting paths = two paths.
    """
    capacity: dict[tuple, dict[tuple, int]] = {}

    def add(u, v, c):
        capacity.setdefault(u, {})[v] = capacity.get(u, {}).get(v, 0) + c
        capacity.setdefault(v, {}).setdefault(u, 0)

    for node, targets in successors.items():
        add((node, 0), (node, 1), 2 if node in (start, end) else 1)
        for target in targets:
            add((node, 1), (target, 0), 1)
    source, sink = (start, 1), (end, 0)
    flow_edges: dict[tuple, dict[tuple, int]] = {u: dict(v) for u, v in capacity.items()}
    found = 0
    for _ in range(2):
        parent = {source: None}
        queue = deque([source])
        while queue and sink not in parent:
            u = queue.popleft()
            for v, c in flow_edges.get(u, {}).items():
                if c > 0 and v not in parent:
                    parent[v] = u
                    queue.append(v)
        if sink not in parent:
            break
        v = sink
        while parent[v] is not None:
            u = parent[v]
            flow_edges[u][v] -= 1
            flow_edges[v][u] += 1
            v = u
        found += 1
    if found < 2:
        return None
    # Read the two paths off the flow: follow edges that carry flow.
    carried = {u: {v: capacity[u][v] - c for v, c in targets.items()
                   if capacity[u][v] > 0 and capacity[u][v] - c > 0}
               for u, targets in flow_edges.items()}
    paths = []
    for _ in range(2):
        path, node = [start], source
        while node != sink:
            nxt = next(iter(carried[node]))
            carried[node][nxt] -= 1
            if not carried[node][nxt]:
                del carried[node][nxt]
            if nxt[1] == 0:
                path.append(nxt[0])
            node = nxt
        paths.append(path)
    return paths[0], paths[1]


def _graph(net: PetriNet) -> dict[str, list[str]]:
    """Successor lists over prefixed ids (``p:…`` places, ``t:…`` transitions)."""
    graph = {f"p:{p}": [f"t:{t}" for t in net.postset(p)] for p in net.places}
    graph.update({f"t:{t}": [f"p:{p}" for p in net.postset(t)] for t in net.transitions})
    return graph


def handles(net: PetriNet, limit: int = 5) -> list[Handle]:
    """Up to ``limit`` handles of ``net`` (empty list: the net is well-handled).

    Only splits (≥ 2 outgoing arcs) can start a handle and only joins (≥ 2
    incoming arcs) can end one, which keeps this fast on real models.
    """
    graph = _graph(net)
    incoming: dict[str, int] = {node: 0 for node in graph}
    for targets in graph.values():
        for target in targets:
            incoming[target] += 1
    splits = [n for n, targets in graph.items() if len(targets) >= 2]
    joins = [n for n, count in incoming.items() if count >= 2]
    found = []
    for start in sorted(splits):
        for end in sorted(joins):
            if start[0] == end[0]:
                continue                      # a handle links a place and a transition
            paths = _two_disjoint_paths(graph, start, end)
            if paths is not None:
                found.append(Handle(start, end, paths))
                if len(found) >= 50:
                    break
    # The shortest handles are the easiest to see in the drawing.
    found.sort(key=lambda h: len(h.paths[0]) + len(h.paths[1]))
    return found[:limit]


# ---------------------------------------------------------------------------
# S-components
# ---------------------------------------------------------------------------
class _Budget(Exception):
    pass


def _s_component_search(net: PetriNet, start: str, must_contain: str, budget: list[int]):
    """An S-component (set of place ids) containing place ``start`` and node
    ``must_contain`` (a place or transition id), or None.

    Unknowns are the places; x_p = 1 means "p is in the component".  For
    every transition the state-machine rule says
    ``Σ_{p ∈ •t} x_p = Σ_{p ∈ t•} x_p ≤ 1``.  We propagate that rule, branch
    where a transition still has a choice, and check strong connectivity of
    each solution (a solution may split into several cycles; any of them
    that is closed is an S-component on its own).
    """
    pre = {t: sorted(net.preset(t)) for t in net.transitions}
    post = {t: sorted(net.postset(t)) for t in net.transitions}
    touching = {p: sorted(net.preset(p) | net.postset(p)) for p in net.places}

    def propagate(x: dict[str, int], changed: list[str]) -> bool:
        queue = deque(t for p in changed for t in touching[p])
        while queue:
            t = queue.popleft()
            sides = []
            for side in (pre[t], post[t]):
                ones = [p for p in side if x.get(p) == 1]
                unknown = [p for p in side if p not in x]
                sides.append((side, ones, unknown))
            (_, ones_in, unk_in), (_, ones_out, unk_out) = sides
            if len(ones_in) > 1 or len(ones_out) > 1:
                return False
            assign: list[tuple[str, int]] = []
            for (side, ones, unknown), (_, other_ones, other_unknown) in (
                    (sides[0], sides[1]), (sides[1], sides[0])):
                if ones:
                    assign += [(p, 0) for p in unknown]
                    if not other_ones:
                        if not other_unknown:
                            return False
                        if len(other_unknown) == 1:
                            assign.append((other_unknown[0], 1))
                elif not unknown:
                    if other_ones:
                        return False
                    assign += [(p, 0) for p in other_unknown]
            for place, value in assign:
                if place in x:
                    if x[place] != value:
                        return False
                    continue
                x[place] = value
                queue.extend(touching[place])
        return True

    def closed_components(places: set[str]):
        """The strongly connected parts of a solution that are S-components."""
        succ = {}
        for p in places:
            succ[f"p:{p}"] = [f"t:{t}" for t in net.postset(p)]
            for t in net.postset(p) | net.preset(p):
                succ.setdefault(f"t:{t}", [f"p:{q}" for q in net.postset(t) if q in places])
        from .analysis import strongly_connected_components
        nodes = list(succ)
        index = {n: i for i, n in enumerate(nodes)}
        for component in strongly_connected_components(
                len(nodes), lambda i: [index[m] for m in succ[nodes[i]]]):
            members = {nodes[i] for i in component}
            q = {n[2:] for n in members if n.startswith("p:")}
            if not q:
                continue
            ts = {t for p in q for t in net.postset(p) | net.preset(p)}
            if all(len(net.preset(t) & q) == 1 and len(net.postset(t) & q) == 1 for t in ts) \
                    and {f"t:{t}" for t in ts} <= members:
                yield q, ts

    def search(x: dict[str, int]):
        budget[0] -= 1
        if budget[0] < 0:
            raise _Budget
        for t in net.transitions:
            for side, other in ((pre[t], post[t]), (post[t], pre[t])):
                if any(x.get(p) == 1 for p in side) and not any(x.get(p) == 1 for p in other):
                    options = [p for p in other if p not in x]
                    for choice in options:
                        trial = dict(x)
                        trial[choice] = 1
                        for p in options:
                            if p != choice:
                                trial[p] = 0
                        if propagate(trial, options):
                            result = search(trial)
                            if result is not None:
                                return result
                    return None
        places = {p for p, v in x.items() if v == 1}
        for q, ts in closed_components(places):
            if start in q and (must_contain in q or must_contain in ts):
                return q
        return None

    x = {start: 1}
    if not propagate(x, [start]):
        return None
    return search(x)


@dataclass
class SCoverage:
    components: list[set[str]] = field(default_factory=list)
    uncovered: list[str] = field(default_factory=list)   # node ids
    complete: bool = True                                  # False: search budget ran out

    @property
    def s_coverable(self) -> bool | None:
        if self.uncovered and self.complete:
            return False
        return True if not self.uncovered else None


def s_coverage(net: PetriNet, budget: int = 20_000) -> SCoverage:
    """Find S-components until every node is covered (or show which is not)."""
    result = SCoverage()
    covered: set[str] = set()
    remaining = [budget]
    for node in list(net.places) + list(net.transitions):
        if node in covered:
            continue
        starts = [node] if node in net.places else sorted(net.preset(node))
        found = None
        try:
            for start in starts:
                found = _s_component_search(net, start, node, remaining)
                if found is not None:
                    break
        except _Budget:
            result.complete = False
            result.uncovered.append(node)
            continue
        if found is None:
            result.uncovered.append(node)
            continue
        result.components.append(found)
        covered |= found
        covered |= {t for p in found for t in net.preset(p) | net.postset(p)}
    return result


# ---------------------------------------------------------------------------
# Everything for a WF-net
# ---------------------------------------------------------------------------
@dataclass
class StructureReport:
    free_choice: list[tuple[str, str, str]]      # violations of Definition 7
    handles: list[Handle] | None                  # of N̄; None if skipped (too big)
    coverage: SCoverage | None                    # of N̄
    state_machine: bool                           # every transition 1 in, 1 out
    lemma4: list[str] = field(default_factory=list)   # transition ids breaking Lemma 4

    @property
    def is_free_choice(self) -> bool:
        return not self.free_choice

    @property
    def well_structured(self) -> bool | None:
        return None if self.handles is None else not self.handles

    @property
    def s_coverable(self) -> bool | None:
        return None if self.coverage is None else self.coverage.s_coverable


def check_structure(net: PetriNet, source: str, sink: str,
                    max_nodes: int = 400) -> StructureReport:
    """Free-choice, well-structured and S-coverable, as in §6 of the paper."""
    from .analysis import short_circuit
    closed = short_circuit(net, source, sink)
    small = len(closed.places) + len(closed.transitions) <= max_nodes
    lemma4 = [t for t in net.transitions
              if (source in net.preset(t) and net.preset(t) != {source})
              or (sink in net.postset(t) and net.postset(t) != {sink})]
    return StructureReport(
        free_choice=free_choice_violations(net),
        handles=handles(closed) if small else None,
        coverage=s_coverage(closed) if small else None,
        state_machine=all(len(net.preset(t)) == 1 and len(net.postset(t)) == 1
                          for t in net.transitions),
        lemma4=lemma4)
