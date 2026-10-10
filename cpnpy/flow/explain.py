"""How a box got to its result: notes, intermediate values and steps.

A box shows what it did, not just what it produced.  Two mechanisms, both
optional:

* **A result with steps.**  If a box's result has a ``steps()`` method that
  returns ``(title, content)`` rows, they are shown; ``AlphaResult`` already
  has one (the eight steps).  A ``warnings`` attribute becomes notes.
* **A trace of calls.**  While it runs, a box may call :func:`note`,
  :func:`show` and :func:`steps`::

      flow.note("Split on XOR: {a, e} | {b, c}")
      flow.show(dfg, "Filtered DFG")

  Everything goes into the :class:`Explanation` of the box that is running,
  in order.  Outside a running box the calls do nothing, so a box works as a
  plain function in a script.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from typing import Any

_current: contextvars.ContextVar["Explanation | None"] = contextvars.ContextVar(
    "cpnpy.flow.explanation", default=None)


@dataclass
class Explanation:
    """What a box reported while it ran, in order."""

    #: ``(title, content)`` rows, as the α-algorithm's eight steps.
    steps: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: Intermediate values with a label, each shown in its own viewer.
    shows: list[tuple[str, Any]] = field(default_factory=list)
    #: Every entry in the order it was made: ("note", text), ("show", label, value), ("steps", rows).
    entries: list[tuple] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.steps or self.notes or self.shows)


def current() -> Explanation | None:
    """The explanation of the box running now, or None outside a box."""
    return _current.get()


def note(text: str) -> None:
    """Record one line of what is happening."""
    explanation = _current.get()
    if explanation is not None:
        explanation.notes.append(str(text))
        explanation.entries.append(("note", str(text)))


def show(value: Any, label: str = "") -> Any:
    """Record an intermediate value (a DFG, a tree, a table) to be shown
    under *How*; returns the value, so it can wrap an expression."""
    explanation = _current.get()
    if explanation is not None:
        explanation.shows.append((label, value))
        explanation.entries.append(("show", label, value))
    return value


def steps(rows) -> None:
    """Record ``(title, content)`` rows: the derivation as the book writes it."""
    explanation = _current.get()
    if explanation is not None:
        rows = [(str(title), str(content)) for title, content in rows]
        explanation.steps.extend(rows)
        explanation.entries.append(("steps", rows))


class explaining:
    """``with explaining() as explanation:`` runs a box and collects what it
    reports."""

    def __init__(self, explanation: Explanation | None = None) -> None:
        self.explanation = explanation or Explanation()
        self._token = None

    def __enter__(self) -> Explanation:
        self._token = _current.set(self.explanation)
        return self.explanation

    def __exit__(self, *_exc) -> None:
        _current.reset(self._token)


def collect_result(value: Any, explanation: Explanation) -> None:
    """Add what a result object can say about itself: its ``steps()`` and
    its ``warnings``.  Only when the box did not record steps itself."""
    if not explanation.steps:
        method = getattr(value, "steps", None)
        if callable(method):
            try:
                rows = method()
                if isinstance(rows, list):
                    steps_rows = [(str(t), str(c)) for t, c in rows]
                    explanation.steps.extend(steps_rows)
                    explanation.entries.append(("steps", steps_rows))
            except Exception:       # noqa: BLE001 - a result's own method; never fatal
                pass
    warnings = getattr(value, "warnings", None)
    if isinstance(warnings, list):
        for warning in warnings:
            text = f"Warning: {warning}"
            if text not in explanation.notes:
                explanation.notes.append(text)
                explanation.entries.append(("note", text))
