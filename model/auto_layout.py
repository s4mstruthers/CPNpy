"""Automatic layout of a CPN page: places and transitions in tidy layers.

CPN Tools models are laid out by hand, and a model that grew over time (or
was drawn quickly) can be hard to read.  :func:`auto_layout` re-arranges one
page with the same layered method the process-mining views use
(:func:`cpnpy.mining.layout.layered_layout`, Sugiyama's method, as in
Graphviz ``dot``):

* the net's flow runs left to right (or top to bottom), following the arcs;
* nodes are ordered within each layer to minimise crossing arcs;
* an arc spanning several layers is routed through bendpoints around the
  nodes in between;
* each node gets room for its inscriptions (initial marking, colour set,
  guard, time delay) and each layer gap room for arc inscriptions.

Hand-placed inscription positions are dropped, so the canvas places every
inscription next to its node or arc again.  Only coordinates change -- never
the behaviour -- and the GUI makes the whole operation undoable.
"""

from __future__ import annotations

from ..mining.layout import layered_layout
from .net import Page

#: Rough width of one character of an inscription (10 pt monospace), used to
#: leave room for text without needing a font engine.
CHAR_WIDTH = 6.4
#: Inscription positions the layout resets (the token bubble keeps its own).
LABEL_KEYS = ("type", "initmark", "cond", "time", "annot", "code", "priority")


def _text_width(text: str, limit: float = 132.0) -> float:
    return min(len(text.strip()) * CHAR_WIDTH, limit)


