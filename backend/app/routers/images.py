"""Reference photos: upload, sheet detection, rectification and tracing."""

from __future__ import annotations

import base64
import time

import cv2
import numpy as np
from fastapi import (APIRouter, Depends, File, HTTPException, Query, Response,
                     UploadFile, status)
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import owned_project
from ..models import Image, Project
from ..schemas import (ImageOut, ImageUpdate, RectifyRequest, TraceRequest,
                       TraceResult, UploadResult)
from ..services import segment, storage, vision
from .projects import _image_out

router = APIRouter(prefix="/api/projects/{project_id}/images", tags=["images"])


def _get_image(db: Session, project: Project, image_id: str) -> Image:
    image = db.get(Image, image_id)
    if image is None or image.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bild nicht gefunden")
    return image


@router.post("", response_model=UploadResult,
             status_code=status.HTTP_201_CREATED)
async def upload_images(files: list[UploadFile] = File(...),
                        project: Project = Depends(owned_project),
                        db: Session = Depends(get_db)) -> UploadResult:
    """Take any number of photographs at once.

    Shooting and tracing are separate jobs done in different places: the phone
    is where the photographs happen, a desk with a mouse is where the outlines
    get drawn. So uploading accepts a whole batch and asks nothing further --
    the sheet is detected on the way in, and the rest waits for later.
    """
    settings = get_settings()
    stored: list[ImageOut] = []
    failed: list[dict] = []

    for upload in files:
        name = upload.filename or "foto.jpg"
        data = await upload.read()
        if len(data) > settings.max_upload_mb * 1024 * 1024:
            failed.append({"filename": name,
                           "reason": f"größer als {settings.max_upload_mb} MB"})
            continue
        try:
            decoded = storage.decode_image(data)
        except ValueError as exc:
            failed.append({"filename": name, "reason": str(exc)})
            continue

        # Phone photos are far larger than we need; 2600 px keeps well under a
        # tenth of a millimetre per pixel on an A4 sheet.
        decoded = storage.shrink_to(decoded, 2600)
        key = storage.new_key("images", ".jpg")
        storage.write_bytes(key, storage.encode_jpeg(decoded, 90))

        corners = vision.detect_sheet(decoded)
        image = Image(
            project_id=project.id, filename=name, storage_key=key,
            width=decoded.shape[1], height=decoded.shape[0],
            corners=[list(c) for c in corners] if corners else None,
        )
        db.add(image)
        db.commit()
        db.refresh(image)
        stored.append(_image_out(image))

    if not stored and failed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "; ".join(f["reason"] for f in failed))
    return UploadResult(images=stored, failed=failed)


@router.patch("/{image_id}", response_model=ImageOut)
def update_image(image_id: str, payload: ImageUpdate,
                 project: Project = Depends(owned_project),
                 db: Session = Depends(get_db)) -> ImageOut:
    image = _get_image(db, project, image_id)
    if payload.note is not None:
        image.note = payload.note
    if payload.processed is not None:
        image.processed = payload.processed
    db.add(image)
    db.commit()
    db.refresh(image)
    return _image_out(image)


@router.get("", response_model=list[ImageOut])
def list_images(project: Project = Depends(owned_project)) -> list[ImageOut]:
    return [_image_out(i) for i in project.images]


