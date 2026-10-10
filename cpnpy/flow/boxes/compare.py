"""Compare: any number of scores side by side."""

from __future__ import annotations

from ... import flow
from ..box import box
from ..types import Scores, Table


@box(name="Compare", group="Compare")
def compare(scores: list[Scores]) -> Table:
    """Puts any number of scores side by side, with columns taken from the
    scores themselves. Under a sweep it collects the scores of every value."""
    table = Table.from_scores(scores, "Compare")
    flow.note(f"{len(table)} models, {len(table.columns) - 1} columns")
    return table
