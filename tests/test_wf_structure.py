"""The WF-net checks of van der Aalst, *Workflow Verification*, on the paper's own figures."""

from cpnpy.mining.analysis import check_short_circuited, check_soundness, check_workflow_net
from cpnpy.mining.petrinet import PetriNet
from cpnpy.mining.structure import check_structure, handles


def _net(arcs, name="net"):
    net = PetriNet(name)
    nodes = {}
    for source, target in arcs:
        for label in (source, target):
            if label not in nodes:
                is_place = label[0] in "ico" and (label in ("i", "o") or label[1:].isdigit())
                nodes[label] = net.add_place(label, id=label) if is_place else \
                    net.add_transition(label, id=label)
        net.add_arc(nodes[source], nodes[target])
    return net


def figure_3():
    """Fig. 3: unsound, free-choice, not well-handled, not S-coverable."""
    return _net([("i", "register"), ("register", "c1"), ("register", "c2"),
                 ("c1", "time_out_1"), ("c1", "processing_1"), ("c2", "time_out_2"),
                 ("c2", "processing_2"), ("time_out_1", "c3"), ("time_out_2", "c3"),
                 ("processing_1", "c4"), ("processing_2", "c5"), ("c3", "processing_NOK"),
                 ("c4", "processing_OK"), ("c5", "processing_OK"), ("processing_NOK", "o"),
                 ("processing_OK", "o")], "Figure 3")


def figure_4():
    """Fig. 4: parallelism mixed with choice -- sound, not free-choice, S-coverable."""
    return _net([("i", "t1"), ("t1", "c1"), ("t1", "c2"), ("c1", "t2"), ("t2", "c3"),
                 ("c2", "t3"), ("t3", "c4"), ("c3", "t4"), ("c4", "t4"), ("t4", "o"),
                 ("c1", "t5"), ("c4", "t5"), ("t5", "o")], "Figure 4")


def test_figure_3_is_unsound_free_choice_not_s_coverable():
    net = figure_3()
    workflow = check_workflow_net(net)
    report = check_soundness(net)
    assert report.sound is False
    # Theorem 1 agrees: N̄ is not live and bounded (tokens pile up in o).
    assert report.short_circuit.sound is False
    structure = check_structure(net, workflow.source, workflow.sink)
    assert structure.is_free_choice
    assert structure.well_structured is False
    assert structure.s_coverable is False
    # "the AND-split register is complemented by the OR-join c3 or o"
    kinds = {(h.kind, h.start) for h in structure.handles}
    assert ("TP", "t:register") in kinds


def test_figure_4_is_sound_but_not_free_choice():
    net = figure_4()
    workflow = check_workflow_net(net)
    report = check_soundness(net)
    assert report.sound is True
    assert report.short_circuit.live and report.short_circuit.bounded
    structure = check_structure(net, workflow.source, workflow.sink)
    assert not structure.is_free_choice
    # t5 shares c1 with t2 and c4 with t4, but needs both
    assert {frozenset(v[:2]) for v in structure.free_choice} == {
        frozenset({"t2", "t5"}), frozenset({"t4", "t5"})}
    assert structure.s_coverable is True
    assert report.short_circuit.safe


def test_theorem_1_matches_definition_12_on_a_deadlock():
    """Bounded but not live: a choice at i where both branches get stuck."""
    net = _net([("i", "a"), ("a", "c1"), ("i", "b"), ("b", "c2"),
                ("c1", "d"), ("c2", "d"), ("d", "o")])
    workflow = check_workflow_net(net)
    closed = check_short_circuited(net, workflow.source, workflow.sink)
    assert closed.bounded and closed.live is False and not closed.deadlock_free
    assert closed.sound is check_soundness(net).sound is False
    assert "d" in closed.not_live and "t_star" in closed.not_live
    # d can never fire, not even from [i]: the witness is the initial marking
    assert closed.properties.graph.path_to(closed.not_live["d"]) == []


def test_sequence_is_well_structured_and_handles_need_two_disjoint_paths():
    net = _net([("i", "a"), ("a", "c1"), ("c1", "b"), ("b", "o")])
    workflow = check_workflow_net(net)
    structure = check_structure(net, workflow.source, workflow.sink)
    assert structure.is_free_choice and structure.well_structured and structure.s_coverable
    assert structure.state_machine
    # An AND-split joined by an AND-join is fine, joined by an OR-join is a TP-handle.
    good = _net([("i", "a"), ("a", "c1"), ("a", "c2"), ("c1", "b"), ("c2", "b"),
                 ("b", "o")])
    assert handles(good) == []
    bad = _net([("i", "a"), ("a", "c1"), ("a", "c2"), ("c1", "b"), ("c2", "c"),
                ("b", "c3"), ("c", "c3"), ("c3", "d"), ("d", "o")])
    found = handles(bad)
    assert found and found[0].kind == "TP" and found[0].start == "t:a" \
        and found[0].end == "p:c3"
    assert check_soundness(bad).sound is False


def test_lemma_4_flags_a_transition_that_needs_i_and_another_place():
    net = _net([("i", "a"), ("a", "c1"), ("c1", "b"), ("i", "b"), ("b", "o")])
    workflow = check_workflow_net(net)
    assert check_structure(net, workflow.source, workflow.sink).lemma4 == ["b"]
