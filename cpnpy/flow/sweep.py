"""Sweeps: run the boxes after a setting once per value.

A sweep is a setting marked as a range or a list rather than a loop drawn on
the canvas::

    node.settings["noise"] = Sweep.parse("0..0.5 step 0.1")
    node.settings["seed"] = Sweep([0, 1, 2, 3, 4])

The runner runs every box after a swept box once per value (the cartesian
product when several settings are swept), and a box that takes *any
number* of inputs (Compare, Plot, Sweep table) collects the results of all
the values.  Every :class:`~.types.Scores` and :class:`~.types.Table` made
under a sweep carries the values in its ``context``, so a stacked table
tells them apart.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from typing import Any

_RANGE = re.compile(r"^\s*(-?[\d.]+)\s*\.\.\s*(-?[\d.]+)\s*(?:step\s+(-?[\d.]+))?\s*$")


@dataclass(frozen=True)
class Sweep:
    """The values a setting takes, one run each."""

    values: tuple = field(default_factory=tuple)

    @classmethod
    def parse(cls, text: str) -> "Sweep":
        """``"0..0.5 step 0.1"``, ``"1..5"`` (step 1) or ``"a, b, c"``."""
        match = _RANGE.match(text)
        if match:
            start, stop, step = (float(match.group(1)), float(match.group(2)),
                                 float(match.group(3) or 1))
            if step == 0 or (stop - start) * step < 0:
                raise ValueError(f"The range {text!r} never reaches its end")
            values, value, count = [], start, 0
            while (value <= stop + 1e-9 if step > 0 else value >= stop - 1e-9) and count < 10_000:
                values.append(round(value, 10))
                value += step
                count += 1
            if all(float(v).is_integer() for v in values) and all(
                    "." not in part for part in (match.group(1), match.group(2), match.group(3) or "")):
                values = [int(v) for v in values]
            return cls(tuple(values))
        parts = [p.strip() for p in text.split(",") if p.strip()]
        if not parts:
            raise ValueError("A sweep needs at least one value")
        return cls(tuple(_number(p) for p in parts))

    def describe(self) -> str:
        values = self.values
        if len(values) > 6:
            return f"{values[0]} … {values[-1]} ({len(values)} values)"
        return ", ".join(str(v) for v in values)

    def __len__(self) -> int:
        return len(self.values)

    def to_json(self) -> dict:
        return {"sweep": list(self.values)}


def _number(text: str):
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return text


def is_sweep(value: Any) -> bool:
    return isinstance(value, Sweep)


def assignments(swept: list[tuple[str, str, Sweep]]) -> list[dict[tuple[str, str], Any]]:
    """Every combination of values: ``[{(node, setting): value, ...}, ...]``."""
    if not swept:
        return [{}]
    keys = [(node, setting) for node, setting, _ in swept]
    return [dict(zip(keys, combination))
            for combination in itertools.product(*(s.values for _, _, s in swept))]


__all__ = ["Sweep", "assignments", "is_sweep"]
