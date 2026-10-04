"""Live preview, statistics and print-ready exports."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Header, Path, Response, status

from ..deps import current_user
from ..gridfinity import exporters
from ..gridfinity import spec as S
from ..models import User
from ..schemas import BuildRequest, ModelStats
from ..services import preview

router = APIRouter(prefix="/api/geometry", tags=["geometry"])


@router.get("/spec")
def gridfinity_spec() -> dict:
    """The dimensional constants, so the 2D editor can draw a true grid."""
    return {
        "grid_pitch": S.GRID_PITCH,
        "bin_size": S.BIN_SIZE,
        "height_unit": S.HEIGHT_UNIT,
        "base_height": S.BASE_HEIGHT,
        "lip_height": S.LIP_HEIGHT,
        "outer_radius": S.OUTER_RADIUS,
        "hole_offset": S.HOLE_OFFSET,
        "defaults": {
            "wall": S.DEFAULT_WALL,
            "floor": S.DEFAULT_FLOOR,
            "magnet_diameter": S.MAGNET_DIAMETER,
            "magnet_depth": S.MAGNET_DEPTH,
            "screw_diameter": S.SCREW_DIAMETER,
            "screw_depth": S.SCREW_DEPTH,
        },
    }


@router.post("/stats", response_model=ModelStats)
def model_stats(payload: BuildRequest,
                user: User = Depends(current_user)) -> ModelStats:
    return preview.stats(payload.bin, payload.cutouts)


@router.post("/preview.glb")
def preview_glb(payload: BuildRequest, user: User = Depends(current_user),
                if_none_match: str | None = Header(default=None)) -> Response:
    """The mesh the 3D view renders.

    Tagged with the hash of the inputs, so a slider nudged back to where it was
    costs a 304 rather than a rebuild and a download.
    """
    data, key = preview.get_glb(payload.bin, payload.cutouts)
    etag = f'W/"{key}"'
    if if_none_match == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED,
                        headers={"ETag": etag})
    return Response(data, media_type="model/gltf-binary",
                    headers={"ETag": etag, "Cache-Control": "private, max-age=600"})


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@router.post("/export.{fmt}")
def export_model(payload: BuildRequest,
                 fmt: str = Path(pattern="^(stl|3mf)$"),
                 name: str = "gridfinity-bin",
                 user: User = Depends(current_user)) -> Response:
    solid, _ = preview.get_model(payload.bin, payload.cutouts)
    safe = _SAFE_NAME.sub("-", name).strip("-") or "gridfinity-bin"
    settings = payload.bin
    filename = (f"{safe}-{settings.grid_x}x{settings.grid_y}x"
                f"{settings.height_units:g}u.{fmt}")

    if fmt == "stl":
        data = exporters.export_stl(solid)
        media = "model/stl"
    else:
        data = exporters.export_3mf(solid, name=safe)
        media = "model/3mf"

    return Response(data, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
    })
