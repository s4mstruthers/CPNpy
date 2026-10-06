"""Making a page of a net neat: snap it to the grid, keeping its layout.

:func:`snap_page` puts every node's centre and every arc bend on the canvas's
dot grid, and drops bends that no longer turn a corner.  It works on the model
(a :class:`~cpnpy.model.net.Page`), in model coordinates -- the canvas's with
``y`` flipped (see :func:`.items.to_scene`) -- so the editor only has to take
an undo snapshot first and redraw after.

(An automatic left-to-right layout was tried too, and taken out again: on a
model drawn by hand it threw away the modeller's layout for a worse one.)
"""

from __future__ import annotations

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
