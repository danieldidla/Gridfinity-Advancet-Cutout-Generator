"""The optional 3D capture: guided shooting, reconstruction, reuse as a cutout."""

from __future__ import annotations

from fastapi import (APIRouter, Depends, File, HTTPException, Response,
                     UploadFile, status)
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import current_user, owned_project
from ..models import Job, Project, Scan, ScanShot, User
from ..scan import board as board_module
from ..scan import carve
from ..schemas import (JobOut, ScanCreate, ScanOut, ScanSettings, ShotOut)
from ..services import jobs, storage
from .projects import _scan_out

router = APIRouter(tags=["scans"])


@router.get("/api/scan-board.pdf")
def scan_board_pdf() -> Response:
    """The printable target. Deliberately open: it carries no user data."""
    return Response(board_module.board_pdf(), media_type="application/pdf",
                    headers={"Content-Disposition":
                             'inline; filename="gridfinity-scanboard-a4.pdf"'})


@router.get("/api/scan-board.png")
def scan_board_png() -> Response:
    return Response(storage.encode_png(board_module.render_board()),
                    media_type="image/png")


@router.get("/api/scan-board/info")
def scan_board_info() -> dict:
    spec = board_module.DEFAULT_BOARD
    return {
        "squares_x": spec.squares_x, "squares_y": spec.squares_y,
        "square_mm": spec.square_mm, "width_mm": spec.width_mm,
        "height_mm": spec.height_mm,
        "azimuth_sectors": carve.AZIMUTH_SECTORS,
        "elevation_bands": [list(b) for b in carve.ELEVATION_BANDS],
        "band_labels": list(carve.BAND_LABELS),
        "reconstruction_available": carve.reconstruction_available(),
    }


scoped = APIRouter(prefix="/api/projects/{project_id}/scans", tags=["scans"])


def _get_scan(db: Session, project: Project, scan_id: str) -> Scan:
    scan = db.get(Scan, scan_id)
    if scan is None or scan.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aufnahme nicht gefunden")
    return scan


@scoped.post("", response_model=ScanOut, status_code=status.HTTP_201_CREATED)
def create_scan(payload: ScanCreate, project: Project = Depends(owned_project),
                db: Session = Depends(get_db)) -> ScanOut:
    scan = Scan(project_id=project.id, name=payload.name,
                settings=ScanSettings().model_dump())
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return _scan_out(scan)


@scoped.get("", response_model=list[ScanOut])
def list_scans(project: Project = Depends(owned_project)) -> list[ScanOut]:
    return [_scan_out(s) for s in project.scans]


@scoped.get("/{scan_id}", response_model=ScanOut)
def read_scan(scan_id: str, project: Project = Depends(owned_project),
              db: Session = Depends(get_db)) -> ScanOut:
    return _scan_out(_get_scan(db, project, scan_id))


@scoped.get("/{scan_id}/shots", response_model=list[ShotOut])
def list_shots(scan_id: str, project: Project = Depends(owned_project),
               db: Session = Depends(get_db)) -> list[ScanShot]:
    scan = _get_scan(db, project, scan_id)
    return sorted(scan.shots, key=lambda s: s.sequence)


