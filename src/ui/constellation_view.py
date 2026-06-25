"""Core Graphics view that draws the insight constellation.

The native counterpart of the inline-SVG mock in
``design-system/pages/insights-engine.js``: an ``NSView`` whose ``drawRect_``
paints the nodes (notes), quadratic arcs (connections) and the golden bloom (the
insight) from the pure :mod:`~src.ui.constellation_geometry` primitives.

The geometry is computed on the base 300×150 design canvas and aspect-fit-centred
into the view's bounds (the SVG's ``preserveAspectRatio xMidYMid meet``), so the
same drawing reads correctly mini (thumbnails) or large (the reader).

AppKit-optional: with no AppKit :func:`build_constellation_view` returns ``None``
and the window falls back to an empty box.
"""

from __future__ import annotations

from src.ui import constellation_geometry as cg

try:
    import objc
    from AppKit import (
        NSAffineTransform,
        NSBezierPath,
        NSColor,
        NSColorSpace,
        NSGradient,
        NSGraphicsContext,
        NSShadow,
        NSView,
    )
    from Foundation import NSMakePoint, NSMakeRect, NSMakeSize

    _APPKIT_AVAILABLE = True
except ImportError:  # pragma: no cover - non-mac
    _APPKIT_AVAILABLE = False

#: Base design canvas the geometry is authored against (matches the SVG viewBox).
_BASE_W = 300.0
_BASE_H = 150.0


def _c(r: float, g: float, b: float, a: float = 1.0):
    """NSColor from 0–255 channels (the literal values from the SVG spec)."""
    return NSColor.colorWithRed_green_blue_alpha_(r / 255.0, g / 255.0, b / 255.0, a)


