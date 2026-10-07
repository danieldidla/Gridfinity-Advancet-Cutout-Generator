"""Builds the negative solids that get subtracted from a bin."""

from __future__ import annotations

import math
from collections import OrderedDict
from pathlib import Path

import numpy as np
from manifold3d import CrossSection, JoinType, Manifold, Mesh, OpType

from . import spec as S
from .profile2d import (align_ring, cross_section, loft, normalise_orientation,
                        outer_ring, resample_ring, round_corners)

_MIN_SAMPLES = 128
_MAX_SAMPLES = 2048
_TARGET_SPACING = 0.15   # mm between loft samples


def _perimeter(ring: np.ndarray) -> float:
    closed = np.vstack([ring, ring[:1]])
    return float(np.sum(np.linalg.norm(np.diff(closed, axis=0), axis=1)))


def _sample_count(ring: np.ndarray) -> int:
    n = int(_perimeter(ring) / _TARGET_SPACING)
    return max(_MIN_SAMPLES, min(_MAX_SAMPLES, n))


def _bottom_fillet_delta(z: float, radius: float) -> float:
    """Inward offset of the wall at height ``z`` above the pocket floor."""
    if radius <= 0 or z >= radius:
        return 0.0
    dz = radius - z
    return -(radius - math.sqrt(max(0.0, radius * radius - dz * dz)))


def _level_offsets(cut: S.CutoutSpec, depth: float) -> list[tuple[float, float]]:
    """(height above pocket floor, in-plane offset) pairs, bottom to top."""
    draft = math.tan(math.radians(max(0.0, min(60.0, cut.draft_angle))))
    r = max(0.0, min(cut.bottom_radius, depth / 2.0))

    levels: list[tuple[float, float]] = []
    if r > 0:
        steps = max(3, int(math.ceil(r / 0.25)) + 2)
        for i in range(steps):
            z = r * i / (steps - 1)
            levels.append((z, _bottom_fillet_delta(z, r) + z * draft))
    else:
        levels.append((0.0, 0.0))
    if levels[-1][0] < depth:
        levels.append((depth, depth * draft))
    return levels


def _straight(section: CrossSection, z0: float, z1: float) -> Manifold:
    return section.extrude(z1 - z0).translate((0.0, 0.0, z0))


def _lofted(section: CrossSection, levels: list[tuple[float, float]],
            z_floor: float) -> Manifold:
    """Loft a pocket whose cross-section changes with height.

    Offsetting an outline breaks any vertex correspondence, so every level is
    resampled to a common count by arc length and re-indexed against the level
    below it.
    """
    base_ring = outer_ring(section)
    if base_ring is None:
        return Manifold()
    n = _sample_count(base_ring)

    rings: list[tuple[float, np.ndarray]] = []
    previous: np.ndarray | None = None
    for dz, delta in levels:
        lvl = section if abs(delta) < 1e-9 else section.offset(
            delta, JoinType.Round, 2.0, 32)
        ring = outer_ring(lvl)
        if ring is None:
            continue
        ring = resample_ring(ring, n)
        if previous is not None:
            ring = align_ring(ring, previous)
        previous = ring
        rings.append((z_floor + dz, ring))

    if len(rings) < 2:
        return Manifold()

    solid = loft(rings)

    # holes are lofted the same way and taken back out
    inner = [np.asarray(p, dtype=np.float64) for p in section.to_polygons()]
    if len(inner) > 1:
        base_area = abs(_area(outer_ring(section)))
        for poly in inner:
            if abs(abs(_area(poly)) - base_area) < 1e-6:
                continue
            hole_sec = CrossSection([normalise_orientation(poly)])
            hole_rings: list[tuple[float, np.ndarray]] = []
            prev: np.ndarray | None = None
            hn = _sample_count(normalise_orientation(poly))
            for dz, delta in levels:
                lvl = hole_sec if abs(delta) < 1e-9 else hole_sec.offset(
                    -delta, JoinType.Round, 2.0, 32)
                r_ = outer_ring(lvl)
                if r_ is None:
                    continue
                r_ = resample_ring(r_, hn)
                if prev is not None:
                    r_ = align_ring(r_, prev)
                prev = r_
                hole_rings.append((z_floor + dz, r_))
            if len(hole_rings) >= 2:
                solid = Manifold.batch_boolean([solid, loft(hole_rings)], OpType.Subtract)
    return solid