@router.get("/{image_id}/file")
def image_file(image_id: str, rectified: bool = Query(default=False),
               project: Project = Depends(owned_project),
               db: Session = Depends(get_db)) -> Response:
    image = _get_image(db, project, image_id)
    key = image.rectified_key if rectified else image.storage_key
    if not key or not storage.exists(key):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Datei nicht vorhanden")
    return Response(storage.read_bytes(key), media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=86400"})


@router.post("/{image_id}/detect", response_model=ImageOut)
def redetect(image_id: str, project: Project = Depends(owned_project),
             db: Session = Depends(get_db)) -> ImageOut:
    image = _get_image(db, project, image_id)
    corners = vision.detect_sheet(storage.load_image(image.storage_key))
    if corners is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Blatt nicht erkannt - Ecken bitte von Hand setzen")
    image.corners = [list(c) for c in corners]
    db.add(image)
    db.commit()
    db.refresh(image)
    return _image_out(image)


@router.post("/{image_id}/rectify", response_model=ImageOut)
def rectify_image(image_id: str, payload: RectifyRequest,
                  project: Project = Depends(owned_project),
                  db: Session = Depends(get_db)) -> ImageOut:
    image = _get_image(db, project, image_id)
    source = storage.load_image(image.storage_key)
    warped, rect = vision.rectify(source, [tuple(c) for c in payload.corners],
                                  payload.paper, payload.px_per_mm,
                                  payload.size_mm)

    storage.delete(image.rectified_key)
    key = storage.new_key("images", ".jpg")
    storage.write_bytes(key, storage.encode_jpeg(warped, 92))

    image.rectified_key = key
    image.corners = [list(c) for c in payload.corners]
    image.paper = payload.paper
    image.px_per_mm = rect.px_per_mm
    image.trace = {**(image.trace or {}),
                   "width_mm": rect.width_mm, "height_mm": rect.height_mm}
    db.add(image)
    db.commit()
    db.refresh(image)
    return _image_out(image)


@router.post("/{image_id}/trace", response_model=TraceResult)
def trace_image(image_id: str, payload: TraceRequest,
                project: Project = Depends(owned_project),
                db: Session = Depends(get_db)) -> TraceResult:
    """Segment the object in the rectified photo and return its outline in mm."""
    image = _get_image(db, project, image_id)
    if not image.rectified_key:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Bild muss zuerst entzerrt werden")
    rectified = storage.load_image(image.rectified_key)

    settings = segment.TraceSettings(
        engine=payload.engine,
        sensitivity=payload.sensitivity,
        shadow_tolerance=payload.shadow_tolerance,
        texture_suppression_mm=payload.texture_suppression_mm,
        neutral_objects=payload.neutral_objects,
        illumination_order=payload.illumination_order,
        refine=payload.refine,
        refine_band_mm=payload.refine_band_mm,
        close_mm=payload.close_mm,
        open_mm=payload.open_mm,
        fill_holes=payload.fill_holes,
        min_area_mm2=payload.min_area_mm2,
        smooth_mm=payload.smooth_mm,
        ai_model=get_settings().segmentation_model,
        ai_threshold=payload.ai_threshold,
        foreground=[s.points for s in payload.strokes if s.foreground],
        background=[s.points for s in payload.strokes if not s.foreground],
        brush=payload.brush,
    )

    started = time.perf_counter()
    result = segment.trace(rectified, image.px_per_mm, settings, payload.rect)
    took = (time.perf_counter() - started) * 1000.0
    mask = result["mask"]

    if mask.sum() == 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Kein Objekt gefunden. Empfindlichkeit erhöhen, einen Rahmen "
            "ziehen oder mit „Behalten“ über das Objekt malen.")

    outline, holes = vision.mask_to_polygons(
        mask, image.px_per_mm, simplify_mm=payload.simplify_mm,
        min_area_mm2=payload.min_hole_area_mm2, smooth=0.0,
        include_holes=payload.include_holes,
    )
    if len(outline) < 3:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Kontur zu klein")

    # Remember what worked, so reopening the photo starts where it left off.
    image.settings = payload.model_dump(exclude={"strokes", "rect"})
    db.add(image)
    db.commit()

    points = np.asarray(outline)
    preview = storage.encode_png(storage.shrink_to(
        cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR), 700))
    return TraceResult(
        polygon=[tuple(p) for p in outline],
        holes=[[tuple(p) for p in hole] for hole in holes],
        width_mm=round(float(np.ptp(points[:, 0])), 2),
        height_mm=round(float(np.ptp(points[:, 1])), 2),
        area_mm2=round(float((mask > 0).sum()) / (image.px_per_mm ** 2), 2),
        mask_preview="data:image/png;base64," + base64.b64encode(preview).decode(),
        engine_used=result["engine"],
        took_ms=round(took, 1),
    )


@router.delete("/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_image(image_id: str, project: Project = Depends(owned_project),
                 db: Session = Depends(get_db)) -> Response:
    image = _get_image(db, project, image_id)
    storage.delete(image.storage_key)
    storage.delete(image.rectified_key)
    db.delete(image)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