def auto_layout(page: Page, direction: str = "LR", spacing: float = 1.0) -> None:
    """Re-arrange ``page`` in place.

    ``direction`` is ``"LR"`` (left to right) or ``"TB"`` (top to bottom).
    ``spacing`` scales every gap (1.0 = comfortable for typical inscriptions).
    """
    horizontal = direction.upper() != "TB"
    places = {p.id: p for p in page.places}
    transitions = {t.id: t for t in page.transitions}
    if not places and not transitions:
        return

    # -- node boxes, including room for their inscriptions --------------------
    boxes: dict[str, tuple[float, float]] = {}
    for place in places.values():
        w, h = place.graphics.width or 76.0, place.graphics.height or 48.0
        label = max(_text_width(place.initial_marking_text), _text_width(place.colour_set_name))
        width = max(w, label) + 24
        height = h + 44                      # initial marking below, bubble above
        boxes[place.id] = (width, height)
    for transition in transitions.values():
        w, h = transition.graphics.width or 82.0, transition.graphics.height or 48.0
        label = _text_width(transition.guard_text) + _text_width(transition.time_text)
        width = max(w, label) + 24
        height = h + 36                      # guard and time delay above
        boxes[transition.id] = (width, height)

    # Where things are now tells which way the modeller reads the net: it
    # orients arcs that go both ways and decides which arcs of a cycle count
    # as the way "back".  Upstream = earlier in reading order: further left
    # and higher up (model y points up), whichever direction is asked for.
    def upstream(node_id: str) -> float:
        element = places.get(node_id) or transitions.get(node_id)
        return element.graphics.x - element.graphics.y

    # -- edges: one per connected pair, in the direction the tokens flow -----
    pairs: dict[frozenset, tuple[str, str]] = {}
    arcs_of_pair: dict[frozenset, list] = {}
    flows: dict[frozenset, set[str]] = {}     # "in" / "out" arcs seen for a pair
    for arc in page.arcs:
        if arc.place_id not in places or arc.transition_id not in transitions:
            continue
        if arc.is_input and not arc.is_output:
            edge = (arc.place_id, arc.transition_id)
        elif arc.is_output and not arc.is_input:
            edge = (arc.transition_id, arc.place_id)
        else:                                # double-headed: read as an input
            edge = (arc.place_id, arc.transition_id)
        key = frozenset(edge)
        pairs.setdefault(key, edge)          # the first arc decides the direction
        arcs_of_pair.setdefault(key, []).append(arc)
        kinds = flows.setdefault(key, set())
        if arc.is_input:
            kinds.add("in")
        if arc.is_output:
            kinds.add("out")
    # Arcs both ways between a place and a transition: tokens are taken and
    # put back, so the arcs alone do not say which comes first.  Follow the
    # current drawing.
    for key, kinds in flows.items():
        if kinds == {"in", "out"}:
            a, b = tuple(key)
            pairs[key] = (a, b) if upstream(a) <= upstream(b) else (b, a)
    edge_list = list(pairs.values())
    # A node whose only connection is a take-and-put-back pair -- a counter
    # place such as a next-id, or a transition that just updates one place
    # (moving up the aisle) -- is a side matter rather than a step in the
    # flow: it sits beside its partner instead of getting a layer of its own.
    partners: dict[str, set[str]] = {}
    for key in pairs:
        for node in key:
            partners.setdefault(node, set()).update(key - {node})
    soft = {index for index, key in enumerate(pairs)
            if flows[key] == {"in", "out"} and
            any(len(partners[node]) == 1 for node in key)}
    widest_label = max((_text_width(a.expression_text) for a in page.arcs), default=40.0)

    # The layered layout runs left to right; for top-to-bottom swap the axes.
    # Upstream nodes first: the layout starts from them and breaks cycles at
    # the arcs that run against the reading direction.
    ordered = sorted(boxes, key=upstream)
    sizes = {k: boxes[k] if horizontal else boxes[k][::-1] for k in ordered}
    layer_gap = (max(70.0, widest_label * 0.9) if horizontal else 70.0) * spacing
    node_gap = 48.0 * spacing
    result = layered_layout(sizes, edge_list, layer_gap=layer_gap, node_gap=node_gap,
                            soft_edges=soft)

    def to_model(point: tuple[float, float]) -> tuple[float, float]:
        """Layout coordinates (y down, maybe transposed) -> model (y up)."""
        x, y = point if horizontal else (point[1], point[0])
        return x - result_width / 2, -(y - result_height / 2)

    result_width = result.width if horizontal else result.height
    result_height = result.height if horizontal else result.width

    for node_id, point in result.positions.items():
        element = places.get(node_id) or transitions.get(node_id)
        element.graphics.x, element.graphics.y = to_model(point)
        for key in LABEL_KEYS:
            element.graphics.label_offsets.pop(key, None)

    # -- arcs: bendpoints through the dummy nodes of long edges ---------------
    index_of = {edge: i for i, edge in enumerate(edge_list)}
    for key, arcs in arcs_of_pair.items():
        route = result.routes.get(index_of[pairs[key]], [])
        inner = [to_model(p) for p in route[1:-1]]
        if pairs[key][0] in places:             # stored transition -> place
            inner.reverse()
        for number, arc in enumerate(arcs):
            arc.graphics.label_offsets.pop("annot", None)
            arc.graphics.smooth = False
            if not inner:
                arc.bendpoints = []        # neighbours: a straight (or bowed) arc
                continue
            # Several arcs along the same long route: spread them sideways.
            offset = (number - (len(arcs) - 1) / 2) * 14.0
            if horizontal:
                arc.bendpoints = [(x, y + offset) for x, y in inner]
            else:
                arc.bendpoints = [(x + offset, y) for x, y in inner]


# ---------------------------------------------------------------------------
# Graphviz: the better layout, when the `dot` program is installed
# ---------------------------------------------------------------------------
# Graphviz's ``dot`` (the layout ProM uses) routes arcs as smooth curves
# around the nodes and places every inscription where it collides with
# nothing.  It is a separate program: ``conda install -c conda-forge
# graphviz`` (in environment.yml) or ``brew install graphviz``.  Without it
# the built-in layered layout above is used.

