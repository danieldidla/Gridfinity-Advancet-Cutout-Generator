"""Reconstructing an object from photos taken all around it on the ChArUco board.

The board does three jobs: it fixes the scale, it lets every camera pose be
solved without a separate calibration step, and -- because we know exactly what
it looks like -- it doubles as the background for segmenting the object.

The reconstruction itself is shape-from-silhouette (space carving). A voxel
survives only if it projects inside the object's silhouette in *every* view, so
the result is the visual hull: guaranteed to contain the object, which is
precisely the property a pocket needs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from .board import DEFAULT_BOARD, BoardSpec, make_board, render_board


# OpenCV lays a ChArUco board out with +Z pointing *into* the paper, so a camera
# looking at it sits at negative z. Everything downstream -- the coverage
# hemisphere, the voxel grid, the exported mesh -- is much easier to reason
# about with z pointing up out of the board, so poses are converted once, right
# after calibration. The map is a 180 degree turn about the board's x axis,
# which keeps the frame right-handed: (x, y, z) -> (x, H - y, -z).
_FLIP = np.diag([1.0, -1.0, -1.0])


def _to_world(rvec: np.ndarray, tvec: np.ndarray,
              spec: BoardSpec) -> tuple[np.ndarray, np.ndarray]:
    rotation = cv2.Rodrigues(rvec)[0]
    offset = np.array([[0.0], [spec.height_mm], [0.0]])
    rot_world = rotation @ _FLIP
    t_world = tvec.reshape(3, 1) - rot_world @ offset
    return cv2.Rodrigues(rot_world)[0], t_world


@dataclass(slots=True)
class ViewPose:
    index: int
    rvec: np.ndarray
    tvec: np.ndarray
    corner_count: int

    def rotation(self) -> np.ndarray:
        return cv2.Rodrigues(self.rvec)[0]

    def camera_position(self) -> np.ndarray:
        """Camera centre in board coordinates (millimetres)."""
        r = self.rotation()
        return (-r.T @ self.tvec).ravel()


@dataclass(slots=True)
class Detection:
    index: int
    charuco_corners: np.ndarray | None
    charuco_ids: np.ndarray | None
    image_size: tuple[int, int]
    sharpness: float

    @property
    def usable(self) -> bool:
        return (self.charuco_ids is not None
                and len(self.charuco_ids) >= 8)


@dataclass(slots=True)
class Calibration:
    camera_matrix: np.ndarray
    dist_coeffs: np.ndarray
    poses: list[ViewPose]
    rms: float


@dataclass(slots=True)
class CarveResult:
    voxels: np.ndarray            # bool (nx, ny, nz)
    origin: np.ndarray            # board-space mm of voxel (0,0,0) centre
    voxel_mm: float
    used_views: int
    warnings: list[str] = field(default_factory=list)


def sharpness(image: np.ndarray) -> float:
    """Variance of the Laplacian: low means the shot is blurred."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def detect(image: np.ndarray, spec: BoardSpec = DEFAULT_BOARD,
           index: int = 0) -> Detection:
    board = make_board(spec)
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    detector = cv2.aruco.CharucoDetector(board)
    detector.setDetectorParameters(params)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    corners, ids, _, _ = detector.detectBoard(gray)
    return Detection(
        index=index,
        charuco_corners=corners,
        charuco_ids=ids,
        image_size=(gray.shape[1], gray.shape[0]),
        sharpness=sharpness(gray),
    )


