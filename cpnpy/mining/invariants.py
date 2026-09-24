"""The incidence matrix, place invariants and transition invariants.

Linear algebra instead of state spaces
--------------------------------------
Everything in :mod:`.analysis` explores markings one by one.  Invariants
answer questions from the *structure* alone, with a little linear algebra,
so they work even when the state space is huge or infinite.

**Incidence matrix.**  ``C`` has a row per place and a column per transition;
``C(p, t) = W(t, p) − W(p, t)`` is what firing ``t`` does to ``p`` (the tokens
it puts in minus the tokens it takes out).  Firing a sequence ``σ`` whose
Parikh vector ``σ⃗`` counts how often each transition fires gives the
**marking equation**::

    M  --σ-->  M'    implies    M' = M + C · σ⃗

**Place invariant (P-invariant).**  A weighting ``y`` of the places with
``yᵀ · C = 0``.  Multiplying the marking equation by ``yᵀ`` gives
``y · M' = y · M``: the weighted token count is the same in *every* reachable
marking.  In a WF-net, ``i + c1 + c2 + o`` being invariant says "exactly one
token moves through these places".

**Transition invariant (T-invariant).**  A firing count ``x`` with
``C · x = 0``: firing every transition as often as ``x`` says (in any
enabled order) leads back to the marking you started from.  A cycle of the
net's behaviour.

We compute the **minimal semi-positive** invariants (no negative weights, not
all zero, and no other invariant uses a strict subset of their places or
transitions).  Every semi-positive invariant is a non-negative combination
of these, so they are *the* invariants to show.  The method is Farkas'
algorithm (Martínez & Silva, 1982): start from ``[C | I]`` and eliminate one
column of ``C`` at a time by adding pairs of rows with opposite signs.

What they tell you
------------------
* Every place in some semi-positive P-invariant (**covered by P-invariants**)
  ⇒ the net is *structurally bounded*: bounded from any initial marking.
* A net that is live and bounded is covered by T-invariants, so a transition
  in no T-invariant means "not both live and bounded".  For a WF-net, apply
  that to the short-circuited net N̄: by the soundness theorem, a sound
  WF-net's N̄ is covered by T-invariants.

The number of minimal invariants can grow exponentially with the size of the
net.  :func:`invariants` stops at ``limit`` intermediate rows and says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import gcd

from .petrinet import Marking, PetriNet


class TooManyInvariants(Exception):
    """Farkas' algorithm needed more than the allowed number of rows."""


def incidence_matrix(net: PetriNet) -> tuple[list[str], list[str], list[list[int]]]:
    """``(places, transitions, C)`` with ``C[i][j] = W(t_j, p_i) − W(p_i, t_j)``."""
    places = list(net.places)
    transitions = list(net.transitions)
    row = {p: i for i, p in enumerate(places)}
    column = {t: j for j, t in enumerate(transitions)}
    matrix = [[0] * len(transitions) for _ in places]
    for arc in net.arcs:
        if arc.source in row and arc.target in column:          # p -> t: consumed
            matrix[row[arc.source]][column[arc.target]] -= arc.weight
        elif arc.source in column and arc.target in row:        # t -> p: produced
            matrix[row[arc.target]][column[arc.source]] += arc.weight
    return places, transitions, matrix


