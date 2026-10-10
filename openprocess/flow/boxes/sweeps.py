"""Sweep table: the scores of every swept value, stacked."""

from __future__ import annotations

from ... import flow
from ..box import box
from ..types import Scores, Table


@box(name="Sweep table", group="Sweep")
def sweep_table(scores: list[Scores]) -> Table:
    """Collects the scores of every value of a sweep into one table: the
    swept settings as columns (from the scores' context), then the scores.
    Feed it to Plot (with x and y) or Correlate."""
    table = Table.from_scores(scores, "Sweep")
    swept = [c for c in table.columns if c != "model" and any(c in s.context for s in scores)]
    flow.note(f"{len(table)} rows; swept: {', '.join(swept) or 'nothing'}")
    return table
