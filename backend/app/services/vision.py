"""Turning a photo into a millimetre-accurate outline.

The reference sheet in the photo gives us scale. We find its four corners,
warp the photo to a flat top-down view with a known millimetres-per-pixel
ratio, and from then on every coordinate is in millimetres.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

# name -> (width_mm, height_mm) in portrait orientation
PAPER_SIZES: dict[str, tuple[float, float]] = {
    "a4": (210.0, 297.0),
    "a5": (148.0, 210.0),
    "a3": (297.0, 420.0),
    "letter": (215.9, 279.4),
}

DEFAULT_DPI = 8.0   # rectified pixels per millimetre


@dataclass(slots=True)
class Rectification:
    corners: list[tuple[float, float]]   # source pixels, TL TR BR BL
    width_mm: float
    height_mm: float
    px_per_mm: float

    @property
    def size_px(self) -> tuple[int, int]:
        return (int(round(self.width_mm * self.px_per_mm)),
                int(round(self.height_mm * self.px_per_mm)))


def order_corners(pts: np.ndarray) -> np.ndarray:
    """Sort four points to top-left, top-right, bottom-right, bottom-left."""
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    centre = pts.mean(axis=0)
    angles = np.arctan2(pts[:, 1] - centre[1], pts[:, 0] - centre[0])
    order = np.argsort(angles)
    pts = pts[order]
    # angles start at -pi (left), rotate so the top-left corner leads
    start = int(np.argmin(pts.sum(axis=1)))
    return np.roll(pts, -start, axis=0)


def detect_sheet(image: np.ndarray) -> list[tuple[float, float]] | None:
    """Best-effort detection of a bright rectangular sheet.

    Returns the four corners in source pixels, or None when nothing
    convincing is found -- the UI then asks the user to place them.
    """
    h, w = image.shape[:2]
    scale = 1000.0 / max(h, w)
    small = cv2.resize(image, None, fx=scale, fy=scale,
                       interpolation=cv2.INTER_AREA) if scale < 1 else image.copy()
    inv = 1.0 / scale if scale < 1 else 1.0

    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 9, 60, 60)

    candidates: list[tuple[float, np.ndarray]] = []
    area_total = small.shape[0] * small.shape[1]

    for thresh in _candidate_masks(gray):
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < area_total * 0.05:
                continue
            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
            if len(approx) != 4 or not cv2.isContourConvex(approx):
                continue
            quad = order_corners(approx)
            if _corner_sanity(quad) and area < area_total * 0.98:
                candidates.append((area, quad))

    if not candidates:
        return None
    _, best = max(candidates, key=lambda c: c[0])
    return [(float(x) * inv, float(y) * inv) for x, y in best]


def _candidate_masks(gray: np.ndarray):
    """A few thresholdings, because paper on a desk is not always high contrast."""
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield otsu

    edges = cv2.Canny(blurred, 50, 150)
    yield cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))

    adaptive = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                     cv2.THRESH_BINARY, 51, -10)
    yield cv2.morphologyEx(adaptive, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))


def _corner_sanity(quad: np.ndarray) -> bool:
    """Reject quads whose corners are too far from right angles."""
    for i in range(4):
        a = quad[(i - 1) % 4] - quad[i]
        b = quad[(i + 1) % 4] - quad[i]
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na < 1e-6 or nb < 1e-6:
            return False
        angle = math.degrees(math.acos(
            float(np.clip(np.dot(a, b) / (na * nb), -1.0, 1.0))))
        if not 55.0 <= angle <= 125.0:
            return False
    return True


def guess_orientation(corners: list[tuple[float, float]],
                      paper: str) -> tuple[float, float]:
    """Decide whether the sheet is portrait or landscape in the photo."""
    w_mm, h_mm = PAPER_SIZES.get(paper, PAPER_SIZES["a4"])
    quad = np.asarray(corners, dtype=np.float32)
    top = np.linalg.norm(quad[1] - quad[0])
    bottom = np.linalg.norm(quad[2] - quad[3])
    left = np.linalg.norm(quad[3] - quad[0])
    right = np.linalg.norm(quad[2] - quad[1])
    horizontal = (top + bottom) / 2.0
    vertical = (left + right) / 2.0
    if horizontal > vertical:
        return h_mm, w_mm      # landscape
    return w_mm, h_mm


def rectify(image: np.ndarray, corners: list[tuple[float, float]], paper: str,
            px_per_mm: float = DEFAULT_DPI,
            size_mm: tuple[float, float] | None = None
            ) -> tuple[np.ndarray, Rectification]:
    """Warp the sheet to a flat, scale-true top-down view."""
    w_mm, h_mm = size_mm if size_mm else guess_orientation(corners, paper)
    rect = Rectification(corners=list(corners), width_mm=w_mm, height_mm=h_mm,
                         px_per_mm=px_per_mm)
    out_w, out_h = rect.size_px

    src = np.asarray(corners, dtype=np.float32).reshape(4, 2)
    dst = np.array([[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1],
                    [0, out_h - 1]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(image, matrix, (out_w, out_h),
                                 flags=cv2.INTER_CUBIC,
                                 borderMode=cv2.BORDER_REPLICATE)
    return warped, rect


# --- object segmentation ----------------------------------------------------

def segment(rectified: np.ndarray, rect_px: tuple[int, int, int, int],
            foreground: list[list[tuple[int, int]]] | None = None,
            background: list[list[tuple[int, int]]] | None = None,
            brush: int = 8, iterations: int = 5) -> np.ndarray:
    """GrabCut with optional user strokes. Returns a uint8 0/255 mask."""
    h, w = rectified.shape[:2]
    mask = np.full((h, w), cv2.GC_BGD, dtype=np.uint8)

    x, y, rw, rh = rect_px
    x = max(0, min(x, w - 2)); y = max(0, min(y, h - 2))
    rw = max(2, min(rw, w - x)); rh = max(2, min(rh, h - y))
    mask[y:y + rh, x:x + rw] = cv2.GC_PR_FGD

    for stroke in foreground or []:
        _draw_stroke(mask, stroke, cv2.GC_FGD, brush)
    for stroke in background or []:
        _draw_stroke(mask, stroke, cv2.GC_BGD, brush)

    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(rectified, mask, None, bgd, fgd, iterations,
                    cv2.GC_INIT_WITH_MASK)
    except cv2.error:
        # degenerate input (e.g. a uniform region) -- fall back to the rectangle
        out = np.zeros((h, w), np.uint8)
        out[y:y + rh, x:x + rw] = 255
        return out

    binary = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0)
    return binary.astype(np.uint8)


def _draw_stroke(mask: np.ndarray, stroke: list[tuple[int, int]], value: int,
                 brush: int) -> None:
    pts = np.asarray(stroke, dtype=np.int32)
    if len(pts) == 1:
        cv2.circle(mask, tuple(pts[0]), brush, value, -1)
    elif len(pts) > 1:
        cv2.polylines(mask, [pts], False, value, brush * 2)


def clean_mask(mask: np.ndarray, close: int = 5, open_: int = 3,
               keep_largest: bool = True) -> np.ndarray:
    """Morphological tidy-up plus optional speckle removal."""
    if close > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close * 2 + 1,) * 2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    if open_ > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_ * 2 + 1,) * 2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    if keep_largest:
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        if count > 1:
            biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
            mask = np.where(labels == biggest, 255, 0).astype(np.uint8)
    return mask


def mask_to_polygons(mask: np.ndarray, px_per_mm: float,
                     simplify_mm: float = 0.25,
                     min_area_mm2: float = 4.0,
                     smooth: float = 0.0,
                     include_holes: bool = True
                     ) -> tuple[list[tuple[float, float]], list[list[tuple[float, float]]]]:
    """Largest contour of the mask as an outline plus its holes, in millimetres.

    The origin is the mask's centre so that the outline is already centred on
    the cutout it will become.
    """
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP,
                                           cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return [], []

    areas = [cv2.contourArea(c) for c in contours]
    idx = int(np.argmax(areas))
    epsilon = max(0.5, simplify_mm * px_per_mm)

    h, w = mask.shape[:2]
    cx, cy = w / 2.0, h / 2.0

    def convert(contour: np.ndarray) -> list[tuple[float, float]]:
        pts = contour.reshape(-1, 2).astype(np.float64)
        if smooth > 0:
            pts = _smooth_closed(pts, smooth * px_per_mm)
        pts = cv2.approxPolyDP(pts.astype(np.float32).reshape(-1, 1, 2),
                               epsilon, True).reshape(-1, 2)
        # y flips: image rows grow downwards, millimetres grow upwards
        return [(float((px - cx) / px_per_mm), float((cy - py) / px_per_mm))
                for px, py in pts]

    outline = convert(contours[idx])
    holes: list[list[tuple[float, float]]] = []
    if include_holes and hierarchy is not None:
        for i, contour in enumerate(contours):
            if hierarchy[0][i][3] != idx:
                continue
            if cv2.contourArea(contour) < min_area_mm2 * px_per_mm ** 2:
                continue
            holes.append(convert(contour))
    return outline, holes


def _smooth_closed(pts: np.ndarray, sigma_px: float) -> np.ndarray:
    """Gaussian-smooth a closed contour, wrapping at the seam."""
    if sigma_px < 0.5 or len(pts) < 8:
        return pts
    radius = max(1, int(sigma_px * 2))
    kernel = cv2.getGaussianKernel(radius * 2 + 1, sigma_px).ravel()
    padded = np.vstack([pts[-radius:], pts, pts[:radius]])
    out = np.column_stack([
        np.convolve(padded[:, 0], kernel, mode="same")[radius:-radius],
        np.convolve(padded[:, 1], kernel, mode="same")[radius:-radius],
    ])
    return out


def auto_threshold_mask(rectified: np.ndarray) -> np.ndarray:
    """A quick mask for objects lying on a plain sheet, used as a starting guess."""
    gray = cv2.cvtColor(rectified, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    _, mask = cv2.threshold(gray, 0, 255,
                            cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    border = 4
    mask[:border, :] = 0; mask[-border:, :] = 0
    mask[:, :border] = 0; mask[:, -border:] = 0
    return clean_mask(mask)
