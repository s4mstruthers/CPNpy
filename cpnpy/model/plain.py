"""Plain (uncoloured) Petri nets in the editor.

The editor draws and simulates :class:`~cpnpy.model.net.CPNet` models.  A
plain Petri net -- the kind the course uses: black tokens, arc weights,
WF-nets -- is simply a CPN in which every place has the colour set ``UNIT``:

====================  ==========================  ============================
plain net             stored in the editor as     shown on the canvas as
====================  ==========================  ============================
3 tokens in *p*       initial marking ``3`()``    three black dots
arc of weight 2       inscription ``2`()``        a small "2" on the arc
silent transition τ   ``Transition.silent``       a black bar
====================  ==========================  ============================

That way the plain editor reuses everything the CPN editor has (undo,
saving, the token game) with no second implementation.  For analysis the
drawing is converted to a :class:`~cpnpy.mining.petrinet.PetriNet`
(:func:`to_petri_net`) -- the model the soundness check, the reachability
graph, the footprint and conformance checking work on -- and back again
(:func:`from_petri_net`) to edit a discovered or imported net.
"""

from __future__ import annotations

import re

from ..mining.petrinet import Marking, PetriNet
from .net import Arc, CPNet, Place, Transition

#: Node sizes used for plain nets (model units).
PLACE_SIZE = 40.0
TRANSITION_SIZE = (40.0, 40.0)
SILENT_SIZE = (14.0, 40.0)

_TERM = re.compile(r"^\s*(\d+)\s*`\s*\(\s*\)\s*$")


def token_count(text: str) -> int:
    """How many black tokens a UNIT marking or arc inscription stands for.

    Accepts what people type or what files contain: ``""`` (none), ``"3"``,
    ``"3`()"``, ``"()"``, ``"1`()++2`()"``.  Anything else counts as 1, the
    safe default for an arc.
    """
    text = (text or "").strip()
    if not text:
        return 0
    if text.isdigit():
        return int(text)
    total = 0
    for term in text.split("++"):
        term = term.strip()
        if term == "()":
            total += 1
            continue
        match = _TERM.match(term)
        if match is None:
            return 1
        total += int(match.group(1))
    return total


def tokens_text(count: int) -> str:
    """The CPN ML text for ``count`` black tokens (``""`` for none)."""
    return f"{count}`()" if count > 0 else ""


def weight_of(arc: Arc) -> int:
    """An arc's weight (an empty inscription means 1)."""
    return max(1, token_count(arc.expression_text) or 1)


def is_plain(net: CPNet) -> bool:
    """Is every place a UNIT place (so the net can be analysed as a plain net)?"""
    return all(place.colour_set_name == "UNIT" for place in net.all_places())


def new_plain_net(name: str) -> CPNet:
    """An empty plain Petri net, ready to draw on."""
    net = CPNet(name)
    net.add_declaration("colset UNIT = unit;")
    net.add_page("Net")
    net.plain = True
    return net


def to_petri_net(net: CPNet) -> PetriNet:
    """The drawing as a :class:`PetriNet` (ids, names and positions kept).

    Positions become PNML-style coordinates (y pointing down).  A
    double-headed arc becomes one arc each way.  If the net has exactly one
    place without outgoing arcs (a WF-net's sink), the final marking is one
    token there.
    """
    petri = PetriNet(net.name)
    initial: dict[str, int] = {}
    for place in net.all_places():
        node = petri.add_place(place.name or place.id, id=place.id)
        node.position = (place.graphics.x, -place.graphics.y)
        count = token_count(place.initial_marking_text)
        if count:
            initial[place.id] = count
    for transition in net.all_transitions():
        silent = getattr(transition, "silent", False)
        node = petri.add_transition(None if silent else (transition.name or transition.id),
                                    name=transition.name or ("τ" if silent else transition.id),
                                    id=transition.id)
        node.position = (transition.graphics.x, -transition.graphics.y)
    for arc in net.all_arcs():
        weight = weight_of(arc)
        bends = [(x, -y) for x, y in arc.bendpoints]           # transition -> place
        if arc.is_input:
            petri.add_arc(arc.place_id, arc.transition_id, weight).points = bends[::-1]
        if arc.is_output:
            petri.add_arc(arc.transition_id, arc.place_id, weight).points = list(bends)
    petri.initial_marking = Marking(initial)
    sinks = petri.sink_places()
    if len(sinks) == 1:
        petri.final_marking = Marking({sinks[0]: 1})
    return petri


def from_petri_net(petri: PetriNet) -> CPNet:
    """A plain net the editor can draw, from a mined, imported or typed
    :class:`PetriNet`.  Nodes without a stored position are laid out left to
    right, as in the course's figures."""
    net = new_plain_net(petri.name)
    page = net.pages[0]
    positions = _positions(petri)
    for place in petri.places.values():
        x, y = positions[place.id]
        node = Place(id=place.id, name=place.name, colour_set_name="UNIT",
                     initial_marking_text=tokens_text(petri.initial_marking[place.id]))
        node.graphics.x, node.graphics.y = x, -y
        node.graphics.width = node.graphics.height = PLACE_SIZE
        page.places.append(node)
    for transition in petri.transitions.values():
        x, y = positions[transition.id]
        node = Transition(id=transition.id,
                          name="" if transition.silent and transition.name in ("τ", "tau")
                          else transition.name)
        node.silent = transition.silent
        node.graphics.x, node.graphics.y = x, -y
        node.graphics.width, node.graphics.height = SILENT_SIZE if node.silent else \
            TRANSITION_SIZE
        page.transitions.append(node)
    for arc in petri.arcs:
        if arc.source in petri.places:
            place_id, transition_id, orientation = arc.source, arc.target, "PtoT"
        else:
            place_id, transition_id, orientation = arc.target, arc.source, "TtoP"
        points = [(x, -y) for x, y in getattr(arc, "points", [])]      # source -> target
        page.arcs.append(Arc(place_id=place_id, transition_id=transition_id,
                             orientation=orientation,
                             expression_text="" if arc.weight == 1 else tokens_text(arc.weight),
                             bendpoints=points if orientation == "TtoP" else points[::-1]))
    return net


def _positions(petri: PetriNet) -> dict[str, tuple[float, float]]:
    """Stored positions where every node has one; otherwise a fresh layered
    layout, flowing left to right."""
    nodes = list(petri.places.values()) + list(petri.transitions.values())
    if nodes and all(node.position is not None for node in nodes):
        return {node.id: node.position for node in nodes}
    from ..mining.layout import layered_layout
    sizes = {node.id: (PLACE_SIZE, PLACE_SIZE) for node in petri.places.values()}
    sizes.update({node.id: TRANSITION_SIZE for node in petri.transitions.values()})
    edges = [(arc.source, arc.target) for arc in petri.arcs]
    layout = layered_layout(sizes, edges, layer_gap=60.0, node_gap=50.0)
    return {node: (x, y) for node, (x, y) in layout.positions.items()}
