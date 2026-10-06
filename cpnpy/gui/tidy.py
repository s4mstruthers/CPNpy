"""Making a page of a net neat: snap it to the grid, or arrange it afresh.

Both work on the model (a :class:`~cpnpy.model.net.Page`), in model
coordinates -- the canvas's with ``y`` flipped (see :func:`.items.to_scene`)
-- so the editor only has to take an undo snapshot first and redraw after.

* :func:`snap_page` puts every node's centre and every arc bend on the
  canvas's dot grid, and drops bends that no longer turn a corner.
* :func:`arrange_page` lays the page out from scratch, left to right in
  layers (the layout used for discovered models), on the grid, with straight
  arcs except where an arc must go round other nodes.
"""

from __future__ import annotations

from ..mining.layout import layered_layout
from ..model.net import Page


def _round(value: float, step: float) -> float:
    return round(value / step) * step


def _straight(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> bool:
    """Is ``b`` on the straight line from ``a`` to ``c`` (so not a real corner)?"""
    cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    length = max(abs(c[0] - a[0]) + abs(c[1] - a[1]), 1e-9)
    return abs(cross) / length < 1.0


def _clean_bends(start: tuple[float, float], bends: list[tuple[float, float]],
                 end: tuple[float, float]) -> list[tuple[float, float]]:
    """Without repeated points, points on a node's centre, and bends that do
    not turn (all of which snapping can produce)."""
    points = [start]
    for bend in bends:
        if bend != points[-1] and bend != end:
            points.append(bend)
    points.append(end)
    changed = True
    while changed and len(points) > 2:
        changed = False
        for index in range(1, len(points) - 1):
            if _straight(points[index - 1], points[index], points[index + 1]):
                del points[index]
                changed = True
                break
    return points[1:-1]


def _centres(page: Page) -> dict[str, tuple[float, float]]:
    return {node.id: (node.graphics.x, node.graphics.y)
            for node in [*page.places, *page.transitions]}


def _midpoint(centres, arc) -> tuple[float, float] | None:
    if arc.transition_id not in centres or arc.place_id not in centres:
        return None
    (ax, ay), (bx, by) = centres[arc.transition_id], centres[arc.place_id]
    return (ax + bx) / 2, (ay + by) / 2


def snap_page(page: Page, step: float) -> int:
    """Put every node and arc bend of ``page`` on the grid.  Returns how many
    nodes moved.  An inscription the modeller placed keeps its place beside
    its arc (it is stored as an absolute position, so it moves along)."""
    before = _centres(page)
    middles = {id(arc): _midpoint(before, arc) for arc in page.arcs}
    moved = 0
    for node in [*page.places, *page.transitions]:
        x, y = _round(node.graphics.x, step), _round(node.graphics.y, step)
        if (x, y) != (node.graphics.x, node.graphics.y):
            moved += 1
        node.graphics.x, node.graphics.y = x, y
    centres = _centres(page)
    for arc in page.arcs:
        if arc.transition_id not in centres or arc.place_id not in centres:
            continue
        bends = [(_round(x, step), _round(y, step)) for x, y in arc.bendpoints]
        # Bends run from the transition to the place (see cpnpy.model.net.Arc).
        arc.bendpoints = _clean_bends(centres[arc.transition_id], bends,
                                      centres[arc.place_id])
        old, new = middles.get(id(arc)), _midpoint(centres, arc)
        label = arc.graphics.label_offsets.get("annot")
        if label is not None and old is not None and new is not None:
            arc.graphics.label_offsets["annot"] = (label[0] + new[0] - old[0],
                                                   label[1] + new[1] - old[1])
    return moved


def arrange_page(page: Page, step: float, layer_gap: float = 84.0,
                 node_gap: float = 56.0) -> None:
    """Lay ``page`` out afresh, left to right, on the grid."""
    nodes = [*page.places, *page.transitions]
    if not nodes:
        return
    sizes = {node.id: (max(node.graphics.width, 1.0), max(node.graphics.height, 1.0))
             for node in nodes}
    edges: list[tuple[str, str]] = []
    first_edge: dict[int, tuple[int, bool]] = {}      # arc index -> (edge, place first?)
    # A place a transition takes from and puts back into (a resource: seats,
    # a lock, a counter) should sit beside that transition, not stretch the
    # drawing into one long chain: its "put back" edge does not decide layers.
    takes = {(a.place_id, a.transition_id) for a in page.arcs if a.is_input}
    soft: set[int] = set()
    for index, arc in enumerate(page.arcs):
        if arc.place_id not in sizes or arc.transition_id not in sizes:
            continue
        if arc.is_input:
            first_edge.setdefault(index, (len(edges), True))
            edges.append((arc.place_id, arc.transition_id))
        if arc.is_output:
            first_edge.setdefault(index, (len(edges), False))
            if (arc.place_id, arc.transition_id) in takes:
                soft.add(len(edges))
            edges.append((arc.transition_id, arc.place_id))
    layout = layered_layout(sizes, edges, layer_gap=layer_gap, node_gap=node_gap,
                            soft_edges=soft)
    # The layout's y grows downwards, as on the canvas: model y is its negation.
    for node in nodes:
        x, y = layout.positions[node.id]
        node.graphics.x, node.graphics.y = _round(x, step), _round(-y, step)
    centres = _centres(page)
    for index, arc in enumerate(page.arcs):
        if index not in first_edge:
            continue
        edge, place_first = first_edge[index]
        route = [(_round(x, step), _round(-y, step)) for x, y in layout.routes.get(edge, [])]
        inner = route[1:-1] if len(route) > 2 else []
        if place_first:                                  # stored transition -> place
            inner.reverse()
        arc.bendpoints = _clean_bends(centres[arc.transition_id], inner,
                                      centres[arc.place_id])
        # Inscriptions placed for the old layout would be left behind (their
        # position is absolute): let the canvas put each one on its arc.
        arc.graphics.label_offsets.pop("annot", None)
