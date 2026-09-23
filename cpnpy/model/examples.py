"""Small Petri nets to try the editor and the analyses on.

Each function returns a :class:`~cpnpy.mining.petrinet.PetriNet` with node
positions, the way the course's figures draw them (flowing left to right).
They are listed under File ▸ Open Example Petri Net, and saved as PNML in
``examples/petri/``.
"""

from __future__ import annotations

from ..mining.petrinet import Marking, PetriNet


def _build(name: str, places: dict[str, tuple[float, float]],
           transitions: dict[str, tuple[float, float]], arcs: list[tuple[str, str]],
           silent: set[str] = frozenset(), start: str | None = None) -> PetriNet:
    net = PetriNet(name)
    nodes = {}
    for label, position in places.items():
        nodes[label] = net.add_place(label)
        nodes[label].position = position
    for label, position in transitions.items():
        transition = net.add_transition(None if label in silent else label, name=label)
        transition.position = position
        nodes[label] = transition
    for source, target in arcs:
        net.add_arc(nodes[source], nodes[target])
    if start is not None:
        net.initial_marking = Marking({nodes[start].id: 1})
    sinks = net.sink_places()
    if len(sinks) == 1:
        net.final_marking = Marking({sinks[0]: 1})
    return net


def order_handling_unsound() -> PetriNet:
    """An order process with a bug: *reject* only consumes the stock branch,
    so the credit branch leaves a token behind (no proper completion) and
    the net can get stuck (no option to complete)."""
    return _build(
        "Order handling (unsound)",
        {"start": (0, 0), "c1": (200, -60), "c2": (200, 60), "c3": (400, -60),
         "c4": (400, 60), "end": (620, 0)},
        {"register": (100, 0), "check stock": (300, -60), "check credit": (300, 60),
         "ship": (510, 30), "reject": (510, -90)},
        [("start", "register"), ("register", "c1"), ("register", "c2"),
         ("c1", "check stock"), ("c2", "check credit"), ("check stock", "c3"),
         ("check credit", "c4"), ("c3", "ship"), ("c4", "ship"), ("ship", "end"),
         ("c3", "reject"), ("reject", "end")],
        start="start")


def order_handling_sound() -> PetriNet:
    """The same process, fixed: *reject* waits for both checks."""
    return _build(
        "Order handling (sound)",
        {"start": (0, 0), "c1": (200, -60), "c2": (200, 60), "c3": (400, -60),
         "c4": (400, 60), "end": (620, 0)},
        {"register": (100, 0), "check stock": (300, -60), "check credit": (300, 60),
         "ship": (510, 50), "reject": (510, -50)},
        [("start", "register"), ("register", "c1"), ("register", "c2"),
         ("c1", "check stock"), ("c2", "check credit"), ("check stock", "c3"),
         ("check credit", "c4"), ("c3", "ship"), ("c4", "ship"), ("ship", "end"),
         ("c3", "reject"), ("c4", "reject"), ("reject", "end")],
        start="start")


def textbook_l1() -> PetriNet:
    """The model the α-algorithm finds for L₁ = [⟨a,b,c,d⟩³, ⟨a,c,b,d⟩², ⟨a,e,d⟩]
    (van der Aalst, *Process Mining*, ch. 6)."""
    return _build(
        "Textbook L1 model",
        {"i": (0, 0), "p1": (200, -70), "p2": (200, 70), "p3": (400, -70),
         "p4": (400, 70), "o": (600, 0)},
        {"a": (100, 0), "b": (300, -70), "c": (300, 70), "e": (300, 0), "d": (500, 0)},
        [("i", "a"), ("a", "p1"), ("a", "p2"), ("p1", "b"), ("p2", "c"), ("b", "p3"),
         ("c", "p4"), ("p1", "e"), ("p2", "e"), ("e", "p3"), ("e", "p4"), ("p3", "d"),
         ("p4", "d"), ("d", "o")],
        start="i")


def loop_with_silent_step() -> PetriNet:
    """A loop back via a silent transition τ: ⟨a, b, (c, b)*, d⟩."""
    return _build(
        "Loop with a silent step",
        {"i": (0, 0), "p1": (200, 0), "p2": (400, 0), "o": (600, 0), "p3": (300, 110)},
        {"a": (100, 0), "b": (300, 0), "d": (500, 0), "c": (400, 110), "tau": (200, 110)},
        [("i", "a"), ("a", "p1"), ("p1", "b"), ("b", "p2"), ("p2", "d"), ("d", "o"),
         ("p2", "c"), ("c", "p3"), ("p3", "tau"), ("tau", "p1")],
        silent={"tau"}, start="i")


EXAMPLES = {
    "Order handling (unsound — try Analysis)": order_handling_unsound,
    "Order handling (sound)": order_handling_sound,
    "Textbook L₁ model (α-algorithm)": textbook_l1,
    "Loop with a silent step": loop_with_silent_step,
}
