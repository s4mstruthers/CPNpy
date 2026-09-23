"""Directly-follows graphs (DFGs) -- the "process map" of tools like Disco.

Definition
----------
Activity ``b`` *directly follows* ``a`` in a log, written ``a >_L b``, iff
some trace contains ``a`` immediately followed by ``b``.  The DFG has one
node per activity and an edge ``a -> b`` weighted by *how often* that
happened, plus two artificial nodes ▶ (start) and ■ (end) with edges to the
first and from the last activity of every trace.

A DFG is not a Petri net: it has no concurrency, and every path through it is
allowed, so it usually *overgeneralises* (reading: Leemans, Poppe & Wynn,
"Directly-follows-based process mining").  It is nonetheless the most useful
first look at a log, and the Inductive Miner family works directly on it.

Performance
-----------
When events carry timestamps, each edge also records the time elapsed between
``a`` and the ``b`` that directly followed it.  Mean and median are shown in
performance mode.

Simplification
--------------
Real logs produce "spaghetti".  :meth:`DFG.simplified` keeps a fraction of
the activities (most frequent first) and a fraction of the edges, while
guaranteeing that every kept activity stays connected: each keeps its most
frequent incoming and outgoing edge.  This is the same idea as Disco's two
sliders.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .log import Classifier, EventLog, SimpleLog

START = "▶"
END = "■"


@dataclass
class DFG:
    activities: Counter = field(default_factory=Counter)       # activity -> events
    edges: Counter = field(default_factory=Counter)            # (a, b) -> count
    start: Counter = field(default_factory=Counter)            # activity -> traces
    end: Counter = field(default_factory=Counter)
    durations: dict[tuple[str, str], list[float]] = field(default_factory=dict)
    trace_count: int = 0
    empty_traces: int = 0

    # -- queries --------------------------------------------------------
    def successors(self, activity: str) -> set[str]:
        return {b for (a, b) in self.edges if a == activity}

    def predecessors(self, activity: str) -> set[str]:
        return {a for (a, b) in self.edges if b == activity}

    def mean_duration(self, edge: tuple[str, str]) -> float | None:
        values = self.durations.get(edge)
        return statistics.fmean(values) if values else None

    def median_duration(self, edge: tuple[str, str]) -> float | None:
        values = self.durations.get(edge)
        return statistics.median(values) if values else None

    def all_edges(self) -> list[tuple[str, str, int]]:
        """Edges including the artificial start/end ones, as (a, b, count)."""
        edges = [(START, a, n) for a, n in self.start.items()]
        edges += [(a, b, n) for (a, b), n in self.edges.items()]
        edges += [(a, END, n) for a, n in self.end.items()]
        return edges

    # -- simplification ------------------------------------------------
    def simplified(self, activity_fraction: float = 1.0, edge_fraction: float = 1.0) -> "DFG":
        """Keep the top ``activity_fraction`` of activities and ``edge_fraction`` of edges.

        Fractions are in [0, 1].  At least one activity is always kept.
        Removing activities *projects* them out: we do not reconnect their
        neighbours, because that would invent directly-follows pairs that
        never occurred.  Edges touching removed activities disappear.
        """
        ranked = [a for a, _ in sorted(self.activities.items(), key=lambda x: (-x[1], x[0]))]
        keep_count = max(1, round(len(ranked) * activity_fraction))
        kept = set(ranked[:keep_count])

        candidates = [(a, b, n) for (a, b, n) in self.all_edges()
                      if (a in kept or a == START) and (b in kept or b == END)]
        candidates.sort(key=lambda edge: (-edge[2], edge[0], edge[1]))
        keep_edges = set((a, b) for a, b, _ in candidates[:round(len(candidates) * edge_fraction)])

        # Connectivity guarantee: best incoming and best outgoing per activity.
        for activity in kept:
            incoming = [e for e in candidates if e[1] == activity]
            outgoing = [e for e in candidates if e[0] == activity]
            if incoming:
                keep_edges.add(incoming[0][:2])
            if outgoing:
                keep_edges.add(outgoing[0][:2])

        result = DFG(trace_count=self.trace_count, empty_traces=self.empty_traces)
        result.activities = Counter({a: self.activities[a] for a in kept})
        for a, b, n in candidates:
            if (a, b) not in keep_edges:
                continue
            if a == START:
                result.start[b] = n
            elif b == END:
                result.end[a] = n
            else:
                result.edges[(a, b)] = n
                if (a, b) in self.durations:
                    result.durations[(a, b)] = self.durations[(a, b)]
        return result


def dfg_from_simple_log(log: SimpleLog) -> DFG:
    """DFG of a multiset of sequences (no performance information)."""
    dfg = DFG()
    for sequence, count in log.items():
        dfg.trace_count += count
        if not sequence:
            dfg.empty_traces += count
            continue
        for activity in sequence:
            dfg.activities[activity] += count
        dfg.start[sequence[0]] += count
        dfg.end[sequence[-1]] += count
        for a, b in zip(sequence, sequence[1:]):
            dfg.edges[(a, b)] += count
    return dfg


def discover_dfg(log: EventLog | SimpleLog, classifier: Classifier | None = None) -> DFG:
    """DFG of a log; with an :class:`EventLog`, edge durations are recorded too."""
    if not isinstance(log, EventLog):
        return dfg_from_simple_log(log)

    classifier = classifier or log.default_classifier()
    dfg = DFG()
    durations: dict[tuple[str, str], list[float]] = defaultdict(list)
    for trace in log.traces:
        dfg.trace_count += 1
        events = [e for e in trace.events if classifier.accepts(e)]
        if not events:
            dfg.empty_traces += 1
            continue
        labels = [classifier.label(e) for e in events]
        dfg.activities.update(labels)
        dfg.start[labels[0]] += 1
        dfg.end[labels[-1]] += 1
        for (first, second), (a, b) in zip(zip(events, events[1:]), zip(labels, labels[1:])):
            dfg.edges[(a, b)] += 1
            if first.timestamp is not None and second.timestamp is not None:
                durations[(a, b)].append((second.timestamp - first.timestamp).total_seconds())
    dfg.durations = dict(durations)
    return dfg