def _area(ring: np.ndarray) -> float:
    return 0.5 * float(np.sum(ring[:, 0] * np.roll(ring[:, 1], -1)
                              - np.roll(ring[:, 0], -1) * ring[:, 1]))


def _finger_scoop(cut: S.CutoutSpec, section: CrossSection,
                  z_floor: float) -> Manifold | None:
    """The ramp in the pocket's front-bottom corner that items slide up.

    This is *added* material, so the caller subtracts it from the pocket's
    negative solid rather than unioning it in. Shape: the corner block between
    floor and front wall, minus a cylinder tangent to both, which leaves a
    quarter-round ramp.
    """
    if not cut.finger_scoop:
        return None
    r = max(1.0, cut.finger_scoop_radius)
    x0, y0, x1, y1 = section.bounds()
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        return None
    r = min(r, (y1 - y0) * 0.9)
    width = (x1 - x0) + 2.0
    box = Manifold.cube((width, r, r)).translate((x0 - 1.0, y0, z_floor))
    cyl = (Manifold.cylinder(width + 2.0, r, -1.0, 64)
           .rotate((0.0, 90.0, 0.0))
           .translate((x0 - 2.0, y0 + r, z_floor + r)))
    ramp = Manifold.batch_boolean([box, cyl], OpType.Subtract)
    # keep it inside the pocket footprint
    column = section.extrude(r + 0.02).translate((0.0, 0.0, z_floor - 0.01))
    return Manifold.batch_boolean([ramp, column], OpType.Intersect)


def _finger_notch(cut: S.CutoutSpec, section: CrossSection,
                  z_floor: float, z_top: float) -> Manifold | None:
    """A half-round bite out of the pocket wall so a finger can reach in."""
    if not cut.finger_notch:
        return None
    d = max(2.0, cut.finger_notch_diameter)
    x0, y0, x1, y1 = section.bounds()
    cx = (x0 + x1) / 2.0
    return (Manifold.cylinder(z_top - z_floor + 0.02, d / 2.0, -1.0, 64)
            .translate((cx, y0, z_floor - 0.01)))


def build_cutout(cut: S.CutoutSpec, binspec: S.BinSpec,
                 mesh_dir: Path | None = None) -> Manifold | None:
    """The negative solid for one cutout, already placed in bin coordinates."""
    if not cut.enabled:
        return None

    top = binspec.usable_top_z
    depth = max(0.2, cut.depth)
    if cut.through:
        z_floor = -1.0
        depth = top + 1.0
    else:
        z_floor = max(S.BASE_HEIGHT * 0.0, top - depth)
        depth = top - z_floor

    if cut.mesh_source:
        solid = _mesh_cutout(cut, binspec, z_floor, mesh_dir)
        if solid is None:
            return None
    else:
        if len(cut.polygon) < 3:
            return None
        ring = normalise_orientation(np.asarray(cut.polygon, dtype=np.float64))
        holes = [normalise_orientation(np.asarray(h, dtype=np.float64))
                 for h in cut.holes if len(h) >= 3]
        section = cross_section(ring, holes)
        section = round_corners(section, cut.corner_radius)
        if abs(cut.clearance) > 1e-9:
            section = section.offset(cut.clearance, JoinType.Round, 2.0, 32)
        if section.is_empty():
            return None

        levels = _level_offsets(cut, depth)
        needs_loft = len(levels) > 2 or abs(levels[-1][1]) > 1e-9
        if needs_loft:
            solid = _lofted(section, levels, z_floor)
        else:
            solid = _straight(section, z_floor, z_floor + depth)

        # a notch enlarges the pocket, a scoop puts material back into it
        notch = _finger_notch(cut, section, z_floor, top)
        if notch is not None:
            solid = Manifold.batch_boolean([solid, notch], OpType.Add)
        scoop = _finger_scoop(cut, section, z_floor)
        if scoop is not None:
            solid = Manifold.batch_boolean([solid, scoop], OpType.Subtract)

    # Open the pocket through the top face. Slice just below whatever the
    # solid's own top happens to be -- a scan shallower than the requested
    # depth does not reach the rim on its own.
    if solid.is_empty():
        return None
    solid_top = solid.bounding_box()[5]
    cap = solid.slice(solid_top - 0.01)
    if not cap.is_empty():
        riser = (cap.extrude(binspec.total_height + 1.0 - (solid_top - 0.01))
                 .translate((0.0, 0.0, solid_top - 0.01)))
        solid = Manifold.batch_boolean([solid, riser], OpType.Add)

    if abs(cut.rotation) > 1e-9:
        solid = solid.rotate((0.0, 0.0, cut.rotation))
    return solid.translate((cut.x, cut.y, 0.0))


