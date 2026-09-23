"""Example models, built programmatically.

These double as the fixtures for the test suite and as a demonstration of the
model-construction API.  Each builder returns a compiled :class:`CPNet`, ready
to hand to a :class:`~cpnpy.sim.simulator.Simulator`.

Building a net in code takes four steps, visible in every function below:

1. create the :class:`~cpnpy.model.net.CPNet` and add declarations;
2. create a :class:`~cpnpy.model.net.Page`;
3. add places, transitions and the arcs between them;
4. call :meth:`~cpnpy.model.net.CPNet.compile` and check it returned no errors.
"""

from __future__ import annotations

from cpnpy.model.net import Arc, CPNet, Graphics, Page, Place, Transition


def _connect(page: Page, place: Place, transition: Transition,
             orientation: str, expression: str) -> Arc:
    """Add one arc and return it.  ``orientation`` is ``"PtoT"`` or ``"TtoP"``."""
    arc = Arc(
        place_id=place.id,
        transition_id=transition.id,
        orientation=orientation,
        expression_text=expression,
    )
    page.arcs.append(arc)
    return arc


# ---------------------------------------------------------------------------
def simple_transfer() -> CPNet:
    """Two places and one transition; tokens move from A to B.

    The smallest model that still exercises colour sets, variables and binding.
    """
    net = CPNet("SimpleTransfer")
    net.add_declaration("colset COLOUR = with red | green | blue;")
    net.add_declaration("var c : COLOUR;")

    page = net.add_page("Top")
    a = Place(name="A", colour_set_name="COLOUR",
              initial_marking_text="1`red ++ 2`green",
              graphics=Graphics(x=-190, y=0))
    b = Place(name="B", colour_set_name="COLOUR", graphics=Graphics(x=190, y=0))
    move = Transition(name="move", graphics=Graphics(x=0, y=0))
    page.places += [a, b]
    page.transitions.append(move)
    _connect(page, a, move, "PtoT", "c")
    _connect(page, b, move, "TtoP", "c")

    net.compile()
    return net


# ---------------------------------------------------------------------------
def dining_philosophers(count: int = 3) -> CPNet:
    """The standard CPN Tools dining philosophers model.

    Structure (all places on one page):

    * ``Think``   -- philosophers currently thinking;
    * ``Eat``     -- philosophers currently eating;
    * ``Unused``  -- chopsticks on the table;
    * ``take``    -- a thinking philosopher picks up both neighbouring sticks;
    * ``put``     -- an eating philosopher puts them back.

    The arc expressions use two helper functions declared in ML:
    ``Chopsticks(p)`` returns the multiset of the two sticks philosopher ``p``
    needs.  This is exactly how the CPN Tools sample model is written, and it
    is a good exercise of the multiset machinery: an input arc whose expression
    is a *function call returning a multiset* cannot be treated as a pattern,
    so the binder falls back to evaluating it once ``p`` is known.
    """
    net = CPNet(f"DiningPhilosophers{count}")
    net.add_declaration(f"colset PH = index ph with 1..{count};")
    net.add_declaration(f"colset CS = index cs with 1..{count};")
    net.add_declaration("var p : PH;")
    # `Chopsticks` maps philosopher i to the multiset {cs(i), cs(i mod n + 1)}.
    net.add_declaration(
        f"fun Chopsticks (ph(i)) = 1`cs(i) ++ 1`cs(if i = {count} then 1 else i+1);"
    )

    # Layout: an outer diamond (Think -> take -> Eat -> put -> Think) with the
    # chopstick place at its centre.  Chosen so that no arc passes through a
    # node: the four diamond arcs run diagonally and the two chopstick arcs run
    # vertically along the axis, meeting Unused from opposite sides.
    page = net.add_page("Philosophers")
    think = Place(name="Think", colour_set_name="PH",
                  initial_marking_text=" ++ ".join(
                      f"1`ph({i})" for i in range(1, count + 1)),
                  graphics=Graphics(x=-300, y=0))
    eat = Place(name="Eat", colour_set_name="PH", graphics=Graphics(x=300, y=0))
    unused = Place(name="Unused", colour_set_name="CS",
                   initial_marking_text=" ++ ".join(
                       f"1`cs({i})" for i in range(1, count + 1)),
                   graphics=Graphics(x=0, y=0))
    take = Transition(name="take", graphics=Graphics(x=0, y=150))
    put = Transition(name="put", graphics=Graphics(x=0, y=-150))

    page.places += [think, eat, unused]
    page.transitions += [take, put]

    _connect(page, think, take, "PtoT", "p")
    _connect(page, unused, take, "PtoT", "Chopsticks(p)")
    _connect(page, eat, take, "TtoP", "p")

    _connect(page, eat, put, "PtoT", "p")
    _connect(page, think, put, "TtoP", "p")
    _connect(page, unused, put, "TtoP", "Chopsticks(p)")

    net.compile()
    return net


