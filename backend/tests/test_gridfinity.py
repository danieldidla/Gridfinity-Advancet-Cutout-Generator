"""Dimensional checks against the Gridfinity specification."""

import numpy as np
import pytest
from manifold3d import Error

from app.gridfinity import spec as S
from app.gridfinity.assembly import build_model
from app.gridfinity.bin_builder import build_bin
from app.gridfinity.exporters import export_3mf, export_stl, to_trimesh

from .conftest import needs_reconstruction


def inner_contour(solid, z):
    polygons = [np.asarray(p) for p in solid.slice(z).to_polygons()]
    if len(polygons) < 2:
        return None
    return min(polygons, key=lambda p: np.ptp(p[:, 0]))


@pytest.mark.parametrize("gx,gy,units", [(1, 1, 3), (2, 3, 6), (4, 1, 2)])
def test_outer_dimensions(gx, gy, units):
    binspec = S.BinSpec(grid_x=gx, grid_y=gy, height_units=units)
    box = build_bin(binspec).bounding_box()
    # Bounding boxes come back from a float32 mesh, so a micron of slack is
    # precision, not sloppiness -- printers resolve two orders of magnitude less.
    tolerance = 1e-3
    assert box[3] - box[0] == pytest.approx(gx * 42 - 0.5, abs=tolerance)
    assert box[4] - box[1] == pytest.approx(gy * 42 - 0.5, abs=tolerance)
    # height units set the stacking pitch; the lip sits on top of that
    assert box[5] - box[2] == pytest.approx(units * 7 + S.LIP_HEIGHT, abs=tolerance)


def test_base_foot_profile():
    """The foot must match the spec: 35.6 mm at the bottom, 37.2 mm straight."""
    solid = build_bin(S.BinSpec())
    assert np.ptp(np.asarray(solid.slice(0.01).to_polygons()[0])[:, 0]) \
        == pytest.approx(35.6, abs=0.05)
    for z in (0.85, 2.55):
        width = np.ptp(np.asarray(solid.slice(z).to_polygons()[0])[:, 0])
        assert width == pytest.approx(37.2, abs=0.05)
    assert np.ptp(np.asarray(solid.slice(4.7).to_polygons()[0])[:, 0]) \
        == pytest.approx(41.5, abs=0.15)


@pytest.mark.parametrize("gx,gy", [(1, 1), (2, 2), (3, 2)])
def test_stacking_lip_accepts_a_foot(gx, gy):
    """The seat has to be a touch wider than the foot that drops into it."""
    binspec = S.BinSpec(grid_x=gx, grid_y=gy, solid=True)
    solid = build_bin(binspec)
    inner = inner_contour(solid, binspec.body_top + 0.05)
    assert inner is not None, "no lip cavity found"

    foot_width = binspec.outer_width - 2 * S.BASE_MAX_INSET
    opening = np.ptp(inner[:, 0])
    clearance = (opening - foot_width) / 2
    assert 0.1 <= clearance <= 0.6, f"Spiel {clearance:.2f} mm ist unbrauchbar"


@pytest.mark.parametrize("gx,gy", [(2, 2), (3, 2)])
def test_lip_has_no_notch_at_cell_boundaries(gx, gy):
    """A multi-cell bin gets one perimeter rim, not one socket per cell."""
    binspec = S.BinSpec(grid_x=gx, grid_y=gy, solid=True)
    solid = build_bin(binspec)
    for z in (binspec.body_top + 0.2, binspec.total_height - 0.4):
        inner = inner_contour(solid, z)
        if inner is None:
            continue
        near_axis = inner[np.abs(inner[:, 1]) < 3.0]
        if len(near_axis) == 0:
            continue
        assert np.max(np.abs(inner[:, 0])) - np.max(np.abs(near_axis[:, 0])) < 0.3


def test_solid_bin_is_solid():
    hollow = build_bin(S.BinSpec(solid=False)).volume()
    solid = build_bin(S.BinSpec(solid=True)).volume()
    assert solid > hollow * 2


@pytest.mark.parametrize("options", [
    {},
    {"magnet_holes": True},
    {"screw_holes": True, "magnet_holes": True},
    {"label_tab": True},
    {"stacking_lip": False},
    {"lip_style": "normal"},
    {"solid": True},
])
def test_bins_are_manifold(options):
    solid = build_bin(S.BinSpec(grid_x=2, grid_y=2, **options))
    assert solid.status() == Error.NoError
    assert solid.volume() > 0


def rectangle(w, h):
    return [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]


@pytest.mark.parametrize("cut_options", [
    {},
    {"corner_radius": 3},
    {"draft_angle": 4},
    {"bottom_radius": 2},
    {"draft_angle": 3, "bottom_radius": 1.5, "corner_radius": 2},
    {"through": True},
    {"finger_scoop": True},
    {"finger_notch": True},
    {"clearance": 1.0},
])
def test_cutouts_are_manifold_and_remove_material(cut_options):
    binspec = S.BinSpec(grid_x=2, grid_y=2, height_units=4, solid=True)
    shell = build_bin(binspec)
    cut = S.CutoutSpec(polygon=rectangle(30, 20), depth=10, **cut_options)
    result = build_model(binspec, [cut], bin_solid=shell)

    assert result.status() == Error.NoError
    assert result.volume() < shell.volume(), "Aussparung hat nichts entfernt"


def test_scoop_adds_material_back():
    """A scoop is a ramp inside the pocket, so it leaves more material, not less."""
    binspec = S.BinSpec(grid_x=2, grid_y=2, height_units=4, solid=True)
    shell = build_bin(binspec)
    plain = build_model(binspec, [S.CutoutSpec(polygon=rectangle(30, 20), depth=10)],
                        bin_solid=shell)
    scooped = build_model(
        binspec,
        [S.CutoutSpec(polygon=rectangle(30, 20), depth=10, finger_scoop=True)],
        bin_solid=shell)
    assert scooped.volume() > plain.volume()