@scoped.post("/{scan_id}/shots", status_code=status.HTTP_201_CREATED)
async def add_shot(scan_id: str, file: UploadFile = File(...),
                   project: Project = Depends(owned_project),
                   db: Session = Depends(get_db)) -> dict:
    """Store one capture and tell the user straight away whether it is usable.

    Feedback has to be immediate -- the point of a guided capture is that you
    find out about a blurred or off-target shot while you can still retake it,
    not half an hour later when the reconstruction fails.
    """
    settings = get_settings()
    scan = _get_scan(db, project, scan_id)
    if scan.status == "processing":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Rekonstruktion läuft bereits")
    if len(scan.shots) >= settings.max_scan_images:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Maximal {settings.max_scan_images} Aufnahmen")

    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            "Datei zu gross")
    try:
        image = storage.decode_image(data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    image = storage.shrink_to(image, 2000)
    detection = carve.detect(image, board_module.DEFAULT_BOARD, 0)

    key = storage.new_key("scans", ".jpg")
    storage.write_bytes(key, storage.encode_jpeg(image, 88))

    sequence = 1 + max((s.sequence for s in scan.shots), default=0)
    azimuth = elevation = None
    if detection.usable:
        azimuth, elevation = _single_pose(image, detection)

    shot = ScanShot(
        scan_id=scan.id, sequence=sequence, storage_key=key,
        sharpness=detection.sharpness,
        corner_count=0 if detection.charuco_ids is None else len(detection.charuco_ids),
        azimuth=azimuth, elevation=elevation, usable=detection.usable,
    )
    db.add(shot)
    if scan.status == "ready":
        scan.status = "capturing"
    db.add(scan)
    db.commit()
    db.refresh(shot)

    return {
        "shot": ShotOut.model_validate(shot).model_dump(),
        "hint": _shot_hint(shot),
        "coverage": _live_coverage(scan, db),
    }


def _single_pose(image, detection) -> tuple[float | None, float | None]:
    """Rough camera direction for one shot, for live coverage feedback."""
    import math

    import cv2
    import numpy as np

    spec = board_module.DEFAULT_BOARD
    board = board_module.make_board(spec)
    try:
        obj, img = board.matchImagePoints(detection.charuco_corners,
                                          detection.charuco_ids)
        if obj is None or len(obj) < 6:
            return None, None
        h, w = image.shape[:2]
        guess = np.array([[w * 1.2, 0, w / 2], [0, w * 1.2, h / 2], [0, 0, 1]],
                         dtype=np.float64)
        ok, rvec, tvec = cv2.solvePnP(obj, img, guess, np.zeros(5))
        if not ok:
            return None, None
        rvec, tvec = carve._to_world(rvec, tvec, spec)
        pose = carve.ViewPose(0, rvec, tvec, len(detection.charuco_ids))
        position = pose.camera_position()
        cx, cy = spec.centre
        dx, dy, dz = position[0] - cx, position[1] - cy, position[2]
        horizontal = math.hypot(dx, dy)
        return (
            round((math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0, 1),
            round(math.degrees(math.atan2(dz, horizontal)), 1),
        )
    except cv2.error:
        return None, None


def _shot_hint(shot: ScanShot) -> str:
    if not shot.usable:
        return ("Board nicht erkannt – mehr vom Muster ins Bild nehmen und auf "
                "gleichmäßiges Licht achten.")
    if shot.sharpness < 40:
        return "Bild wirkt unscharf – bitte wiederholen."
    if shot.corner_count < 16:
        return "Nur wenig vom Board sichtbar – etwas weiter weg fotografieren."
    return "Aufnahme in Ordnung."


def _live_coverage(scan: Scan, db: Session) -> dict:
    """Approximate coverage from the per-shot poses, without a full solve."""
    import math

    filled: set[tuple[int, int]] = set()
    for shot in scan.shots:
        if shot.azimuth is None or shot.elevation is None:
            continue
        sector = int(shot.azimuth // (360.0 / carve.AZIMUTH_SECTORS)) % \
            carve.AZIMUTH_SECTORS
        for band, (lo, hi) in enumerate(carve.ELEVATION_BANDS):
            last = band == len(carve.ELEVATION_BANDS) - 1
            if lo <= shot.elevation < hi or (last and shot.elevation >= hi):
                filled.add((sector, band))
                break
    total = carve.AZIMUTH_SECTORS * len(carve.ELEVATION_BANDS)
    return {
        "sectors": carve.AZIMUTH_SECTORS,
        "bands": len(carve.ELEVATION_BANDS),
        "band_labels": list(carve.BAND_LABELS),
        "cells": [{"sector": s, "band": b, "covered": (s, b) in filled}
                  for b in range(len(carve.ELEVATION_BANDS))
                  for s in range(carve.AZIMUTH_SECTORS)],
        "covered": len(filled), "total": total,
        "ratio": len(filled) / total,
    }


@scoped.get("/{scan_id}/coverage")
def scan_coverage(scan_id: str, project: Project = Depends(owned_project),
                  db: Session = Depends(get_db)) -> dict:
    return _live_coverage(_get_scan(db, project, scan_id), db)


@scoped.get("/{scan_id}/shots/{shot_id}/file")
def shot_file(scan_id: str, shot_id: str,
              project: Project = Depends(owned_project),
              db: Session = Depends(get_db)) -> Response:
    scan = _get_scan(db, project, scan_id)
    shot = db.get(ScanShot, shot_id)
    if shot is None or shot.scan_id != scan.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aufnahme nicht gefunden")
    return Response(storage.read_bytes(shot.storage_key), media_type="image/jpeg")


@scoped.delete("/{scan_id}/shots/{shot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shot(scan_id: str, shot_id: str,
                project: Project = Depends(owned_project),
                db: Session = Depends(get_db)) -> Response:
    scan = _get_scan(db, project, scan_id)
    shot = db.get(ScanShot, shot_id)
    if shot is None or shot.scan_id != scan.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aufnahme nicht gefunden")
    storage.delete(shot.storage_key)
    db.delete(shot)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@scoped.post("/{scan_id}/reconstruct", response_model=JobOut,
             status_code=status.HTTP_202_ACCEPTED)
def reconstruct(scan_id: str, payload: ScanSettings | None = None,
                project: Project = Depends(owned_project),
                db: Session = Depends(get_db),
                user: User = Depends(current_user)) -> Job:
    scan = _get_scan(db, project, scan_id)
    # Checked before anything else: someone whose install lacks the libraries
    # should learn that now, not after shooting thirty photographs.
    if not carve.reconstruction_available():
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            "Die 3D-Rekonstruktion ist in dieser Installation nicht eingerichtet "
            "(SciPy und scikit-image fehlen). Fotos und Aussparungen "
            "funktionieren unabhängig davon.")

    usable = [s for s in scan.shots if s.usable]
    if len(usable) < 8:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Nur {len(usable)} verwertbare Aufnahmen – mindestens 8 notwendig")
    if scan.status == "processing":
        raise HTTPException(status.HTTP_409_CONFLICT, "Laeuft bereits")

    if payload is not None:
        scan.settings = payload.model_dump()
    scan.status = "processing"
    scan.message = "in der Warteschlange"
    db.add(scan)
    db.commit()

    return jobs.enqueue(db, "scan.reconstruct", {"scan_id": scan.id},
                        owner_id=user.id)


@scoped.get("/{scan_id}/mesh")
def scan_mesh(scan_id: str, project: Project = Depends(owned_project),
              db: Session = Depends(get_db)) -> Response:
    scan = _get_scan(db, project, scan_id)
    if not scan.mesh_key or not storage.exists(scan.mesh_key):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Noch kein Mesh")
    return Response(storage.read_bytes(scan.mesh_key), media_type="model/stl",
                    headers={"Content-Disposition":
                             f'attachment; filename="{scan.id}.stl"'})


@scoped.delete("/{scan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scan(scan_id: str, project: Project = Depends(owned_project),
                db: Session = Depends(get_db)) -> Response:
    scan = _get_scan(db, project, scan_id)
    for shot in scan.shots:
        storage.delete(shot.storage_key)
    storage.delete(scan.mesh_key)
    storage.delete(scan.voxel_key)
    db.delete(scan)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


jobs_router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@jobs_router.get("/{job_id}", response_model=JobOut)
def read_job(job_id: str, db: Session = Depends(get_db),
             user: User = Depends(current_user)) -> Job:
    job = db.get(Job, job_id)
    if job is None or (job.owner_id and job.owner_id != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Auftrag nicht gefunden")
    return job


@jobs_router.get("", response_model=list[JobOut])
def list_jobs(db: Session = Depends(get_db),
              user: User = Depends(current_user)) -> list[Job]:
    return list(db.execute(
        select(Job).where(Job.owner_id == user.id)
        .order_by(Job.created_at.desc()).limit(20)
    ).scalars())
