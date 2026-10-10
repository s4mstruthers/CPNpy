"""Converters between CPNpy's types and other libraries' objects.

A box that wraps a pandas, PM4Py or matplotlib function asks for the
conversion in one line::

    df = convert(log, "pandas.DataFrame")       # one row per event
    return convert(fig, Figure)                  # a matplotlib figure as SVG

Foreign types are named by their dotted path, so this module imports none
of them until a conversion is asked for.  Register your own with
:func:`register`: a function from one type to another, keyed by the source
class and the target (a class, or a dotted name).
"""

from __future__ import annotations

import importlib
from typing import Any, Callable

from ..mining.log import KEY_NAME, KEY_RESOURCE, KEY_TIME, EventLog, SimpleLog
from ..mining.petrinet import PetriNet
from .types import Figure, Table

_converters: dict[tuple[str, str], Callable] = {}


def _name(target) -> str:
    if isinstance(target, str):
        return target
    return f"{target.__module__}.{target.__qualname__}"


def register(source, target, function: Callable) -> None:
    """``function(value) -> converted`` for a value of class ``source``."""
    _converters[(_name(source), _name(target))] = function


def _class_names(value) -> list[str]:
    return [f"{cls.__module__}.{cls.__qualname__}" for cls in type(value).__mro__]


def can_convert(value: Any, target) -> bool:
    return any((name, _name(target)) in _converters for name in _class_names(value))


def convert(value: Any, target):
    """Convert ``value`` to ``target`` (a class or a dotted name)."""
    wanted = _name(target)
    for name in _class_names(value):
        if name == wanted:
            return value
        function = _converters.get((name, wanted))
        if function is not None:
            return function(value)
    raise TypeError(f"No converter from {type(value).__name__} to {wanted}")


def converters() -> list[tuple[str, str]]:
    return sorted(_converters)


# ---------------------------------------------------------------------------
# Built-in converters
# ---------------------------------------------------------------------------
def _simple_to_log(simple: SimpleLog) -> EventLog:
    return EventLog.from_simple_log(simple)


def _log_to_simple(log: EventLog) -> SimpleLog:
    return log.simple_log()


def _log_to_dataframe(log: EventLog):
    pd = importlib.import_module("pandas")
    rows = []
    for trace in log:
        case = trace.case_id
        for event in trace:
            row = {"case:concept:name": case}
            row.update(event.attributes)
            rows.append(row)
    frame = pd.DataFrame(rows)
    if KEY_TIME in frame.columns:
        frame[KEY_TIME] = pd.to_datetime(frame[KEY_TIME], utc=True, errors="coerce")
    return frame


def _dataframe_to_log(frame) -> EventLog:
    from ..mining.log import Event, Trace
    case_column = "case:concept:name" if "case:concept:name" in frame.columns else frame.columns[0]
    log = EventLog(attributes={KEY_NAME: "DataFrame"})
    for case, group in frame.groupby(case_column, sort=False):
        trace = Trace({KEY_NAME: str(case)})
        for record in group.drop(columns=[case_column]).to_dict("records"):
            attributes = {k: (v.to_pydatetime() if hasattr(v, "to_pydatetime") else v)
                          for k, v in record.items() if v == v}       # drop NaN
            trace.events.append(Event(attributes))
        log.traces.append(trace)
    return log


def _table_to_dataframe(table: Table):
    pd = importlib.import_module("pandas")
    return pd.DataFrame(table.rows, columns=table.columns)


def _dataframe_to_table(frame) -> Table:
    columns = [str(c) for c in frame.columns]
    rows = [[_plain(v) for v in row] for row in frame.itertuples(index=False, name=None)]
    return Table("DataFrame", columns, rows)


def _series_to_table(series) -> Table:
    name = str(series.name or "value")
    return Table(name, ["index", name], [[_plain(k), _plain(v)] for k, v in series.items()])


def _plain(value):
    item = getattr(value, "item", None)          # NumPy scalars -> Python
    if callable(item):
        try:
            return item()
        except (ValueError, TypeError):
            return value
    return value


def _ndarray_to_table(array) -> Table:
    rows = array.tolist()
    if rows and not isinstance(rows[0], list):
        rows = [[r] for r in rows]
    width = len(rows[0]) if rows else 0
    return Table("array", [f"c{i}" for i in range(width)], rows)


def _mpl_figure_to_figure(fig) -> Figure:
    import io
    buffer = io.StringIO()
    fig.savefig(buffer, format="svg", bbox_inches="tight")
    svg = buffer.getvalue()
    png = io.BytesIO()
    try:
        fig.savefig(png, format="png", dpi=160, bbox_inches="tight")
        png_bytes = png.getvalue()
    except Exception:    # noqa: BLE001 - no PNG backend
        png_bytes = None
    title = ""
    try:
        title = fig.axes[0].get_title() if fig.axes else ""
    except Exception:    # noqa: BLE001
        pass
    return Figure(title or "Figure", svg=svg, png=png_bytes)


def _petri_to_pm4py(net: PetriNet):
    import os
    import tempfile
    pm4py = importlib.import_module("pm4py")
    from ..mining.pnml import write_pnml
    handle, path = tempfile.mkstemp(suffix=".pnml")
    os.close(handle)
    try:
        write_pnml(net, path)
        return pm4py.read_pnml(path)
    finally:
        os.unlink(path)


def _pm4py_to_petri(triple) -> PetriNet:
    from ..mining.pm4py_bridge import _to_native
    net, im, fm = triple
    return _to_native(net, im, fm, getattr(net, "name", None) or "PM4Py net")


register(SimpleLog, EventLog, _simple_to_log)
register(EventLog, SimpleLog, _log_to_simple)
register(EventLog, "pandas.core.frame.DataFrame", _log_to_dataframe)
register("pandas.core.frame.DataFrame", EventLog, _dataframe_to_log)
register(Table, "pandas.core.frame.DataFrame", _table_to_dataframe)
register("pandas.core.frame.DataFrame", Table, _dataframe_to_table)
register("pandas.core.series.Series", Table, _series_to_table)
register("numpy.ndarray", Table, _ndarray_to_table)
register("matplotlib.figure.Figure", Figure, _mpl_figure_to_figure)
register(PetriNet, "pm4py", _petri_to_pm4py)
register(tuple, "cpnpy.mining.petrinet.PetriNet", _pm4py_to_petri)

__all__ = ["can_convert", "convert", "converters", "register"]
