"""How arcs are edited on the canvas: the rules of CPN IDE.

CPN IDE draws its nets with *diagram-js* (the library behind the bpmn.io
editors), so an arc there behaves like a diagram-js connection.  This module
restates those rules as small functions on plain ``(x, y)`` tuples; the
canvas (:mod:`cpnpy.gui.canvas`) calls them while you drag.

An arc is a list of *waypoints*: the point where it leaves its first node,
its bendpoints, and the point where it meets its second node.  Here the list
always runs from the transition end to the place end, the order ``.cpn``
files store bendpoints in.

Pressing on an arc and dragging does one of four things, decided by where
you pressed (:func:`hit_test`):

* **on a bend** (within 10 units): move that bend;
* **on one of the two ends**: drag that end to another node (reconnect);
* **near the middle of a horizontal or vertical segment**: slide the whole
  segment sideways (:func:`move_segment`);
* **anywhere else on the line**: add a bend there and drag it.

While a bend is dragged it snaps level with, or in line with, its
neighbours (:func:`snap_bend`).  When it is dropped, bends that ended up in a
straight line with their neighbours disappear (:func:`without_redundant`) --
that is how a bend is removed: drag it back into line.

Moving a node leaves the bends where they are, except the one next to the
node: if it was level with (or in line with) the arc's end, it stays so
(:func:`repair_after_move`).  Moving both ends of an arc together moves the
whole arc.
"""

from __future__ import annotations

import math

Point = tuple[float, float]
Rect = tuple[float, float, float, float]          # left, top, width, height

#: How close (in canvas units) a press must be to a bend to grab it, and to
#: a segment's middle to slide the segment.
HIT_TOLERANCE = 10.0
#: A dragged bend snaps to its neighbours' x or y within this distance.
SNAP_TOLERANCE = 10.0
#: A moved node's centre snaps to other nodes' centres within this distance.
NODE_SNAP_TOLERANCE = 7.0
#: Two points this close in x (or y) count as lined up vertically (or
#: horizontally).
ALIGNED_THRESHOLD = 2.0
#: A bend this close to a straight line through its neighbours is dropped.
REDUNDANT_ACCURACY = 5.0
#: After a node move, bends within this distance of either node are dropped.
OVERLAP_PADDING = 20.0


# ---------------------------------------------------------------------------
# Small geometry helpers
# ---------------------------------------------------------------------------
def distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def aligned(a: Point, b: Point) -> str | None:
    """``"vertical"`` if ``a`` and ``b`` share x, ``"horizontal"`` if they
    share y (within :data:`ALIGNED_THRESHOLD`), else ``None``."""
    if abs(a[0] - b[0]) <= ALIGNED_THRESHOLD:
        return "vertical"
    if abs(a[1] - b[1]) <= ALIGNED_THRESHOLD:
        return "horizontal"
    return None


def on_line(p: Point, q: Point, r: Point, accuracy: float = REDUNDANT_ACCURACY) -> bool:
    """Is ``r`` within ``accuracy`` of the straight line through ``p`` and ``q``?"""
    length = distance(p, q)
    if length == 0:
        return distance(p, r) <= accuracy
    cross = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return abs(cross / length) <= accuracy


def inside(p: Point, rect: Rect, padding: float = 0.0) -> bool:
    left, top, width, height = rect
    return (left - padding < p[0] < left + width + padding
            and top - padding < p[1] < top + height + padding)


def closest_on_segment(p: Point, a: Point, b: Point) -> Point:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return a
    share = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    return a[0] + dx * share, a[1] + dy * share


# ---------------------------------------------------------------------------
# Where did the press land?
# ---------------------------------------------------------------------------
def hit_test(waypoints: list[Point], p: Point,
             tolerance: float = HIT_TOLERANCE) -> tuple[str, int, Point] | None:
    """Classify a press at ``p`` on an arc with the given waypoints.

    Returns ``(kind, index, point)`` or ``None`` when ``p`` is not on the arc:

    * ``("bend", i, point)`` -- on waypoint ``i``.  ``i == 0`` and
      ``i == len(waypoints) - 1`` are the two ends (reconnect);
    * ``("segment", i, point)`` -- near the middle of the horizontal or
      vertical segment from waypoint ``i - 1`` to waypoint ``i``;
    * ``("insert", i, point)`` -- elsewhere on that segment: a new bend goes
      in at index ``i``; ``point`` is the spot on the line.
    """
    for index, waypoint in enumerate(waypoints):
        if distance(waypoint, p) <= tolerance:
            return "bend", index, waypoint
    best: tuple[float, int, Point] | None = None
    for index in range(1, len(waypoints)):
        a, b = waypoints[index - 1], waypoints[index]
        foot = closest_on_segment(p, a, b)
        gap = distance(foot, p)
        if gap <= tolerance and (best is None or gap < best[0]):
            best = (gap, index, foot)
    if best is None:
        return None
    _, index, foot = best
    a, b = waypoints[index - 1], waypoints[index]
    middle = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    if aligned(a, b) and abs(foot[0] - middle[0]) <= tolerance \
            and abs(foot[1] - middle[1]) <= tolerance:
        return "segment", index, middle
    return "insert", index, foot


# ---------------------------------------------------------------------------
# Dragging a bend
# ---------------------------------------------------------------------------
def snap_value(value: float, candidates: list[float],
               tolerance: float = SNAP_TOLERANCE) -> float:
    for candidate in candidates:
        if abs(candidate - value) <= tolerance:
            return candidate
    return value


def snap_bend(p: Point, neighbours: list[Point]) -> Point:
    """Snap a dragged bend level with / in line with its neighbours.

    The neighbours are the waypoints on either side; for an end of the arc
    pass the node's centre, as diagram-js does."""
    xs = [n[0] for n in neighbours]
    ys = [n[1] for n in neighbours]
    return snap_value(p[0], xs), snap_value(p[1], ys)


