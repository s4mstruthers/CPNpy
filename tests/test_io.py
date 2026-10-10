"""Round-tripping models through the CPN Tools ``.cpn`` XML format."""

from models import dining_philosophers, guarded_choice, timed_conveyor

from openprocess.io.cpn_reader import parse_cpn
from openprocess.io.cpn_writer import to_xml_string
from openprocess.sim.simulator import Simulator


def round_trip(net):
    return parse_cpn(to_xml_string(net), name=net.name)


def test_header_and_doctype_are_written():
    xml = to_xml_string(guarded_choice())
    assert xml.startswith('<?xml version="1.0"')
    assert "CPNXML 1.0" in xml
    assert "<workspaceElements>" in xml


def test_structure_survives_a_round_trip():
    original = dining_philosophers(3)
    reloaded = round_trip(original)

    assert [p.name for p in reloaded.all_places()] == \
           [p.name for p in original.all_places()]
    assert [t.name for t in reloaded.all_transitions()] == \
           [t.name for t in original.all_transitions()]
    assert [a.orientation for a in reloaded.all_arcs()] == \
           [a.orientation for a in original.all_arcs()]


def test_inscriptions_survive_a_round_trip():
    original = timed_conveyor()
    reloaded = round_trip(original)
    assert [a.expression_text for a in reloaded.all_arcs()] == \
           [a.expression_text for a in original.all_arcs()]
    assert [p.initial_marking_text for p in reloaded.all_places()] == \
           [p.initial_marking_text for p in original.all_places()]


def test_declarations_survive_a_round_trip():
    original = dining_philosophers(3)
    reloaded = round_trip(original)
    assert reloaded.errors == []
    assert set(reloaded.declarations.variables) == set(original.declarations.variables)
    assert set(reloaded.declarations.colour_sets) >= {"PH", "CS"}


def test_behaviour_is_identical_after_a_round_trip():
    original = dining_philosophers(3)
    reloaded = round_trip(original)
    before = Simulator(original, seed=7)
    after = Simulator(reloaded, seed=7)
    assert {b.describe(original) for b in before.all_enabled()} == \
           {b.describe(reloaded) for b in after.all_enabled()}


def test_graphics_survive_a_round_trip():
    original = guarded_choice()
    original.pages[0].places[0].graphics.x = -123.5
    reloaded = round_trip(original)
    assert reloaded.pages[0].places[0].graphics.x == -123.5


def test_new_elements_never_reuse_an_id_from_an_opened_file(tmp_path):
    """Regression: the id counter starts at 1 in every session, so a place
    added after opening a file saved in an earlier session could get one of
    its transitions' ids -- and the file could then no longer be saved."""
    from openprocess.mining.petrinet import PetriNet
    from openprocess.model.net import Place, Transition, new_id
    from openprocess.model.plain import from_petri_net, to_petri_net

    # The file uses the very ids this session would hand out next.
    first = int(new_id()[2:]) + 1
    petri = PetriNet("earlier")
    for n in range(first, first + 20, 2):
        petri.add_place(f"p{n}", id=f"ID{n}")
        petri.add_transition(f"t{n}", id=f"ID{n + 1}")
        petri.add_arc(f"ID{n}", f"ID{n + 1}")
    net = from_petri_net(petri)
    place, transition = Place(name="new"), Transition(name="new")
    used = {f"ID{n}" for n in range(first, first + 20)}
    assert place.id not in used and transition.id not in used
    net.pages[0].places.append(place)
    to_petri_net(net)                            # saves without complaint
