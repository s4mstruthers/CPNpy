"""What an exercise gives: its files, read once, and the student's variant.

A :class:`Context` is made for one exercise and handed to every check and
compute.  It reads the log, the net and the transition system the first
time they are asked for, so checking ten answer boxes reads the log once.

Variants (``seed: student`` in the exercise or the pack, with
``generate: net.pnml, cases: 20``): the exercise has no log file; its log is
played out from the net with a seed made from the student's name, so every
student gets a log of their own and the computes still check every answer
(see :mod:`.pack` for where the name is kept).
"""

from __future__ import annotations

import zlib
from functools import cached_property
from pathlib import Path

from .pack import Exercise


class TaskError(ValueError):
    """The answer block cannot be checked (a missing file, an unknown compute)."""


class Context:
    """The exercise's files, read once and only when a check needs them."""

    def __init__(self, exercise: Exercise, student: str | None = None) -> None:
        self.exercise = exercise
        self.files = exercise.files
        #: The student's name, for variants (None: the pack has no variants).
        self.student = student if student is not None else exercise.student()
        self._cache: dict = {}

    # -- files ------------------------------------------------------------------------
    def path(self, name: str | None, default: Path | None, what: str) -> Path:
        if name:
            path = self.files.file(name)
            if path is None:
                raise TaskError(f"the exercise has no file “{name}”")
            return path
        if default is None:
            raise TaskError(f"the exercise has no {what}")
        return default

    @property
    def seed(self) -> int | None:
        """The seed of the student's variant (None: no variants)."""
        setting = self.exercise.setting("seed")
        if setting is None:
            return None
        if setting.strip().lower() in ("student", "name", "per student"):
            return zlib.crc32((self.student or "").strip().casefold().encode("utf-8"))
        try:
            return int(setting)
        except ValueError:
            raise TaskError(f"“seed: {setting}” is neither a number nor “student”") from None

    def generated_log(self):
        """The log played out from ``generate: net.pnml, cases: 20`` (an EventLog),
        or None when the exercise does not generate one."""
        setting = self.exercise.setting("generate")
        if not setting:
            return None
        if "generated" in self._cache:
            return self._cache["generated"]
        from ..mining.playout import play_out
        from .exam import parse_generate
        net_name, cases, max_length = parse_generate(setting)
        net = self.net(net_name)
        from ..mining.analysis import check_workflow_net
        from ..mining.petrinet import Marking
        if not net.initial_marking:
            workflow = check_workflow_net(net)
            if workflow.is_workflow_net:
                net = net.copy()
                net.initial_marking = Marking({workflow.source: 1})
                net.final_marking = Marking({workflow.sink: 1})
        seed = self.seed if self.seed is not None else 0
        log = play_out(net, traces=cases, max_length=max_length, seed=seed,
                       name=f"Generated log (seed {seed})").log
        self._cache["generated"] = log
        return log

    def event_log(self, name: str | None = None):
        """The exercise's log as an :class:`EventLog` (with timestamps when the
        file has them)."""
        key = ("event_log", name)
        if key in self._cache:
            return self._cache[key]
        from ..mining.csv_import import guess_mapping, read_csv, sniff
        from ..mining.log import EventLog, parse_simple_log
        from ..mining.xes import read_xes
        if not name and self.files.log is None:
            generated = self.generated_log()
            if generated is not None:
                self._cache[key] = generated
                return generated
        path = self.path(name, self.files.log, "log (log.txt, log.xes or log.csv)")
        lower = path.name.lower()
        if lower.endswith(".txt"):
            log = EventLog.from_simple_log(
                parse_simple_log(path.read_text(encoding="utf-8", errors="replace")), "L")
        elif lower.endswith(".csv"):
            log = read_csv(str(path), guess_mapping(sniff(str(path))[1]))
        else:
            log = read_xes(str(path))
        self._cache[key] = log
        return log

    def simple_log(self, name: str | None = None):
        """The log as a multiset of activity sequences."""
        key = ("simple_log", name)
        if key not in self._cache:
            self._cache[key] = self.event_log(name).simple_log()
        return self._cache[key]

    def net(self, name: str | None = None):
        key = ("net", name)
        if key not in self._cache:
            from ..mining.pnml import read_pnml
            self._cache[key] = read_pnml(str(self.path(name, self.files.net, "net (net.pnml)")))
        return self._cache[key]

    def ts(self, name: str | None = None):
        key = ("ts", name)
        if key not in self._cache:
            from ..mining.transition_system import parse_transition_system
            path = self.path(name, self.files.ts, "transition system (ts.txt)")
            self._cache[key] = parse_transition_system(
                path.read_text(encoding="utf-8", errors="replace"))
        return self._cache[key]

    @cached_property
    def alpha(self):
        from ..mining.discovery.alpha import alpha_miner
        return alpha_miner(self.simple_log())

    @cached_property
    def library(self):
        """The boxes a workflow in this exercise may use (see :mod:`openprocess.flow`)."""
        from ..flow.library import library_for
        return library_for(self.exercise.folder)
