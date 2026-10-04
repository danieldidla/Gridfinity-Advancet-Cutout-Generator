"""The 3D capture, exercised against synthetic photos of a known object.

Rather than checking the pieces in isolation, this renders a solid of known
size standing on the printed board, from camera positions we choose, and runs
the whole chain: board detection, self-calibration, silhouette segmentation and
space carving. That is the only way to catch the errors that matter here --
a flipped axis or a clipped silhouette passes every unit test and still
reconstructs nothing usable.
"""

import math

import cv2
import numpy as np
import pytest

trimesh = pytest.importorskip("trimesh")
pytest.importorskip("scipy")
pytest.importorskip("skimage")

from app.scan import board as board_module
from app.scan import carve

SPEC = board_module.DEFAULT_BOARD
WIDTH, HEIGHT = 1280, 960
CAMERA = np.array([[1500.0, 0, WIDTH / 2], [0, 1500.0, HEIGHT / 2], [0, 0, 1]])


@pytest.fixture(scope="module")
def template():
    return board_module.render_board(SPEC, px_per_mm=12.0, with_margin=False)


def look_at(azimuth_deg: float, elevation_deg: float, distance: float):
    """A camera pointed at the middle of the board from a compass bearing."""
    cx, cy = SPEC.centre
    azimuth = math.radians(azimuth_deg)
    elevation = math.radians(elevation_deg)
    position = np.array([
        cx + distance * math.cos(elevation) * math.cos(azimuth),
        cy + distance * math.cos(elevation) * math.sin(azimuth),
        distance * math.sin(elevation),
    ])
    forward = np.array([cx, cy, 12.0]) - position
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, [0, 0, 1.0])
    right /= np.linalg.norm(right)
    down = np.cross(forward, right)
    rotation = np.vstack([right, down, forward])
    return cv2.Rodrigues(rotation)[0], (-rotation @ position).reshape(3, 1)


