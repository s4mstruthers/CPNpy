"""The columnar log store: the same log, read into arrays instead of objects,
must look exactly the same through the EventLog API."""

from __future__ import annotations

from pathlib import Path

from openprocess.mining import discover_dfg, read_xes, summarise
from openprocess.mining.columns import ColumnStore, LazyTraces
from openprocess.mining.log import BY_NAME, KEY_NAME, EventLog, Trace
from openprocess.mining.xes import read_xes_string, xes_string

DATA = Path(__file__).parent / "data"


def test_columnar_log_reads_the_same_as_objects():
    objects = read_xes(DATA / "plane_wilma_10.xes", columnar=False)
    columns = read_xes(DATA / "plane_wilma_10.xes", columnar=True)
    assert columns.columnar and not objects.columnar
    assert isinstance(columns.traces, LazyTraces)
    assert len(columns) == len(objects) == 10 and columns.event_count == objects.event_count == 210
    assert columns.default_classifier() == objects.default_classifier()        # from the lifecycle codes
    assert columns.sequences() == objects.sequences()
    assert columns.simple_log() == objects.simple_log()
    assert [t.attributes for t in columns] == [t.attributes for t in objects]
    assert [[e.attributes for e in t] for t in columns] == [[e.attributes for e in t] for t in objects]
    # The same file again (attribute order inside an event may differ: XES gives it no meaning).
    again = read_xes_string(xes_string(columns))
    assert [[e.attributes for e in t] for t in again] == [[e.attributes for e in t] for t in objects]
    a, b = summarise(objects), summarise(columns)
    assert (a.case_count, a.event_count, a.variant_count, a.start, a.end, a.case_durations) == \
        (b.case_count, b.event_count, b.variant_count, b.start, b.end, b.case_durations)
    assert discover_dfg(objects).edges == discover_dfg(columns).edges
    assert discover_dfg(objects).durations == discover_dfg(columns).durations


def test_lazy_traces_build_on_demand_and_edits_materialise():
    log = read_xes(DATA / "plane_wilma_10.xes", columnar=True)
    traces = log.traces
    assert traces._built.count(None) == 10
    first = log.traces[0]
    assert first is log.traces[0] and traces._built.count(None) == 9          # built once, kept
    assert len(log.traces[2:4]) == 2 and log.traces[-1].case_id == log.traces[9].case_id
    log.traces.append(Trace({KEY_NAME: "new"}))
    assert not log.columnar and len(log) == 11 and log.event_count == 210
    del log.traces[-1]
    assert len(log) == 10 and log.sequences() == read_xes(DATA / "plane_wilma_10.xes").sequences()


def test_column_store_keeps_other_attributes_and_missing_values():
    store = ColumnStore()
    store.add("a", None, "complete", "Ann", [("amount", 1.5)])
    store.add("b", None, None, None, [])
    store.end_case({KEY_NAME: "c1"})
    store.add("a", None, "start", None, [("note", "x")])
    store.end_case({KEY_NAME: "c2"})
    log = EventLog.from_columns(store)
    assert [e.attributes for e in log[0]] == [
        {"concept:name": "a", "lifecycle:transition": "complete", "org:resource": "Ann", "amount": 1.5},
        {"concept:name": "b"}]
    assert log[1][0].attributes == {"concept:name": "a", "lifecycle:transition": "start", "note": "x"}
    assert store.extra["amount"] == [1.5, None, None] and store.extra["note"] == [None, None, "x"]
    assert log.sequences(BY_NAME) == [("a", "b"), ("a",)]
    assert log.has_lifecycle_pairs() and log.sequences() == [("a", "b"), ()]      # complete events only
    assert len(log) == 2 and log.event_count == 3
