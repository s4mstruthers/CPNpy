"""Hierarchical models: substitution transitions run their subpages.

A port place on a subpage is the socket place it is assigned to, so tokens
put into the socket are consumed by the subpage's transitions.  The model
below has three levels:

    Top:     Orders --[Handle]--> Done
    Handle:  In --check--> Mid --[Ship]--> Out      (In, Out: ports)
    Ship:    From --pack--> To                       (From, To: ports)
"""

from cpnpy.analysis.state_space import StateSpace
from cpnpy.io.cpn_reader import read_cpn
from cpnpy.io.cpn_writer import write_cpn
from cpnpy.ml.multiset import Multiset
from cpnpy.model.net import Arc, CPNet, Place, Transition
from cpnpy.sim.simulator import Simulator


def hierarchical() -> CPNet:
    net = CPNet("Hierarchy")
    net.add_declaration("colset N = int with 1..3;")
    net.add_declaration("var n : N;")
    top, handle_page, ship_page = (net.add_page(n) for n in ("Top", "Handle", "Ship"))

    orders = Place(name="Orders", colour_set_name="N", initial_marking_text="1`1 ++ 1`2")
    done = Place(name="Done", colour_set_name="N")
    handle = Transition(name="Handle", substitution_subpage=handle_page.id)
    top.places += [orders, done]
    top.transitions.append(handle)
    top.arcs += [Arc(place_id=orders.id, transition_id=handle.id, expression_text="n"),
                 Arc(place_id=done.id, transition_id=handle.id, orientation="TtoP",
                     expression_text="n")]

    # A port's own initial marking is ignored: the socket's counts.
    port_in = Place(name="In", colour_set_name="N", port_type="In", initial_marking_text="1`3")
    mid = Place(name="Mid", colour_set_name="N")
    port_out = Place(name="Out", colour_set_name="N", port_type="Out")
    check = Transition(name="check", guard_text="[n <> 3]")
    ship = Transition(name="Ship", substitution_subpage=ship_page.id)
    handle_page.places += [port_in, mid, port_out]
    handle_page.transitions += [check, ship]
    handle_page.arcs += [Arc(place_id=port_in.id, transition_id=check.id, expression_text="n"),
                         Arc(place_id=mid.id, transition_id=check.id, orientation="TtoP",
                             expression_text="n")]
    handle.port_assignments = {orders.id: port_in.id, done.id: port_out.id}

    source = Place(name="From", colour_set_name="N", port_type="In")
    target = Place(name="To", colour_set_name="N", port_type="Out")
    pack = Transition(name="pack")
    ship_page.places += [source, target]
    ship_page.transitions.append(pack)
    ship_page.arcs += [Arc(place_id=source.id, transition_id=pack.id, expression_text="n"),
                       Arc(place_id=target.id, transition_id=pack.id, orientation="TtoP",
                           expression_text="n * 10")]
    ship.port_assignments = {mid.id: source.id, port_out.id: target.id}
    return net


def _tokens(net, simulator, name):
    place = next(p for p in net.all_places() if p.name == name)
    return simulator.marking.get(net.marking_key(place.id))


def test_tokens_flow_through_the_subpages():
    net = hierarchical()
    assert net.compile() == []
    simulator = Simulator(net, seed=0)
    assert _tokens(net, simulator, "In") == Multiset({1: 1, 2: 1})     # the socket's tokens
    simulator.run(10)
    assert sorted(r.binding.describe(net).split()[0] for r in simulator.log) == \
        ["check", "check", "pack", "pack"]
    assert _tokens(net, simulator, "Done") == Multiset({10: 1, 20: 1})
    assert _tokens(net, simulator, "To") == _tokens(net, simulator, "Done")


def test_state_space_of_a_hierarchical_model():
    net = hierarchical()
    net.compile()
    space = StateSpace(net).generate()
    # Each order is at one of three stages, independently: 3 x 3 markings.
    assert space.node_count == 9
    assert len(space.dead_markings()) == 1
    assert space.dead_transitions() == []


def test_hierarchy_survives_saving(tmp_path):
    net = hierarchical()
    net.compile()
    write_cpn(net, tmp_path / "hierarchy.cpn")
    again = read_cpn(tmp_path / "hierarchy.cpn")
    assert again.errors == []
    simulator = Simulator(again, seed=0)
    simulator.run(10)
    assert _tokens(again, simulator, "Done") == Multiset({10: 1, 20: 1})


def test_a_subpage_used_twice_is_reported():
    net = hierarchical()
    top = net.pages[0]
    handle = top.transitions[0]
    top.transitions.append(Transition(name="Handle again",
                                      substitution_subpage=handle.substitution_subpage,
                                      port_assignments=dict(handle.port_assignments)))
    problems = net.compile()
    assert len(problems) == 1 and "used by 2 substitution transitions" in problems[0].message
