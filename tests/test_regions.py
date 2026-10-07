"""State-based regions, transition systems from logs, and comparing nets on behaviour.

The two exam cases come from TU/e 2AMI10 (2022/23 Q1) and its grading scheme
(issue #30); the values were checked with a brute-force script over every
subset of states.
"""

from cpnpy.mining.compare_nets import compare_nets, replayable_prefix
from cpnpy.mining.discovery.state_regions import region_miner, region_result
from cpnpy.mining.log import parse_simple_log
from cpnpy.mining.petrinet import Marking, PetriNet
from cpnpy.mining.regions import analyse_regions, check_region, synthesise
from cpnpy.mining.transition_system import (
    isomorphic, parse_states, parse_transition_system, transition_system_from_log,
)

EXAM_TS = """s0 -a-> s1, s0 -d-> s2, s0 -c-> s3, s0 -b-> s4
s1 -d-> s5, s2 -a-> s5, s3 -b-> s6, s4 -c-> s6, s5 -e-> s7, s6 -e-> s7"""


def fs(*states):
    return frozenset(states)


# ---------------------------------------------------------------------------
# Transition systems
# ---------------------------------------------------------------------------
def test_log_to_transition_system_exam_case():
    log = parse_simple_log("[<a,d,d,c>, <b,a,c>, <b,d,a,c>, <a,d,c,b>]")
    ts = transition_system_from_log(log, "prefix", "set", horizon=2)
    assert set(ts.states) == {"{}", "{a}", "{b}", "{a,d}", "{b,d}", "{a,b}", "{d}", "{c,d}",
                              "{a,c}", "{b,c}"}
    assert set(ts.transitions) == {
        ("{}", "a", "{a}"), ("{}", "b", "{b}"), ("{a}", "d", "{a,d}"), ("{b}", "d", "{b,d}"),
        ("{b}", "a", "{a,b}"), ("{a,d}", "d", "{d}"), ("{a,d}", "c", "{c,d}"),
        ("{a,d}", "c", "{a,c}"), ("{b,d}", "a", "{a,d}"), ("{a,b}", "c", "{a,c}"),
        ("{d}", "c", "{c,d}"), ("{c,d}", "b", "{b,c}")}
    assert ts.initial == ["{}"]
    # Each variant remembers the states it passes through.
    walks = {trace: walk for trace, _, walk in ts.traces}
    assert walks[("a", "d", "d", "c")] == ["{}", "{a}", "{a,d}", "{d}", "{c,d}"]


def test_state_functions():
    log = parse_simple_log("[<a,b,a>]")
    assert transition_system_from_log(log, "prefix", "sequence").states == \
        ["⟨⟩", "⟨a⟩", "⟨a,b⟩", "⟨a,b,a⟩"]
    assert transition_system_from_log(log, "prefix", "multiset").states[-1] == "[a^2,b]"
    assert transition_system_from_log(log, "prefix", "sequence", 1).states == \
        ["⟨⟩", "⟨a⟩", "⟨b⟩"]
    postfix = transition_system_from_log(parse_simple_log("[<a,b>, <c>]"), "postfix", "set")
    assert sorted(postfix.initial) == ["{a,b}", "{c}"]      # one start per trace
    both = transition_system_from_log(log, "both", "set", 1)
    assert both.states[0] == "({}, {a})"


def test_parse_transition_system_notations():
    ts = parse_transition_system("s_0 \\xrightarrow{a} s_1\ns1 --b--> s2; s2 –c→ s0\n"
                                 "final: s2")
    assert ts.transitions == [("s0", "a", "s1"), ("s1", "b", "s2"), ("s2", "c", "s0")]
    assert ts.initial == ["s0"] and ts.final == ["s2"]
    braces = parse_transition_system("{a} -d-> {a,d}, {a,d} -c-> {c,d}\ninitial: {a}")
    assert braces.states == ["{a}", "{a,d}", "{c,d}"]
    assert parse_states("{a}, {a,d}, s0") == ["{a}", "{a,d}", "s0"]
    again = parse_transition_system(braces.to_text())
    assert again.transitions == braces.transitions and again.initial == braces.initial


