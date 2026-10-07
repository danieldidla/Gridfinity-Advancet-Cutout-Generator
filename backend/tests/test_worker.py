"""The background worker, driven exactly as the API would drive it."""

import cv2
import numpy as np
import pytest

trimesh = pytest.importorskip("trimesh")
pytest.importorskip("scipy")
pytest.importorskip("skimage")

from app.db import SessionLocal
from app.gridfinity import spec as S
from app.gridfinity.assembly import build_model
from app.gridfinity.bin_builder import build_bin
from app.models import Scan
from app import worker

from .test_scan import DEFAULT_VIEWS, look_at, make_box, render, SPEC
from app.scan import board as board_module


@pytest.fixture(scope="module")
def reconstructed(account):
    """Push synthetic photos through the API, then run the worker over the job."""
    template = board_module.render_board(SPEC, px_per_mm=12.0, with_margin=False)
    mesh = make_box()

    project = account.post("/api/projects", json={"name": "Worker"}).json()
    scan = account.post(f"/api/projects/{project['id']}/scans",
                        json={"name": "Kiste"}).json()

    for azimuth, elevation in DEFAULT_VIEWS:
        image = render(template, mesh, *look_at(azimuth, elevation, 420))
        blob = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 92])[1].tobytes()
        response = account.post(
            f"/api/projects/{project['id']}/scans/{scan['id']}/shots",
            files={"file": ("shot.jpg", blob, "image/jpeg")})
        assert response.status_code == 201

    started = account.post(
        f"/api/projects/{project['id']}/scans/{scan['id']}/reconstruct",
        json={"voxel_mm": 0.8, "max_height_mm": 60, "extent_mm": 140,
              "threshold": 40, "smooth": 0.6, "extend_beyond_board": True})
    assert started.status_code == 202

    db = SessionLocal()
    try:
        assert worker.run_once(db) is True, "kein Auftrag aufgenommen"
    finally:
        db.close()

    return project, scan, mesh, account


def test_worker_completes_the_job(reconstructed):
    project, scan, _, account = reconstructed
    job = account.get("/api/jobs").json()[0]
    assert job["status"] == "done", job.get("error")
    assert job["progress"] == 1.0


def test_scan_gets_a_mesh_and_dimensions(reconstructed):
    project, scan, mesh, account = reconstructed
    updated = account.get(f"/api/projects/{project['id']}/scans/{scan['id']}").json()
    assert updated["status"] == "ready"
    assert updated["has_mesh"] is True

    dimensions = updated["dimensions"]
    truth = mesh.extents
    # a visual hull encloses the object, so it is never smaller
    assert dimensions["width_mm"] >= truth[0] - 1.5
    assert dimensions["depth_mm"] >= truth[1] - 1.5
    assert dimensions["width_mm"] == pytest.approx(truth[0], abs=3.0)
    assert dimensions["depth_mm"] == pytest.approx(truth[1], abs=3.0)


def test_scan_coverage_is_recorded(reconstructed):
    project, scan, _, account = reconstructed
    coverage = account.get(
        f"/api/projects/{project['id']}/scans/{scan['id']}").json()["coverage"]
    assert coverage["covered"] >= coverage["total"] * 0.6


def test_scan_mesh_downloads(reconstructed):
    project, scan, _, account = reconstructed
    response = account.get(f"/api/projects/{project['id']}/scans/{scan['id']}/mesh")
    assert response.status_code == 200
    assert len(response.content) > 1000


def test_scan_becomes_a_usable_cutout(reconstructed):
    """The whole point: the captured shape has to cut a real pocket."""
    project, scan, mesh, _ = reconstructed
    db = SessionLocal()
    try:
        record = db.get(Scan, scan["id"])
        voxel_key = record.voxel_key
    finally:
        db.close()
    assert voxel_key, "kein Voxelgitter gespeichert"

    from app.config import get_settings

    binspec = S.BinSpec(grid_x=2, grid_y=2, height_units=5, solid=True)
    shell = build_bin(binspec)
    cut = S.CutoutSpec(mesh_source=voxel_key, depth=25, clearance=0.4,
                       mesh_open_top=True)
    result = build_model(binspec, [cut], mesh_dir=get_settings().data_dir,
                         bin_solid=shell)

    assert result.status() == 0 or str(result.status()) == "Error.NoError"
    removed = shell.volume() - result.volume()
    assert removed > mesh.volume * 0.5, \
        f"Tasche entfernt nur {removed:.0f} mm3, Objekt hat {mesh.volume:.0f} mm3"