if _APPKIT_AVAILABLE:

    def _oval(cx: float, cy: float, r: float):
        return NSBezierPath.bezierPathWithOvalInRect_(
            NSMakeRect(cx - r, cy - r, 2 * r, 2 * r)
        )

    def _radial(colors_locs, center, radius):
        """Draw a radial gradient (list of (NSColor, location)) into a disc."""
        colors = [c for c, _ in colors_locs]
        locs = [loc for _, loc in colors_locs]
        grad = NSGradient.alloc().initWithColors_atLocations_colorSpace_(
            colors, locs, NSColorSpace.sRGBColorSpace()
        )
        if grad is None:
            return
        grad.drawFromCenter_radius_toCenter_radius_options_(
            center, 0.0, center, radius, 0
        )

    class _ConstellationView(NSView):
        """Draws a constellation; flipped so y grows downward like the SVG."""

        def initWithFrame_layout_dim_(self, frame, layout, dim):
            self = objc.super(_ConstellationView, self).initWithFrame_(frame)
            if self is None:
                return None
            self._layout = layout
            self._dim = bool(dim)
            return self

        def isFlipped(self):
            return True

        @objc.python_method
        def set_layout(self, layout, dim=False):
            self._layout = layout
            self._dim = bool(dim)
            self.setNeedsDisplay_(True)

        def drawRect_(self, _rect):
            bounds = self.bounds()
            geom = cg.build_geometry(self._layout, scale=1.0, dim=self._dim)

            # Aspect-fit-centre the base canvas into the view bounds.
            fit = min(bounds.size.width / _BASE_W, bounds.size.height / _BASE_H)
            off_x = (bounds.size.width - _BASE_W * fit) / 2.0
            off_y = (bounds.size.height - _BASE_H * fit) / 2.0
            xf = NSAffineTransform.transform()
            xf.translateXBy_yBy_(off_x, off_y)
            xf.scaleBy_(fit)
            xf.concat()

            try:
                self._draw_geometry(geom)
            finally:
                # Undo the transform so later drawing is unaffected.
                inv = xf.copy()
                inv.invert()
                inv.concat()

        @objc.python_method
        def _draw_geometry(self, geom):
            # 1. contradiction time-axis (dashed, behind everything)
            if geom.axis is not None:
                axis = NSBezierPath.bezierPath()
                axis.moveToPoint_(NSMakePoint(geom.axis.x1, geom.axis.y1))
                axis.lineToPoint_(NSMakePoint(geom.axis.x2, geom.axis.y2))
                axis.setLineWidth_(1.0)
                axis.setLineDash_count_phase_([2.0, 5.0], 2, 0.0)
                _c(224, 99, 58, 0.28).setStroke()
                axis.stroke()

            # 2. bloom feed-lines
            for ln in geom.bloomlines:
                p = NSBezierPath.bezierPath()
                p.moveToPoint_(NSMakePoint(ln.x1, ln.y1))
                p.lineToPoint_(NSMakePoint(ln.x2, ln.y2))
                p.setLineWidth_(1.1)
                _c(214, 176, 51, 0.5).setStroke()
                p.stroke()

            # 3. connection arcs (quadratic bézier + terracotta glow)
            for arc in geom.arcs:
                path = NSBezierPath.bezierPath()
                path.moveToPoint_(NSMakePoint(arc.x1, arc.y1))
                # quadratic → cubic control points
                c1x = arc.x1 + 2.0 / 3.0 * (arc.cx - arc.x1)
                c1y = arc.y1 + 2.0 / 3.0 * (arc.cy - arc.y1)
                c2x = arc.x2 + 2.0 / 3.0 * (arc.cx - arc.x2)
                c2y = arc.y2 + 2.0 / 3.0 * (arc.cy - arc.y2)
                path.curveToPoint_controlPoint1_controlPoint2_(
                    NSMakePoint(arc.x2, arc.y2),
                    NSMakePoint(c1x, c1y),
                    NSMakePoint(c2x, c2y),
                )
                path.setLineWidth_(1.8)
                path.setLineCapStyle_(1)  # round
                shadow = NSShadow.alloc().init()
                shadow.setShadowColor_(_c(194, 64, 16, 0.6))
                shadow.setShadowBlurRadius_(2.4)
                shadow.setShadowOffset_(NSMakeSize(0, 0))
                NSGraphicsContext.saveGraphicsState()
                shadow.set()
                _c(217, 84, 42, 0.92).setStroke()
                path.stroke()
                NSGraphicsContext.restoreGraphicsState()

            # 4. nodes (glow halo → ring → core → light centre)
            for n in geom.nodes:
                _radial(
                    [
                        (_c(217, 84, 42, 0.55), 0.0),
                        (_c(194, 64, 16, 0.20), 0.5),
                        (_c(194, 64, 16, 0.0), 1.0),
                    ],
                    NSMakePoint(n.x, n.y),
                    n.glow_r,
                )
                ring = _oval(n.x, n.y, n.r + 3.6 * geom.scale)
                ring.setLineWidth_(1.0)
                _c(217, 84, 42, 0.5).setStroke()
                ring.stroke()
                _c(194, 64, 16, 1.0).setFill()
                _oval(n.x, n.y, n.r).fill()
                _c(250, 243, 226, 1.0).setFill()
                _oval(n.x, n.y, n.r * 0.42).fill()

            # 5. bloom (the insight)
            b = geom.bloom
            if b is not None:
                _radial(
                    [
                        (_c(244, 221, 142, 0.92), 0.0),
                        (_c(214, 176, 51, 0.30), 0.5),
                        (_c(214, 176, 51, 0.0), 1.0),
                    ],
                    NSMakePoint(b.x, b.y),
                    b.outer_r,
                )
                inner_ring = _oval(b.x, b.y, b.ring_r)
                inner_ring.setLineWidth_(1.2)
                _c(214, 176, 51, 0.5).setStroke()
                inner_ring.stroke()
                outer_ring = _oval(b.x, b.y, b.outer_r)
                outer_ring.setLineWidth_(1.0)
                _c(214, 176, 51, 0.22).setStroke()
                outer_ring.stroke()
                _c(244, 221, 142, 1.0).setFill()
                _oval(b.x, b.y, b.core_r).fill()
                _c(255, 251, 240, 1.0).setFill()
                _oval(b.x, b.y, b.spark_r).fill()


def build_constellation_view(frame, layout: str, dim: bool = False):
    """Create a constellation view for *layout*, or ``None`` without AppKit.

    *frame* is an ``NSRect``; *layout* is one of ``contradiction`` / ``thread`` /
    ``triad`` (unknown values fall back to ``thread``). *dim* draws the quiet
    nodes-only empty state.
    """
    if not _APPKIT_AVAILABLE:
        return None
    return _ConstellationView.alloc().initWithFrame_layout_dim_(frame, layout, dim)