# ---------------------------------------------------------------------------
def timed_conveyor() -> CPNet:
    """A timed model: each item takes 3 time units to traverse a stage.

    Demonstrates the three timed rules -- stamped tokens, ``@+`` delays, and
    the clock jumping to the next stamp when nothing is enabled now.
    """
    net = CPNet("TimedConveyor")
    net.add_declaration("colset ITEM = int timed;")
    net.add_declaration("var i : ITEM;")

    page = net.add_page("Line")
    waiting = Place(name="Waiting", colour_set_name="ITEM",
                    initial_marking_text="1`1 ++ 1`2 ++ 1`3",
                    graphics=Graphics(x=-150, y=0))
    done = Place(name="Done", colour_set_name="ITEM", graphics=Graphics(x=150, y=0))
    process = Transition(name="process", graphics=Graphics(x=0, y=0))
    # (Waiting, process, Done are collinear, which is fine: only two arcs,
    #  and neither passes through a third node.)

    page.places += [waiting, done]
    page.transitions.append(process)
    _connect(page, waiting, process, "PtoT", "i")
    # The produced token is only available three time units later.
    _connect(page, done, process, "TtoP", "1`i @+ 3")

    net.compile()
    return net


# ---------------------------------------------------------------------------
def guarded_choice() -> CPNet:
    """A transition whose guard filters which bindings are enabled.

    ``Waiting`` holds the integers 1..5; ``big`` may only fire on values above
    three.  Used to test that guards are evaluated after binding, not before.
    """
    net = CPNet("GuardedChoice")
    net.add_declaration("colset N = int with 1..5;")
    net.add_declaration("var n : N;")

    # Two symmetric branches out of one source place.  Without explicit
    # coordinates every element would sit at the origin on top of the others.
    page = net.add_page("Top")
    waiting = Place(name="Waiting", colour_set_name="N",
                    initial_marking_text="1`1 ++ 1`2 ++ 1`3 ++ 1`4 ++ 1`5",
                    graphics=Graphics(x=-230, y=0))
    big = Place(name="Big", colour_set_name="N", graphics=Graphics(x=230, y=100))
    small = Place(name="Small", colour_set_name="N", graphics=Graphics(x=230, y=-100))
    to_big = Transition(name="toBig", guard_text="n > 3",
                        graphics=Graphics(x=0, y=100))
    to_small = Transition(name="toSmall", guard_text="n <= 3",
                          graphics=Graphics(x=0, y=-100))

    page.places += [waiting, big, small]
    page.transitions += [to_big, to_small]
    _connect(page, waiting, to_big, "PtoT", "n")
    _connect(page, big, to_big, "TtoP", "n")
    _connect(page, waiting, to_small, "PtoT", "n")
    _connect(page, small, to_small, "TtoP", "n")

    net.compile()
    return net


ALL_EXAMPLES = {
    "simple_transfer": simple_transfer,
    "dining_philosophers": dining_philosophers,
    "timed_conveyor": timed_conveyor,
    "guarded_choice": guarded_choice,
}