def calibrate(detections: list[Detection],
              spec: BoardSpec = DEFAULT_BOARD) -> Calibration:
    """Solve intrinsics and every camera pose from the capture set itself.

    A guided capture is already a calibration sequence -- many views of a known
    planar target from varied angles -- so there is no reason to make the user
    shoot a separate calibration set.
    """
    usable = [d for d in detections if d.usable]
    if len(usable) < 4:
        raise ValueError(
            f"nur {len(usable)} verwertbare Aufnahmen, mindestens 4 notwendig")

    board = make_board(spec)
    size = usable[0].image_size
    corners = [d.charuco_corners for d in usable]
    ids = [d.charuco_ids for d in usable]

    flags = cv2.CALIB_FIX_PRINCIPAL_POINT | cv2.CALIB_ZERO_TANGENT_DIST | \
        cv2.CALIB_FIX_K3
    guess = np.array([[size[0] * 1.2, 0, size[0] / 2.0],
                      [0, size[0] * 1.2, size[1] / 2.0],
                      [0, 0, 1]], dtype=np.float64)

    rms, matrix, dist, rvecs, tvecs = cv2.aruco.calibrateCameraCharuco(
        corners, ids, board, size, guess,
        np.zeros((5, 1)), flags=flags,
        criteria=(cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 60, 1e-6),
    )

    poses = []
    for detection, rvec, tvec in zip(usable, rvecs, tvecs):
        r_world, t_world = _to_world(np.asarray(rvec, np.float64),
                                     np.asarray(tvec, np.float64), spec)
        poses.append(ViewPose(index=detection.index, rvec=r_world,
                              tvec=t_world,
                              corner_count=len(detection.charuco_ids)))
    return Calibration(camera_matrix=matrix, dist_coeffs=dist, poses=poses,
                       rms=float(rms))


# --- coverage guidance ------------------------------------------------------

AZIMUTH_SECTORS = 8
# Low views are what bound the object's height: a voxel floating above it is
# only carved away by a camera flat enough to see past the top. High views
# pin down the footprint. The capture guide asks for all three bands.
ELEVATION_BANDS = ((8.0, 30.0), (30.0, 55.0), (55.0, 85.0))
BAND_LABELS = ("flach (knapp über dem Tisch)", "mittel (schräg von oben)",
               "steil (fast senkrecht)")


