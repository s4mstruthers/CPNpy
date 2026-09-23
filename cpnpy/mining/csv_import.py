"""Importing event logs from CSV files.

A CSV event log has one row per event.  Three columns are essential:

* **case id** -- which process instance the event belongs to,
* **activity** -- what happened,
* **timestamp** -- when (optional, but needed to order events and for any
  time-based analysis).

Everything else becomes an ordinary event attribute.

Because column names differ per source system, :func:`guess_mapping` proposes
a mapping from common names (``case:concept:name``, ``Case ID``, ``Activity``,
``Timestamp``, ...), and the GUI lets the user correct it before importing.

Ordering: rows of one case are sorted by timestamp.  The sort is *stable*, so
events with equal (or missing) timestamps keep their file order -- which is
the only other evidence of order a CSV contains.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .log import KEY_LIFECYCLE, KEY_NAME, KEY_RESOURCE, KEY_TIME, Event, EventLog, Trace


@dataclass
class ColumnMapping:
    """Which CSV column plays which role.  ``None`` means "not present"."""

    case: str
    activity: str
    timestamp: str | None = None
    resource: str | None = None
    lifecycle: str | None = None


_CANDIDATES = {
    "case": ["case:concept:name", "case id", "caseid", "case_id", "case", "trace", "case:id"],
    "activity": ["concept:name", "activity", "activity name", "event", "task", "action"],
    "timestamp": ["time:timestamp", "timestamp", "complete timestamp", "time", "date",
                  "end", "end time", "completetime"],
    "resource": ["org:resource", "resource", "user", "performer", "agent"],
    "lifecycle": ["lifecycle:transition", "lifecycle", "transition", "event type"],
}


def sniff(path: str | Path, sample_size: int = 64_000) -> tuple[csv.Dialect, list[str]]:
    """Detect the delimiter and read the header row."""
    with open(path, newline="", encoding="utf-8-sig") as handle:
        sample = handle.read(sample_size)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel  # fall back to plain commas
    header = next(csv.reader(sample.splitlines(), dialect), [])
    return dialect, header


def guess_mapping(header: list[str]) -> ColumnMapping | None:
    """Propose a mapping by matching column names, case-insensitively."""
    lowered = {name.strip().lower(): name for name in header}
    chosen: dict[str, str | None] = {}
    for role, candidates in _CANDIDATES.items():
        chosen[role] = next((lowered[c] for c in candidates if c in lowered), None)
    if chosen["case"] is None or chosen["activity"] is None:
        return None
    return ColumnMapping(**chosen)  # type: ignore[arg-type]


_DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
    "%d-%m-%Y %H:%M:%S.%f", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d-%m-%Y",
    "%d/%m/%Y %H:%M:%S.%f", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
    "%Y/%m/%d %H:%M:%S.%f", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d",
    "%d.%m.%Y %H:%M:%S.%f", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y",
]


def parse_timestamp(text: str) -> datetime | None:
    """Parse a timestamp in ISO 8601 or one of the common European forms.

    Day-first is assumed for ``dd-mm-yyyy`` because that is the convention in
    the Netherlands and most of Europe; ISO dates (year first) are
    unambiguous anyway.  Returns ``None`` rather than raising, so one odd
    cell does not abort an import.
    """
    value = text.strip()
    if not value:
        return None
    try:
        from .xes import parse_xes_date
        return parse_xes_date(value.replace(" ", "T", 1) if "T" not in value and
                              len(value) > 10 and value[4] == "-" else value)
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _typed(text: str):
    """Best-effort conversion of an ordinary cell to int or float."""
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def read_csv(path: str | Path, mapping: ColumnMapping | None = None) -> EventLog:
    """Read a CSV event log.  Without a mapping, one is guessed from the header."""
    dialect, header = sniff(path)
    mapping = mapping or guess_mapping(header)
    if mapping is None:
        raise ValueError(
            "Could not identify the case id and activity columns. "
            f"Columns found: {', '.join(header)}")

    cases: dict[str, list[tuple[int, Event]]] = {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for row_number, row in enumerate(csv.DictReader(handle, dialect=dialect)):
            case_id = (row.get(mapping.case) or "").strip()
            if not case_id:
                continue
            attributes: dict = {}
            for column, cell in row.items():
                if column is None or cell is None:
                    continue
                if column == mapping.case:
                    continue
                if column == mapping.activity:
                    attributes[KEY_NAME] = cell.strip()
                elif column == mapping.timestamp:
                    stamp = parse_timestamp(cell)
                    if stamp is not None:
                        attributes[KEY_TIME] = stamp
                elif column == mapping.resource:
                    attributes[KEY_RESOURCE] = cell.strip()
                elif column == mapping.lifecycle:
                    attributes[KEY_LIFECYCLE] = cell.strip().lower()
                elif cell != "":
                    attributes[column] = _typed(cell)
            cases.setdefault(case_id, []).append((row_number, Event(attributes)))

    log = EventLog(attributes={KEY_NAME: Path(path).stem}, source_path=str(path))
    for case_id, rows in cases.items():
        # Sort by time only if every event of the case has a timestamp;
        # otherwise we cannot place the undated ones, and file order is the
        # more honest ordering.  Ties keep file order (row number).
        if all(event.timestamp is not None for _, event in rows):
            rows.sort(key=lambda item: (item[1].timestamp, item[0]))
        log.traces.append(Trace({KEY_NAME: case_id}, [event for _, event in rows]))
    return log
