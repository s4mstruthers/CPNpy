"""Token-based replay (van der Aalst, *Process Mining*, §8.2).

Replay each trace on the net and *count tokens*:

``p`` produced
    tokens put into places (the environment first produces the initial
    marking, then every fired transition produces its output tokens);
``c`` consumed
    tokens taken out (every fired transition consumes its inputs, and at the
    end the environment consumes the final marking);
``m`` missing
    tokens that had to be *created artificially* because the transition for
    the next event was not enabled -- evidence the log did something the
    model did not allow;
``r`` remaining
    tokens left behind after the final marking was consumed -- evidence the
    model expected something the log did not do.

Fitness of a trace σ on net N::

    fitness(σ, N) = ½ (1 − m / c) + ½ (1 − r / p)

It is 1 exactly when nothing was missing or remaining.  For a whole log the
four counts are summed over all traces (weighted by frequency) before the
formula is applied.

Silent transitions and duplicates
---------------------------------
Events never refer to τ transitions, so the replayer may fire them on its
own: when the transition for the next event is not enabled, it first looks
for a (shortest) sequence of silent transitions that enables it.  With
duplicate labels, it prefers a transition that is enabled, then one reachable
through silent moves, then the one missing the fewest tokens.  These are
heuristics -- token replay is fast but not always optimal, which is why
alignments exist (see :mod:`alignments`).

Diagnostics
-----------
Per place we keep the total missing and remaining tokens, and per transition
how often it fired with missing tokens.  The app paints these on the model
(ProM's "replay" view): a red ``−n`` badge means the log wanted a token here
that was not there; a ``+n`` badge means a token was left behind.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field

from ..log import SimpleLog
from ..petrinet import Marking, PetriNet


@dataclass
class TraceReplay:
    trace: tuple[str, ...]
    count: int
    produced: int
    consumed: int
    missing: int
    remaining: int
    #: activities that do not occur in the model at all
    unknown_activities: list[str] = field(default_factory=list)
    #: indices of events whose transition was not enabled
    problem_events: list[int] = field(default_factory=list)
    missing_by_place: Counter = field(default_factory=Counter)
    remaining_by_place: Counter = field(default_factory=Counter)
    fired: Counter = field(default_factory=Counter)             # transition id -> times
    forced: Counter = field(default_factory=Counter)            # fired with missing tokens

    @property
    def fitness(self) -> float:
        return _fitness(self.produced, self.consumed, self.missing, self.remaining)

    @property
    def fits(self) -> bool:
        return self.missing == 0 and self.remaining == 0 and not self.unknown_activities


def _fitness(p: int, c: int, m: int, r: int) -> float:
    part_missing = 1 - m / c if c else 1.0
    part_remaining = 1 - r / p if p else 1.0
    return 0.5 * part_missing + 0.5 * part_remaining


@dataclass
class ReplayResult:
    net: PetriNet
    traces: list[TraceReplay]           # one per variant, most frequent first

    def _total(self, attribute: str) -> int:
        return sum(getattr(t, attribute) * t.count for t in self.traces)

    @property
    def produced(self) -> int:
        return self._total("produced")

    @property
    def consumed(self) -> int:
        return self._total("consumed")

    @property
    def missing(self) -> int:
        return self._total("missing")

    @property
    def remaining(self) -> int:
        return self._total("remaining")

    @property
    def fitness(self) -> float:
        """Log-level fitness from the summed counts."""
        return _fitness(self.produced, self.consumed, self.missing, self.remaining)

    @property
    def fitting_traces(self) -> int:
        return sum(t.count for t in self.traces if t.fits)

    @property
    def trace_count(self) -> int:
        return sum(t.count for t in self.traces)

    def place_totals(self) -> tuple[Counter, Counter]:
        """(missing, remaining) per place, frequency-weighted."""
        missing, remaining = Counter(), Counter()
        for t in self.traces:
            for place, n in t.missing_by_place.items():
                missing[place] += n * t.count
            for place, n in t.remaining_by_place.items():
                remaining[place] += n * t.count
        return missing, remaining

    def transition_totals(self) -> tuple[Counter, Counter]:
        """(fired, forced) per transition, frequency-weighted."""
        fired, forced = Counter(), Counter()
        for t in self.traces:
            for transition, n in t.fired.items():
                fired[transition] += n * t.count
            for transition, n in t.forced.items():
                forced[transition] += n * t.count
        return fired, forced


# ---------------------------------------------------------------------------
# Silent moves
# ---------------------------------------------------------------------------
def silent_path(net: PetriNet, marking: Marking, goal, max_states: int = 2000) -> list[str] | None:
    """Shortest sequence of τ transitions from ``marking`` to a marking where
    ``goal(marking)`` holds.  ``[]`` if it already holds, ``None`` if none found."""
    if goal(marking):
        return []
    silent = [t for t, tr in net.transitions.items() if tr.silent]
    if not silent:
        return None
    parent: dict[Marking, tuple[Marking, str] | None] = {marking: None}
    queue = deque([marking])
    while queue and len(parent) < max_states:
        current = queue.popleft()
        for transition in silent:
            if not net.is_enabled(current, transition):
                continue
            successor = net.fire(current, transition)
            if successor in parent:
                continue
            parent[successor] = (current, transition)
            if goal(successor):
                path = []
                node = successor
                while parent[node] is not None:
                    previous, step = parent[node]  # type: ignore[misc]
                    path.append(step)
                    node = previous
                return path[::-1]
            queue.append(successor)
    return None


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------
def replay_trace(net: PetriNet, trace: tuple[str, ...], count: int = 1) -> TraceReplay:
    marking = net.initial_marking
    result = TraceReplay(trace, count, produced=marking.total, consumed=0, missing=0,
                         remaining=0)
    by_label: dict[str, list[str]] = {}
    for transition in net.transitions.values():
        if transition.label is not None:
            by_label.setdefault(transition.label, []).append(transition.id)

    def fire(transition: str, current: Marking) -> Marking:
        pre, post = net.pre(transition), net.post(transition)
        short = Marking({p: n - current[p] for p, n in pre.items() if current[p] < n})
        if short:
            result.missing += short.total
            result.missing_by_place.update(dict(short.items()))
            result.forced[transition] += 1
            current = current + short
        result.consumed += pre.total
        result.produced += post.total
        result.fired[transition] += 1
        return current - pre + post

    for index, activity in enumerate(trace):
        candidates = by_label.get(activity)
        if not candidates:
            result.unknown_activities.append(activity)
            result.problem_events.append(index)
            continue
        chosen: str | None = next((t for t in candidates if net.is_enabled(marking, t)), None)
        if chosen is None:
            # Try enabling one of the candidates with silent moves.
            best_path = None
            for transition in candidates:
                path = silent_path(net, marking, lambda m, t=transition: net.is_enabled(m, t))
                if path is not None and (best_path is None or len(path) < len(best_path[1])):
                    best_path = (transition, path)
            if best_path is not None:
                chosen, path = best_path
                for step in path:
                    marking = fire(step, marking)
        if chosen is None:
            # Force the transition missing the fewest tokens.
            chosen = min(candidates, key=lambda t: sum(
                max(0, n - marking[p]) for p, n in net.pre(t).items()))
            result.problem_events.append(index)
        marking = fire(chosen, marking)

    # Finish: move silently to the final marking if possible, then let the
    # environment consume it.
    final = net.final_marking
    path = silent_path(net, marking, lambda m: m == final)
    if path is None:
        path = silent_path(net, marking, lambda m: m >= final) or []
    for step in path:
        marking = fire(step, marking)
    short = Marking({p: n - marking[p] for p, n in final.items() if marking[p] < n})
    if short:
        result.missing += short.total
        result.missing_by_place.update(dict(short.items()))
        marking = marking + short
    result.consumed += final.total
    leftover = marking - final
    result.remaining = leftover.total
    result.remaining_by_place.update(dict(leftover.items()))
    return result


def token_replay(net: PetriNet, log: SimpleLog) -> ReplayResult:
    """Replay every variant once and weight the results by frequency."""
    traces = [replay_trace(net, trace, count)
              for trace, count in sorted(log.items(), key=lambda item: (-item[1], item[0]))]
    return ReplayResult(net, traces)
