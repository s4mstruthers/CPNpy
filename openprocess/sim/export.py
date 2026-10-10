"""A simulation's firing history as an event log.

One event per firing that binds the *case variable*: the activity is the
transition's name, the case is the variable's value, and the timestamp is
a start time plus the model time.  The CPN page's *Export as event log…*
and the *Simulate CPN* box both use this.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..ml.values import format_value
from ..mining.log import KEY_LIFECYCLE, KEY_NAME, KEY_TIME, Event, EventLog, Trace
from ..model.net import CPNet

UNITS = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400}


def simulation_to_log(net: CPNet, records, case_variable: str, unit: str = "minutes",
                      start: datetime | None = None) -> EventLog:
    """Turn a simulator's firing history into an event log.

    Firings at the same model time keep their firing order.  Every other
    bound variable becomes an event attribute ``cpn:<name>``.
    """
    start = start or datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)
    seconds = UNITS[unit]
    traces: dict[str, Trace] = {}
    for record in records:
        values = dict(record.binding.assignments)
        if case_variable not in values:
            continue
        case = format_value(values[case_variable])
        transition = net.find_transition(record.binding.transition_id)
        activity = transition.name if transition else record.binding.transition_id
        trace = traces.get(case)
        if trace is None:
            trace = traces[case] = Trace({KEY_NAME: case})
        event = Event({KEY_NAME: activity,
                       KEY_TIME: start + timedelta(seconds=float(record.time) * seconds),
                       KEY_LIFECYCLE: "complete"})
        for name, value in record.binding.assignments:
            if name != case_variable:
                event.attributes[f"cpn:{name}"] = format_value(value)
        trace.events.append(event)
    log = EventLog(attributes={KEY_NAME: f"{net.name} simulation"})
    log.traces.extend(traces.values())
    return log


def case_variables(net: CPNet) -> list[str]:
    """Variable names bound by some transition, candidates for the case id."""
    names: list[str] = []
    for transition in net.all_transitions():
        for arc in net.page_of(transition).arcs_of(transition) if net.page_of(transition) else []:
            for token in _identifiers(arc.expression_text):
                if token not in names:
                    names.append(token)
    return names


def _identifiers(text: str) -> list[str]:
    import re
    return [t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_']*", text or "")
            if t not in ("if", "then", "else", "andalso", "orelse", "not", "let", "in", "end", "case", "of", "fn")]