def test_clearance_widens_the_pocket():
    binspec = S.BinSpec(grid_x=2, grid_y=2, height_units=4, solid=True)
    shell = build_bin(binspec)
    volumes = [
        build_model(binspec, [S.CutoutSpec(polygon=rectangle(30, 20), depth=10,
                                           clearance=c)], bin_solid=shell).volume()
        for c in (0.0, 0.5, 1.0)
    ]
    assert volumes[0] > volumes[1] > volumes[2]


def test_exports_are_watertight():
    """Slicers re-merge STL vertices by position; the result must stay closed."""
    import trimesh

    binspec = S.BinSpec(grid_x=2, grid_y=2, height_units=4, solid=True)
    model = build_model(binspec, [
        S.CutoutSpec(polygon=rectangle(30, 20), x=-18, depth=12,
                     bottom_radius=2, draft_angle=3),
        S.CutoutSpec(polygon=rectangle(24, 24), x=18, depth=20, through=True),
    ])

    data = export_stl(model)
    reloaded = trimesh.load(trimesh.util.wrap_as_stream(data), file_type="stl")
    assert reloaded.is_watertight
    assert reloaded.volume == pytest.approx(to_trimesh(model).volume, rel=1e-4)

    assert export_3mf(model).startswith(b"PK")


# --- scans used as pockets --------------------------------------------------

def _write_voxel_scan(tmp_path, narrow_low: bool = True):
    """A stepped block stored the way the worker stores a reconstruction.

    Asymmetric on purpose: a symmetric test object would pass whichever way up
    the pocket ends up, which is exactly the mistake worth catching.
    """
    import numpy as np

    voxel_mm = 1.0
    grid = np.zeros((40, 40, 20), bool)
    if narrow_low:
        grid[15:25, 15:25, 0:10] = True    # narrow near the board
        grid[8:32, 8:32, 10:20] = True     # wide away from the board
    else:
        grid[8:32, 8:32, 0:10] = True
        grid[15:25, 15:25, 10:20] = True

    path = tmp_path / "meshes" / "scan.npz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        np.savez_compressed(
            handle, voxels=np.packbits(grid), shape=np.asarray(grid.shape),
            origin=np.zeros(3), voxel_mm=np.asarray([voxel_mm]))
    return "meshes/scan.npz"


@needs_reconstruction
def test_upside_down_scan_is_turned_back_over(tmp_path):
    """The face the camera saw best has to end up on the pocket floor.

    The capture guide puts the object on its head, so the widest part of the
    scan sits away from the board; in the finished pocket it belongs at the
    bottom.
    """
    key = _write_voxel_scan(tmp_path, narrow_low=True)
    binspec = S.BinSpec(grid_x=2, grid_y=2, height_units=6, solid=True)
    cut = S.CutoutSpec(mesh_source=key, depth=20, clearance=0.0,
                       mesh_open_top=False, mesh_flip_z=True)

    from app.gridfinity.cutouts import build_cutout

    pocket = build_cutout(cut, binspec, tmp_path)
    assert pocket is not None

    floor = binspec.usable_top_z - 20
    wide = np.ptp(np.asarray(pocket.slice(floor + 2).to_polygons()[0])[:, 0])
    narrow = np.ptp(np.asarray(pocket.slice(floor + 17).to_polygons()[0])[:, 0])
    assert wide > narrow + 5, \
        f"Tasche steht auf dem Kopf: unten {wide:.1f} mm, oben {narrow:.1f} mm"


@needs_reconstruction
def test_scan_pocket_sits_inside_the_bin(tmp_path):
    """A pocket that floats above the rim removes nothing at all."""
    key = _write_voxel_scan(tmp_path)
    binspec = S.BinSpec(grid_x=2, grid_y=2, height_units=6, solid=True)
    shell = build_bin(binspec)
    cut = S.CutoutSpec(mesh_source=key, depth=15, clearance=0.0)

    from app.gridfinity.cutouts import build_cutout

    pocket = build_cutout(cut, binspec, tmp_path)
    box = pocket.bounding_box()
    assert box[2] == pytest.approx(binspec.usable_top_z - 15, abs=0.5)

    result = build_model(binspec, [cut], mesh_dir=tmp_path, bin_solid=shell)
    assert result.volume() < shell.volume() - 1000


@needs_reconstruction
def test_open_top_removes_undercuts(tmp_path):
    """Without this the part cannot be dropped in from above."""
    key = _write_voxel_scan(tmp_path, narrow_low=False)
    binspec = S.BinSpec(grid_x=2, grid_y=2, height_units=6, solid=True)

    from app.gridfinity.cutouts import build_cutout

    closed = build_cutout(
        S.CutoutSpec(mesh_source=key, depth=20, clearance=0.0,
                     mesh_open_top=False, mesh_flip_z=True), binspec, tmp_path)
    opened = build_cutout(
        S.CutoutSpec(mesh_source=key, depth=20, clearance=0.0,
                     mesh_open_top=True, mesh_flip_z=True), binspec, tmp_path)
    assert opened.volume() > closed.volume()

    # every level of an opened pocket is at least as wide as the one below it
    floor = binspec.usable_top_z - 20
    widths = [np.ptp(np.asarray(opened.slice(floor + z).to_polygons()[0])[:, 0])
              for z in (2, 10, 18)]
    assert widths[1] >= widths[0] - 0.1 and widths[2] >= widths[1] - 0.1