def coverage(poses: list[ViewPose], spec: BoardSpec = DEFAULT_BOARD
             ) -> dict:
    """Which parts of the viewing hemisphere still have no photo."""
    cx, cy = spec.centre
    filled: set[tuple[int, int]] = set()
    for pose in poses:
        pos = pose.camera_position()
        dx, dy, dz = pos[0] - cx, pos[1] - cy, pos[2]
        horizontal = math.hypot(dx, dy)
        if horizontal < 1e-6 and dz <= 0:
            continue
        elevation = math.degrees(math.atan2(dz, horizontal))
        azimuth = (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0
        sector = int(azimuth // (360.0 / AZIMUTH_SECTORS)) % AZIMUTH_SECTORS
        for band, (lo, hi) in enumerate(ELEVATION_BANDS):
            if lo <= elevation < hi or (band == len(ELEVATION_BANDS) - 1
                                        and elevation >= hi):
                filled.add((sector, band))
                break

    cells = [{"sector": s, "band": b, "covered": (s, b) in filled}
             for b in range(len(ELEVATION_BANDS))
             for s in range(AZIMUTH_SECTORS)]
    total = AZIMUTH_SECTORS * len(ELEVATION_BANDS)
    return {
        "sectors": AZIMUTH_SECTORS,
        "bands": len(ELEVATION_BANDS),
        "band_labels": list(BAND_LABELS),
        "band_ranges": [list(b) for b in ELEVATION_BANDS],
        "cells": cells,
        "covered": len(filled),
        "total": total,
        "ratio": len(filled) / total,
    }


# --- segmentation -----------------------------------------------------------

def board_homography(calib: Calibration, pose: ViewPose) -> np.ndarray:
    """World board plane (z=0, millimetres) to image pixels."""
    rotation = pose.rotation()
    matrix = np.column_stack([rotation[:, 0], rotation[:, 1], pose.tvec.ravel()])
    return calib.camera_matrix @ matrix


def template_to_world(spec: BoardSpec, px_per_mm: float) -> np.ndarray:
    """Template pixels (row 0 at the top) to world millimetres (y upwards)."""
    return np.array([[1.0 / px_per_mm, 0.0, 0.0],
                     [0.0, -1.0 / px_per_mm, spec.height_mm],
                     [0.0, 0.0, 1.0]])


def object_mask(image: np.ndarray, calib: Calibration, pose: ViewPose,
                spec: BoardSpec = DEFAULT_BOARD,
                threshold: int = 45, min_area_ratio: float = 0.0008,
                template: np.ndarray | None = None,
                extend_beyond_board: bool = True) -> np.ndarray:
    """Segment the object by comparing the photo against the board we printed.

    Anything on the board that does not look like the board is either the
    object or its shadow; shadows are rejected by requiring a solid blob and by
    matching brightness statistics first.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    h, w = gray.shape[:2]

    if template is None:
        template = render_board(spec, px_per_mm=6.0, with_margin=False)
    tpl_ppm = template.shape[1] / spec.width_mm

    homography = board_homography(calib, pose) @ template_to_world(spec, tpl_ppm)
    warped = cv2.warpPerspective(template, homography, (w, h),
                                 flags=cv2.INTER_LINEAR,
                                 borderValue=0)
    inside = cv2.warpPerspective(np.full(template.shape, 255, np.uint8),
                                 homography, (w, h), flags=cv2.INTER_NEAREST,
                                 borderValue=0)
    inside = cv2.erode(inside, np.ones((5, 5), np.uint8))

    # match exposure before differencing, otherwise lighting alone trips it
    valid = inside > 0
    if valid.sum() < 100:
        return np.zeros((h, w), np.uint8)
    src = warped[valid].astype(np.float32)
    dst = gray[valid].astype(np.float32)
    scale = (dst.std() + 1e-6) / (src.std() + 1e-6)
    shift = dst.mean() - src.mean() * scale
    adjusted = np.clip(warped.astype(np.float32) * scale + shift, 0, 255)

    diff = cv2.absdiff(gray.astype(np.float32), adjusted).astype(np.uint8)
    diff = cv2.medianBlur(diff, 5)
    mask = np.where((diff > threshold) & valid, 255, 0).astype(np.uint8)

    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))

    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if count <= 1:
        return mask
    min_area = min_area_ratio * h * w
    keep = np.zeros(count, bool)
    for i in range(1, count):
        keep[i] = stats[i, cv2.CC_STAT_AREA] >= min_area
    if not keep.any():
        return np.zeros((h, w), np.uint8)
    # the object is the blob nearest the board centre
    centre_px = _project(calib, pose, np.array([[*spec.centre, 0.0]]))[0]
    best, best_d = 0, float("inf")
    for i in range(1, count):
        if not keep[i]:
            continue
        cxx = stats[i, cv2.CC_STAT_LEFT] + stats[i, cv2.CC_STAT_WIDTH] / 2
        cyy = stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT] / 2
        d = (cxx - centre_px[0]) ** 2 + (cyy - centre_px[1]) ** 2
        if d < best_d:
            best, best_d = i, d
    filled = np.where(labels == best, 255, 0).astype(np.uint8)
    filled = cv2.morphologyEx(filled, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))

    if extend_beyond_board and _touches_board_edge(filled, inside):
        filled = _grow_past_board(image, filled, inside)
    return filled


def _touches_board_edge(mask: np.ndarray, inside: np.ndarray) -> bool:
    """Does the silhouette run into the edge of the visible board?

    From a low angle a tall object sticks out past the sheet, and the part that
    does has no board behind it to be differenced against. Clipping there would
    saw the top off the object and, with it, off the reconstruction.
    """
    edge = cv2.morphologyEx(inside, cv2.MORPH_GRADIENT, np.ones((7, 7), np.uint8))
    return bool(np.any((mask > 0) & (edge > 0)))


def _grow_past_board(image: np.ndarray, seed: np.ndarray,
                     inside: np.ndarray, work_width: int = 640) -> np.ndarray:
    """Let GrabCut carry the silhouette off the sheet and onto the backdrop.

    The template difference is trustworthy over the board, so it seeds the
    foreground; board pixels well clear of the object seed the background.
    Everything else -- crucially the area above the sheet -- is left for
    GrabCut to decide.
    """
    h, w = seed.shape
    scale = min(1.0, work_width / max(h, w))
    size = (max(1, int(w * scale)), max(1, int(h * scale)))
    small_img = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
    small_seed = cv2.resize(seed, size, interpolation=cv2.INTER_NEAREST)
    small_inside = cv2.resize(inside, size, interpolation=cv2.INTER_NEAREST)

    kernel = np.ones((5, 5), np.uint8)
    sure_fg = cv2.erode(small_seed, kernel, iterations=2)
    near = cv2.dilate(small_seed, kernel, iterations=6)
    sure_bg = (small_inside > 0) & (near == 0)

    if sure_fg.sum() < 50 or sure_bg.sum() < 50:
        return seed

    gc = np.full(small_img.shape[:2], cv2.GC_PR_BGD, np.uint8)
    gc[sure_bg] = cv2.GC_BGD
    gc[(near > 0) & (sure_fg == 0)] = cv2.GC_PR_FGD
    gc[sure_fg > 0] = cv2.GC_FGD
    try:
        cv2.grabCut(small_img, gc, None, np.zeros((1, 65), np.float64),
                    np.zeros((1, 65), np.float64), 3, cv2.GC_INIT_WITH_MASK)
    except cv2.error:
        return seed

    grown = np.where((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    grown = cv2.morphologyEx(grown, cv2.MORPH_CLOSE, kernel)
    grown = cv2.resize(grown, (w, h), interpolation=cv2.INTER_NEAREST)

    # keep only the component that the seed already vouched for
    union = np.maximum(grown, seed)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(union, 8)
    if count <= 1:
        return seed
    overlap = [(labels == i)[seed > 0].sum() for i in range(count)]
    overlap[0] = 0
    best = int(np.argmax(overlap))
    if overlap[best] == 0:
        return seed
    result = np.where(labels == best, 255, 0).astype(np.uint8)
    # a runaway segmentation is worse than a clipped one
    if result.sum() > seed.sum() * 6:
        return seed
    return result


def _project(calib: Calibration, pose: ViewPose, points: np.ndarray) -> np.ndarray:
    projected, _ = cv2.projectPoints(points.astype(np.float64), pose.rvec,
                                     pose.tvec, calib.camera_matrix,
                                     calib.dist_coeffs)
    return projected.reshape(-1, 2)


# --- space carving ----------------------------------------------------------

def carve(masks: dict[int, np.ndarray], calib: Calibration,
          spec: BoardSpec = DEFAULT_BOARD,
          voxel_mm: float = 0.5, max_height_mm: float = 120.0,
          extent_mm: float = 160.0, coarse_mm: float = 2.0,
          progress=None) -> CarveResult:
    """Two passes: a coarse grid to find the object, then a fine one around it."""
    poses = [p for p in calib.poses if p.index in masks]
    if len(poses) < 3:
        raise ValueError("mindestens 3 auswertbare Ansichten notwendig")

    # Undistorting once turns every later projection into plain matrix algebra.
    undistorted: dict[int, np.ndarray] = {}
    for pose in poses:
        m = masks[pose.index]
        undistorted[pose.index] = cv2.undistort(
            m, calib.camera_matrix, calib.dist_coeffs) > 127

    cx, cy = spec.centre
    half = extent_mm / 2.0
    bounds = (cx - half, cx + half, cy - half, cy + half, 0.0, max_height_mm)

    if progress:
        progress(0.05, "Grobraster")
    coarse_grid, coarse_origin = _carve_grid(
        undistorted, calib, poses, bounds, coarse_mm)
    if not coarse_grid.any():
        raise ValueError(
            "Kein Objekt rekonstruiert – Silhouetten prüfen (Schwellwert, Licht)")

    bounds = _occupied_bounds(coarse_grid, coarse_origin, coarse_mm,
                              margin_mm=max(2.0, coarse_mm * 2))
    if progress:
        progress(0.35, "Feinraster")
    grid, origin = _carve_grid(undistorted, calib, poses, bounds, voxel_mm,
                               progress=progress)

    warnings: list[str] = []
    if len(poses) < 12:
        warnings.append(
            f"Nur {len(poses)} Ansichten verwendet – mehr Bilder erhöhen die Genauigkeit.")
    return CarveResult(voxels=grid, origin=origin, voxel_mm=voxel_mm,
                       used_views=len(poses), warnings=warnings)


def _carve_grid(masks: dict[int, np.ndarray], calib: Calibration,
                poses: list[ViewPose], bounds: tuple, step: float,
                progress=None) -> tuple[np.ndarray, np.ndarray]:
    x0, x1, y0, y1, z0, z1 = bounds
    nx = max(1, int(math.ceil((x1 - x0) / step)))
    ny = max(1, int(math.ceil((y1 - y0) / step)))
    nz = max(1, int(math.ceil((z1 - z0) / step)))

    xs = x0 + (np.arange(nx) + 0.5) * step
    ys = y0 + (np.arange(ny) + 0.5) * step
    zs = z0 + (np.arange(nz) + 0.5) * step
    origin = np.array([xs[0], ys[0], zs[0]])

    occupancy = np.ones((nx, ny, nz), dtype=bool)
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    flat_xy = np.column_stack([gx.ravel(), gy.ravel()])

    for n, pose in enumerate(poses):
        mask = masks[pose.index]
        h, w = mask.shape
        rotation = pose.rotation()
        translation = pose.tvec.ravel()
        matrix = calib.camera_matrix

        # camera-space basis for the xy plane, so each z slice is one add
        base = flat_xy @ rotation[:, :2].T + translation
        dz = rotation[:, 2]

        for k, z in enumerate(zs):
            alive = occupancy[:, :, k]
            if not alive.any():
                continue
            cam = base + dz * z
            depth = cam[:, 2]
            uv = (matrix[:2, :2] @ cam[:, :2].T).T / np.maximum(
                depth, 1e-6)[:, None]
            uv[:, 0] += matrix[0, 2]
            uv[:, 1] += matrix[1, 2]
            u = np.rint(uv[:, 0]).astype(np.int32)
            v = np.rint(uv[:, 1]).astype(np.int32)
            valid = (depth > 1e-3) & (u >= 0) & (u < w) & (v >= 0) & (v < h)
            hit = np.zeros(len(u), bool)
            hit[valid] = mask[v[valid], u[valid]]
            occupancy[:, :, k] &= hit.reshape(nx, ny)

        if progress:
            progress(0.35 + 0.6 * (n + 1) / len(poses),
                     f"Carving {n + 1}/{len(poses)}")
    return occupancy, origin


def _occupied_bounds(occupancy: np.ndarray, origin: np.ndarray, step: float,
                     margin_mm: float) -> tuple:
    """Axis-aligned millimetre bounds of the occupied voxels, plus a margin."""
    indices = np.argwhere(occupancy)
    lo = indices.min(axis=0) * step + origin - margin_mm
    hi = (indices.max(axis=0) + 1) * step + origin + margin_mm
    lo[2] = max(0.0, lo[2])
    return (float(lo[0]), float(hi[0]), float(lo[1]), float(hi[1]),
            float(lo[2]), float(hi[2]))


def sweep_up(occupancy: np.ndarray) -> np.ndarray:
    """Make every layer at least as large as everything below it.

    A pocket has to be open towards the top, so undercuts have to go. In voxel
    form that is a running OR along the vertical axis.
    """
    return np.maximum.accumulate(occupancy, axis=2)


def dilate(occupancy: np.ndarray, millimetres: float,
           voxel_mm: float) -> np.ndarray:
    """Grow the hull by a clearance, in place of a mesh offset."""
    if millimetres <= 0:
        return occupancy
    radius = int(round(millimetres / voxel_mm))
    if radius < 1:
        return occupancy
    from scipy import ndimage
    size = radius * 2 + 1
    grid = np.indices((size,) * 3) - radius
    ball = (grid ** 2).sum(axis=0) <= radius ** 2
    return ndimage.binary_dilation(occupancy, structure=ball)


def to_mesh(occupancy: np.ndarray, origin: np.ndarray, voxel_mm: float,
            smooth: float = 0.8):
    """Marching cubes over the occupancy grid, in board millimetres."""
    import trimesh
    from skimage import measure

    padded = np.pad(occupancy.astype(np.float32), 1, constant_values=0.0)
    if smooth > 0:
        from scipy import ndimage
        padded = ndimage.gaussian_filter(padded, sigma=smooth)

    verts, faces, _, _ = measure.marching_cubes(padded, level=0.5)
    verts = (verts - 1.0) * voxel_mm + origin
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.update_faces(mesh.unique_faces())
    mesh.remove_unreferenced_vertices()
    mesh.fix_normals()
    return mesh


def recentre(mesh, drop_to_zero: bool = True):
    """Move the mesh so it is centred in XY with its lowest point at z=0."""
    bounds = mesh.bounds
    shift = np.array([
        -(bounds[0][0] + bounds[1][0]) / 2.0,
        -(bounds[0][1] + bounds[1][1]) / 2.0,
        -bounds[0][2] if drop_to_zero else 0.0,
    ])
    mesh.apply_translation(shift)
    return mesh
