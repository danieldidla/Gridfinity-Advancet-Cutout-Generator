"""Tracing an object out of a photograph of a sheet of paper.

Built around the cases that went wrong in practice -- a cast shadow, squared
paper, uneven light -- with ground truth to measure against, because "looks
better" is not a thing one can regress against.
"""

import cv2
import numpy as np
import pytest

from app.services import segment as S

PPM = 6.0                       # px per mm; smaller than production, to stay quick
W, H = int(148 * PPM), int(210 * PPM)       # A5, enough to show the effects


def _object(kind: str) -> np.ndarray:
    mask = np.zeros((H, W), np.uint8)
    cx, cy = W // 2, H // 2
    if kind == "ring":
        cv2.circle(mask, (cx, cy), int(26 * PPM), 255, -1)
        cv2.circle(mask, (cx, cy), int(9 * PPM), 0, -1)
    elif kind == "bracket":
        cv2.rectangle(mask, (cx - int(30 * PPM), cy - int(8 * PPM)),
                      (cx + int(30 * PPM), cy + int(8 * PPM)), 255, -1)
        cv2.rectangle(mask, (cx - int(30 * PPM), cy - int(8 * PPM)),
                      (cx - int(14 * PPM), cy + int(26 * PPM)), 255, -1)
    else:
        cv2.rectangle(mask, (cx - int(25 * PPM), cy - int(16 * PPM)),
                      (cx + int(25 * PPM), cy + int(16 * PPM)), 255, -1)
    return mask


def scene(kind="block", paper="plain", shadow=0.0, contrast="high",
          gradient=0.3, seed=0):
    """A photograph of the sheet, plus the mask the tracing should produce."""
    rng = np.random.default_rng(seed)
    truth = _object(kind)

    base = np.full((H, W, 3), 238.0, np.float32)
    if paper == "grid":
        for x in range(0, W, int(5 * PPM)):
            base[:, x:x + 2] = (225, 205, 180)
        for y in range(0, H, int(5 * PPM)):
            base[y:y + 2, :] = (225, 205, 180)

    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    light = 1.0 - gradient * ((xx / W) * 0.6 + (yy / H) * 0.4)
    base *= light[..., None]

    colour = {"high": (70, 75, 80), "low": (196, 199, 201),
              "colour": (60, 110, 170)}[contrast]
    image = base.copy()
    inside = truth > 0
    image[inside] = (np.asarray(colour, np.float32)[None, None, :]
                     * (0.75 + 0.25 * light[..., None]))[inside]

    if shadow > 0:
        offset = int(6 * PPM)
        cast = np.zeros((H, W), np.float32)
        cast[offset:, offset:] = truth[:H - offset, :W - offset] / 255.0
        cast = cv2.GaussianBlur(cast, (0, 0), 7.0)
        cast[inside] = 0.0
        image *= (1.0 - shadow * cast)[..., None]

    image += rng.normal(0, 3.0, image.shape)
    return np.clip(image, 0, 255).astype(np.uint8), truth


