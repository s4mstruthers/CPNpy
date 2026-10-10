"""Input boxes: what a workflow starts from."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Literal

from ... import flow
from ...mining.log import KEY_NAME, Event, EventLog, Trace, parse_simple_log
from ...mining.petrinet import PetriNet
from ...mining.playout import play_out
from ...mining.transition_system import TransitionSystem, parse_transition_system
from ...model.net import CPNet
from ..box import box


def _resolve(file: Path) -> Path:
    path = Path(file)
    if not path.is_file():
        raise FileNotFoundError(f"No such file: {path}")
    return path


@box(name="Open log", group="Input")
def open_log(file: Path) -> EventLog:
    """Reads an event log from the folder: XES (also gzipped), CSV, or a
    ``.txt`` file in the course notation ``[<a,b,c>^3, <a,c>]``.

    file: the log file, relative to the workflow's folder
    """
    path = _resolve(file)
    lower = path.name.lower()
    if lower.endswith(".csv"):
        from ...mining.csv_import import read_csv
        log = read_csv(path)
    elif lower.endswith(".txt"):
        log = EventLog.from_simple_log(parse_simple_log(path.read_text(encoding="utf-8")), path.stem)
    else:
        from ...mining.xes import read_xes
        log = read_xes(path)
    flow.note(f"{path.name}: {len(log)} cases, {log.event_count} events, "
              f"classifier {log.default_classifier().name}")
    return log


@box(name="Typed log", group="Input")
def typed_log(text: str = "[<a,b,c,d>^3, <a,c,b,d>^2, <a,e,d>]", name: str = "Typed log") -> EventLog:
    """A log typed in the course notation: ``[<a,b,c,d>^3, <a,c,b,d>^2, <a,e,d>]``."""
    return EventLog.from_simple_log(parse_simple_log(text), name)


@box(name="Open net", group="Input")
def open_net(file: Path) -> PetriNet:
    """Opens a Petri net from the folder: a PNML file, or a net drawn in the editor."""
    from ...mining.pnml import read_pnml
    net = read_pnml(_resolve(file))
    flow.note(f"{Path(file).name}: {net.summary()}")
    return net


@box(name="Open coloured net", group="Input")
def open_cpn(file: Path) -> CPNet:
    """Opens a coloured Petri net (a CPN Tools ``.cpn`` file)."""
    from ...io.cpn_reader import read_cpn
    net = read_cpn(str(_resolve(file)))
    if net.errors:
        raise ValueError("The model does not compile: " + "; ".join(str(e) for e in net.errors[:3]))
    return net


@box(name="Open transition system", group="Input")
def open_transition_system(file: Path) -> TransitionSystem:
    """Opens a transition system typed as ``s0 -a-> s1, s0 -b-> s2`` (a ``ts.txt`` file)."""
    path = _resolve(file)
    return parse_transition_system(path.read_text(encoding="utf-8"), path.stem)


@box(name="Open dataset", group="Input")
def open_dataset(name: Literal["BPI Challenge 2012", "BPI Challenge 2013 incidents", "BPI Challenge 2017",
                               "BPI Challenge 2019", "BPI Challenge 2020 domestic declarations",
                               "Sepsis cases", "Road traffic fine management", "Hospital billing"]
                 = "Sepsis cases") -> EventLog:
    """A standard public log by name, fetched once into a shared cache and
    checked against its fingerprint, so the same name means the same bytes
    in every workflow and every paper (see ``openprocess datasets``)."""
    from ..datasets import info, open_dataset as fetch_and_read
    entry = info(name)
    log = fetch_and_read(name)
    flow.note(f"{entry.name}: {entry.citation or entry.page}")
    flow.note(f"sha256 {log.attributes.get('openprocess:sha256', '')[:16]}… · {len(log)} cases, {log.event_count} events")
    return log


@box(name="Simulate log", group="Input")
def simulate_log(net: PetriNet, cases: int = 200, noise: float = 0.0, seed: int = 0,
                 max_length: int = 200) -> EventLog:
    """Plays the net out into a log, then adds noise: with probability
    *noise* a case loses one event or has two neighbouring events swapped.
    The seed makes it repeatable.

    cases: how many cases to generate
    noise: the chance that a case is damaged (0 keeps the log clean)
    seed: the random seed, recorded in the workflow file
    """
    result = play_out(net, traces=cases, max_length=max_length, seed=seed,
                      name=f"Simulation of {net.name}")
    rng = random.Random(seed * 7919 + 17)
    damaged = 0
    for trace in result.log:
        if noise > 0 and len(trace.events) > 1 and rng.random() < noise:
            events = trace.events
            j = rng.randrange(1, len(events))
            if rng.random() < 0.5:
                del events[j]
            elif j < len(events) - 1:
                events[j], events[j + 1] = events[j + 1], events[j]
            else:
                events[j - 1], events[j] = events[j], events[j - 1]
            trace.attributes["openprocess:noise"] = "yes"
            damaged += 1
    flow.note(f"{result.completed} runs completed, {result.deadlocked} deadlocked, "
              f"{result.cut_off} cut off at {max_length} steps; {damaged} cases damaged by noise")
    return result.log
