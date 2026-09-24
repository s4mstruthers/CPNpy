"""Optional bridge to PM4Py for the algorithms not implemented natively.

PM4Py is *not* a dependency.  If it is installed (``pip install -e ".[pm4py]"``)
the app offers these extra discovery algorithms:

* **Heuristics → Petri net (PM4Py)** -- PM4Py's own heuristics net, to
  compare with the built-in one (:func:`..discovery.heuristics.heuristics_net`);
* **ILP Miner** -- region-based discovery via integer linear programming;
* **Split Miner**-style / other miners can be added here the same way.

Models travel between the two libraries as PNML text, the neutral exchange
format, so nothing in the rest of CPNpy ever imports PM4Py.

Licensing note: PM4Py is AGPL-3.0.  Importing it at run time from this
optional module keeps the CPNpy code base itself independent of it.
"""

from __future__ import annotations

import os
import tempfile
from collections import Counter
from importlib.util import find_spec

from .log import SimpleLog
from .petrinet import PetriNet
from .pnml import parse_pnml


def available() -> bool:
    return find_spec("pm4py") is not None


def _dataframe(log: SimpleLog):
    import pandas as pd

    rows, case = [], 0
    base = pd.Timestamp("2000-01-01")
    for sequence, count in log.items():
        for _ in range(count):
            case += 1
            for position, activity in enumerate(sequence):
                rows.append({"case:concept:name": str(case), "concept:name": activity,
                             "time:timestamp": base + pd.Timedelta(minutes=position)})
    return pd.DataFrame(rows)


def _to_native(net, initial, final, name: str) -> PetriNet:
    import pm4py

    handle, path = tempfile.mkstemp(suffix=".pnml")
    os.close(handle)
    try:
        pm4py.write_pnml(net, initial, final, path)
        with open(path, "rb") as stream:
            native = parse_pnml(stream.read())
    finally:
        os.unlink(path)
    native.name = name
    return native


def heuristics_petri_net(log: SimpleLog, dependency_threshold: float = 0.5) -> PetriNet:
    import pm4py

    net, im, fm = pm4py.discover_petri_net_heuristics(
        _dataframe(log), dependency_threshold=dependency_threshold)
    result = _to_native(net, im, fm, "Heuristics (PM4Py)")
    result.info["algorithm"] = f"Heuristics Miner via PM4Py (threshold {dependency_threshold:g})"
    return result


def ilp_petri_net(log: SimpleLog, alpha: float = 1.0) -> PetriNet:
    import pm4py

    net, im, fm = pm4py.discover_petri_net_ilp(_dataframe(log), alpha=alpha)
    result = _to_native(net, im, fm, "ILP (PM4Py)")
    result.info["algorithm"] = f"ILP Miner via PM4Py (alpha {alpha:g})"
    return result


__all__ = ["available", "heuristics_petri_net", "ilp_petri_net", "Counter"]
