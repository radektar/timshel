"""Pure geometry for the insight constellation (Direction B).

A 1:1 port of the inline-SVG generator in
``design-system/pages/insights-engine.js``: nodes (notes), quadratic-bézier arcs
(connections) and a golden bloom (the insight). Kept pure so the coordinates are
unit-testable; the AppKit view (``constellation_view.py``) draws these primitives
in ``NSView.drawRect_`` with Core Graphics.

Base canvas is 300×150; every coordinate is multiplied by ``scale`` so the same
geometry renders mini (popover/thumbnails) or large (the reader, scale ~1.55).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class _LayoutSpec:
    """Base (pre-scale) geometry for one layout, from insights-engine.js `LAY`."""

    nodes: List[Tuple[float, float]]
    arcs: List[Tuple[int, int]]
    bloom: Tuple[float, float]
    split: bool


_LAY: Dict[str, _LayoutSpec] = {
    "contradiction": _LayoutSpec(
        nodes=[(82.0, 86.0), (228.0, 86.0)],
        arcs=[(0, 1)],
        bloom=(155.0, 86.0),
        split=True,
    ),
    "thread": _LayoutSpec(
        nodes=[(110.0, 98.0), (202.0, 98.0)],
        arcs=[(0, 1)],
        bloom=(156.0, 40.0),
        split=False,
    ),
    "triad": _LayoutSpec(
        nodes=[(78.0, 60.0), (226.0, 74.0), (150.0, 124.0)],
        arcs=[(0, 1), (1, 2), (2, 0)],
        bloom=(151.0, 84.0),
        split=False,
    ),
}

#: Multipliers from the SVG spec, applied to the scale.
_NODE_R = 6.4
_NODE_R_DIM = 3.0
_NODE_GLOW = 4.6  # glow radius = node_r * this
_ARC_CTRL_BIAS = 0.34  # arc control point pulled toward the bloom
_SPLIT_SPREAD = 42.0  # contradiction: half-distance the two arcs bow apart
_SPLIT_AXIS_EXT = 16.0  # time-axis overshoot past the nodes
_BLOOM_OUTER = 34.0
_BLOOM_RING = 24.0
_BLOOM_CORE = 5.4
_BLOOM_SPARK = 2.4


@dataclass(frozen=True)
class Node:
    """A note: terracotta core at (x, y), radius r, with a soft glow halo."""

    x: float
    y: float
    r: float
    glow_r: float


@dataclass(frozen=True)
class Arc:
    """A connection: quadratic bézier from (x1, y1) via control (cx, cy)."""

    x1: float
    y1: float
    cx: float
    cy: float
    x2: float
    y2: float


@dataclass(frozen=True)
class Line:
    """A straight segment — the contradiction time-axis or a bloom feed-line."""

    x1: float
    y1: float
    x2: float
    y2: float


@dataclass(frozen=True)
class Bloom:
    """The insight: concentric gold rings + a white spark at (x, y)."""

    x: float
    y: float
    outer_r: float
    ring_r: float
    core_r: float
    spark_r: float


@dataclass(frozen=True)
class ConstellationGeometry:
    """Everything the view draws, already scaled."""

    layout: str
    scale: float
    nodes: List[Node] = field(default_factory=list)
    arcs: List[Arc] = field(default_factory=list)
    bloomlines: List[Line] = field(default_factory=list)
    axis: Optional[Line] = None
    bloom: Optional[Bloom] = None


def has_layout(layout: str) -> bool:
    return layout in _LAY


def build_geometry(
    layout: str, scale: float = 1.0, dim: bool = False
) -> ConstellationGeometry:
    """Scaled primitives for *layout*.

    ``dim`` draws nodes only (smaller, no arcs/bloom) — the quiet empty state.
    Unknown layouts fall back to ``thread``.
    """
    spec = _LAY.get(layout, _LAY["thread"])
    s = scale
    base_nodes = spec.nodes
    bx = spec.bloom[0] * s
    by = spec.bloom[1] * s
    split = spec.split

    nodes: List[Node] = []
    arcs: List[Arc] = []
    bloomlines: List[Line] = []
    axis: Optional[Line] = None
    bloom: Optional[Bloom] = None

    if not dim:
        if split:
            p1, p2 = base_nodes[0], base_nodes[1]
            x1, y1 = p1[0] * s, p1[1] * s
            x2, y2 = p2[0] * s, p2[1] * s
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            spread = _SPLIT_SPREAD * s
            axis = Line(x1 - _SPLIT_AXIS_EXT * s, y1, x2 + _SPLIT_AXIS_EXT * s, y2)
            arcs.append(Arc(x1, y1, mx, my - spread, x2, y2))
            arcs.append(Arc(x1, y1, mx, my + spread, x2, y2))
        else:
            for a, b in spec.arcs:
                p1, p2 = base_nodes[a], base_nodes[b]
                x1, y1 = p1[0] * s, p1[1] * s
                x2, y2 = p2[0] * s, p2[1] * s
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                cx = mx + (bx - mx) * _ARC_CTRL_BIAS
                cy = my + (by - my) * _ARC_CTRL_BIAS
                arcs.append(Arc(x1, y1, cx, cy, x2, y2))
            for p in base_nodes[:2]:
                bloomlines.append(Line(p[0] * s, p[1] * s, bx, by))

    node_r = (_NODE_R_DIM if dim else _NODE_R) * s
    for p in base_nodes:
        nodes.append(Node(p[0] * s, p[1] * s, node_r, node_r * _NODE_GLOW))

    if not dim:
        bloom = Bloom(
            bx, by, _BLOOM_OUTER * s, _BLOOM_RING * s, _BLOOM_CORE * s, _BLOOM_SPARK * s
        )

    return ConstellationGeometry(
        layout=layout if has_layout(layout) else "thread",
        scale=s,
        nodes=nodes,
        arcs=arcs,
        bloomlines=bloomlines,
        axis=axis,
        bloom=bloom,
    )
