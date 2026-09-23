"""Colour sets: membership and enumeration."""

import pytest

from cpnpy.ml.colorsets import (
    BoolColourSet, EnumColourSet, IndexColourSet, InfiniteColourSetError,
    IntColourSet, ListColourSet, ProductColourSet, RecordColourSet,
    UnionColourSet, standard_colour_sets,
)
from cpnpy.ml.values import Constructor, MLList, Record
from cpnpy.model.declarations import parse_colour_set_declaration


def test_bool_is_not_a_member_of_int():
    # Python's bool subclasses int, so this needs an explicit guard.
    assert not IntColourSet("INT").contains(True)
    assert BoolColourSet("BOOL").contains(True)


def test_ranged_int_is_finite_and_enumerable():
    colour_set = IntColourSet("SMALL", low=1, high=3)
    assert colour_set.is_finite()
    assert list(colour_set.members()) == [1, 2, 3]


def test_unranged_int_refuses_enumeration():
    with pytest.raises(InfiniteColourSetError):
        list(IntColourSet("INT").members())


def test_product_enumerates_the_cartesian_product():
    colours = EnumColourSet("E", ["a", "b"])
    numbers = IntColourSet("N", low=1, high=2)
    product = ProductColourSet("P", [colours, numbers])
    assert len(list(product.members())) == 4


def test_list_is_infinite_without_a_length_bound():
    element = IntColourSet("N", low=1, high=2)
    assert not ListColourSet("L", element).is_finite()
    assert ListColourSet("L", element, length_high=2).is_finite()


# -- declaration parsing ----------------------------------------------------
@pytest.mark.parametrize(
    "source, kind, finite",
    [
        ("colset E = with red | green;", EnumColourSet, True),
        ("colset N = int with 1..4;", IntColourSet, True),
        ("colset X = index ph with 1..3;", IndexColourSet, True),
        ("colset P = product INT * INT;", ProductColourSet, False),
        ("colset R = record a:INT * b:INT;", RecordColourSet, False),
        ("colset U = union Car:INT + Walk;", UnionColourSet, False),
    ],
)
def test_declaration_forms(source, kind, finite):
    registry = standard_colour_sets()
    colour_set = parse_colour_set_declaration(source, registry)
    assert isinstance(colour_set, kind)
    assert colour_set.is_finite() is finite


def test_timed_keyword_is_recognised():
    registry = standard_colour_sets()
    colour_set = parse_colour_set_declaration("colset T = int timed;", registry)
    assert colour_set.timed


def test_union_membership_checks_the_payload():
    registry = standard_colour_sets()
    union = parse_colour_set_declaration("colset U = union Car:INT + Walk;", registry)
    assert union.contains(Constructor("Car", 3))
    assert union.contains(Constructor("Walk"))
    assert not union.contains(Constructor("Car", "three"))
    assert not union.contains(Constructor("Bike", 3))
