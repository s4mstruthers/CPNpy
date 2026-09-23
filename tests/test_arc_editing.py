"""CPN IDE's arc-editing rules (cpnpy.gui.arc_editing), without a window."""

from cpnpy.gui import arc_editing as edit

T_RECT = (-40.0, -20.0, 80.0, 40.0)          # a transition at (0, 0)
P_RECT = (160.0, -20.0, 80.0, 40.0)          # a place at (200, 0)


def test_hit_test_classifies_presses():
    route = [(40.0, 0.0), (100.0, 0.0), (100.0, 80.0), (160.0, 80.0)]
    assert edit.hit_test(route, (103.0, 4.0))[:2] == ("bend", 1)        # on a bend
    assert edit.hit_test(route, (38.0, 2.0))[:2] == ("bend", 0)         # an end
    assert edit.hit_test(route, (101.0, 40.0))[:2] == ("segment", 2)    # middle of |
    assert edit.hit_test(route, (101.0, 22.0))[:2] == ("insert", 2)     # elsewhere on |
    assert edit.hit_test(route, (60.0, 30.0)) is None                   # off the arc


def test_dragged_bend_snaps_and_straight_bends_vanish():
    # Snaps level with the left neighbour, in line with the right one.
    assert edit.snap_bend((97.0, 7.0), [(40.0, 0.0), (100.0, 80.0)]) == (100.0, 0.0)
    # A bend dragged (almost) into line with its neighbours is removed.
    assert edit.without_redundant([(0.0, 0.0), (50.0, 3.0), (100.0, 0.0)]) == \
        [(0.0, 0.0), (100.0, 0.0)]
    assert edit.without_redundant([(0.0, 0.0), (50.0, 30.0), (100.0, 0.0)]) == \
        [(0.0, 0.0), (50.0, 30.0), (100.0, 0.0)]


def test_sliding_a_straight_arc_out_of_its_nodes_makes_an_s_bend():
    route = [(40.0, 0.0), (160.0, 0.0)]          # straight across, no bends
    moved = edit.move_segment(route, 1, 60.0, ((0.0, 0.0), T_RECT),
                              ((200.0, 0.0), P_RECT), snap_to=False)
    assert moved[1:-1] == [(0.0, 60.0), (200.0, 60.0)]
    # A small slide stays inside both nodes: no bends needed.
    moved = edit.move_segment(route, 1, 10.0, ((0.0, 0.0), T_RECT),
                              ((200.0, 0.0), P_RECT), snap_to=False)
    assert moved[1:-1] == []


def test_moving_a_node_keeps_right_angles_and_drops_covered_bends():
    # Transition end, bend level with it, bend, place end.
    points = [(40.0, 0.0), (100.0, 0.0), (100.0, 80.0), (200.0, 80.0)]
    moved = edit.repair_after_move(points, (40.0, 30.0), (-40.0, 10.0, 80.0, 40.0), P_RECT)
    assert moved[1] == (100.0, 30.0)                 # still level with the end
    assert moved[2] == (100.0, 80.0)                 # the rest stays put
    # Moving the node on top of the first bend drops it.
    moved = edit.repair_after_move(points, (100.0, 0.0), (60.0, -20.0, 80.0, 40.0), P_RECT)
    assert (100.0, 0.0) not in moved[1:-1]


def test_node_snapping_and_corner_bends():
    assert edit.snap_node((103.0, 45.0), [(100.0, 0.0), (0.0, 200.0)]) == (100.0, None)
    route = [(0.0, 0.0), (100.0, 0.0), (150.0, 60.0), (200.0, 90.0)]
    assert edit.corner_bends(route) == [(100.0, 0.0)]
