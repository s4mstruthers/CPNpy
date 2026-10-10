"""A worked example of a box of your own: copy this file into the ``boxes/``
subfolder of the folder you have open in CPNpy, and *Last two* appears in
the box list under Discover, marked *Yours*.

A box is a function with type hints.  The parameter typed ``EventLog`` is
its input, the return type its output, ``representation`` (a choice) a
setting, and this docstring its help text.  ``flow.note`` puts a line on
the How tab.
"""

from typing import Literal

from cpnpy import flow
from cpnpy.flow import EventLog, TransitionSystem, box
from cpnpy.mining.transition_system import transition_system_from_log


@box(name="Last two", group="Discover")
def last_two(log: EventLog,
             representation: Literal["multiset", "sequence", "set"] = "multiset") -> TransitionSystem:
    """A transition system whose state is the last two activities of the
    prefix: a cheap abstraction between the full sequence and a set.

    representation: how the last two activities make a state
    """
    ts = transition_system_from_log(log.simple_log(), "prefix", representation, 2)
    flow.note(f"{len(ts.states)} states, {len(ts.transitions)} transitions")
    return ts
