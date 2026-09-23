"""End-to-end behaviour: binding, firing, guards, time, and fusion sets."""

import pytest

from models import (
    dining_philosophers, guarded_choice, simple_transfer, timed_conveyor,
)

from cpnpy.ml.multiset import Multiset
from cpnpy.model.net import Arc, CPNet, Page, Place, Transition
from cpnpy.sim.simulator import DeadMarkingError, Simulator


def marking_of(net, simulator, place_name):
    place = next(p for p in net.all_places() if p.name == place_name)
    return simulator.marking.get(net.marking_key(place.id))


# -- basic firing -----------------------------------------------------------
def test_example_models_compile_without_errors():
    for builder in (simple_transfer, guarded_choice, timed_conveyor,
                    lambda: dining_philosophers(3)):
        net = builder()
        assert net.errors == [], f"{net.name}: {net.errors}"


def test_one_binding_per_distinct_token():
    net = simple_transfer()
    simulator = Simulator(net, seed=0)
    # A holds 1`red ++ 2`green, so `move` has two bindings, not three: the two
    # green tokens are indistinguishable and give the same binding element.
    assert len(simulator.all_enabled()) == 2


def test_firing_moves_exactly_the_bound_token():
    net = simple_transfer()
    simulator = Simulator(net, seed=0)
    red = next(b for b in simulator.all_enabled() if "red" in b.describe(net))
    simulator.step(red)
    assert marking_of(net, simulator, "A") == Multiset({_green(net): 2})
    assert marking_of(net, simulator, "B").size() == 1


def _green(net):
    from cpnpy.ml.values import Constructor
    return Constructor("green")


def test_run_reaches_the_expected_final_marking():
    net = simple_transfer()
    simulator = Simulator(net, seed=1)
    simulator.run(50)
    assert marking_of(net, simulator, "A").is_empty()
    assert marking_of(net, simulator, "B").size() == 3


def test_dead_marking_stops_the_run():
    net = simple_transfer()
    simulator = Simulator(net, seed=1)
    simulator.run(50)
    with pytest.raises(DeadMarkingError):
        simulator.step()


# -- guards -----------------------------------------------------------------
def test_guard_filters_bindings():
    net = guarded_choice()
    simulator = Simulator(net, seed=0)
    to_big = next(t for t in net.all_transitions() if t.name == "toBig")
    values = {b.as_dict()["n"] for b in simulator.enabled_bindings(to_big)}
    assert values == {4, 5}


# -- time -------------------------------------------------------------------
def test_produced_tokens_carry_the_arc_delay():
    net = timed_conveyor()
    simulator = Simulator(net, seed=0)
    simulator.step()
    done = marking_of(net, simulator, "Done")
    # One token, stamped three units in the future.
    assert [stamp for _value, stamp, _count in done.items()] == [3]


def test_clock_jumps_to_the_next_timestamp():
    net = timed_conveyor()
    simulator = Simulator(net, seed=0)
    simulator.run(10)
    assert simulator.clock == 3


# -- dining philosophers ----------------------------------------------------
def test_taking_chopsticks_consumes_both_neighbours():
    net = dining_philosophers(3)
    simulator = Simulator(net, seed=0)
    take = next(t for t in net.all_transitions() if t.name == "take")
    element = simulator.enabled_bindings(take)[0]
    simulator.step(element)
    # One philosopher eating, one chopstick left of three.
    assert marking_of(net, simulator, "Eat").size() == 1
    assert marking_of(net, simulator, "Unused").size() == 1


def test_only_one_philosopher_can_eat_at_a_time_with_three_seats():
    net = dining_philosophers(3)
    simulator = Simulator(net, seed=0)
    take = next(t for t in net.all_transitions() if t.name == "take")
    simulator.step(simulator.enabled_bindings(take)[0])
    assert simulator.enabled_bindings(take) == []


# -- fusion sets ------------------------------------------------------------
def test_places_in_a_fusion_set_share_one_marking():
    net = CPNet("Fusion")
    net.add_declaration("colset U = unit;")
    page = net.add_page("Top")

    # Two drawings of the same place, joined by a fusion group.
    left = Place(name="Shared A", colour_set_name="U",
                 initial_marking_text="1`()", fusion_group="F")
    right = Place(name="Shared B", colour_set_name="U", fusion_group="F")
    sink = Place(name="Sink", colour_set_name="U")
    drain = Transition(name="drain")
    page.places += [left, right, sink]
    page.transitions.append(drain)
    # Consume from the *other* drawing of the fused place.
    page.arcs += [
        Arc(place_id=right.id, transition_id=drain.id, orientation="PtoT",
            expression_text="1`()"),
        Arc(place_id=sink.id, transition_id=drain.id, orientation="TtoP",
            expression_text="1`()"),
    ]
    assert net.compile() == []

    simulator = Simulator(net, seed=0)
    # The token was declared on `left` but must be visible through `right`.
    assert simulator.is_enabled(drain)
    simulator.step()
    assert marking_of(net, simulator, "Shared A").is_empty()
    assert marking_of(net, simulator, "Sink").size() == 1
