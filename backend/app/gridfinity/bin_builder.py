"""Builds the Gridfinity bin solid (without cutouts)."""

from __future__ import annotations

import math

import numpy as np
from manifold3d import Manifold, OpType

from . import spec as S
from .profile2d import loft, rounded_rect


def _stage_rings(stages, cell: float, radius: float, top_inset: float,
                 segments: int, z0: float = 0.0) -> list[tuple[float, np.ndarray]]:
    """Turn a (rise, inset) stage list into a bottom-to-top ring stack."""
    rings: list[tuple[float, np.ndarray]] = []
    z = z0
    insets = [inset for _, inset in stages] + [top_inset]
    for i, (rise, inset) in enumerate(stages):
        rings.append((z, rounded_rect(cell - 2 * inset, cell - 2 * inset,
                                      radius - inset, segments)))
        z += rise
        nxt = insets[i + 1]
        if abs(nxt - inset) < 1e-9:
            continue
    # emit every boundary explicitly so vertical stages keep their sharp edges
    rings = []
    z = z0
    for i, (rise, inset) in enumerate(stages):
        rings.append((z, rounded_rect(cell - 2 * inset, cell - 2 * inset,
                                      radius - inset, segments)))
        z += rise
        nxt = insets[i + 1]
        rings.append((z, rounded_rect(cell - 2 * nxt, cell - 2 * nxt,
                                      radius - nxt, segments)))
    # collapse duplicate consecutive z levels that carry identical rings
    cleaned: list[tuple[float, np.ndarray]] = []
    for z_, ring in rings:
        if cleaned and abs(cleaned[-1][0] - z_) < 1e-9 and \
                np.allclose(cleaned[-1][1], ring):
            continue
        cleaned.append((z_, ring))
    return cleaned


def build_foot(binspec: S.BinSpec) -> Manifold:
    """One base foot, origin at the centre of its grid cell, bottom at z=0."""
    rings = _stage_rings(
        S.BASE_STAGES,
        cell=binspec.cell_size,
        radius=S.OUTER_RADIUS,
        top_inset=0.0,
        segments=binspec.corner_segments,
    )
    return loft(rings)


def build_base(binspec: S.BinSpec) -> Manifold:
    """All feet of the bin, unioned, bottom at z=0."""
    foot = build_foot(binspec)
    pitch = binspec.grid_pitch
    ox = (binspec.grid_x - 1) * pitch / 2.0
    oy = (binspec.grid_y - 1) * pitch / 2.0
    parts = [
        foot.translate((ix * pitch - ox, iy * pitch - oy, 0.0))
        for ix in range(binspec.grid_x)
        for iy in range(binspec.grid_y)
    ]
    return Manifold.batch_boolean(parts, OpType.Add) if len(parts) > 1 else parts[0]


def _outer_prism(binspec: S.BinSpec, z0: float, z1: float,
                 inset: float = 0.0) -> Manifold:
    ring = rounded_rect(
        binspec.outer_width - 2 * inset,
        binspec.outer_depth - 2 * inset,
        S.OUTER_RADIUS - inset,
        binspec.corner_segments,
    )
    return loft([(z0, ring), (z1, ring)])


def build_lip_cavity(binspec: S.BinSpec) -> Manifold | None:
    """The volume carved out of the top rim to form the stacking lip.

    The lip runs once around the bin's outside, not once per grid cell: a
    multi-cell bin accepts a bin of the same footprint, and anything smaller
    simply rests on the flat interior. Building it per cell and filling the gaps
    with a straight prism left a notch at every cell boundary, because the
    sockets flare outwards with height while the filler did not.
    """
    if binspec.lip_height <= 0:
        return None

    c = S.LIP_CLEARANCE
    top_inset = S.LIP_TOP_INSET - c
    if binspec.lip_style == "reduced" and binspec.lip_top_rim > top_inset:
        top_inset = binspec.lip_top_rim

    rings: list[tuple[float, np.ndarray]] = []
    z = binspec.body_top
    stages = [(rise, inset - c) for rise, inset in S.LIP_STAGES]
    insets = [inset for _, inset in stages] + [top_inset]

    for i, (rise, inset) in enumerate(stages):
        rings.append((z, _footprint(binspec, inset)))
        z += rise
        rings.append((z, _footprint(binspec, insets[i + 1])))

    # run past the top face so the boolean has something to cut through
    rings.append((binspec.total_height + 0.01, rings[-1][1]))

    cleaned: list[tuple[float, np.ndarray]] = []
    for level, ring in rings:
        if cleaned and abs(cleaned[-1][0] - level) < 1e-9 and \
                np.allclose(cleaned[-1][1], ring):
            continue
        cleaned.append((level, ring))
    return loft(cleaned)


def _footprint(binspec: S.BinSpec, inset: float) -> np.ndarray:
    return rounded_rect(
        binspec.outer_width - 2 * inset,
        binspec.outer_depth - 2 * inset,
        S.OUTER_RADIUS - inset,
        binspec.corner_segments,
    )


def _lip_support_z0(binspec: S.BinSpec) -> float:
    seat_inset = S.BASE_MAX_INSET - S.LIP_CLEARANCE
    ledge = seat_inset - binspec.wall_thickness
    return max(binspec.inner_floor_z, binspec.body_top - ledge)