def _mesh_cutout(cut: S.CutoutSpec, binspec: S.BinSpec, z_floor: float,
                 mesh_dir: Path | None) -> Manifold | None:
    """Use a captured 3D scan as the pocket's shape.

    Clearance is applied in voxel space rather than as a mesh offset: growing
    the occupancy grid by a few voxels is exact, cheap and cannot self-
    intersect, which is more than can be said for offsetting a marching-cubes
    surface. Removing undercuts is a running OR along the vertical axis in the
    same representation.
    """
    if mesh_dir is None or not cut.mesh_source:
        return None
    path = _resolve_mesh(Path(mesh_dir), cut.mesh_source)
    if path is None:
        return None

    solid = (_voxel_solid(path, cut) if path.suffix == ".npz"
             else _stl_solid(path, cut))
    if solid is None or solid.is_empty():
        return None

    if cut.mesh_flip_z:
        # The capture guide has the object standing on its head, so the face the
        # camera sees best is its underside -- exactly the face that will rest on
        # the pocket floor. Turning the scan back over puts it there. Skip this
        # only if the object was photographed the right way up.
        box = solid.bounding_box()
        solid = solid.mirror((0.0, 0.0, 1.0)).translate((0.0, 0.0, box[5]))

    box = solid.bounding_box()
    solid = solid.translate((0.0, 0.0, -box[2]))
    height = box[5] - box[2]

    depth = height if cut.through else min(cut.depth, height)
    if depth < height - 1e-6:
        # Keep the bottom of the object: that is the part the pocket holds, and
        # the rest simply stands proud of the rim.
        solid = solid.trim_by_plane((0.0, 0.0, -1.0), -depth)

    return solid.translate((0.0, 0.0, z_floor))


def _resolve_mesh(root: Path, key: str) -> Path | None:
    """Turn a storage key into a path, refusing to leave the store.

    The key travels through the browser as part of the project document, so it
    is input like any other and cannot be joined onto a path unchecked.
    """
    if not key or key.startswith(("/", "\\")) or ".." in key.replace("\\", "/").split("/"):
        return None
    candidate = (root / key).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


_MESH_CACHE: "OrderedDict[tuple, Manifold]" = OrderedDict()
_MESH_CACHE_LIMIT = 16


def _cached(key: tuple, build):
    hit = _MESH_CACHE.get(key)
    if hit is not None:
        _MESH_CACHE.move_to_end(key)
        return hit
    value = build()
    if value is not None:
        _MESH_CACHE[key] = value
        _MESH_CACHE.move_to_end(key)
        while len(_MESH_CACHE) > _MESH_CACHE_LIMIT:
            _MESH_CACHE.popitem(last=False)
    return value


