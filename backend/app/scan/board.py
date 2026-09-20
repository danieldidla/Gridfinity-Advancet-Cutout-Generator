"""The printable ChArUco board that gives the 3D capture its scale and poses."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

DICTIONARY = cv2.aruco.DICT_5X5_250


@dataclass(frozen=True, slots=True)
class BoardSpec:
    """A ChArUco board sized to print on one A4 sheet with a margin."""

    squares_x: int = 7
    squares_y: int = 10
    square_mm: float = 25.0
    marker_ratio: float = 0.72
    margin_mm: float = 10.0

    @property
    def marker_mm(self) -> float:
        return self.square_mm * self.marker_ratio

    @property
    def width_mm(self) -> float:
        return self.squares_x * self.square_mm

    @property
    def height_mm(self) -> float:
        return self.squares_y * self.square_mm

    @property
    def centre(self) -> tuple[float, float]:
        return self.width_mm / 2.0, self.height_mm / 2.0


DEFAULT_BOARD = BoardSpec()


def make_board(spec: BoardSpec = DEFAULT_BOARD) -> cv2.aruco.CharucoBoard:
    dictionary = cv2.aruco.getPredefinedDictionary(DICTIONARY)
    board = cv2.aruco.CharucoBoard(
        (spec.squares_x, spec.squares_y),
        spec.square_mm, spec.marker_mm, dictionary,
    )
    board.setLegacyPattern(False)
    return board


def render_board(spec: BoardSpec = DEFAULT_BOARD, px_per_mm: float = 10.0,
                 with_margin: bool = True) -> np.ndarray:
    """A print-ready greyscale image of the board."""
    board = make_board(spec)
    w = int(round(spec.width_mm * px_per_mm))
    h = int(round(spec.height_mm * px_per_mm))
    image = board.generateImage((w, h))
    if not with_margin:
        return image
    m = int(round(spec.margin_mm * px_per_mm))
    return cv2.copyMakeBorder(image, m, m, m, m, cv2.BORDER_CONSTANT, value=255)


def board_pdf(spec: BoardSpec = DEFAULT_BOARD) -> bytes:
    """Wrap the board in a single A4 PDF page at exact scale.

    Written by hand rather than pulled in as a dependency: it is one image on
    one page, and getting the scale right matters more than features.
    """
    import io
    import zlib

    from PIL import Image

    image = render_board(spec, px_per_mm=12.0, with_margin=False)
    pil = Image.fromarray(image).convert("L")
    raw = pil.tobytes()
    compressed = zlib.compress(raw, 9)

    pt = 72.0 / 25.4                     # PostScript points per millimetre
    page_w, page_h = 210.0 * pt, 297.0 * pt
    draw_w, draw_h = spec.width_mm * pt, spec.height_mm * pt
    off_x = (page_w - draw_w) / 2.0
    off_y = (page_h - draw_h) / 2.0

    label = (f"ChArUco {spec.squares_x}x{spec.squares_y} - "
             f"square {spec.square_mm:g} mm - print at 100%, no scaling")
    content = (
        f"q\n{draw_w:.3f} 0 0 {draw_h:.3f} {off_x:.3f} {off_y:.3f} cm\n"
        f"/Im0 Do\nQ\n"
        f"BT /F1 9 Tf {off_x:.3f} {off_y - 16:.3f} Td ({label}) Tj ET\n"
    ).encode("latin-1")

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_w:.3f} {page_h:.3f}]"
         f" /Resources << /XObject << /Im0 5 0 R >> /Font << /F1 6 0 R >> >>"
         f" /Contents 4 0 R >>").encode("latin-1"),
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
        + content + b"\nendstream",
        (f"<< /Type /XObject /Subtype /Image /Width {pil.width} /Height {pil.height}"
         f" /ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode"
         f" /Length {len(compressed)} >>").encode("latin-1")
        + b"\nstream\n" + compressed + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_at = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
              f"startxref\n{xref_at}\n%%EOF\n".encode())
    return out.getvalue()