def build_lip_support(binspec: S.BinSpec) -> Manifold | None:
    """A 45 deg chamfer bridging the cavity wall up to the lip's seat.

    Without it the seat is an unsupported horizontal ring hanging over the
    cavity; with it the transition prints as a self-supporting overhang.
    """
    if binspec.lip_height <= 0 or binspec.solid or not binspec.lip_support:
        return None
    seat_inset = S.BASE_MAX_INSET - S.LIP_CLEARANCE
    ledge = seat_inset - binspec.wall_thickness
    if ledge <= 0.05:
        return None
    z1 = binspec.body_top
    z0 = _lip_support_z0(binspec)
    if z1 - z0 <= 0.05:
        return None
    lower = rounded_rect(
        binspec.outer_width - 2 * binspec.wall_thickness,
        binspec.outer_depth - 2 * binspec.wall_thickness,
        S.OUTER_RADIUS - binspec.wall_thickness, binspec.corner_segments)
    upper = rounded_rect(
        binspec.outer_width - 2 * seat_inset,
        binspec.outer_depth - 2 * seat_inset,
        S.OUTER_RADIUS - seat_inset, binspec.corner_segments)
    return loft([(z0, lower), (z1, upper)])


def build_holes(binspec: S.BinSpec) -> Manifold | None:
    """Magnet and screw holes in the underside of each foot."""
    if not (binspec.magnet_holes or binspec.screw_holes):
        return None
    pitch = binspec.grid_pitch
    ox = (binspec.grid_x - 1) * pitch / 2.0
    oy = (binspec.grid_y - 1) * pitch / 2.0
    parts: list[Manifold] = []
    for ix in range(binspec.grid_x):
        for iy in range(binspec.grid_y):
            cx = ix * pitch - ox
            cy = iy * pitch - oy
            for sx in (-1, 1):
                for sy in (-1, 1):
                    hx = cx + sx * S.HOLE_OFFSET
                    hy = cy + sy * S.HOLE_OFFSET
                    if binspec.magnet_holes:
                        parts.append(
                            Manifold.cylinder(binspec.magnet_depth + 0.01,
                                              binspec.magnet_diameter / 2.0,
                                              -1.0, 48)
                            .translate((hx, hy, -0.01))
                        )
                    if binspec.screw_holes:
                        parts.append(
                            Manifold.cylinder(binspec.screw_depth + 0.01,
                                              binspec.screw_diameter / 2.0,
                                              -1.0, 32)
                            .translate((hx, hy, -0.01))
                        )
    if not parts:
        return None
    return Manifold.batch_boolean(parts, OpType.Add)


def build_label_tab(binspec: S.BinSpec) -> Manifold | None:
    """A sloped overhang along the back edge for a printed label."""
    if not binspec.label_tab:
        return None
    width = binspec.label_tab_width
    angle = math.radians(max(5.0, min(80.0, binspec.label_tab_angle)))
    drop = width * math.tan(angle)
    top = binspec.body_top
    y_back = binspec.outer_depth / 2.0 - binspec.wall_thickness
    y_front = y_back - width
    x_half = binspec.outer_width / 2.0 - binspec.wall_thickness

    verts = np.array([
        (-x_half, y_front, top - drop), (x_half, y_front, top - drop),
        (x_half, y_back, top), (-x_half, y_back, top),
        (-x_half, y_back, top - drop), (x_half, y_back, top - drop),
    ], dtype=np.float32)
    tris = np.array([
        (0, 1, 2), (0, 2, 3),        # sloped face
        (0, 4, 5), (0, 5, 1),        # bottom
        (4, 3, 2), (4, 2, 5),        # back
        (0, 3, 4), (1, 5, 2),        # ends
    ], dtype=np.uint32)
    from manifold3d import Mesh
    return Manifold(Mesh(verts, tris))


def build_bin(binspec: S.BinSpec) -> Manifold:
    """The complete bin solid, foot bottom sitting on z=0."""
    solid = build_base(binspec)
    body = _outer_prism(binspec, S.BASE_HEIGHT - 0.01, binspec.total_height)
    solid = Manifold.batch_boolean([solid, body], OpType.Add)

    subtract: list[Manifold] = []

    if not binspec.solid:
        # The cavity stops at the rim. Above it the wall thickens inward to form
        # the lip's seat, which is what actually stops a stacked bin's foot.
        cavity_top = binspec.body_top if binspec.lip_height > 0 \
            else binspec.total_height + 0.01
        # The taper, when present, replaces the top of the straight cavity.
        support = build_lip_support(binspec)
        if support is not None:
            cavity_top = min(cavity_top, _lip_support_z0(binspec))
        cavity = _outer_prism(binspec, binspec.inner_floor_z, cavity_top + 0.05,
                              inset=binspec.wall_thickness)
        subtract.append(cavity)
        if support is not None:
            subtract.append(support)

    lip = build_lip_cavity(binspec)
    if lip is not None:
        subtract.append(lip)

    holes = build_holes(binspec)
    if holes is not None:
        subtract.append(holes)

    if subtract:
        solid = Manifold.batch_boolean([solid] + subtract, OpType.Subtract)

    tab = build_label_tab(binspec)
    if tab is not None:
        solid = Manifold.batch_boolean([solid, tab], OpType.Add)

    return solid
