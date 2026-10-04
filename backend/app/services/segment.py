"""Separating the object from the sheet it lies on.

The naive approach -- threshold the photo, or hand a rectangle to GrabCut --
fails on exactly the things every real photo has: a cast shadow, light falling
unevenly across the sheet, and ruled or squared paper. This module models the
sheet instead of guessing at it.

The idea that does the work: a shadow scales every colour channel by about the
same factor, because it is the same light, just less of it. An object changes
the ratios between channels. So after dividing the photo by an estimate of the
paper's own brightness, a shadow shows up as "darker but still neutral" and an
object as "a different colour" -- which separates them without any threshold on
brightness alone.

What brightness alone cannot settle -- a grey object on white paper, which is
neutral and darker, exactly like a shadow -- is settled by the fact that an
object has a sharp edge and a cast shadow does not.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

Rect = tuple[int, int, int, int]


@dataclass(slots=True)
class TraceSettings:
    """Everything the tracing step exposes. All lengths in millimetres."""

    engine: str = "paper"            # paper | grabcut | ai

    # --- paper engine ---
    # The decisive threshold is not a fixed number but a multiple of the paper's
    # own noise, measured on this photograph. A fixed value cannot work: the
    # colour deviation that marks an object sits around 0.07 on plain paper and
    # the noise floor around 0.007, and both move with the camera and the light.
    sensitivity: float = 2.5         # multiples of the paper's noise
    chroma_threshold: float = 0.0    # 0 = derive it; a value overrides
    shadow_tolerance: float = 0.22   # near-black counts as object regardless.
                                     # Deliberately low: a hard cast shadow
                                     # reaches 0.37 of the paper's brightness,
                                     # darker than plenty of real parts, so
                                     # brightness cannot be the deciding cue.
    edge_strength: float = 0.0       # 0 = derive it
    # Off by default: a neutral grey part and a cast shadow are both "darker
    # but the same colour", so switching this on gains pale parts at the cost of
    # dragging shadows in. The AI engine handles that case far better.
    neutral_objects: bool = False
    texture_suppression_mm: float = 1.2   # removes ruled and squared lines
    illumination_order: int = 2      # polynomial fitted to the paper's brightness

    # --- shared ---
    # Only ever applied to a mask that needs it. The paper model already lands
    # the boundary inside a tenth of a millimetre; letting GrabCut loose on that
    # pulls it back out into the shadow, measurably worse.
    refine: bool = True              # tighten a coarse boundary with GrabCut
    refine_band_mm: float = 2.5
    close_mm: float = 0.8
    open_mm: float = 0.5
    fill_holes: bool = False
    min_area_mm2: float = 25.0
    smooth_mm: float = 0.0

    # --- ai engine ---
    ai_model: str = "u2netp"
    ai_threshold: float = 0.5

    # strokes the user painted, in rectified pixels
    foreground: list[list[tuple[int, int]]] = field(default_factory=list)
    background: list[list[tuple[int, int]]] = field(default_factory=list)
    brush: int = 10


def _px(millimetres: float, px_per_mm: float, minimum: int = 0) -> int:
    return max(minimum, int(round(millimetres * px_per_mm)))


def _odd(value: int) -> int:
    return value if value % 2 == 1 else value + 1


# --- paper model -------------------------------------------------------------

def estimate_paper(image: np.ndarray, exclude: np.ndarray | None,
                   order: int = 2) -> np.ndarray:
    """Per-pixel estimate of what the bare paper looks like.

    A smooth polynomial per colour channel, fitted only to pixels that are
    plausibly paper and refitted once with the darkest residuals thrown out, so
    that the object and its shadow do not drag the estimate down.
    """
    h, w = image.shape[:2]
    scale = 160.0 / max(h, w)
    small = cv2.resize(image, None, fx=scale, fy=scale,
                       interpolation=cv2.INTER_AREA).astype(np.float32)
    sh, sw = small.shape[:2]

    valid = np.ones((sh, sw), bool)
    if exclude is not None:
        mask = cv2.resize(exclude, (sw, sh), interpolation=cv2.INTER_NEAREST)
        valid &= mask == 0
    if valid.sum() < 40:
        valid = np.ones((sh, sw), bool)

    yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
    xx /= sw; yy /= sh
    terms = [np.ones_like(xx), xx, yy]
    if order >= 2:
        terms += [xx * xx, xx * yy, yy * yy]
    basis = np.stack([t.ravel() for t in terms], axis=1)

    fitted = np.zeros_like(small)
    for channel in range(3):
        values = small[:, :, channel].ravel()
        keep = valid.ravel().copy()
        for _ in range(2):
            if keep.sum() < basis.shape[1] + 2:
                break
            coefficients, *_ = np.linalg.lstsq(basis[keep], values[keep], rcond=None)
            model = basis @ coefficients
            residual = values - model
            # paper is the bright side: discard anything notably darker
            keep = valid.ravel() & (residual > -max(3.0, 1.2 * residual[keep].std()))
        fitted[:, :, channel] = (basis @ coefficients).reshape(sh, sw)

    fitted = np.clip(fitted, 1.0, None)
    return cv2.resize(fitted, (w, h), interpolation=cv2.INTER_LINEAR)


def paper_response(image: np.ndarray, px_per_mm: float,
                   settings: TraceSettings,
                   exclude: np.ndarray | None = None) -> dict[str, np.ndarray]:
    """Decompose the photo into 'how much darker' and 'how much other-coloured'."""
    blur = _odd(_px(settings.texture_suppression_mm, px_per_mm, 1))
    source = cv2.medianBlur(image, min(blur, 15)) if blur >= 3 else image

    paper = estimate_paper(source, exclude, settings.illumination_order)
    ratio = source.astype(np.float32) / paper

    luma = ratio.mean(axis=2)
    # how far the channels drift apart once the overall darkening is divided out
    chroma = np.abs(ratio - luma[..., None]).max(axis=2) / np.maximum(luma, 0.2)

    grey = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    sharp = cv2.magnitude(cv2.Scharr(grey, cv2.CV_32F, 1, 0),
                          cv2.Scharr(grey, cv2.CV_32F, 0, 1))
    sharp = cv2.GaussianBlur(sharp, (0, 0), max(1.0, px_per_mm * 0.25))

    return {"luma": luma, "chroma": chroma, "sharp": sharp, "paper": paper}


def calibrate(response: dict[str, np.ndarray], outside: np.ndarray,
              settings: TraceSettings) -> dict[str, float]:
    """Read the thresholds off the bare paper in this very photograph."""
    luma, chroma, sharp = response["luma"], response["chroma"], response["sharp"]
    paper = outside & (luma > 0.9)
    if paper.sum() < 500:
        paper = outside
    if paper.sum() < 500:
        paper = np.ones_like(luma, bool)

    chroma_floor = float(np.percentile(chroma[paper], 99.9))
    sharp_floor = float(np.percentile(sharp[paper], 99.5))
    luma_floor = float(np.percentile(luma[paper], 1.0))
    return {
        "chroma": settings.chroma_threshold or max(
            0.010, settings.sensitivity * chroma_floor),
        "sharp": settings.edge_strength or max(0.02, 1.4 * sharp_floor),
        # anything below the paper's own darkest 1 % is darker than paper
        "luma": min(0.99, luma_floor - 1.5 * (1.0 - luma_floor) - 0.004),
        "chroma_floor": chroma_floor,
    }


def paper_mask(image: np.ndarray, px_per_mm: float, settings: TraceSettings,
               rect: Rect | None = None,
               thresholds: dict | None = None) -> np.ndarray:
    """The object, as told apart from the paper and from its own shadow."""
    exclude = None
    outside = np.ones(image.shape[:2], bool)
    if rect is not None:
        exclude = np.zeros(image.shape[:2], np.uint8)
        x, y, w, h = rect
        cv2.rectangle(exclude, (x, y), (x + w, y + h), 255, -1)
        outside = exclude == 0

    response = paper_response(image, px_per_mm, settings, exclude)
    luma, chroma, sharp = response["luma"], response["chroma"], response["sharp"]
    limits = thresholds or calibrate(response, outside, settings)

    # A different colour is the one cue a shadow cannot fake: it dims every
    # channel by the same factor, so it stays neutral however dark it gets.
    coloured = chroma > limits["chroma"]
    # Darker than any plausible shadow.
    dark = luma < settings.shadow_tolerance
    # Neutral and only slightly darker -- a pale grey part looks exactly like a
    # shadow. What separates them is that the part has a crisp edge.
    ambiguous = np.zeros_like(coloured)
    if settings.neutral_objects:
        ambiguous = (luma < limits["luma"]) & ~coloured & ~dark
        crisp = (sharp > limits["sharp"]).astype(np.uint8)
        reach = _odd(_px(0.8, px_per_mm, 1))
        ambiguous &= cv2.dilate(crisp, np.ones((reach, reach), np.uint8)) > 0

    mask = ((coloured | dark | ambiguous).astype(np.uint8)) * 255
    if rect is not None:
        keep = np.zeros_like(mask)
        x, y, w, h = rect
        cv2.rectangle(keep, (x, y), (x + w, y + h), 255, -1)
        mask &= keep
    return mask


# --- cleanup and refinement --------------------------------------------------

def tidy(mask: np.ndarray, px_per_mm: float, settings: TraceSettings,
         anchor: tuple[int, int] | None = None,
         protect: np.ndarray | None = None) -> np.ndarray:
    """Morphology, then keep the blob the user actually pointed at.

    ``protect`` marks what the user painted as "keep": every blob it touches
    survives, whichever one is nearest the anchor. Painting has to add to the
    selection, not move it -- otherwise a stroke meant to recover a missing
    corner throws away the rest of the object.
    """
    close = _px(settings.close_mm, px_per_mm)
    if close:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (_odd(close * 2),) * 2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    opening = _px(settings.open_mm, px_per_mm)
    if opening:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (_odd(opening * 2),) * 2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    if count <= 1:
        return mask

    min_area = settings.min_area_mm2 * px_per_mm ** 2
    candidates = [i for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] >= min_area]
    if not candidates:
        candidates = [1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))]

    if anchor is not None:
        # The component nearest where the user drew, not merely the biggest --
        # otherwise a stray blob can steal the selection from one edit to the next.
        chosen = min(candidates, key=lambda i: (centroids[i][0] - anchor[0]) ** 2
                     + (centroids[i][1] - anchor[1]) ** 2)
    else:
        chosen = max(candidates, key=lambda i: stats[i, cv2.CC_STAT_AREA])

    keep = {chosen}
    if protect is not None and protect.any():
        keep.update(int(label) for label in np.unique(labels[protect > 0])
                    if label != 0)

    out = np.where(np.isin(labels, list(keep)), 255, 0).astype(np.uint8)
    if settings.fill_holes:
        filled = out.copy()
        flood = np.zeros((out.shape[0] + 2, out.shape[1] + 2), np.uint8)
        cv2.floodFill(filled, flood, (0, 0), 255)
        out |= cv2.bitwise_not(filled)
    return out


def refine_boundary(image: np.ndarray, mask: np.ndarray, px_per_mm: float,
                    settings: TraceSettings) -> np.ndarray:
    """Let GrabCut decide only the narrow band where the edge actually is.

    Seeded from a mask we already trust, GrabCut has a colour model worth having
    and only a few millimetres to search, which is both faster and far steadier
    than handing it a bare rectangle.
    """
    band = _px(settings.refine_band_mm, px_per_mm, 1)
    if band < 2 or mask.max() == 0:
        return mask

    kernel = np.ones((3, 3), np.uint8)
    sure_fg = cv2.erode(mask, kernel, iterations=band)
    sure_bg = cv2.bitwise_not(cv2.dilate(mask, kernel, iterations=band))
    if sure_fg.sum() < 255 * 50 or sure_bg.sum() < 255 * 50:
        return mask

    gc = np.full(mask.shape, cv2.GC_PR_BGD, np.uint8)
    gc[mask > 0] = cv2.GC_PR_FGD
    gc[sure_fg > 0] = cv2.GC_FGD
    gc[sure_bg > 0] = cv2.GC_BGD
    try:
        cv2.grabCut(image, gc, None, np.zeros((1, 65), np.float64),
                    np.zeros((1, 65), np.float64), 2, cv2.GC_INIT_WITH_MASK)
    except cv2.error:
        return mask
    return np.where((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)


# --- the learned engine ------------------------------------------------------

_SESSIONS: dict[str, object] = {}
_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], np.float32)
MODEL_SIZES = {"u2netp": 320, "u2net": 320, "isnet-general-use": 1024}


def model_path(name: str):
    from ..config import get_settings

    return get_settings().models_dir / f"{name}.onnx"


def ai_available(name: str = "u2net") -> bool:
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return model_path(name).exists()


def _session(name: str):
    if name not in _SESSIONS:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.log_severity_level = 3
        _SESSIONS[name] = ort.InferenceSession(
            str(model_path(name)), options, providers=["CPUExecutionProvider"])
    return _SESSIONS[name]


def ai_probability(image: np.ndarray, name: str = "u2net") -> np.ndarray:
    """How strongly a salient-object model thinks each pixel is the object.

    The model works at a fixed small input size, so the result is reliable about
    *where* the object is and vague about exactly where its edge runs. Treated
    accordingly: as a prior, never as the final mask.
    """
    session = _session(name)
    size = MODEL_SIZES.get(name, 320)

    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB).astype(np.float32)
    small = cv2.resize(rgb, (size, size), interpolation=cv2.INTER_AREA)
    small /= max(small.max(), 1e-6)
    small = (small - _IMAGENET_MEAN) / _IMAGENET_STD

    output = session.run(None, {session.get_inputs()[0].name:
                                small.transpose(2, 0, 1)[None]})[0]
    probability = output[0, 0]
    low, high = float(probability.min()), float(probability.max())
    probability = (probability - low) / max(high - low, 1e-6)
    return cv2.resize(probability, (image.shape[1], image.shape[0]),
                      interpolation=cv2.INTER_LINEAR)


# --- strokes -----------------------------------------------------------------

def stroke_mask(shape, strokes, brush: int) -> np.ndarray:
    canvas = np.zeros(shape[:2], np.uint8)
    for stroke in strokes:
        points = np.asarray(stroke, np.int32)
        if len(points) == 1:
            cv2.circle(canvas, tuple(points[0]), brush, 255, -1)
        elif len(points) > 1:
            cv2.polylines(canvas, [points], False, 255, brush * 2)
    return canvas


# --- the engine the API calls ------------------------------------------------

def trace(image: np.ndarray, px_per_mm: float, settings: TraceSettings,
          rect: Rect | None = None) -> dict:
    """Produce the object mask, by whichever engine was asked for.

    Whatever the engine decides, the strokes win: paint is a statement of fact
    from the person looking at the photograph, so it is applied as a hard
    constraint afterwards rather than as one more hint for the optimiser. That
    is what makes corrections behave -- painting one place can no longer make a
    different place change its mind.
    """
    engine = settings.engine
    if engine in ("ai", "hybrid") and not ai_available(settings.ai_model):
        engine = "paper"

    probability = None
    if engine in ("ai", "hybrid"):
        probability = ai_probability(image, settings.ai_model)

    # Refinement helps a coarse mask and harms a precise one, so it follows the
    # engine that actually produced the mask rather than the engine that was
    # asked for -- the hybrid can end up on either path.
    coarse = False
    if engine == "grabcut":
        mask = _grabcut_from_rect(image, rect)
    elif engine == "ai":
        mask = (probability > settings.ai_threshold).astype(np.uint8) * 255
        coarse = True
    elif engine == "hybrid":
        mask, coarse = _hybrid(image, px_per_mm, settings, rect, probability)
    else:
        mask = paper_mask(image, px_per_mm, settings, rect)

    forced_in = stroke_mask(image.shape, settings.foreground, settings.brush)
    forced_out = stroke_mask(image.shape, settings.background, settings.brush)
    if forced_in.any() or forced_out.any():
        mask = np.where(forced_in > 0, 255, mask)
        mask = np.where(forced_out > 0, 0, mask).astype(np.uint8)

    anchor = _anchor(rect, forced_in, mask)
    mask = tidy(mask, px_per_mm, settings, anchor, forced_in)

    if settings.refine and coarse:
        refined = refine_boundary(image, mask, px_per_mm, settings)
        # the strokes outrank the refinement too
        if forced_in.any() or forced_out.any():
            refined = np.where(forced_in > 0, 255, refined)
            refined = np.where(forced_out > 0, 0, refined).astype(np.uint8)
        mask = tidy(refined, px_per_mm, settings, anchor, forced_in)

    if settings.smooth_mm > 0:
        radius = _odd(_px(settings.smooth_mm, px_per_mm, 1))
        mask = cv2.GaussianBlur(mask, (radius, radius), 0)
        mask = ((mask > 127).astype(np.uint8)) * 255

    return {"mask": mask, "engine": engine, "refined": bool(coarse and settings.refine),
            "probability": probability}


def _anchor(rect, forced_in, mask) -> tuple[int, int] | None:
    """Where the user is pointing, so the chosen blob cannot wander off.

    The rectangle wins over the strokes: a stroke adds to the selection (see
    ``tidy``), it does not move it.
    """
    if rect is not None:
        x, y, w, h = rect
        return x + w // 2, y + h // 2
    if forced_in.any():
        ys, xs = np.nonzero(forced_in)
        return int(xs.mean()), int(ys.mean())
    if mask.any():
        ys, xs = np.nonzero(mask)
        return int(xs.mean()), int(ys.mean())
    return None


def _grabcut_from_rect(image: np.ndarray, rect: Rect | None) -> np.ndarray:
    """The old behaviour, kept so a difficult photo has a fallback."""
    height, width = image.shape[:2]
    if rect is None:
        rect = (width // 8, height // 8, width * 3 // 4, height * 3 // 4)
    x, y, w, h = rect
    x = max(0, min(x, width - 2)); y = max(0, min(y, height - 2))
    w = max(2, min(w, width - x)); h = max(2, min(h, height - y))

    mask = np.zeros((height, width), np.uint8)
    try:
        cv2.grabCut(image, mask, (x, y, w, h), np.zeros((1, 65), np.float64),
                    np.zeros((1, 65), np.float64), 5, cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        out = np.zeros((height, width), np.uint8)
        out[y:y + h, x:x + w] = 255
        return out
    return np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD),
                    255, 0).astype(np.uint8)


def snap_to_edges(image: np.ndarray, mask: np.ndarray, px_per_mm: float,
                  band_mm: float = 4.0) -> np.ndarray:
    """Pull a roughly-right boundary onto the nearest real edge.

    The learned model reasons at a few hundred pixels square, so it knows where
    the object is to within a millimetre or two but not where its edge runs.
    Watershed fixes that: flooding from inside and outside at once, the two
    fronts meet on the strongest ridge between them, which is the edge.
    """
    band = _px(band_mm, px_per_mm, 2)
    kernel = np.ones((3, 3), np.uint8)
    inner = cv2.erode(mask, kernel, iterations=band)
    outer = cv2.dilate(mask, kernel, iterations=band)
    if inner.max() == 0 or outer.min() == 255:
        return mask

    markers = np.zeros(mask.shape, np.int32)
    markers[outer == 0] = 1          # certainly background
    markers[inner > 0] = 2           # certainly object
    smoothed = cv2.bilateralFilter(image, 9, 60, 9)
    cv2.watershed(smoothed, markers)
    return np.where(markers == 2, 255, 0).astype(np.uint8)


def _hybrid(image: np.ndarray, px_per_mm: float, settings: TraceSettings,
            rect: Rect | None, probability: np.ndarray) -> tuple[np.ndarray, bool]:
    """Let each engine do what it is actually good at.

    The paper model is exact wherever colour separates object from sheet, which
    is most photographs, and it alone can tell a shadow from a part. The
    learned model has no blind spot but only a coarse idea of the edge, and it
    happily takes a cast shadow for part of the object.

    So the paper model leads, and the learned one is consulted only when the
    paper model came back with nothing worth having -- a pale, neutral part,
    the one case colour cannot settle. Merging the two masks was tried and is
    worse than either: the shadow the learned model includes destroys exactly
    the precision the paper model was brought in for.
    """
    paper = paper_mask(image, px_per_mm, settings, rect)

    area = float((paper > 0).sum())
    reference = float((probability > 0.5).sum())
    plausible = area > max(settings.min_area_mm2 * px_per_mm ** 2,
                           0.2 * reference)

    if plausible:
        return paper, False

    rough = (probability > settings.ai_threshold).astype(np.uint8) * 255
    if rough.max() == 0:
        return paper, False
    return snap_to_edges(image, rough, px_per_mm), True
