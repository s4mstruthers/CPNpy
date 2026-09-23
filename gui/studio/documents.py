"""Open documents: the objects the sidebar lists.

A *document* wraps one thing the user opened or produced -- an event log or
a Petri net -- together with the derived data the views need (statistics,
activity colours) so that switching between pages never recomputes them.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from ...mining.log import Classifier, EventLog
from ...mining.petrinet import PetriNet
from ...mining.stats import LogSummary, summarise
from .style import ActivityColours

_ids = itertools.count(1)


@dataclass(eq=False)
class LogDocument:
    log: EventLog
    path: str | None = None
    id: int = field(default_factory=lambda: next(_ids))

    def __post_init__(self) -> None:
        self.classifier: Classifier = self.log.default_classifier()
        self._summary: LogSummary | None = None
        self._colours: ActivityColours | None = None

    @property
    def name(self) -> str:
        return self.log.name

    def set_classifier(self, classifier: Classifier) -> None:
        self.classifier = classifier
        self._summary = None
        self._colours = None

    @property
    def summary(self) -> LogSummary:
        if self._summary is None:
            self._summary = summarise(self.log, self.classifier)
        return self._summary

    @property
    def colours(self) -> ActivityColours:
        if self._colours is None:
            self._colours = ActivityColours([a.name for a in self.summary.activities])
        return self._colours

    def simple_log(self):
        return self.log.simple_log(self.classifier)


@dataclass(eq=False)
class ModelDocument:
    net: PetriNet
    path: str | None = None
    #: Where it came from: "α-algorithm on <log>", "PNML file", ...
    origin: str = ""
    #: Algorithm-specific extras (AlphaResult, InductiveResult, ...)
    derivation: object | None = None
    source_log: LogDocument | None = None
    id: int = field(default_factory=lambda: next(_ids))

    @property
    def name(self) -> str:
        return self.net.name


@dataclass(eq=False)
class CpnDocument:
    """A coloured Petri net (CPN Tools model) being edited and simulated."""

    net: object                      # cpnpy.model.net.CPNet
    path: str | None = None
    id: int = field(default_factory=lambda: next(_ids))
    #: Edited since it was opened or last saved.
    dirty: bool = False

    @property
    def name(self) -> str:
        return self.net.name


@dataclass(eq=False)
class ComparisonDocument:
    """Two or more open logs shown side by side (nothing is stored on disk)."""

    logs: list
    id: int = field(default_factory=lambda: next(_ids))
    path: str | None = None

    @property
    def name(self) -> str:
        if len(self.logs) == 2:
            return f"{self.logs[0].name} vs {self.logs[1].name}"
        return f"{len(self.logs)} logs compared"
