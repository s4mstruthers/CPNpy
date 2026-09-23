"""Round-tripping models through the CPN Tools ``.cpn`` XML format."""

from models import dining_philosophers, guarded_choice, timed_conveyor

from cpnpy.io.cpn_reader import parse_cpn
from cpnpy.io.cpn_writer import to_xml_string
from cpnpy.sim.simulator import Simulator


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