def _voxel_solid(path: Path, cut: S.CutoutSpec) -> Manifold | None:
    """Rebuild the hull from the stored occupancy grid at the wanted clearance."""
    key = (str(path), path.stat().st_mtime_ns, round(cut.clearance, 3),
           bool(cut.mesh_open_top))

    def build() -> Manifold | None:
        from skimage import measure

        from ..scan import carve as carve_module

        with np.load(path) as data:
            shape = tuple(int(v) for v in data["shape"])
            packed = data["voxels"]
            origin = np.asarray(data["origin"], dtype=np.float64)
            voxel_mm = float(np.asarray(data["voxel_mm"]).ravel()[0])
        count = int(np.prod(shape))
        grid = np.unpackbits(packed)[:count].astype(bool).reshape(shape)

        if cut.clearance > 0:
            grid = carve_module.dilate(grid, cut.clearance, voxel_mm)
        if cut.mesh_open_top:
            grid = carve_module.sweep_up(grid)
        if not grid.any():
            return None

        padded = np.pad(grid.astype(np.float32), 1, constant_values=0.0)
        verts, faces, _, _ = measure.marching_cubes(padded, level=0.5)
        verts = (verts - 1.0) * voxel_mm

        # centre in plan, sit on z=0
        verts[:, 0] -= (verts[:, 0].min() + verts[:, 0].max()) / 2.0
        verts[:, 1] -= (verts[:, 1].min() + verts[:, 1].max()) / 2.0
        verts[:, 2] -= verts[:, 2].min()

        return _solid_from_arrays(verts, faces)

    return _cached(key, build)


def _solid_from_arrays(verts: np.ndarray, faces: np.ndarray) -> Manifold | None:
    """Build a Manifold, making sure it is the right way out.

    Marching cubes hands back triangles wound the opposite way from what
    Manifold expects, which yields a solid of negative volume -- an inside-out
    body that subtracts nothing at all. Rather than hard-coding a flip, check
    the sign and correct it, so either convention works.
    """
    def make(triangles: np.ndarray) -> Manifold:
        return Manifold(Mesh(np.ascontiguousarray(verts, dtype=np.float32),
                             np.ascontiguousarray(triangles, dtype=np.uint32)))

    solid = make(faces)
    if solid.is_empty():
        return None
    if solid.volume() < 0:
        solid = make(faces[:, ::-1])
    return None if solid.is_empty() or solid.volume() <= 0 else solid


def _stl_solid(path: Path, cut: S.CutoutSpec) -> Manifold | None:
    """Fallback for a scan that only has a surface mesh stored."""
    key = (str(path), path.stat().st_mtime_ns, bool(cut.mesh_open_top), "stl")

    def build() -> Manifold | None:
        import trimesh

        tm = trimesh.load(path, force="mesh")
        if tm.is_empty:
            return None
        bounds = tm.bounds
        tm.apply_translation([
            -(bounds[0][0] + bounds[1][0]) / 2.0,
            -(bounds[0][1] + bounds[1][1]) / 2.0,
            -bounds[0][2],
        ])
        solid = _solid_from_arrays(np.asarray(tm.vertices),
                                   np.asarray(tm.faces))
        if solid is None:
            return None
        if cut.mesh_open_top:
            solid = _sweep_up(solid, solid.bounding_box()[5])
        return solid

    return _cached(key, build)


def _sweep_up(solid: Manifold, height: float, layers: int = 48) -> Manifold:
    """Remove undercuts by unioning every cross-section with everything above it."""
    if height <= 0:
        return solid
    bounds = solid.bounding_box()
    z0, z1 = bounds[2], bounds[5]
    step = (z1 - z0) / layers
    if step <= 0:
        return solid
    parts: list[Manifold] = []
    accumulated: CrossSection | None = None
    for i in range(layers):
        z = z0 + step * (i + 0.5)
        section = solid.slice(z)
        accumulated = section if accumulated is None else \
            CrossSection.batch_boolean([accumulated, section], OpType.Add)
        if accumulated.is_empty():
            continue
        parts.append(accumulated.extrude(step * 1.02)
                     .translate((0.0, 0.0, z0 + step * i)))
    if not parts:
        return solid
    return Manifold.batch_boolean(parts, OpType.Add)