def test_isomorphism():
    one = parse_transition_system("s0 -a-> s1, s0 -b-> s2, s1 -b-> s3, s2 -a-> s3")
    two = parse_transition_system("x -b-> y, x -a-> z, y -a-> w, z -b-> w")
    three = parse_transition_system("s0 -a-> s1, s0 -b-> s2, s1 -b-> s3, s2 -a-> s4")
    assert isomorphic(one, two)
    assert not isomorphic(one, three)


# ---------------------------------------------------------------------------
# Regions
# ---------------------------------------------------------------------------
def test_regions_exam_case():
    ts = parse_transition_system(EXAM_TS)
    analysis = analyse_regions(ts)
    expected = {
        "a": ([fs("s0", "s2", "s3"), fs("s0", "s2", "s4")], fs("s0", "s2")),
        "b": ([fs("s0", "s2", "s3"), fs("s0", "s1", "s3")], fs("s0", "s3")),
        "c": ([fs("s0", "s2", "s4"), fs("s0", "s1", "s4")], fs("s0", "s4")),
        "d": ([fs("s0", "s1", "s3"), fs("s0", "s1", "s4")], fs("s0", "s1")),
        "e": ([fs("s1", "s3", "s5", "s6"), fs("s1", "s4", "s5", "s6"),
               fs("s2", "s3", "s5", "s6"), fs("s2", "s4", "s5", "s6")], fs("s5", "s6")),
    }
    for event, (minimal_pre, ger) in expected.items():
        item = analysis.by_event[event]
        assert set(item.minimal_pre) == set(minimal_pre), event
        assert item.intersection == ger and item.ger == ger, event
    assert len(analysis.by_event["e"].minimal_pre) == 4
    assert analysis.forward_closure is True
    assert analysis.state_separation is False
    assert [(p.first, p.second) for p in analysis.inseparable] == [("s5", "s6")]
    assert ("e", "s7", "target") in analysis.inseparable[0].reasons
    assert analysis.elementary is False
    synthesis = synthesise(ts, analysis)
    assert synthesis.net is not None and synthesis.isomorphic is False


def test_is_this_a_region():
    ts = parse_transition_system(EXAM_TS)
    yes = check_region(ts, {"s0", "s2", "s3"})
    assert yes.is_region and yes.events["a"] == "exit" and yes.events["e"] == "no cross"
    no = check_region(ts, {"s0", "s1"})
    assert not no.is_region and no.event == "c"
    kinds = {relation for _, _, relation in no.conflict}
    assert kinds == {"exit", "outside"}
    assert "event c" in no.explanation(ts.states)
    assert check_region(ts, set(ts.states)).trivial
    assert check_region(ts, {"s0", "nope"}).unknown == ["nope"]


def test_elementary_synthesis_reproduces_the_transition_system():
    # A diamond: a and b concurrent, two places each.
    diamond = parse_transition_system("s0 -a-> s1; s0 -b-> s2; s1 -b-> s3; s2 -a-> s3")
    result = region_result(diamond)
    assert result.analysis.elementary is True
    assert result.synthesis.isomorphic is True
    net = result.net
    assert len(net.places) == 4 and len(net.transitions) == 2
    assert net.initial_marking.total == 2
    # From a log: concurrency, a choice and a final marking.
    result = region_miner(parse_simple_log("[<a,b,c,d>^3, <a,c,b,d>^2, <a,e,d>]"),
                          representation="set")
    assert result.analysis.elementary is True and result.synthesis.isomorphic is True
    assert result.net.labels() == {"a", "b", "c", "d", "e"}
    # Its traces end in two different states, so there is no one final marking ...
    assert not result.net.final_marking
    # ... but with a horizon of one event they all end in {d}.
    short = region_miner(parse_simple_log("[<a,b,c,d>, <a,c,b,d>]"), horizon=1)
    assert short.ts.final == ["{d}"] and short.net.final_marking
    # The full sequence cannot see that b and c commute: not elementary.
    tree = region_miner(parse_simple_log("[<a,b>, <b,a>]"), representation="sequence")
    assert tree.analysis.elementary is False


