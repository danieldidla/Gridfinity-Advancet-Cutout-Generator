"""Puts a bin and its cutouts together."""

from __future__ import annotations

from pathlib import Path

from manifold3d import Manifold, OpType

from . import spec as S
from .bin_builder import build_bin
from .cutouts import build_cutout


def build_model(binspec: S.BinSpec, cuts: list[S.CutoutSpec],
                mesh_dir: Path | None = None,
                bin_solid: Manifold | None = None) -> Manifold:
    """The final printable solid.

    ``bin_solid`` lets a caller pass a cached shell so that dragging a cutout
    around only pays for the boolean, not for rebuilding the bin.
    """
    solid = bin_solid if bin_solid is not None else build_bin(binspec)

    negatives = []
    for cut in cuts:
        neg = build_cutout(cut, binspec, mesh_dir)
        if neg is not None and not neg.is_empty():
            negatives.append(neg)

    if negatives:
        solid = Manifold.batch_boolean([solid] + negatives, OpType.Subtract)
    return solid
