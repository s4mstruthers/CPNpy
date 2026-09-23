"""Play-out: generate an event log by simulating a Petri net.

This is the reverse direction of discovery.  Starting from the initial
marking, repeatedly pick a random enabled transition and fire it; the labels
of the visible transitions fired form one trace.  A run ends when

* the net reaches its **final marking** (a completed case), or
* nothing is enabled (a deadlock -- the trace is kept but marked), or
* the run exceeds ``max_length`` firings (e.g. a loop that could go on forever).

Why it is useful in the course: simulate a model, mine the generated log,
and compare the discovered model with the original.  A sound model's log
rediscovered by the Inductive Miner should give back the same behaviour.

Timestamps are synthetic: each case starts ``case_gap`` after the previous
one and each visible event takes ``event_gap``, so the dotted chart and
performance views have something regular to show.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .log import KEY_NAME, KEY_TIME, Event, EventLog, Trace
from .petrinet import PetriNet


@dataclass
class PlayoutResult:
    log: EventLog
    completed: int          # runs that reached the final marking
    deadlocked: int         # runs that got stuck elsewhere
    cut_off: int            # runs stopped at max_length


def random_run(net: PetriNet, rng: random.Random, max_length: int = 200):
    """One random run: (visible labels, how it ended)."""
    marking = net.initial_marking
    labels: list[str] = []
    for _ in range(max_length):
        if net.final_marking and marking == net.final_marking:
            return labels, "completed"
        enabled = net.enabled(marking)
        if not enabled:
            return labels, "deadlocked"
        transition = rng.choice(enabled)
        marking = net.fire(marking, transition)
        label = net.transitions[transition].label
        if label is not None:
            labels.append(label)
    if net.final_marking and marking == net.final_marking:
        return labels, "completed"
    return labels, "cut off"


def play_out(net: PetriNet, traces: int = 100, max_length: int = 200, seed: int | None = None,
             name: str | None = None, start: datetime | None = None,
             case_gap: timedelta = timedelta(minutes=5),
             event_gap: timedelta = timedelta(minutes=1)) -> PlayoutResult:
    rng = random.Random(seed)
    start = start or datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)
    log = EventLog(attributes={KEY_NAME: name or f"Play-out of {net.name}"})
    outcomes: Counter = Counter()
    for number in range(traces):
        labels, outcome = random_run(net, rng, max_length)
        outcomes[outcome] += 1
        begin = start + number * case_gap
        trace = Trace({KEY_NAME: f"case {number + 1}", "playout:outcome": outcome})
        for position, label in enumerate(labels):
            trace.events.append(Event({KEY_NAME: label, KEY_TIME: begin + position * event_gap}))
        log.traces.append(trace)
    return PlayoutResult(log, outcomes["completed"], outcomes["deadlocked"], outcomes["cut off"])
