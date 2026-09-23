"""Precision, generalisation and simplicity -- the other three quality dimensions.

Fitness (token replay, alignments) asks "can the model replay the log?".
Three more dimensions complete the picture (course: the four quality
criteria):

precision
    Does the model allow *only* what the log shows?  A flower model fits
    everything but has terrible precision.
generalisation
    Does the model generalise beyond the examples, rather than overfitting
    exactly the traces seen?
simplicity
    Is the model as simple as possible (Occam's razor)?

Precision: escaping edges (ETConformance, Muñoz-Gama & Carmona)
---------------------------------------------------------------
Walk through every *prefix* of every trace.  After prefix ``h``, the log
continued with some set of activities ``log_next(h)``; the model, in the
marking reached by replaying ``h``, would *allow* a set ``model_next(h)``.
Anything the model allows but the log never did is an **escaping edge**::

                     Σ_h  freq(h) · |model_next(h) \\ log_next(h)|
    precision = 1 −  ─────────────────────────────────────────────
                     Σ_h  freq(h) · |model_next(h)|

Prefixes that do not fit the model are skipped (there is no meaningful
marking to compare against).  ``model_next`` looks through τ transitions.

Generalisation (token-based, as in PM4Py)
-----------------------------------------
A transition that fired only a few times during replay gives little evidence
that the model is right about it.  With ``n_t`` the number of firings of
transition t::

    generalisation = 1 − mean_t ( 1 / sqrt(n_t) )

Simplicity (arc degree, as in PM4Py)
------------------------------------
The mean number of arcs per node; a pure sequence has degree 2.  Anything
above that makes the model harder to read::

    simplicity = 1 / (1 + max(mean degree − 2, 0))

These last two are rough proxies -- which is also what the literature says
about them -- but they make the trade-off between the four dimensions
visible when comparing models discovered from the same log.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict, deque

from ..log import SimpleLog
from ..petrinet import Marking, PetriNet
from .token_replay import ReplayResult, silent_path


def _visible_enabled(net: PetriNet, marking: Marking, max_states: int = 2000) -> set[str]:
    """Labels that can fire next, possibly after τ moves."""
    result: set[str] = set()
    seen = {marking}
    queue = deque([marking])
    while queue and len(seen) < max_states:
        current = queue.popleft()
        for transition in net.enabled(current):
            label = net.transitions[transition].label
            if label is not None:
                result.add(label)
            else:
                successor = net.fire(current, transition)
                if successor not in seen:
                    seen.add(successor)
                    queue.append(successor)
    return result


def _replay_prefix(net: PetriNet, prefix: tuple[str, ...],
                   cache: dict[tuple[str, ...], Marking | None]) -> Marking | None:
    """Marking after replaying ``prefix`` without missing tokens, or None."""
    if prefix in cache:
        return cache[prefix]
    if not prefix:
        cache[prefix] = net.initial_marking
        return net.initial_marking
    before = _replay_prefix(net, prefix[:-1], cache)
    result: Marking | None = None
    if before is not None:
        activity = prefix[-1]
        candidates = net.transitions_with_label(activity)
        for transition in candidates:
            if net.is_enabled(before, transition):
                result = net.fire(before, transition)
                break
        else:
            for transition in candidates:
                path = silent_path(net, before, lambda m, t=transition: net.is_enabled(m, t))
                if path is not None:
                    marking = before
                    for step in path:
                        marking = net.fire(marking, step)
                    result = net.fire(marking, transition)
                    break
    cache[prefix] = result
    return result


def precision(net: PetriNet, log: SimpleLog) -> float:
    """ETConformance precision with escaping edges."""
    log_next: dict[tuple[str, ...], set[str]] = defaultdict(set)
    frequency: Counter = Counter()
    for trace, count in log.items():
        for i, activity in enumerate(trace):
            prefix = trace[:i]
            log_next[prefix].add(activity)
            frequency[prefix] += count

    cache: dict[tuple[str, ...], Marking | None] = {}
    escaping = allowed = 0
    for prefix, observed in log_next.items():
        marking = _replay_prefix(net, prefix, cache)
        if marking is None:
            continue
        enabled = _visible_enabled(net, marking)
        allowed += frequency[prefix] * len(enabled)
        escaping += frequency[prefix] * len(enabled - observed)
    return 1.0 if allowed == 0 else 1 - escaping / allowed


def generalisation(replay: ReplayResult) -> float:
    fired, _ = replay.transition_totals()
    net = replay.net
    if not net.transitions:
        return 1.0
    terms = [1 / math.sqrt(fired[t]) if fired[t] else 1.0 for t in net.transitions]
    return 1 - sum(terms) / len(terms)


def simplicity(net: PetriNet) -> float:
    nodes = len(net.places) + len(net.transitions)
    if nodes == 0:
        return 1.0
    mean_degree = 2 * len(net.arcs) / nodes
    return 1 / (1 + max(mean_degree - 2, 0))
