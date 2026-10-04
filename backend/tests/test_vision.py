"""The photo path has to give back real millimetres."""

import cv2
import numpy as np
import pytest

from app.services import vision

PPM = 6.0
OBJECT_MM = (60.0, 40.0)
HOLE_DIAMETER_MM = 12.0


def synthetic_photo():
    """An A4 sheet with a known rectangle on it, photographed at an angle."""
    sheet = np.full((int(297 * PPM), int(210 * PPM), 3), 235, np.uint8)
    cv2.rectangle(sheet, (int(75 * PPM), int(128 * PPM)),
                  (int(135 * PPM), int(168 * PPM)), (40, 45, 50), -1)
    cv2.circle(sheet, (int(105 * PPM), int(148 * PPM)),
               int(HOLE_DIAMETER_MM / 2 * PPM), (235, 235, 235), -1)

    canvas = np.full((1400, 1100, 3), 150, np.uint8)
    source = np.float32([[0, 0], [sheet.shape[1] - 1, 0],
                         [sheet.shape[1] - 1, sheet.shape[0] - 1],
                         [0, sheet.shape[0] - 1]])
    target = np.float32([[220, 130], [880, 210], [810, 1290], [150, 1180]])
    cv2.warpPerspective(sheet, cv2.getPerspectiveTransform(source, target),
                        (canvas.shape[1], canvas.shape[0]), canvas,
                        borderMode=cv2.BORDER_TRANSPARENT)
    return canvas, target


def test_sheet_detection_finds_the_corners():
    photo, truth = synthetic_photo()
    corners = vision.detect_sheet(photo)
    assert corners is not None
    error = max(np.linalg.norm(np.asarray(c) - t) for c, t in zip(corners, truth))
    assert error < 6.0, f"Ecken {error:.1f} px daneben"


def test_measurements_survive_the_perspective():
    photo, _ = synthetic_photo()
    corners = vision.detect_sheet(photo)
    rectified, rect = vision.rectify(photo, corners, "a4", px_per_mm=8.0)
    assert rect.width_mm == pytest.approx(210.0)
    assert rect.height_mm == pytest.approx(297.0)

    mask = vision.auto_threshold_mask(rectified)
    outline, holes = vision.mask_to_polygons(mask, rect.px_per_mm, simplify_mm=0.3)

    points = np.asarray(outline)
    assert np.ptp(points[:, 0]) == pytest.approx(OBJECT_MM[0], abs=1.0)
    assert np.ptp(points[:, 1]) == pytest.approx(OBJECT_MM[1], abs=1.0)

    assert len(holes) == 1
    hole = np.asarray(holes[0])
    assert np.ptp(hole[:, 0]) == pytest.approx(HOLE_DIAMETER_MM, abs=1.0)


def test_outline_is_centred_on_the_origin():
    """A traced outline should be ready to drop in as a cutout, not offset."""
    photo, _ = synthetic_photo()
    corners = vision.detect_sheet(photo)
    rectified, rect = vision.rectify(photo, corners, "a4", px_per_mm=8.0)
    mask = np.zeros(rectified.shape[:2], np.uint8)
    h, w = mask.shape
    cv2.rectangle(mask, (w // 2 - 80, h // 2 - 40), (w // 2 + 80, h // 2 + 40), 255, -1)

    outline, _ = vision.mask_to_polygons(mask, rect.px_per_mm)
    points = np.asarray(outline)
    assert abs(points[:, 0].mean()) < 1.0
    assert abs(points[:, 1].mean()) < 1.0


def test_rejects_unreadable_input():
    blank = np.full((400, 400, 3), 128, np.uint8)
    assert vision.detect_sheet(blank) is None


def test_sheet_detection_survives_a_spurious_corner():
    """A single simplification tolerance is not enough.

    The contour of a photographed sheet often simplifies to five corners at one
    tolerance and four at the next, and the tolerance that finally gives four
    can put a corner a hundred pixels out. Detection sweeps the tolerance and
    then fits each edge, because these four points set the scale for every
    measurement the application makes.
    """
    photo, truth = synthetic_photo()
    # JPEG, as every real photograph arrives
    encoded = cv2.imencode(".jpg", photo, [int(cv2.IMWRITE_JPEG_QUALITY), 90])[1]
    photo = cv2.imdecode(encoded, cv2.IMREAD_COLOR)

    corners = vision.detect_sheet(photo)
    assert corners is not None, "Blatt nicht erkannt"
    error = max(np.linalg.norm(np.asarray(c) - t) for c, t in zip(corners, truth))
    assert error < 12.0, f"Ecken {error:.1f} px daneben"


def test_corner_refinement_declines_to_make_things_worse():
    """A refinement that moves a corner wildly has misread the edge."""
    contour = np.array([[[100, 100]], [[400, 110]], [[395, 400]], [[105, 395]]],
                       dtype=np.int32)
    quad = vision.order_corners(contour)
    refined = vision._refine_corners(contour, quad)
    assert np.max(np.abs(refined - quad)) < 30