def without_redundant(waypoints: list[Point],
                      accuracy: float = REDUNDANT_ACCURACY) -> list[Point]:
    """Drop bends that lie on the straight line through their neighbours, or
    on top of the next point.  The two ends always stay."""
    points = list(waypoints)
    index = 1
    while index < len(points) - 1:
        point = points[index]
        if distance(point, points[index + 1]) == 0 or \
                on_line(points[index - 1], points[index + 1], point, accuracy):
            del points[index]
        else:
            index += 1
    return points


# ---------------------------------------------------------------------------
# Sliding a segment
# ---------------------------------------------------------------------------
def move_segment(waypoints: list[Point], index: int, delta: float,
                 first_node: tuple[Point, Rect], last_node: tuple[Point, Rect],
                 snap_to: bool = True) -> list[Point]:
    """Slide the segment from waypoint ``index - 1`` to ``index`` sideways.

    A horizontal segment moves up or down by ``delta``, a vertical one left
    or right.  ``first_node`` / ``last_node`` are ``(centre, rect)`` of the
    nodes at the two ends.  Where the segment starts or ends at a node:

    * if its moved end still lies inside the node, the arc simply meets the
      node at the new height;
    * if it has left the node, a new bend is added, so the arc leaves the
      node straight and then turns -- an S-bend.

    A bend next to a node that is moved *into* that node is dropped.
    Returns the new waypoint list (ends included, not yet tidied).
    """
    start, end = waypoints[index - 1], waypoints[index]
    axis = 1 if aligned(start, end) == "horizontal" else 0    # which coordinate moves
    last = len(waypoints) - 1
    # An end of the arc counts from the node's centre (its "docking" point).
    if index - 1 == 0:
        start = _with(start, 1 - axis, first_node[0][1 - axis])
    if index == last:
        end = _with(end, 1 - axis, last_node[0][1 - axis])
    target = start[axis] + delta
    if snap_to:
        references = [start[axis], end[axis]]
        if index - 2 >= 0:
            references.append(waypoints[index - 2][axis])
        if index + 1 <= last:
            references.append(waypoints[index + 1][axis])
        if index - 1 <= 1:
            references.append(first_node[0][axis])
        if index >= last - 1:
            references.append(last_node[0][axis])
        target = snap_value(target, [r for r in references if r != start[axis]])
    new_start, new_end = _with(start, axis, target), _with(end, axis, target)

    points = list(waypoints)
    points[index - 1], points[index] = new_start, new_end
    # The node end at the start of the segment ...
    if index - 1 == 0:
        if not inside(new_start, first_node[1]):
            points.insert(0, start)               # the arc leaves the node, then turns
            index += 1
    elif index - 1 == 1 and inside(new_start, first_node[1]):
        del points[0]                             # the first bend went into the node
        index -= 1
    # ... and at its end.
    last = len(points) - 1
    if index == last:
        if not inside(new_end, last_node[1]):
            points.append(end)
    elif index == last - 1 and inside(new_end, last_node[1]):
        del points[-1]
    return points


def _with(p: Point, axis: int, value: float) -> Point:
    return (value, p[1]) if axis == 0 else (p[0], value)


# ---------------------------------------------------------------------------
# After a node moved
# ---------------------------------------------------------------------------
def repair_after_move(points: list[Point], new_end: Point,
                      moved: Rect, other: Rect) -> list[Point]:
    """The waypoints of an arc after the node at ``points[0]`` moved.

    ``points`` runs from the moved node's end to the other end; ``new_end``
    is the old end point moved with the node; ``moved`` and ``other`` are
    the two nodes' rectangles at their new places.  Only the first bend
    changes: kept level (or in line) with the end if it was.  Bends that the
    move put on top of either node are dropped, with everything before them.
    """
    for _ in range(len(points)):                  # at most one pass per bend
        if len(points) < 3:
            return [new_end, points[-1]]
        old_end = points[0]
        repaired = list(points)
        repaired[0] = new_end
        bend = repaired[1]
        alignment = aligned(old_end, bend)
        if alignment == "vertical":
            repaired[1] = (new_end[0], bend[1])
        elif alignment == "horizontal":
            repaired[1] = (bend[0], new_end[1])
        for i in range(len(repaired) - 2, 0, -1):
            if inside(repaired[i], moved, OVERLAP_PADDING) or \
                    inside(repaired[i], other, OVERLAP_PADDING):
                points = repaired[i:]
                break
        else:
            return repaired
    return [new_end, points[-1]]


def snap_node(centre: Point, targets: list[Point],
              tolerance: float = NODE_SNAP_TOLERANCE) -> tuple[float | None, float | None]:
    """The x and y a dragged node's centre snaps to (``None`` = no snap):
    other nodes' centres and the corners of right-angled arcs."""
    best_x = best_y = None
    gap_x = gap_y = tolerance + 1e-9
    for tx, ty in targets:
        if abs(tx - centre[0]) < gap_x:
            best_x, gap_x = tx, abs(tx - centre[0])
        if abs(ty - centre[1]) < gap_y:
            best_y, gap_y = ty, abs(ty - centre[1])
    return best_x, best_y


def corner_bends(waypoints: list[Point]) -> list[Point]:
    """Bends that start or end a horizontal or vertical segment -- the ones
    nodes snap to, as in CPN IDE."""
    corners = []
    for i in range(1, len(waypoints) - 1):
        point = waypoints[i]
        before, after = waypoints[i - 1], waypoints[i + 1]
        if point[0] in (before[0], after[0]) or point[1] in (before[1], after[1]):
            corners.append(point)
    return corners