def _normalise(vector: list[int]) -> list[int]:
    divisor = 0
    for value in vector:
        divisor = gcd(divisor, value)
    return [value // divisor for value in vector] if divisor > 1 else vector


def _support(vector: list[int]) -> frozenset[int]:
    return frozenset(i for i, value in enumerate(vector) if value)


def _minimal(rows: list[tuple[list[int], list[int]]]) -> list[tuple[list[int], list[int]]]:
    """Drop duplicate rows and rows whose support strictly contains another's."""
    unique: dict[tuple[int, ...], tuple[list[int], list[int]]] = {}
    for rest, generator in rows:
        unique.setdefault(tuple(rest) + tuple(generator), (rest, generator))
    rows = list(unique.values())
    supports = [_support(generator) for _, generator in rows]
    return [row for row, support in zip(rows, supports)
            if not any(other < support for other in supports)]


def semi_positive_invariants(matrix: list[list[int]], limit: int = 5_000) -> list[list[int]]:
    """Minimal semi-positive solutions ``y ≥ 0, y ≠ 0`` of ``yᵀ · matrix = 0``.

    ``matrix`` has one row per variable.  Farkas' algorithm: rows are pairs
    (what is left of the matrix row, the combination of variables it stands
    for).  Column by column, rows with opposite signs in that column are
    combined so that it cancels, and rows that do not cancel are dropped.
    """
    count = len(matrix)
    columns = len(matrix[0]) if count else 0
    rows = [(list(matrix[i]), [1 if j == i else 0 for j in range(count)]) for i in range(count)]
    for column in range(columns):
        keep = [row for row in rows if row[0][column] == 0]
        positive = [row for row in rows if row[0][column] > 0]
        negative = [row for row in rows if row[0][column] < 0]
        for up_rest, up_generator in positive:
            for down_rest, down_generator in negative:
                # a·up + b·down cancels the column, with a, b > 0.
                a, b = -down_rest[column], up_rest[column]
                combined = _normalise([a * x + b * y for x, y in zip(
                    up_rest + up_generator, down_rest + down_generator)])
                keep.append((combined[:columns], combined[columns:]))
        rows = _minimal(keep)
        if len(rows) > limit:
            raise TooManyInvariants(f"more than {limit} candidate invariants")
    invariants = [_normalise(generator) for _, generator in _minimal(rows) if any(generator)]
    return sorted(invariants, key=lambda v: (sum(1 for x in v if x), [-x for x in v]))


@dataclass
class Invariants:
    """The incidence matrix and the minimal semi-positive invariants of a net."""

    net: PetriNet
    places: list[str]
    transitions: list[str]
    #: ``incidence[i][j]``: the effect of transitions[j] on places[i].
    incidence: list[list[int]]
    #: Each P-invariant as ``{place id: weight}`` (weights > 0 only).
    p_invariants: list[dict[str, int]] = field(default_factory=list)
    #: Each T-invariant as ``{transition id: count}`` (counts > 0 only).
    t_invariants: list[dict[str, int]] = field(default_factory=list)
    #: Set when there were too many to compute: the lists are then empty.
    p_truncated: bool = False
    t_truncated: bool = False

    def uncovered_places(self) -> list[str]:
        covered = {p for invariant in self.p_invariants for p in invariant}
        return [p for p in self.places if p not in covered]

    def uncovered_transitions(self) -> list[str]:
        covered = {t for invariant in self.t_invariants for t in invariant}
        return [t for t in self.transitions if t not in covered]

    @property
    def covered_by_p_invariants(self) -> bool | None:
        """Every place in some P-invariant (⇒ structurally bounded)."""
        return None if self.p_truncated else not self.uncovered_places()

    @property
    def covered_by_t_invariants(self) -> bool | None:
        return None if self.t_truncated else not self.uncovered_transitions()

    def token_sum(self, invariant: dict[str, int], marking: Marking | None = None) -> int:
        """``y · M``: the weighted token count the invariant keeps constant."""
        marking = self.net.initial_marking if marking is None else marking
        return sum(weight * marking[place] for place, weight in invariant.items())

    def describe(self, invariant: dict[str, int], with_value: bool = False) -> str:
        """``2·p1 + p2`` (P-invariant) or ``a + b + t*`` (T-invariant), by name."""
        terms = [(f"{weight}·" if weight != 1 else "") + self.net.node_name(node)
                 for node, weight in invariant.items()]
        text = " + ".join(terms)
        if with_value:
            text += f" = {self.token_sum(invariant)}"
        return text


def invariants(net: PetriNet, limit: int = 5_000) -> Invariants:
    """Incidence matrix plus minimal semi-positive P- and T-invariants."""
    places, transitions, matrix = incidence_matrix(net)
    result = Invariants(net, places, transitions, matrix)
    try:
        for vector in semi_positive_invariants(matrix, limit):
            result.p_invariants.append({p: w for p, w in zip(places, vector) if w})
    except TooManyInvariants:
        result.p_truncated = True
    transposed = [list(column) for column in zip(*matrix)] if places else \
        [[] for _ in transitions]
    try:
        for vector in semi_positive_invariants(transposed, limit):
            result.t_invariants.append({t: w for t, w in zip(transitions, vector) if w})
    except TooManyInvariants:
        result.t_truncated = True
    return result
