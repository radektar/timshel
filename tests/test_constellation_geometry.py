"""Tests for the pure constellation geometry (src/ui/constellation_geometry.py)."""

from __future__ import annotations

import math

from src.ui import constellation_geometry as cg


def test_thread_layout_two_nodes_one_arc_bloom():
    g = cg.build_geometry("thread", scale=1.0)
    assert len(g.nodes) == 2
    assert len(g.arcs) == 1
    assert g.bloom is not None
    assert g.axis is None  # thread is not a split layout
    # two bloom feed-lines (from the first two nodes)
    assert len(g.bloomlines) == 2


def test_triad_layout_three_nodes_three_arcs():
    g = cg.build_geometry("triad", scale=1.0)
    assert len(g.nodes) == 3
    assert len(g.arcs) == 3
    assert g.bloom is not None


def test_contradiction_is_split_with_axis_and_two_arcs():
    g = cg.build_geometry("contradiction", scale=1.0)
    assert len(g.nodes) == 2
    assert g.axis is not None
    assert len(g.arcs) == 2  # two arcs bowing apart
    assert len(g.bloomlines) == 0  # split layout has no feed-lines
    # the two arcs bow symmetrically above/below the midline
    a_above, a_below = g.arcs
    mid_y = (g.nodes[0].y + g.nodes[1].y) / 2
    assert a_above.cy < mid_y < a_below.cy


def test_scale_multiplies_all_coordinates():
    g1 = cg.build_geometry("triad", scale=1.0)
    g2 = cg.build_geometry("triad", scale=2.0)
    for n1, n2 in zip(g1.nodes, g2.nodes):
        assert math.isclose(n2.x, n1.x * 2)
        assert math.isclose(n2.y, n1.y * 2)
        assert math.isclose(n2.r, n1.r * 2)
        assert math.isclose(n2.glow_r, n1.glow_r * 2)
    assert g2.bloom is not None and g1.bloom is not None
    assert math.isclose(g2.bloom.outer_r, g1.bloom.outer_r * 2)


def test_node_glow_is_proportional_to_radius():
    g = cg.build_geometry("thread", scale=1.0)
    for n in g.nodes:
        assert math.isclose(n.glow_r, n.r * cg._NODE_GLOW)


def test_dim_mode_draws_nodes_only():
    g = cg.build_geometry("triad", scale=1.0, dim=True)
    assert len(g.nodes) == 3
    assert g.arcs == []
    assert g.bloomlines == []
    assert g.bloom is None
    assert g.axis is None
    # dimmed nodes are smaller than full ones
    full = cg.build_geometry("triad", scale=1.0)
    assert g.nodes[0].r < full.nodes[0].r


def test_unknown_layout_falls_back_to_thread():
    g = cg.build_geometry("nonsense", scale=1.0)
    assert g.layout == "thread"
    assert len(g.nodes) == 2


def test_arc_control_biased_toward_bloom():
    # For thread, the bloom sits above the nodes; the arc control point should be
    # pulled from the chord midpoint toward the bloom (i.e. above the nodes).
    g = cg.build_geometry("thread", scale=1.0)
    arc = g.arcs[0]
    chord_mid_y = (arc.y1 + arc.y2) / 2
    assert g.bloom is not None
    # bloom is above (smaller y); control y should be between chord and bloom
    assert g.bloom.y < arc.cy < chord_mid_y