def iou(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a > 0, b > 0
    union = (a | b).sum()
    return float((a & b).sum() / union) if union else 0.0


def rect_around(truth: np.ndarray, pad_mm: float = 8.0):
    ys, xs = np.nonzero(truth)
    pad = int(pad_mm * PPM)
    x0, y0 = max(0, xs.min() - pad), max(0, ys.min() - pad)
    x1 = min(W - 1, xs.max() + pad)
    y1 = min(H - 1, ys.max() + pad)
    return (x0, y0, x1 - x0, y1 - y0)


def run(image, truth, **overrides):
    settings = S.TraceSettings(**overrides)
    return S.trace(image, PPM, settings, rect_around(truth))["mask"]


# --- the cases that drove this engine ---------------------------------------

@pytest.mark.parametrize("name,kwargs,floor", [
    ("plain", dict(), 0.95),
    ("cast shadow", dict(shadow=0.45, kind="ring"), 0.93),
    ("hard shadow", dict(shadow=0.62, kind="bracket"), 0.90),
    ("squared paper", dict(paper="grid", kind="ring"), 0.93),
    ("squared paper and shadow", dict(paper="grid", shadow=0.45), 0.90),
    ("coloured part", dict(contrast="colour", shadow=0.4), 0.93),
    ("steep light gradient", dict(gradient=0.55, shadow=0.3), 0.90),
])
def test_paper_engine_handles_the_hard_cases(name, kwargs, floor):
    image, truth = scene(**kwargs)
    assert iou(run(image, truth, engine="paper"), truth) >= floor, name


def test_shadow_is_not_taken_for_the_object():
    """The whole point of modelling the paper: a shadow dims every channel
    alike, an object changes the ratios between them."""
    image, truth = scene(kind="ring", shadow=0.55)
    mask = run(image, truth, engine="paper")

    shadow_only = (cv2.dilate(truth, np.ones((int(14 * PPM),) * 2, np.uint8)) > 0) \
        & (truth == 0)
    leaked = (mask > 0) & shadow_only
    assert leaked.sum() < 0.05 * shadow_only.sum(), \
        f"{100 * leaked.sum() / shadow_only.sum():.0f}% des Schattens wurde mitgenommen"


def test_squared_paper_is_not_mistaken_for_the_object():
    image, truth = scene(paper="grid", kind="ring")
    mask = run(image, truth, engine="paper")
    outside = (cv2.dilate(truth, np.ones((int(20 * PPM),) * 2, np.uint8)) == 0)
    assert (mask > 0)[outside].sum() < 0.01 * outside.sum()


def test_boundary_lands_within_half_a_millimetre():
    image, truth = scene(kind="block", shadow=0.4)
    mask = run(image, truth, engine="paper")
    edges = cv2.Canny(mask, 50, 150) > 0
    distance = cv2.distanceTransform(255 - cv2.Canny(truth, 50, 150), cv2.DIST_L2, 5)
    assert float(distance[edges].mean()) / PPM < 0.5


def test_holes_in_the_object_survive():
    image, truth = scene(kind="ring", shadow=0.3)
    mask = run(image, truth, engine="paper")
    centre = mask[H // 2 - 5:H // 2 + 5, W // 2 - 5:W // 2 + 5]
    assert centre.max() == 0, "das Loch in der Mitte wurde zugemacht"


# --- corrections ------------------------------------------------------------

def test_a_stroke_is_obeyed_and_changes_nothing_elsewhere():
    """The complaint this was built for: correcting one place used to make a
    different place change its mind."""
    image, truth = scene(kind="block", shadow=0.4)
    before = run(image, truth, engine="paper")

    point = (W // 2 + int(40 * PPM), H // 2)      # plainly outside the object
    after = run(image, truth, engine="paper",
                foreground=[[point]], brush=int(4 * PPM))

    assert after[point[1], point[0]] > 0, "der Strich wurde nicht befolgt"

    painted = cv2.dilate(S.stroke_mask(image.shape, [[point]], int(4 * PPM)),
                         np.ones((int(8 * PPM),) * 2, np.uint8)) > 0
    assert iou(before[~painted], after[~painted]) > 0.99, \
        "die Korrektur hat anderswo etwas verändert"


def test_painting_background_removes_what_was_painted():
    image, truth = scene(kind="block")
    ys, xs = np.nonzero(truth)
    point = (int(xs.mean()), int(ys.mean()))
    mask = run(image, truth, engine="paper",
               background=[[point]], brush=int(5 * PPM))
    assert mask[point[1], point[0]] == 0


# --- engine selection -------------------------------------------------------

def test_every_engine_returns_something_usable():
    image, truth = scene(kind="block", shadow=0.35)
    for engine in ("paper", "hybrid", "grabcut"):
        mask = run(image, truth, engine=engine)
        assert mask.max() > 0, engine
        assert iou(mask, truth) > 0.5, engine


def test_ai_engines_fall_back_when_no_model_is_installed(monkeypatch):
    """A missing model must degrade to the paper engine, not raise."""
    monkeypatch.setattr(S, "ai_available", lambda name="u2net": False)
    image, truth = scene(kind="block", shadow=0.35)
    settings = S.TraceSettings(engine="hybrid")
    result = S.trace(image, PPM, settings, rect_around(truth))
    assert result["engine"] == "paper"
    assert iou(result["mask"], truth) > 0.9


def test_sensitivity_changes_how_much_is_taken():
    image, truth = scene(kind="block", contrast="low", shadow=0.2)
    greedy = run(image, truth, engine="paper", sensitivity=1.2).sum()
    cautious = run(image, truth, engine="paper", sensitivity=8.0).sum()
    assert greedy >= cautious


def test_thresholds_are_read_off_the_photograph():
    """A fixed threshold cannot work across cameras; it has to be calibrated."""
    bright, truth = scene(kind="block")
    dim = (bright.astype(np.float32) * 0.55).astype(np.uint8)
    assert iou(run(bright, truth, engine="paper"), truth) > 0.93
    assert iou(run(dim, truth, engine="paper"), truth) > 0.93
