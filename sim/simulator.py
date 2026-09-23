"""The simulation engine: firing transitions and advancing the clock.

The firing rule
---------------
For a transition ``t`` and a binding ``b`` that :mod:`cpnpy.sim.binding` has
found to be enabled in marking ``M``, firing produces ``M'`` where, for every
place ``p``::

    M'(p)  =  ( M(p)  --  E(p,t)<b> )  ++  E(t,p)<b>

``E(p,t)`` is the inscription on the arc from ``p`` to ``t`` (what is consumed)
and ``E(t,p)`` the inscription on the arc back (what is produced).  Everything
below is bookkeeping around those two multiset operations.

Timed nets
----------
A timed model adds a global clock.  Three rules govern it:

1. A token in a timed place carries a **time stamp**: the model time at which
   it becomes available.  Only tokens whose stamp has been reached may be
   consumed.
2. Produced tokens are stamped ``clock + delay``, where the delay comes from
   the arc's ``@+`` expression, or the transition's own time inscription if the
   arc has none.
3. When no transition is enabled at the current clock but some place holds a
   token stamped for the future, the clock **jumps** to the earliest such
   stamp.  Model time therefore moves in event-driven jumps, never in ticks.

Only when no transition is enabled and no future stamp exists is the model
genuinely dead.

Determinism
-----------
Which enabled binding element fires is a free choice in CPN semantics.  The
simulator uses its own seeded random generator for that choice, separate from
the one inscriptions draw from, so that a replayed run makes the same choices
even if the model's own random calls change.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from ..ml.errors import CPNMLError
from ..ml.evaluator import Environment, expand_lists, to_multiset
from ..ml.multiset import Multiset, TimedMultiset
from ..model.net import Arc, CPNet, Marking, Place, Transition
from .binding import Binder, BindingElement


@dataclass
class FiringRecord:
    """One entry of the simulation log."""

    step: int
    time: int
    binding: BindingElement
    #: The marking *after* this firing.  Kept so that the GUI can rewind.
    marking: Marking

    def describe(self, net: CPNet) -> str:
        return f"{self.step:>4}  t={self.time:<6} {self.binding.describe(net)}"


class DeadMarkingError(RuntimeError):
    """Raised by :meth:`Simulator.step` when nothing can happen at all."""


class Simulator:
    """Drives a :class:`~cpnpy.model.net.CPNet` forward.

    The simulator owns the *current* marking and clock.  Every firing builds a
    new :class:`~cpnpy.model.net.Marking` rather than mutating the old one, so
    the history in :attr:`log` stays valid and can be replayed or stepped back
    through.
    """

    def __init__(self, net: CPNet, marking: Marking | None = None,
                 seed: int | None = None) -> None:
        self.net = net
        self.marking = marking if marking is not None else net.initial_marking()
        self.clock = 0
        self.step_count = 0
        self.log: list[FiringRecord] = []
        self.binder = Binder(net)
        #: Choice generator, deliberately separate from the model's own RNG.
        self.choice_rng = random.Random(seed)

    # =======================================================================
    # Enabling
    # =======================================================================
    def enabled_bindings(self, transition: Transition) -> list[BindingElement]:
        """Enabled binding elements of one transition at the current time."""
        if transition.is_substitution:
            # A substitution transition is a drawing device: the behaviour
            # lives on its subpage, so it never fires itself.
            return []
        return self.binder.bindings(transition, self.marking, self.clock)

    def all_enabled(self) -> list[BindingElement]:
        """Every enabled binding element in the whole model, in a stable order."""
        result: list[BindingElement] = []
        for transition in self.net.all_transitions():
            result.extend(self.enabled_bindings(transition))
        return result

    def is_enabled(self, transition: Transition) -> bool:
        return bool(self.enabled_bindings(transition))

    # =======================================================================
    # Firing
    # =======================================================================
    def fire(self, element: BindingElement, marking: Marking | None = None,
             clock: int | None = None) -> tuple[Marking, int]:
        """Apply one binding element, returning the new marking and clock.

        Pure with respect to the simulator's own state when ``marking`` and
        ``clock`` are supplied -- which is how the state space explorer uses it.
        Called without them it reads (but still does not write) the simulator's
        current state.
        """
        current = self.marking if marking is None else marking
        now = self.clock if clock is None else clock

        transition = self.net.find_transition(element.transition_id)
        if transition is None:
            raise DeadMarkingError(f"unknown transition {element.transition_id}")
        page = self.net.page_of(transition)
        assert page is not None

        bindings = element.as_dict()
        environment = Environment(bindings, self.net.evaluator.globals)
        self.net.evaluator.set_model_time(now)

        # The transition's own time inscription is the default delay for output
        # arcs that do not carry their own `@+`.
        default_delay = 0
        if transition.time_ast is not None:
            value = self.net.evaluator.evaluate(transition.time_ast, environment)
            default_delay = value          # int or real, like the model's clock

        result = current.copy()

        # --- 1. consume -----------------------------------------------------
        for arc in page.arcs_of(transition):
            if not arc.is_input or arc.expression_ast is None:
                continue
            key = self.net.marking_key(arc.place_id)
            tokens, _stamp = self.net.evaluator.evaluate_arc(
                arc.expression_ast, environment, now
            )
            current_tokens = result.get(key)
            if isinstance(current_tokens, TimedMultiset):
                result.set(key, current_tokens.remove_available(tokens, now))
            else:
                if not (tokens <= current_tokens):
                    raise DeadMarkingError(
                        f"transition '{transition.name}' is not enabled under "
                        f"{element.describe(self.net)}: place is missing {tokens}"
                    )
                result.set(key, current_tokens - tokens)

        # --- 2. produce -----------------------------------------------------
        for arc in page.arcs_of(transition):
            if not arc.is_output or arc.expression_ast is None:
                continue
            key = self.net.marking_key(arc.place_id)
            place = self.net.find_place(arc.place_id)
            colour_set = self.net.colour_set_of(place) if place else None

            tokens, stamp = self.net.evaluator.evaluate_arc(
                arc.expression_ast, environment, now
            )
            tokens = expand_lists(tokens, colour_set)
            if colour_set is not None and colour_set.timed:
                # No `@+` on the arc means the transition's delay applies.
                if stamp == now:
                    stamp = now + default_delay
                existing = result.get(key)
                if not isinstance(existing, TimedMultiset):
                    existing = TimedMultiset.from_multiset(existing, now)
                result.set(key, existing.add(TimedMultiset.from_multiset(tokens, stamp)))
            else:
                existing = result.get(key)
                if isinstance(existing, TimedMultiset):
                    # Defensive: a place whose colour set lost its `timed` flag.
                    existing = existing.available_at(now)
                result.set(key, existing + tokens)

        return result, now

    # =======================================================================
    # Stepping
    # =======================================================================
    def step(self, element: BindingElement | None = None) -> BindingElement:
        """Fire one binding element, advancing the clock first if necessary.

        With no argument, picks a random enabled binding element (see
        :meth:`_random_enabled_element`) -- the usual way to explore a model's
        behaviour.  If nothing is enabled now, time passes, one token-release
        moment at a time, until something is: stopping at the *first* moment
        would be wrong, because the token released there may not enable
        anything while a later one does (CPN Tools keeps advancing too).
        Raises :class:`DeadMarkingError` when the marking is dead.
        """
        if element is None:
            element = self._random_enabled_element()
            while element is None:
                if not self.advance_time():
                    raise DeadMarkingError(
                        f"dead marking at time {self.clock} after {self.step_count} steps"
                    )
                element = self._random_enabled_element()
        return self._fire_and_record(element)

    def _fire_and_record(self, element: BindingElement) -> BindingElement:
        self.marking, self.clock = self.fire(element)
        self.step_count += 1
        self.log.append(FiringRecord(self.step_count, self.clock, element, self.marking))
        return element

    def _random_enabled_element(self) -> BindingElement | None:
        """Pick a random enabled binding element without computing them all.

        Like CPN Tools' automatic simulation: visit the transitions in random
        order, and fire a random binding of the first one that is enabled.
        (Every enabled transition is equally likely to be chosen; its
        bindings then share that chance.)  Computing every binding of every
        transition at every step was the simulator's main cost.
        """
        transitions = list(self.net.all_transitions())
        self.choice_rng.shuffle(transitions)
        for transition in transitions:
            bindings = self.enabled_bindings(transition)
            if bindings:
                return self.choice_rng.choice(bindings)
        return None

    def advance_time(self) -> bool:
        """Jump the clock to the next moment something could happen.

        Returns ``True`` if the clock moved.  ``False`` means every timed place
        is either empty or holds only tokens already available, so waiting
        cannot help and the marking is dead.
        """
        candidates: list[int] = []
        for place in self.net.all_places():
            tokens = self.marking.get(self.net.marking_key(place.id))
            if isinstance(tokens, TimedMultiset):
                next_time = tokens.next_time_after(self.clock)
                if next_time is not None:
                    candidates.append(next_time)
        if not candidates:
            return False
        self.clock = min(candidates)
        self.net.evaluator.set_model_time(self.clock)
        return True

    def run(self, max_steps: int = 100, until_time: int | None = None) -> int:
        """Fire repeatedly.  Returns the number of steps actually taken.

        Stops early on a dead marking, or when the clock passes ``until_time``.
        Both stopping conditions are normal outcomes, not errors -- inspect
        :attr:`log` and :attr:`marking` afterwards to see where it got to.
        """
        taken = 0
        for _ in range(max_steps):
            if until_time is not None and self.clock > until_time:
                break
            try:
                self.step()
            except DeadMarkingError:
                break
            taken += 1
        return taken

    # =======================================================================
    # Inspection
    # =======================================================================
    def reset(self, marking: Marking | None = None) -> None:
        """Return to the initial marking (or a supplied one) at time zero."""
        self.marking = marking if marking is not None else self.net.initial_marking()
        self.clock = 0
        self.step_count = 0
        self.log.clear()

    def rewind_to(self, step: int) -> None:
        """Restore the state as it was after ``step`` firings."""
        if step <= 0:
            self.reset()
            return
        if step > len(self.log):
            raise IndexError(f"only {len(self.log)} steps have been taken")
        record = self.log[step - 1]
        self.marking = record.marking
        self.clock = record.time
        self.step_count = record.step
        del self.log[step:]

    def describe(self) -> str:
        """A short status line plus the current marking."""
        header = f"step {self.step_count}, time {self.clock}"
        return f"{header}\n{self.marking.describe(self.net)}"
