"""Object-centric event logs: reading, flattening, the object-centric map, the boxes."""

from __future__ import annotations

import json
from pathlib import Path

from openprocess.flow import Runner, Workflow, standard_library
from openprocess.flow.boxes.discover import inductive_miner, object_centric_map
from openprocess.flow.boxes.input import flatten_ocel, open_ocel
from openprocess.mining.ocel import flatten, object_centric_dfg, read_ocel

DATA = Path(__file__).parent / "data"


def test_an_ocel2_file_is_read_with_its_objects_by_type():
    log = read_ocel(DATA / "orders.jsonocel")
    assert log.name == "orders" and len(log) == 9 and log.object_types == ["order", "item", "package"]
    assert log.counts_by_type() == {"order": 2, "item": 3, "package": 1}
    pack = next(e for e in log.events if e.activity == "pack items")
    assert pack.objects == {"item": ["i1", "i2", "i3"], "package": ["p1"]}
    assert [e.id for e in log.events] == [f"e{i}" for i in range(1, 10)]           # in time order
    assert log.objects["o1"].attributes["price"] == 120.0


def test_a_json_ocel_1_file_is_read_too(tmp_path):
    data = {"ocel:global-log": {"ocel:object-types": ["order"]},
            "ocel:objects": {"o1": {"ocel:type": "order", "ocel:ovmap": {}}},
            "ocel:events": {"e1": {"ocel:activity": "a", "ocel:timestamp": "2024-01-01T10:00:00", "ocel:omap": ["o1"], "ocel:vmap": {}},
                            "e2": {"ocel:activity": "b", "ocel:timestamp": "2024-01-01T11:00:00", "ocel:omap": ["o1"], "ocel:vmap": {}}}}
    path = tmp_path / "old.jsonocel"
    path.write_text(json.dumps(data), encoding="utf-8")
    log = read_ocel(path)
    assert [e.activity for e in log.events] == ["a", "b"] and log.object_types == ["order"]


def test_flattening_copies_shared_events_into_each_case():
    log = read_ocel(DATA / "orders.jsonocel")
    items = flatten(log, "item")
    assert len(items) == 3 and items.name == "orders · item"
    assert [e.activity for e in items[0].events] == ["place order", "pick item", "pack items"]
    assert items.event_count == 9                                 # pack items: once per item
    orders = flatten(log)                                         # the type with most objects: item
    assert orders.name.endswith("item")
    by_type = flatten(log, "order")
    assert sorted(t.case_id for t in by_type) == ["o1", "o2"]
    assert by_type[0].events[0].attributes["ocel:item"] == "i1, i2"      # the other objects, kept


def test_the_object_centric_map_follows_every_object():
    graph = object_centric_dfg(read_ocel(DATA / "orders.jsonocel"))
    assert graph.object_types == ["order", "item", "package"]
    assert graph.edges["order"] == {("place order", "pay order"): 2}
    assert graph.edges["item"][("pick item", "pack items")] == 3 and graph.edges["item"][("place order", "pick item")] == 3
    assert graph.edges["package"] == {("pack items", "ship package"): 1}
    assert graph.starts["item"] == {"place order": 3} and graph.ends["order"] == {"pay order": 2}
    assert graph.objects_at[("pack items", "item")] == 3
    assert "3 object types" in graph.summary()


def test_the_boxes_open_flatten_and_map(tmp_path):
    wf = Workflow("OCEL")
    ocel = wf.add(open_ocel, {"file": str(DATA / "orders.jsonocel")})
    flat = wf.add(flatten_ocel, {"object_type": "order"})
    miner = wf.add(inductive_miner)
    graph = wf.add(object_centric_map)
    wf.connect(ocel, flat)
    wf.connect(flat, miner)
    wf.connect(ocel, graph)
    run = Runner(standard_library(), folder=tmp_path).run(wf)
    assert run.ok, [r.error for r in run.failed()]
    assert len(run.value(flat)) == 2 and run.value(miner).transitions
    assert run.value(graph).edges["order"] == {("place order", "pay order"): 2}
    notes = run.result(ocel).explanation.notes
    assert any("Object types: order (2), item (3), package (1)" in n for n in notes)