def test_clearance_changes_the_pocket_size(reconstructed):
    project, scan, _, _ = reconstructed
    from app.config import get_settings

    db = SessionLocal()
    try:
        voxel_key = db.get(Scan, scan["id"]).voxel_key
    finally:
        db.close()

    binspec = S.BinSpec(grid_x=2, grid_y=2, height_units=5, solid=True)
    shell = build_bin(binspec)
    volumes = []
    for clearance in (0.0, 1.0):
        model = build_model(
            binspec,
            [S.CutoutSpec(mesh_source=voxel_key, depth=25, clearance=clearance)],
            mesh_dir=get_settings().data_dir, bin_solid=shell)
        volumes.append(model.volume())
    assert volumes[1] < volumes[0], "mehr Spiel muss mehr Material entfernen"


def test_a_scan_the_api_hands_out_can_be_used_as_a_cutout(reconstructed):
    """The path the interface actually walks, end to end.

    The earlier test read the storage key straight out of the database and so
    skipped the one step that was broken: the interface only ever sees what the
    API returns, and it has to be able to build a cutout from that alone.
    """
    project, scan, mesh, account = reconstructed

    listed = account.get(f"/api/projects/{project['id']}/scans").json()[0]
    assert listed["has_mesh"] is True
    assert listed.get("mesh_source"), "die API nennt die Datei des Scans nicht"

    from app.config import get_settings
    from app.gridfinity import spec as S
    from app.gridfinity.assembly import build_model
    from app.gridfinity.bin_builder import build_bin

    binspec = S.BinSpec(grid_x=2, grid_y=2, height_units=5, solid=True)
    shell = build_bin(binspec)
    cut = S.CutoutSpec(mesh_source=listed["mesh_source"], depth=25, clearance=0.4)
    result = build_model(binspec, [cut], mesh_dir=get_settings().data_dir,
                         bin_solid=shell)

    removed = shell.volume() - result.volume()
    assert removed > mesh.volume * 0.5, \
        f"Die Aussparung hat nur {removed:.0f} mm3 entfernt - der Scan kam nicht an"


def test_stats_say_so_when_a_scan_file_is_missing(account):
    """A cutout that quietly cuts nothing is the worst kind of failure."""
    stats = account.post("/api/geometry/stats", json={
        "bin": {"grid_x": 2, "grid_y": 2, "height_units": 4, "solid": True},
        "cutouts": [{"name": "Scan", "depth": 10,
                     "mesh_source": "meshes/gibtesnicht.npz"}],
    }).json()
    assert any("3D-Aufnahme" in w or "Scan" in w for w in stats["warnings"]), \
        f"keine Warnung: {stats['warnings']}"


def test_an_old_project_with_the_broken_reference_is_repaired(reconstructed):
    """Projects saved by the earlier version must not need rebuilding by hand."""
    project, scan, _, account = reconstructed

    broken = {
        "bin": {"grid_x": 2, "grid_y": 2, "height_units": 5, "solid": True},
        "cutouts": [{
            "name": "Alter Scan", "depth": 20,
            "mesh_source": f"meshes/{scan['id']}.npz",      # never existed
            "source": {"kind": "scan", "id": scan["id"], "label": "3D-Aufnahme"},
        }],
    }
    current = account.get(f"/api/projects/{project['id']}").json()
    account.patch(f"/api/projects/{project['id']}",
                  json={"state": broken, "revision": current["revision"]})

    reloaded = account.get(f"/api/projects/{project['id']}").json()
    repaired = reloaded["state"]["cutouts"][0]["mesh_source"]
    assert repaired != f"meshes/{scan['id']}.npz", "Verweis nicht repariert"

    stats = account.post("/api/geometry/stats", json={
        "bin": reloaded["state"]["bin"], "cutouts": reloaded["state"]["cutouts"],
    }).json()
    assert not any("3D-Aufnahme" in w for w in stats["warnings"]), stats["warnings"]
