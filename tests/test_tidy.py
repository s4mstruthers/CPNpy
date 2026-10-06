"""Making a page neat: snapping it to the grid."""

from __future__ import annotations

from pathlib import Path

from cpnpy.gui.tidy import _clean_bends, snap_page
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
