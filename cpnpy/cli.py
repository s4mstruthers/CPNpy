"""Command-line interface: ``cpnpy <command> [options]``.

The CLI exists so that the engine is usable without the GUI -- in a script, in
a notebook, from a Makefile, or over SSH.  Every command works on a ``.cpn``
file, except ``example``, which writes one of the built-in demo models so you
have something to try immediately.

Commands
--------
``check``       parse a model and list any problems
``info``        summarise pages, declarations and net elements
``simulate``    run the simulator and print the firing log
``statespace``  generate the reachability graph and print the report
``example``     write a built-in example model to a ``.cpn`` file
``gui``         launch the CPN editor
``studio``      launch CPNpy Studio (process mining workspace)
``mine``        process mining from the command line:
                ``stats``, ``discover``, ``conform``, ``soundness``
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .analysis.state_space import StateSpace
from .io.cpn_reader import read_cpn
from .io.cpn_writer import write_cpn
from .model.net import CPNet
from .sim.simulator import DeadMarkingError, Simulator


def _load(path: str) -> CPNet:
    net = read_cpn(path)
    if net.errors:
        print(f"{len(net.errors)} problem(s) found while compiling '{path}':",
              file=sys.stderr)
        for issue in net.errors:
            print(f"  {issue}", file=sys.stderr)
    return net


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def command_check(arguments: argparse.Namespace) -> int:
    net = _load(arguments.model)
    if net.errors:
        return 1
    print(f"'{net.name}' compiled cleanly: "
          f"{sum(1 for _ in net.all_places())} places, "
          f"{sum(1 for _ in net.all_transitions())} transitions, "
          f"{sum(1 for _ in net.all_arcs())} arcs.")
    return 0


def command_info(arguments: argparse.Namespace) -> int:
    net = _load(arguments.model)
    print(f"Model: {net.name}")
    print(f"Pages: {len(net.pages)}")
    for page in net.pages:
        print(f"  {page.name}: {len(page.places)} places, "
              f"{len(page.transitions)} transitions, {len(page.arcs)} arcs")

    print("\nColour sets:")
    for name, colour_set in sorted(net.declarations.colour_sets.items()):
        finite = "finite" if colour_set.is_finite() else "infinite"
        timed = ", timed" if colour_set.timed else ""
        print(f"  {name:<16}{type(colour_set).__name__:<22}{finite}{timed}")

    print("\nVariables:")
    for name, colour_set_name in sorted(net.declarations.variables.items()):
        print(f"  {name} : {colour_set_name}")

    print("\nInitial marking:")
    print(net.initial_marking().describe(net) or "  (empty)")
    return 0


def command_simulate(arguments: argparse.Namespace) -> int:
    net = _load(arguments.model)
    if net.errors:
        return 1
    simulator = Simulator(net, seed=arguments.seed)

    print("Initial marking:")
    print(simulator.marking.describe(net))
    print()

    taken = simulator.run(arguments.steps)
    for record in simulator.log:
        print(record.describe(net))

    print()
    print(f"Fired {taken} step(s); final state at time {simulator.clock}:")
    print(simulator.marking.describe(net))

    if taken < arguments.steps:
        print("\nStopped early: the marking is dead (nothing further is enabled).")
    return 0


def command_statespace(arguments: argparse.Namespace) -> int:
    net = _load(arguments.model)
    if net.errors:
        return 1
    space = StateSpace(net).generate(max_nodes=arguments.max_nodes)
    print(space.report())
    return 0


def command_example(arguments: argparse.Namespace) -> int:
    # Imported lazily so that the examples directory is optional at runtime.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
    try:
        import models  # type: ignore[import-not-found]
    except ImportError:
        print("The examples directory is not available.", file=sys.stderr)
        return 1

    if arguments.name not in models.ALL_EXAMPLES:
        print(f"Unknown example '{arguments.name}'. Available: "
              f"{', '.join(sorted(models.ALL_EXAMPLES))}", file=sys.stderr)
        return 1

    net = models.ALL_EXAMPLES[arguments.name]()
    path = write_cpn(net, arguments.output)
    print(f"Wrote {path}")
    return 0


def command_gui(arguments: argparse.Namespace) -> int:
    try:
        from .gui.app import main as gui_main
    except ImportError:
        print("The GUI needs PySide6. Install it with:\n"
              "  pip install 'cpnpy[gui]'", file=sys.stderr)
        return 1
    argv = ["cpn-ide"] + ([arguments.model] if arguments.model else [])
    return gui_main(argv)


def command_studio(arguments: argparse.Namespace) -> int:
    try:
        from .gui.studio.app import main as studio_main
    except ImportError:
        print("CPNpy Studio needs PySide6. Install it with:\n"
              "  pip install 'cpnpy[gui]'", file=sys.stderr)
        return 1
    return studio_main(["cpnpy-studio"] + list(arguments.files))


# ---------------------------------------------------------------------------
# Process mining commands
# ---------------------------------------------------------------------------
def _read_log(path: str):
    """An event log from .xes/.xes.gz/.csv, or textbook notation in a .txt file."""
    from .mining import EventLog, parse_simple_log, read_csv, read_xes
    lower = path.lower()
    if lower.endswith(".csv"):
        return read_csv(path)
    if lower.endswith(".txt"):
        return EventLog.from_simple_log(parse_simple_log(Path(path).read_text(encoding="utf-8")), Path(path).stem)
    return read_xes(path)


def command_mine_stats(arguments: argparse.Namespace) -> int:
    from .mining import summarise
    from .mining.stats import format_duration
    log = _read_log(arguments.log)
    s = summarise(log)
    print(f"{log.name}: {s.case_count:,} cases, {s.event_count:,} events, "
          f"{s.activity_count} activities, {s.variant_count:,} variants "
          f"(classifier: {log.default_classifier().name})")
    if s.start:
        print(f"From {s.start} to {s.end}; median case duration "
              f"{format_duration(s.median_case_duration)}")
    print("\nActivities:")
    for a in s.activities:
        print(f"  {a.name:<30} {a.occurrences:>8,} events  {a.cases:>6,} cases")
    print(f"\nTop variants (of {s.variant_count:,}):")
    for variant in s.variants[:arguments.top]:
        print(f"  {variant.count:>6,} x  " + ", ".join(variant.sequence))
    return 0


def command_mine_discover(arguments: argparse.Namespace) -> int:
    from .mining import alpha_miner, inductive_miner, write_pnml
    simple = _read_log(arguments.log).simple_log()
    if arguments.algorithm == "alpha":
        result = alpha_miner(simple)
        for step, content in result.steps():
            print(f"{step}\n    {content}")
        for warning in result.warnings:
            print(f"warning: {warning}")
    else:
        noise = arguments.noise if arguments.algorithm == "imf" else 0.0
        result = inductive_miner(simple, noise_threshold=noise)
        print("Process tree:", result.tree)
        print("\n".join(result.trace_of_steps))
    print(f"\nModel: {result.net.summary()}")
    if arguments.output:
        write_pnml(result.net, arguments.output)
        print(f"Wrote {arguments.output}")
    return 0


def command_mine_conform(arguments: argparse.Namespace) -> int:
    from .mining import align_log, generalisation, precision, read_pnml, simplicity, token_replay
    net = read_pnml(arguments.model)
    simple = _read_log(arguments.log).simple_log()
    replay = token_replay(net, simple)
    alignments = align_log(net, simple)
    print(f"Fitness (alignments)   {alignments.average_fitness:.4f}   "
          f"log-level {alignments.log_fitness:.4f}")
    print(f"Fitness (token replay) {replay.fitness:.4f}   "
          f"p={replay.produced} c={replay.consumed} m={replay.missing} r={replay.remaining}")
    print(f"Precision (ETC)        {precision(net, simple):.4f}")
    print(f"Generalisation         {generalisation(replay):.4f}")
    print(f"Simplicity             {simplicity(net):.4f}")
    print(f"Fitting cases          {alignments.fitting_traces} / {alignments.trace_count}")
    return 0


def command_mine_soundness(arguments: argparse.Namespace) -> int:
    from .mining import check_soundness, read_pnml
    report = check_soundness(read_pnml(arguments.model))
    verdict = {True: "SOUND", False: "NOT SOUND", None: "UNDECIDED"}[report.sound]
    print(verdict)
    for finding in report.findings:
        print(f"  - {finding}")
    return 0 if report.sound else 1


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cpnpy",
        description="Coloured Petri Net tools: edit, simulate and analyse .cpn models.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="parse a model and report problems")
    check.add_argument("model")
    check.set_defaults(handler=command_check)

    info = subparsers.add_parser("info", help="summarise a model")
    info.add_argument("model")
    info.set_defaults(handler=command_info)

    simulate = subparsers.add_parser("simulate", help="run the simulator")
    simulate.add_argument("model")
    simulate.add_argument("-n", "--steps", type=int, default=50,
                          help="maximum number of steps (default 50)")
    simulate.add_argument("--seed", type=int, default=None,
                          help="seed for reproducible random choices")
    simulate.set_defaults(handler=command_simulate)

    statespace = subparsers.add_parser("statespace", help="generate the state space")
    statespace.add_argument("model")
    statespace.add_argument("--max-nodes", type=int, default=10_000,
                            help="stop after this many nodes (default 10000)")
    statespace.set_defaults(handler=command_statespace)

    example = subparsers.add_parser("example", help="write a built-in example model")
    example.add_argument("name", help="simple_transfer | dining_philosophers | "
                                      "timed_conveyor | guarded_choice")
    example.add_argument("-o", "--output", default="example.cpn")
    example.set_defaults(handler=command_example)

    gui = subparsers.add_parser("gui", help="launch the desktop application")
    gui.add_argument("model", nargs="?", default=None)
    gui.set_defaults(handler=command_gui)

    studio = subparsers.add_parser("studio", help="launch CPNpy Studio (process mining)")
    studio.add_argument("files", nargs="*", help="logs (.xes/.csv) or nets (.pnml) to open")
    studio.set_defaults(handler=command_studio)

    mine = subparsers.add_parser("mine", help="process mining on event logs")
    mining = mine.add_subparsers(dest="mining_command", required=True)
    stats = mining.add_parser("stats", help="summarise an event log")
    stats.add_argument("log", help=".xes, .xes.gz, .csv, or .txt in textbook notation")
    stats.add_argument("--top", type=int, default=10, help="variants to list (default 10)")
    stats.set_defaults(handler=command_mine_stats)
    discover = mining.add_parser("discover", help="discover a Petri net")
    discover.add_argument("log")
    discover.add_argument("-a", "--algorithm", choices=["alpha", "im", "imf"], default="im")
    discover.add_argument("--noise", type=float, default=0.2, help="IMf noise threshold")
    discover.add_argument("-o", "--output", help="write the model as PNML")
    discover.set_defaults(handler=command_mine_discover)
    conform = mining.add_parser("conform", help="fitness, precision, ... of a model on a log")
    conform.add_argument("model", help="a .pnml file")
    conform.add_argument("log")
    conform.set_defaults(handler=command_mine_conform)
    soundness = mining.add_parser("soundness", help="check WF-net soundness")
    soundness.add_argument("model", help="a .pnml file")
    soundness.set_defaults(handler=command_mine_soundness)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    return arguments.handler(arguments)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
