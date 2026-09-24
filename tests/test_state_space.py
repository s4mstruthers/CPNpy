"""State space generation and the properties derived from it.

Expected values are worked out by hand from the models, not read off the
implementation.
"""

from models import dining_philosophers, simple_transfer

from cpnpy.analysis.state_space import StateSpace


def test_simple_transfer_state_space_size():
    # A holds 1 red + 2 green.  A reachable marking is determined by how many
    # of each colour are still in A: red in {0,1} x green in {0,1,2} = 6.
    space = StateSpace(simple_transfer()).generate()
    assert space.node_count == 6


def test_simple_transfer_has_exactly_one_deadlock():
    space = StateSpace(simple_transfer()).generate()
    dead = space.dead_markings()
    assert len(dead) == 1
    # The deadlock is the marking with everything moved to B.
    final = space.states[dead[0]].marking
    net = space.net
    b = next(p for p in net.all_places() if p.name == "B")
    assert final.get(net.marking_key(b.id)).size() == 3


def test_integer_bounds_are_exact():
    space = StateSpace(simple_transfer()).generate()
    bounds = space.integer_bounds()
    net = space.net
    a = next(p for p in net.all_places() if p.name == "A")
    assert bounds[a.id] == (0, 3)


def test_dining_philosophers_does_not_deadlock():
    # Picking up both chopsticks is atomic here, so the classic deadlock
    # cannot occur.
    space = StateSpace(dining_philosophers(3)).generate()
    assert space.dead_markings() == []


def test_dining_philosophers_transitions_are_live():
    space = StateSpace(dining_philosophers(3)).generate()
    assert {t.name for t in space.live_transitions()} == {"take", "put"}
    assert space.dead_transitions() == []


def test_dining_philosophers_all_markings_are_home_markings():
    space = StateSpace(dining_philosophers(3)).generate()
    assert len(space.home_markings()) == space.node_count


def test_partial_flag_is_set_when_the_limit_is_hit():
    space = StateSpace(simple_transfer()).generate(max_nodes=2)
    assert space.partial


def test_report_mentions_the_key_sections():
    report = StateSpace(dining_philosophers(3)).generate().report()
    for heading in ("Statistics", "Boundedness Properties", "Home Properties",
                    "Liveness Properties"):
        assert heading in report


def test_a_timed_state_waits_past_a_release_that_enables_nothing():
    # t0 puts a token in X at +1 and one in Y at +2; only Y enables t1.  The
    # state after t0 must advance time twice, not be reported as dead.
    from cpnpy.model.net import Arc, CPNet, Place, Transition
    net = CPNet("Waiting")
    net.add_declaration("colset T = unit timed;")
    page = net.add_page("Top")
    start, x, y, z = (Place(name=n, colour_set_name="T") for n in "SXYZ")
    start.initial_marking_text = "1`()"
    t0, t1 = Transition(name="t0"), Transition(name="t1")
    page.places += [start, x, y, z]
    page.transitions += [t0, t1]
    for place, transition, orientation, inscription in [
            (start, t0, "PtoT", "()"), (x, t0, "TtoP", "()@+1"), (y, t0, "TtoP", "()@+2"),
            (y, t1, "PtoT", "()"), (z, t1, "TtoP", "()")]:
        page.arcs.append(Arc(place_id=place.id, transition_id=transition.id,
                             orientation=orientation, expression_text=inscription))
    assert net.compile() == []
    space = StateSpace(net).generate()
    assert space.node_count == 3
    assert space.dead_transitions() == []
    assert space.dead_markings() == [2]
