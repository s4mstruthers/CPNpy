"""Regression tests from the course's PlaneBoardingExample.cpn.

Each test pins one CPN Tools behaviour the model depends on and that the
engine got wrong before:

* the built-in ``time`` colour set;
* guards written as lists, ``[a, b]`` meaning ``a andalso b``;
* curried functions with several clauses (``insertBlock x [] = ...``);
* ``++`` on two lists appends them (a CPN ML multiset *is* a list);
* a list-valued initial marking on a non-list place means one token per element;
* model time keeps advancing past moments where nothing becomes enabled;
* arcs whose place or transition no longer exists are ignored.
"""

from __future__ import annotations

from pathlib import Path

from cpnpy import CPNet, Simulator, read_cpn

DATA = Path(__file__).parent / "data"


def _net(*declarations: str) -> CPNet:
    net = CPNet("t")
    for declaration in declarations:
        net.add_declaration(declaration)
    net.add_page("p")
    return net


def test_time_colour_set_and_dependants():
    net = _net("colset TIME = time;", "colset INT = int;", "colset P = product INT*INT;")
    assert net.compile() == []


def test_curried_multi_clause_function():
    net = _net("fun ins x [] = [x] | ins x (h::t) = if h < x then h :: ins x t else x :: h :: t;",
               "val a = ins 3 [1, 2, 5];")
    assert net.compile() == []
    assert str(net.evaluator.globals.lookup("a")) == "[1,2,3,5]"


def test_list_append_with_plus_plus():
    net = _net("val q = [1, 2] ++ [3];")
    assert net.compile() == []
    assert str(net.evaluator.globals.lookup("q")) == "[1,2,3]"


def test_list_guard_parses_as_conjunction():
    from cpnpy.model.net import parse_guard
    guard = parse_guard("r = cr + 1, cr < r")
    assert type(guard).__name__ == "BinOp" and guard.operator == "andalso"


def test_plane_boarding_model_simulates_to_completion():
    net = read_cpn(DATA / "plane_boarding.cpn")
    assert net.errors == []
    # List initial markings become one token per element.
    seats = next(p for p in net.all_places() if p.name.strip() == "Seats")
    simulator = Simulator(net, seed=3)
    tokens = simulator.marking.get(net.marking_key(seats.id))
    assert sum(count for *_, count in tokens.items()) == 126
    simulator.run(5000)
    seated = next(p for p in net.all_places() if p.name.strip() == "Seated")
    tokens = simulator.marking.get(net.marking_key(seated.id))
    assert sum(count for *_, count in tokens.items()) == 120      # everyone found a seat
    assert simulator.clock > 60                                  # time really advanced
