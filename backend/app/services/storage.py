"""Files on disk, addressed by opaque keys."""

from __future__ import annotations

import secrets
from pathlib import Path

import cv2
import numpy as np

from ..config import get_settings

_ALLOWED = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".stl", ".npz",
            ".glb", ".3mf"}


def _root() -> Path:
    return get_settings().data_dir


def new_key(prefix: str, suffix: str) -> str:
    if suffix and not suffix.startswith("."):
        suffix = "." + suffix
    return f"{prefix}/{secrets.token_hex(16)}{suffix}"


def path_for(key: str) -> Path:
    """Resolve a storage key, refusing anything that escapes the data dir."""
    root = _root().resolve()
    candidate = (root / key).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("ungültiger Speicherschlüssel")
    return candidate


def write_bytes(key: str, data: bytes) -> Path:
    target = path_for(key)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def read_bytes(key: str) -> bytes:
    return path_for(key).read_bytes()


def exists(key: str) -> bool:
    try:
        return path_for(key).exists()
    except ValueError:
        return False


def delete(key: str | None) -> None:
    if not key:
        return
    try:
        target = path_for(key)
    except ValueError:
        return
    target.unlink(missing_ok=True)


def decode_image(data: bytes) -> np.ndarray:
    array = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Bild konnte nicht gelesen werden")
    return image


def load_image(key: str) -> np.ndarray:
    return decode_image(read_bytes(key))


def encode_jpeg(image: np.ndarray, quality: int = 88) -> bytes:
    ok, buffer = cv2.imencode(".jpg", image,
                              [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise ValueError("JPEG-Kodierung fehlgeschlagen")
    return buffer.tobytes()


def encode_png(image: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("PNG-Kodierung fehlgeschlagen")
    return buffer.tobytes()


def shrink_to(image: np.ndarray, longest_edge: int) -> np.ndarray:
    h, w = image.shape[:2]
    longest = max(h, w)
    if longest <= longest_edge:
        return image
    scale = longest_edge / longest
    return cv2.resize(image, (int(round(w * scale)), int(round(h * scale))),
                      interpolation=cv2.INTER_AREA)


def guess_suffix(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    return suffix if suffix in _ALLOWED else ".jpg"
