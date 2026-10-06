"""Making a page neat: snapping to the grid and arranging afresh."""

from __future__ import annotations

from pathlib import Path

from cpnpy.gui.tidy import _clean_bends, arrange_page, snap_page
from cpnpy.io.cpn_reader import read_cpn
from cpnpy.mining.pnml import read_pnml
from cpnpy.model.plain import from_petri_net

ROOT = Path(__file__).resolve().parents[1]
STEP = 28


def _on_grid(x: float, y: float) -> bool:
    return x % STEP == 0 and y % STEP == 0


def _nodes(page):
    return [*page.places, *page.transitions]


def test_snapping_puts_nodes_and_bends_on_the_grid():
    net = from_petri_net(read_pnml(str(ROOT / "examples" / "petri" / "order_handling_sound.pnml")))
    page = net.pages[0]
    page.places[0].graphics.x += 9
    page.transitions[0].graphics.y -= 13
    arc = page.arcs[0]
    arc.bendpoints = [(41.0, 3.0)]
    moved = snap_page(page, STEP)
    assert moved >= 2
    assert all(_on_grid(n.graphics.x, n.graphics.y) for n in _nodes(page))
    assert all(_on_grid(x, y) for a in page.arcs for x, y in a.bendpoints)


def test_bends_that_no_longer_turn_are_dropped():
    # Repeated points, a point on the end node, and one on the straight line go.
    assert _clean_bends((0, 0), [(28, 0), (28, 0), (56, 0), (84, 0)], (84, 0)) == []
    assert _clean_bends((0, 0), [(56, 0), (56, 56)], (112, 56)) == [(56, 0), (56, 56)]


def test_arranging_lays_out_left_to_right_on_the_grid():
    for net in (from_petri_net(read_pnml(str(ROOT / "examples" / "petri" /
                                             "order_handling_unsound.pnml"))),
                read_cpn(str(ROOT / "tests" / "data" / "plane_boarding.cpn"))):
        page = net.pages[0]
        arrange_page(page, STEP)
        positions = [(n.graphics.x, n.graphics.y) for n in _nodes(page)]
        assert all(_on_grid(x, y) for x, y in positions)
        assert len(set(positions)) == len(positions)                  # no two on one spot
        assert all(_on_grid(x, y) for a in page.arcs for x, y in a.bendpoints)
    # The flow goes left to right: the start place is left of the end place.
    net = from_petri_net(read_pnml(str(ROOT / "examples" / "petri" / "order_handling_sound.pnml")))
    page = net.pages[0]
    arrange_page(page, STEP)
    x = {p.name: p.graphics.x for p in page.places}
    assert x["start"] < x["c1"] < x["c3"] < x["end"]
