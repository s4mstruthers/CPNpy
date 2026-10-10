"""Coloured net boxes: play a CPN out many times, and compute its state space."""

from __future__ import annotations

from typing import Literal

from ... import flow
from ...analysis.state_space import StateSpace
from ...mining.log import EventLog
from ...model.net import CPNet
from ...sim.export import case_variables, simulation_to_log
from ...sim.simulator import DeadMarkingError, Simulator
from ..box import box
from ..types import Scores, Text


@box(name="Simulate CPN", group="Coloured nets")
def simulate_cpn(net: CPNet, steps: int = 500, case_variable: str = "", seed: int = 0,
                 unit: Literal["seconds", "minutes", "hours", "days"] = "minutes") -> EventLog:
    """Runs the simulator for *steps* firings and turns the firing history
    into an event log: one case per value of *case_variable* (the variable
    that identifies a case in the inscriptions, e.g. ``p`` or ``order``),
    one event per firing, the model time as the timestamp.

    case_variable: the variable whose value is the case id (empty: the first one found)
    """
    simulator = Simulator(net, seed=seed)
    try:
        fired = simulator.run(steps)
    except DeadMarkingError:
        fired = simulator.step_count
    variable = case_variable or next(iter(case_variables(net)), "")
    if not variable:
        raise ValueError("No variable to use as the case id: set case_variable")
    log = simulation_to_log(net, simulator.log, variable, unit)
    flow.note(f"{fired} firings, model time {simulator.clock}, case variable {variable}: "
              f"{len(log)} cases, {log.event_count} events")
    return log


@box(name="State space", group="Coloured nets", heavy=True)
def state_space(net: CPNet, max_nodes: int = 10000) -> Scores:
    """The reachability graph of a coloured net and its report: dead and
    home markings, bounds, dead and live transitions (as CPN Tools reports
    them). The full report is in the notes."""
    space = StateSpace(net).generate(max_nodes=max_nodes)
    report = space.report()
    flow.show(Text(report, "State space report"), "Report")
    dead = space.dead_markings()
    return Scores(net.name, {"nodes": space.node_count, "arcs": space.arc_count,
                             "dead markings": len(dead), "home markings": len(space.home_markings()),
                             "dead transitions": len(space.dead_transitions()),
                             "complete": "No (stopped at the limit)" if space.unexplored_count else "Yes"})