def render(template, mesh, rvec, tvec):
    """Board seen in perspective, with the object painted over it."""
    rotation = cv2.Rodrigues(rvec)[0]
    to_world = carve.template_to_world(SPEC, template.shape[1] / SPEC.width_mm)
    homography = CAMERA @ np.column_stack(
        [rotation[:, 0], rotation[:, 1], tvec.ravel()]) @ to_world
    image = cv2.warpPerspective(template, homography, (WIDTH, HEIGHT),
                                flags=cv2.INTER_LINEAR, borderValue=90)
    image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

    points, _ = cv2.projectPoints(mesh.vertices.astype(np.float64), rvec, tvec,
                                  CAMERA, np.zeros(5))
    points = points.reshape(-1, 2)
    camera_space = mesh.vertices @ rotation.T + tvec.ravel()
    order = np.argsort(-camera_space[mesh.faces][:, :, 2].mean(axis=1))
    normals = mesh.face_normals
    for face in order:
        shade = int(110 + 100 * abs(float(normals[face] @ np.array([0.3, 0.4, 0.86]))))
        cv2.fillConvexPoly(image, points[mesh.faces[face]].astype(np.int32),
                           (shade // 3, shade // 2, shade))
    return image


def make_box(extents=(44.0, 26.0, 20.0)):
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation([SPEC.width_mm / 2, SPEC.height_mm / 2, extents[2] / 2])
    return mesh


def capture(template, mesh, views):
    images = [render(template, mesh, *look_at(az, el, 420)) for az, el in views]
    detections = [carve.detect(image, SPEC, i) for i, image in enumerate(images)]
    return images, detections


DEFAULT_VIEWS = [(az, el) for el in (20, 40, 60, 80) for az in range(0, 360, 45)]


def test_board_is_detected_in_perspective(template):
    _, detections = capture(template, make_box(), DEFAULT_VIEWS[:8])
    assert all(d.usable for d in detections), "Board in schraeger Ansicht nicht erkannt"


def test_calibration_puts_the_cameras_above_the_board(template):
    """OpenCV's board frame points into the paper; poses must be flipped once.

    If this regresses, the voxel grid ends up underneath the sheet and the
    reconstruction silently returns nothing.
    """
    _, detections = capture(template, make_box(), DEFAULT_VIEWS)
    calibration = carve.calibrate(detections, SPEC)
    assert calibration.rms < 1.5

    heights = np.array([p.camera_position()[2] for p in calibration.poses])
    assert (heights > 0).all(), "Kameras liegen hinter dem Board"


def test_segmentation_matches_the_true_silhouette(template):
    mesh = make_box()
    images, detections = capture(template, mesh, DEFAULT_VIEWS)
    calibration = carve.calibrate(detections, SPEC)

    scores = []
    for pose in calibration.poses:
        rvec, tvec = look_at(*DEFAULT_VIEWS[pose.index], 420)
        truth = np.zeros((HEIGHT, WIDTH), np.uint8)
        points, _ = cv2.projectPoints(mesh.vertices.astype(np.float64), rvec, tvec,
                                      CAMERA, np.zeros(5))
        for face in mesh.faces:
            cv2.fillConvexPoly(truth, points.reshape(-1, 2)[face].astype(np.int32), 255)

        found = carve.object_mask(images[pose.index], calibration, pose, SPEC,
                                  threshold=40) > 0
        expected = truth > 0
        union = (found | expected).sum()
        scores.append((found & expected).sum() / max(1, union))

    assert np.mean(scores) > 0.9, f"Silhouetten nur zu {np.mean(scores):.2f} deckungsgleich"


def test_reconstruction_encloses_the_object(template):
    """A visual hull always contains the object -- never less, at most more."""
    mesh = make_box()
    images, detections = capture(template, mesh, DEFAULT_VIEWS)
    calibration = carve.calibrate(detections, SPEC)
    masks = {p.index: carve.object_mask(images[p.index], calibration, p, SPEC,
                                        threshold=40)
             for p in calibration.poses}

    result = carve.carve(masks, calibration, SPEC, voxel_mm=0.6,
                         max_height_mm=60, extent_mm=140)
    reconstruction = carve.to_mesh(result.voxels, result.origin, result.voxel_mm,
                                   smooth=0.6)

    truth = mesh.extents
    got = reconstruction.extents
    assert (got >= truth - 1.0).all(), f"Rekonstruktion zu klein: {got} vs {truth}"
    # the footprint is what a pocket is cut from, so it has to be tight
    assert got[0] == pytest.approx(truth[0], abs=2.0)
    assert got[1] == pytest.approx(truth[1], abs=2.0)


def test_coverage_reports_gaps(template):
    """Photos from one side must not be reported as full coverage."""
    one_side = [(az, el) for el in (20, 40) for az in (0, 45)]
    _, detections = capture(template, make_box(), one_side)
    calibration = carve.calibrate(detections, SPEC)
    coverage = carve.coverage(calibration.poses, SPEC)
    assert coverage["ratio"] < 0.5
    assert coverage["covered"] < coverage["total"]


def test_sweep_up_removes_undercuts():
    grid = np.zeros((10, 10, 10), bool)
    grid[2:8, 2:8, 0:3] = True     # a wide base
    grid[4:6, 4:6, 3:10] = True    # a narrow stem: the base is an undercut
    swept = carve.sweep_up(grid)
    assert swept[2:8, 2:8, 9].all(), "obere Schicht muss die Grundflaeche enthalten"
    assert swept.sum() > grid.sum()


def test_dilation_grows_by_the_requested_clearance():
    grid = np.zeros((40, 40, 40), bool)
    grid[18:22, 18:22, 18:22] = True
    grown = carve.dilate(grid, millimetres=1.0, voxel_mm=0.5)
    extent = np.argwhere(grown)
    span = extent.max(axis=0) - extent.min(axis=0)
    # 4 voxels wide plus two voxels of clearance on each side
    assert (span == 7).all()


def test_printable_board_is_exactly_a4():
    pdf = board_module.board_pdf()
    assert pdf.startswith(b"%PDF")
    assert b"595.276" in pdf and b"841.890" in pdf
