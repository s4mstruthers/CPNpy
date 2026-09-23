"""Process mining: event logs, discovery, conformance checking.

This package is the "ProM half" of the application.  Like the CPN engine it
is pure standard-library Python: every algorithm is implemented here, with
the textbook definitions in the docstrings, so the code doubles as a study
companion for the course.

Quick start::

    from cpnpy.mining import read_xes, inductive_miner, align_log, precision

    log = read_xes("PlaneBoarding.xes")
    simple = log.simple_log()                 # multiset of activity sequences
    model = inductive_miner(simple).net       # a sound WF-net
    fitness = align_log(model, simple).average_fitness
    print(fitness, precision(model, simple))

Modules
-------
``log``, ``xes``, ``csv_import``, ``stats``
    Event logs: data model, file formats, descriptive statistics.
``dfg``, ``footprint``
    Directly-follows graphs and the ordering relations / footprint matrix.
``petrinet``, ``pnml``, ``analysis``, ``processtree``
    Labelled P/T nets, PNML, state spaces, properties, WF-net soundness,
    process trees.
``discovery``
    α-algorithm, Heuristics Miner (dependency graph), Inductive Miner (IM/IMf).
``conformance``
    Token-based replay, alignments, precision, generalisation, simplicity.
``layout``
    Automatic layered graph layout for drawing discovered models.
"""

from .analysis import (analyse, check_soundness, check_workflow_net, coverability_graph,
                       reachability_graph)
from .conformance.alignments import align_log, align_trace
from .conformance.quality import generalisation, precision, simplicity
from .conformance.token_replay import token_replay
from .csv_import import read_csv
from .dfg import discover_dfg
from .discovery.alpha import alpha_miner
from .discovery.heuristics import heuristics_miner
from .discovery.inductive import inductive_miner
from .footprint import compare_footprints, footprint_of_log, footprint_of_net
from .log import (BY_NAME, BY_NAME_COMPLETE, BY_NAME_LIFECYCLE, Classifier, Event, EventLog,
                  Trace, format_simple_log, parse_simple_log)
from .petrinet import Marking, PetriNet
from .pnml import read_pnml, write_pnml
from .processtree import Operator, ProcessTree, to_petri_net
from .stats import summarise
from .xes import read_xes, write_xes

__all__ = [
    "BY_NAME", "BY_NAME_COMPLETE", "BY_NAME_LIFECYCLE", "Classifier", "Event", "EventLog",
    "Marking", "Operator", "PetriNet", "ProcessTree", "Trace",
    "align_log", "align_trace", "alpha_miner", "analyse", "check_soundness",
    "check_workflow_net", "compare_footprints", "coverability_graph", "discover_dfg",
    "footprint_of_log", "footprint_of_net", "format_simple_log", "generalisation",
    "heuristics_miner", "inductive_miner", "parse_simple_log", "precision",
    "reachability_graph", "read_csv", "read_pnml", "read_xes", "simplicity", "summarise",
    "to_petri_net", "token_replay", "write_pnml", "write_xes",
]