def test_synthesis_needs_one_initial_state():
    ts = transition_system_from_log(parse_simple_log("[<a,b>, <c>]"), "postfix", "set")
    result = region_result(ts)
    assert result.net is None
    assert "initial states" in result.warnings[0]


def test_region_search_has_a_limit():
    text = ", ".join(f"s{i} -a{i}-> s{i + 1}" for i in range(30))
    analysis = analyse_regions(parse_transition_system(text))
    assert analysis.truncated and "31 states" in analysis.limit_message
    assert analysis.elementary is None


# ---------------------------------------------------------------------------
# Comparing nets
# ---------------------------------------------------------------------------
def _wf(kind: str, prefix: str = "p", tau: bool = False, label_b: str = "b") -> PetriNet:
    net = PetriNet(kind)
    for place in ["i", "o"] + [f"{prefix}{k}" for k in range(1, 5)]:
        net.add_place(place, id=place)
    net.add_transition("a", id="ta")
    net.add_transition(label_b, id="tb")
    net.add_transition("c", id="tc")
    net.add_transition("d", id="td")
    p = lambda k: f"{prefix}{k}"  # noqa: E731
    net.add_arc("i", "ta")
    if kind == "and":
        for a, b in [("ta", p(1)), ("ta", p(2)), (p(1), "tb"), (p(2), "tc"), ("tb", p(3)),
                     ("tc", p(4)), (p(3), "td"), (p(4), "td")]:
            net.add_arc(a, b)
    else:
        net.remove_place(p(2))
        net.remove_place(p(4))
        for a, b in [("ta", p(1)), (p(1), "tb"), (p(1), "tc"), ("tb", p(3)), ("tc", p(3)),
                     (p(3), "td")]:
            net.add_arc(a, b)
    if tau:
        net.add_place("q", id="q")
        net.add_transition(None, id="tau")
        for a, b in [("td", "q"), ("q", "tau"), ("tau", "o")]:
            net.add_arc(a, b)
    else:
        net.add_arc("td", "o")
    return net


def test_equivalent_nets_drawn_differently_are_equal():
    mine = _wf("and", prefix="x", tau=True, label_b=" B ")
    result = compare_nets(mine, _wf("and"))
    assert result.equivalent and result.exact
    assert not result.only_first and not result.only_second


def test_xor_instead_of_and_is_different_with_an_example():
    result = compare_nets(_wf("xor"), _wf("and"))
    assert not result.equivalent and result.exact
    assert result.only_first == [("a", "b", "d")]           # shortest: yours allows it
    assert result.only_second == [("a", "b", "c", "d")]     # the answer allows it
    assert "Differs" in result.summary()
    path, done = replayable_prefix(_wf("xor"), ("a", "b", "c", "d"))
    assert path == ["ta", "tb"] and done == 2


def test_label_mapping_and_unbounded_nets():
    mine = _wf("and", label_b="register")
    plain = compare_nets(mine, _wf("and"))
    assert not plain.equivalent
    assert plain.labels_only_first == ["register"] and plain.labels_only_second == ["b"]
    assert compare_nets(mine, _wf("and"), mapping={"register": "b"}).equivalent
    # An unbounded net: compared up to a length, and said so.
    pump = PetriNet("pump")
    pump.add_place("p", id="p")
    pump.add_place("q", id="q")
    pump.add_transition("a", id="a")
    pump.add_transition("b", id="b")
    for a, b in [("p", "a"), ("a", "p"), ("a", "q"), ("p", "b")]:
        pump.add_arc(a, b)
    pump.initial_marking = Marking({"p": 1})
    once = PetriNet("once")
    once.add_place("p", id="p")
    once.add_transition("b", id="b")
    once.add_arc("p", "b")
    once.initial_marking = Marking({"p": 1})
    result = compare_nets(pump, once, max_length=5)
    assert not result.exact and result.max_length == 5
    assert result.only_first[0] == ("a", "b")          # the shortest comes first
