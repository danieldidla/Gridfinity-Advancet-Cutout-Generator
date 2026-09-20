"""Building models for the editor, fast enough to feel live.

Two caches do the work. The bin shell only depends on the bin settings, so
dragging a cutout around never rebuilds it. The finished model is cached by the
hash of everything that went into it, so the preview request and the following
export or stats call each cost one boolean at most.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np
from manifold3d import Error, Manifold

from ..config import get_settings
from ..gridfinity import exporters
from ..gridfinity.assembly import build_model
from ..schemas import BinSettings, Cutout, ModelStats

_LOCK = threading.Lock()
_SHELLS: "OrderedDict[str, Manifold]" = OrderedDict()
_MODELS: "OrderedDict[str, Manifold]" = OrderedDict()
_GLB: "OrderedDict[str, bytes]" = OrderedDict()


def _remember(cache: OrderedDict, key: str, value, limit: int):
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > limit:
        cache.popitem(last=False)


def _digest(*parts: object) -> str:
    blob = json.dumps(parts, sort_keys=True, default=str,
                      separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()[:32]


def bin_key(settings: BinSettings) -> str:
    return _digest("bin", settings.model_dump())


# Only what changes the geometry belongs in the cache key. Identity and
# labelling must stay out of it: ``Cutout.id`` defaults to a fresh random value,
# so including it would give two identical requests two different hashes and
# defeat both the cache and the preview's ETag.
_NON_GEOMETRIC = {"id", "name", "source", "enabled"}


def model_key(settings: BinSettings, cutouts: list[Cutout]) -> str:
    active = [c.model_dump(exclude=_NON_GEOMETRIC)
              for c in cutouts if c.enabled]
    return _digest("model", settings.model_dump(), active)


def get_shell(settings: BinSettings) -> Manifold:
    from ..gridfinity.bin_builder import build_bin

    key = bin_key(settings)
    with _LOCK:
        cached = _SHELLS.get(key)
        if cached is not None:
            _SHELLS.move_to_end(key)
            return cached
    shell = build_bin(settings.to_spec())
    with _LOCK:
        _remember(_SHELLS, key, shell, 12)
    return shell


def get_model(settings: BinSettings, cutouts: list[Cutout],
              mesh_dir: Path | None = None) -> tuple[Manifold, float]:
    """The finished solid plus how long it took to build (0 on a cache hit)."""
    key = model_key(settings, cutouts)
    with _LOCK:
        cached = _MODELS.get(key)
        if cached is not None:
            _MODELS.move_to_end(key)
            return cached, 0.0

    started = time.perf_counter()
    shell = get_shell(settings)
    specs = [c.to_spec() for c in cutouts if c.enabled]
    if mesh_dir is None:
        mesh_dir = get_settings().data_dir
    solid = build_model(settings.to_spec(), specs, mesh_dir=mesh_dir,
                        bin_solid=shell)
    elapsed = (time.perf_counter() - started) * 1000.0

    with _LOCK:
        _remember(_MODELS, key, solid, get_settings().preview_cache_size)
    return solid, elapsed


def get_glb(settings: BinSettings, cutouts: list[Cutout]) -> tuple[bytes, str]:
    key = model_key(settings, cutouts)
    with _LOCK:
        cached = _GLB.get(key)
        if cached is not None:
            _GLB.move_to_end(key)
            return cached, key
    solid, _ = get_model(settings, cutouts)
    data = exporters.export_glb(solid)
    with _LOCK:
        _remember(_GLB, key, data, get_settings().preview_cache_size)
    return data, key


def stats(settings: BinSettings, cutouts: list[Cutout]) -> ModelStats:
    solid, elapsed = get_model(settings, cutouts)
    box = solid.bounding_box()
    warnings = _sanity_checks(settings, cutouts, solid)
    return ModelStats(
        triangles=solid.num_tri(),
        volume_mm3=round(solid.volume(), 2),
        width_mm=round(box[3] - box[0], 3),
        depth_mm=round(box[4] - box[1], 3),
        height_mm=round(box[5] - box[2], 3),
        material_cm3=round(solid.volume() / 1000.0, 2),
        build_ms=round(elapsed, 1),
        warnings=warnings,
    )


def _cutout_extent(cut: Cutout) -> tuple[float, float, float, float] | None:
    """Where a cutout actually lands on the bin, in bin millimetres.

    Worked out in the cutout's own frame first -- the finger notch only bites
    out of one wall, and a margin applied to all four sides would report a
    breach that is not there -- then rotated into place.
    """
    if not cut.polygon:
        return None
    points = np.asarray(cut.polygon, dtype=float)
    clearance = max(0.0, cut.clearance)
    x0 = points[:, 0].min() - clearance
    x1 = points[:, 0].max() + clearance
    y0 = points[:, 1].min() - clearance
    y1 = points[:, 1].max() + clearance

    if cut.finger_notch:
        # a half-round bite centred on the front wall of the pocket
        radius = cut.finger_notch_diameter / 2.0
        centre = (points[:, 0].min() + points[:, 0].max()) / 2.0
        x0 = min(x0, centre - radius)
        x1 = max(x1, centre + radius)
        y0 = min(y0, y0 - radius)

    if cut.draft_angle > 0:
        # the pocket is widest where it meets the surface
        grow = cut.depth * math.tan(math.radians(cut.draft_angle))
        x0 -= grow; x1 += grow; y0 -= grow; y1 += grow

    corners = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
    if abs(cut.rotation) > 1e-9:
        angle = math.radians(cut.rotation)
        rotation = np.array([[math.cos(angle), -math.sin(angle)],
                             [math.sin(angle), math.cos(angle)]])
        corners = corners @ rotation.T

    return (corners[:, 0].min() + cut.x, corners[:, 1].min() + cut.y,
            corners[:, 0].max() + cut.x, corners[:, 1].max() + cut.y)


def _sanity_checks(settings: BinSettings, cutouts: list[Cutout],
                   solid: Manifold) -> list[str]:
    """Things worth telling the user before they spend six hours printing."""
    notes: list[str] = []
    spec = settings.to_spec()
    usable_depth = spec.usable_top_z - spec.inner_floor_z
    half_width = spec.outer_width / 2.0
    half_depth = spec.outer_depth / 2.0

    for cut in cutouts:
        if not cut.enabled:
            continue
        if not cut.through and cut.depth > usable_depth + 1e-6:
            notes.append(
                f"'{cut.name}': Tiefe {cut.depth:.1f} mm geht durch den Boden "
                f"(nutzbar {usable_depth:.1f} mm). Höhe erhöhen oder "
                f"'Durchbruch“ aktivieren.")
        if cut.polygon and len(cut.polygon) < 3 and not cut.mesh_source:
            notes.append(f"'{cut.name}': Kontur unvollständig.")
        extent = _cutout_extent(cut)
        if extent is not None:
            wall = settings.wall_thickness
            outside = (extent[0] < -half_width + wall or extent[1] < -half_depth + wall
                       or extent[2] > half_width - wall or extent[3] > half_depth - wall)
            if outside:
                breaches = (extent[0] < -half_width or extent[1] < -half_depth
                            or extent[2] > half_width or extent[3] > half_depth)
                notes.append(
                    f"„{cut.name}“ reicht bis an den Rand: "
                    + ("die Aussparung durchbricht die Außenwand."
                       if breaches else
                       f"es bleiben weniger als {wall:.1f} mm Wand stehen."))

        if not settings.solid and not cut.through:
            pocket_floor = spec.usable_top_z - cut.depth
            if pocket_floor >= spec.inner_floor_z - 1e-6:
                notes.append(
                    f"'{cut.name}': liegt vollständig im hohlen Innenraum und "
                    f"schneidet daher nichts aus. „Massiv“ aktivieren oder den "
                    f"Cutout tiefer machen.")

    # A magnet hole is drilled up from the underside, so what stands between it
    # and the compartment is the whole base foot plus the floor, not the floor
    # alone.
    from ..gridfinity.spec import BASE_HEIGHT
    solid_under_floor = BASE_HEIGHT + settings.floor_thickness
    if settings.magnet_holes and settings.magnet_depth > solid_under_floor:
        notes.append(
            f"Magnetlöcher ({settings.magnet_depth:.1f} mm) reichen in den "
            f"Innenraum (nur {solid_under_floor:.1f} mm Material).")
    if settings.screw_holes and settings.screw_depth > solid_under_floor:
        notes.append(
            f"Schraublöcher ({settings.screw_depth:.1f} mm) durchbrechen den "
            f"Boden (nur {solid_under_floor:.1f} mm Material).")

    if solid.status() != Error.NoError:
        notes.append(f"Geometrie ist nicht sauber ({solid.status()}) – "
                     f"bitte Parameter prüfen.")
    return notes


def invalidate() -> None:
    with _LOCK:
        _SHELLS.clear()
        _MODELS.clear()
        _GLB.clear()
