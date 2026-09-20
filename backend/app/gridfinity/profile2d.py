"""2D contour helpers: rounded rectangles, resampling and lofting.

The bin builder needs exact 45 degree chamfers, which rules out approximating a
taper with a stack of extruded slabs. Instead every tapered surface is built as
a loft between rings that carry an explicit vertex correspondence. Rounded
rectangles offset to rounded rectangles, so their rings correspond naturally;
arbitrary cutout outlines are resampled by arc length to a common vertex count.
"""

from __future__ import annotations

import math

import numpy as np
from manifold3d import CrossSection, FillRule, JoinType, Manifold, Mesh

Ring = np.ndarray  # (N, 2) float64


def rounded_rect(width: float, depth: float, radius: float,
                 corner_segments: int = 12) -> Ring:
    """A counter-clockwise rounded rectangle centred on the origin.

    ``radius`` is clamped to what fits; a radius of zero yields a sharp corner
    but still emits ``corner_segments`` coincident-ish points so that rings
    built with different radii stay correspondent for lofting.
    """
    radius = max(0.0, min(radius, width / 2.0, depth / 2.0))
    hx = width / 2.0 - radius
    hy = depth / 2.0 - radius
    n = max(1, corner_segments)

    pts: list[tuple[float, float]] = []
    # corner centres, counter-clockwise starting bottom-right
    corners = ((hx, -hy, -90.0), (hx, hy, 0.0), (-hx, hy, 90.0), (-hx, -hy, 180.0))
    for cx, cy, start in corners:
        for i in range(n + 1):
            a = math.radians(start + 90.0 * i / n)
            pts.append((cx + radius * math.cos(a), cy + radius * math.sin(a)))
    return np.asarray(pts, dtype=np.float64)


def ring_length(ring: Ring) -> np.ndarray:
    """Cumulative arc length of a closed ring, starting at 0."""
    closed = np.vstack([ring, ring[:1]])
    seg = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    return np.concatenate([[0.0], np.cumsum(seg)])


def resample_ring(ring: Ring, count: int) -> Ring:
    """Resample a closed ring to ``count`` evenly arc-spaced points.

    The start point is preserved as closely as possible by always beginning at
    arc length zero, which keeps successive offsets of the same outline in
    correspondence.
    """
    if len(ring) < 3:
        raise ValueError("ring needs at least 3 points")
    cum = ring_length(ring)
    total = cum[-1]
    if total <= 0:
        raise ValueError("degenerate ring")
    targets = np.linspace(0.0, total, count, endpoint=False)
    closed = np.vstack([ring, ring[:1]])
    x = np.interp(targets, cum, closed[:, 0])
    y = np.interp(targets, cum, closed[:, 1])
    return np.column_stack([x, y])


def normalise_orientation(ring: Ring) -> Ring:
    """Return the ring wound counter-clockwise."""
    area = 0.5 * np.sum(
        ring[:, 0] * np.roll(ring[:, 1], -1) - np.roll(ring[:, 0], -1) * ring[:, 1]
    )
    return ring if area >= 0 else ring[::-1].copy()


def align_ring(ring: Ring, reference: Ring) -> Ring:
    """Rotate ``ring``'s index origin so it best matches ``reference``.

    Both rings must already have the same length. Offsetting can shift where
    arc length zero lands; without this the loft would spiral.
    """
    n = len(ring)
    best, best_cost = 0, float("inf")
    # a coarse scan is enough: rings are dense and the shift is small
    step = max(1, n // 64)
    for shift in range(0, n, step):
        cost = float(np.sum((np.roll(ring, -shift, axis=0) - reference) ** 2))
        if cost < best_cost:
            best, best_cost = shift, cost
    lo = max(0, best - step)
    for shift in range(lo, min(n, best + step + 1)):
        cost = float(np.sum((np.roll(ring, -shift, axis=0) - reference) ** 2))
        if cost < best_cost:
            best, best_cost = shift, cost
    return np.roll(ring, -best, axis=0)


def loft(rings: list[tuple[float, Ring]]) -> Manifold:
    """Build a closed solid through a bottom-to-top stack of correspondent rings.

    Every ring must have the same vertex count and be wound counter-clockwise.
    The bottom and top are capped with a fan triangulation of their ring, which
    is valid because all rings used here are convex or near-convex; non-convex
    caps go through ``loft_cross_sections`` instead.
    """
    if len(rings) < 2:
        raise ValueError("need at least two rings")
    n = len(rings[0][1])
    if any(len(r) != n for _, r in rings):
        raise ValueError("rings must share a vertex count")

    verts: list[tuple[float, float, float]] = []
    for z, ring in rings:
        verts.extend((float(px), float(py), float(z)) for px, py in ring)

    tris: list[tuple[int, int, int]] = []
    for level in range(len(rings) - 1):
        a0 = level * n
        b0 = (level + 1) * n
        for i in range(n):
            j = (i + 1) % n
            tris.append((a0 + i, a0 + j, b0 + j))
            tris.append((a0 + i, b0 + j, b0 + i))

    # bottom cap (clockwise seen from below => reversed fan)
    for i in range(1, n - 1):
        tris.append((0, i + 1, i))
    top0 = (len(rings) - 1) * n
    for i in range(1, n - 1):
        tris.append((top0, top0 + i, top0 + i + 1))

    mesh = Mesh(
        np.asarray(verts, dtype=np.float32),
        np.asarray(tris, dtype=np.uint32),
    )
    return Manifold(mesh)


def cross_section(outline: Ring, holes: list[Ring] | None = None) -> CrossSection:
    contours = [np.asarray(outline, dtype=np.float64)]
    for h in holes or []:
        contours.append(np.asarray(h, dtype=np.float64)[::-1])
    return CrossSection(contours, FillRule.EvenOdd)


def offset_section(section: CrossSection, delta: float,
                   join: JoinType = JoinType.Round,
                   segments: int = 24) -> CrossSection:
    if abs(delta) < 1e-9:
        return section
    return section.offset(delta, join, 2.0, segments)


def round_corners(section: CrossSection, radius: float,
                  segments: int = 24) -> CrossSection:
    """Classic open-then-close rounding of convex and concave corners alike."""
    if radius <= 1e-6:
        return section
    grown = section.offset(radius, JoinType.Round, 2.0, segments)
    return grown.offset(-radius, JoinType.Round, 2.0, segments)


def outer_ring(section: CrossSection) -> Ring | None:
    """The largest contour of a cross-section, counter-clockwise."""
    polys = section.to_polygons()
    if not polys:
        return None
    best = max(polys, key=lambda p: abs(_signed_area(np.asarray(p))))
    return normalise_orientation(np.asarray(best, dtype=np.float64))


def _signed_area(ring: Ring) -> float:
    return 0.5 * float(
        np.sum(ring[:, 0] * np.roll(ring[:, 1], -1)
               - np.roll(ring[:, 0], -1) * ring[:, 1])
    )


def section_area(section: CrossSection) -> float:
    return float(section.area())