def find_dot() -> str | None:
    """Path of Graphviz's ``dot``, or None.

    Also looks next to the running Python and in Homebrew's folders, because
    an app started from Finder does not get the terminal's PATH.
    """
    import os
    import shutil
    import sys
    found = shutil.which("dot")
    if found:
        return found
    for folder in (os.path.join(sys.prefix, "bin"), "/opt/homebrew/bin", "/usr/local/bin"):
        candidate = os.path.join(folder, "dot")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _short(text: str, limit: int = 40) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _bezier_points(spline: str) -> list[tuple[float, float]]:
    """Sample a Graphviz edge spline (``e,x,y  p0 p1 p2 p3 ...``) into points."""
    points: list[tuple[float, float]] = []
    for token in spline.split():
        if token.startswith(("e,", "s,")):
            continue                           # arrow end points: not part of the curve
        x, y = token.split(",")[:2]
        points.append((float(x), float(y)))
    if len(points) < 4:
        return points
    samples = [points[0]]
    for start in range(0, len(points) - 3, 3):
        p0, p1, p2, p3 = points[start:start + 4]
        for step in range(1, 9):
            t = step / 8
            u = 1 - t
            samples.append((
                u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
    return samples


def _simplify(points: list[tuple[float, float]], tolerance: float = 2.5) -> list[tuple[float, float]]:
    """Ramer-Douglas-Peucker: drop points that barely change the shape."""
    if len(points) < 3:
        return points
    (x0, y0), (x1, y1) = points[0], points[-1]
    dx, dy = x1 - x0, y1 - y0
    length = (dx * dx + dy * dy) ** 0.5 or 1.0
    worst, index = 0.0, 0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        distance = abs(dy * px - dx * py + x1 * y0 - y1 * x0) / length
        if distance > worst:
            worst, index = distance, i
    if worst <= tolerance:
        return [points[0], points[-1]]
    left = _simplify(points[:index + 1], tolerance)
    return left[:-1] + _simplify(points[index:], tolerance)


def _near_node(point: tuple[float, float], places: dict, transitions: dict) -> bool:
    """Is ``point`` inside (or right next to) one of the nodes?"""
    x, y = point
    for element in (*places.values(), *transitions.values()):
        g = element.graphics
        if abs(x - g.x) < g.width / 2 + 6 and abs(y - g.y) < g.height / 2 + 6:
            return True
    return False


def graphviz_layout(page: Page, direction: str = "TB", spacing: float = 1.0,
                    dot: str | None = None) -> None:
    """Lay ``page`` out with Graphviz ``dot`` (raises if it cannot run)."""
    import json
    import subprocess

    dot = dot or find_dot()
    if dot is None:
        raise FileNotFoundError("Graphviz (dot) is not installed")
    places = {p.id: p for p in page.places}
    transitions = {t.id: t for t in page.transitions}
    if not places and not transitions:
        return

    lines = [
        "digraph net {",
        f"rankdir={'LR' if direction.upper() == 'LR' else 'TB'};",
        f"nodesep={0.45 * spacing:.2f}; ranksep={0.55 * spacing:.2f};",
        "splines=true; forcelabels=true; outputorder=edgesfirst;",
        'node [fontname="Courier", fontsize=12.5, fixedsize=true];',
        # Labels are sized a little larger than the canvas draws them, so
        # the room Graphviz reserves is enough whatever the font.
        'edge [fontname="Courier", fontsize=12.5];',
    ]
    # The inscriptions of a node go at CPN Tools' usual spots around it
    # (initial marking above right, colour set below right; guard above
    # left, time delay above right; the token count on the right edge).
    # Graphviz is told each node is as big as the node *plus* that ring of
    # text (a transparent margin), so it keeps other nodes and arcs out.
    order: list[str] = []
    ring: dict[str, tuple[float, float]] = {}
    for place in places.values():
        width, height = place.graphics.width or 76.0, place.graphics.height or 48.0
        text = max(_text_width(place.initial_marking_text, 170),
                   _text_width(place.colour_set_name), 30.0)
        box = (width + 2 * text, height + 2 * 16)
        ring[place.id] = box
        lines.append(f"{_quote(place.id)} [shape=box, width={box[0] / 72:.3f}, "
                     f"height={box[1] / 72:.3f}, label=\"\"];")
        order.append(place.id)
    for transition in transitions.values():
        width, height = transition.graphics.width or 82.0, transition.graphics.height or 48.0
        side = max(_text_width(transition.guard_text, 170),
                   _text_width(transition.time_text, 170), 0.0)
        box = (width + 2 * side, height + 2 * 16)
        ring[transition.id] = box
        lines.append(f"{_quote(transition.id)} [shape=box, width={box[0] / 72:.3f}, "
                     f"height={box[1] / 72:.3f}, label=\"\"];")
        order.append(transition.id)
    arcs = []
    for arc in page.arcs:
        if arc.place_id not in places or arc.transition_id not in transitions:
            continue
        # Draw each arc in the direction tokens move (both-ways arcs as inputs).
        forward = arc.is_input
        source, target = (arc.place_id, arc.transition_id) if forward else \
            (arc.transition_id, arc.place_id)
        label = _short(arc.expression_text, 48)
        lines.append(f"{_quote(source)} -> {_quote(target)} [label={_quote(label)}];")
        arcs.append(arc)
    lines.append("}")

    completed = subprocess.run([dot, "-Tjson"], input="\n".join(lines), capture_output=True,
                               text=True, timeout=60)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "Graphviz failed")
    graph = json.loads(completed.stdout)

    # Graphviz, like CPN Tools, has y pointing up: only centre the drawing.
    left, bottom, right, top = (float(v) for v in graph["bb"].split(","))
    cx, cy = (left + right) / 2, (bottom + top) / 2

    def point(text: str) -> tuple[float, float]:
        x, y = text.split(",")[:2]
        return float(x) - cx, float(y) - cy

    by_name = {obj["name"]: obj for obj in graph.get("objects", [])}
    for node_id in order:
        obj = by_name.get(node_id)
        if obj is None or "pos" not in obj:
            continue
        element = places.get(node_id) or transitions.get(node_id)
        element.graphics.x, element.graphics.y = point(obj["pos"])
        # Inscriptions: back to their default spots next to the node.
        for key in LABEL_KEYS:
            element.graphics.label_offsets.pop(key, None)
        element.graphics.label_offsets.pop("token", None)
        element.graphics.label_offsets.pop("marking", None)

    # Match Graphviz's edges back to the arcs by their end nodes (and label,
    # for several arcs between the same two nodes): the output does not keep
    # the input order.
    objects = graph.get("objects", [])
    pending: dict[tuple[str, str], list[dict]] = {}
    for edge in sorted(graph.get("edges", []), key=lambda e: e["_gvid"]):
        key = (objects[edge["tail"]]["name"], objects[edge["head"]]["name"])
        pending.setdefault(key, []).append(edge)
    for arc in arcs:
        key = (arc.place_id, arc.transition_id) if arc.is_input else \
            (arc.transition_id, arc.place_id)
        candidates = pending.get(key) or []
        if not candidates:
            continue
        wanted = _short(arc.expression_text, 48)
        edge = next((e for e in candidates if e.get("label") == wanted), candidates[0])
        candidates.remove(edge)
        arc.graphics.label_offsets.pop("annot", None)
        if "lp" in edge:
            arc.graphics.label_offsets["annot"] = point(edge["lp"])
        curve = [point(f"{x},{y}") for x, y in _bezier_points(edge.get("pos", ""))]
        inner = _simplify(curve, 12.0)[1:-1] if len(curve) > 2 else []
        # Graphviz's curve starts at its source; CPN files store bendpoints
        # from the transition to the place.
        if arc.is_input:
            inner.reverse()
        # The curve starts at the edge of the enlarged box (node plus its
        # inscriptions); points inside the real node's reach are dropped.
        inner = [p for p in inner if not _near_node(p, places, transitions)]
        arc.bendpoints = inner
        arc.graphics.smooth = bool(inner)


def tidy(page: Page, direction: str = "TB", spacing: float = 1.0) -> str:
    """Lay the page out with Graphviz if available, else the built-in method.

    Returns the engine used: ``"graphviz"`` or ``"built-in"``.
    """
    if find_dot() is not None:
        try:
            graphviz_layout(page, direction, spacing)
            return "graphviz"
        except Exception:  # noqa: BLE001 - fall back rather than fail
            pass
    auto_layout(page, direction, spacing)
    return "built-in"
