"""Projects: the autosaved document at the centre of the editor."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user, owned_project
from ..models import Image, Project, Scan, User
from ..schemas import (ImageOut, ProjectCreate, ProjectOut, ProjectState,
                       ProjectSummary, ProjectUpdate, ScanOut)
from ..services import storage

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _image_out(image: Image) -> ImageOut:
    return ImageOut(
        id=image.id, filename=image.filename, width=image.width,
        height=image.height, paper=image.paper, corners=image.corners,
        px_per_mm=image.px_per_mm,
        has_rectified=bool(image.rectified_key),
        trace=image.trace or {},
    )


def _scan_out(scan: Scan) -> ScanOut:
    return ScanOut(
        id=scan.id, name=scan.name, status=scan.status, coverage=scan.coverage,
        dimensions=scan.dimensions, message=scan.message,
        shot_count=len(scan.shots), has_mesh=bool(scan.mesh_key),
    )


def _project_out(project: Project) -> ProjectOut:
    return ProjectOut(
        id=project.id, name=project.name, revision=project.revision,
        created_at=project.created_at, updated_at=project.updated_at,
        thumbnail=project.thumbnail,
        state=ProjectState.model_validate(project.state or {}),
        images=[_image_out(i) for i in project.images],
        scans=[_scan_out(s) for s in project.scans],
    )


@router.get("", response_model=list[ProjectSummary])
def list_projects(db: Session = Depends(get_db),
                  user: User = Depends(current_user)) -> list[Project]:
    return list(db.execute(
        select(Project).where(Project.owner_id == user.id)
        .order_by(Project.updated_at.desc())
    ).scalars())


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db),
                   user: User = Depends(current_user)) -> ProjectOut:
    state = payload.state or ProjectState()
    project = Project(owner_id=user.id, name=payload.name,
                      state=state.model_dump(mode="json"), revision=1)
    db.add(project)
    db.commit()
    db.refresh(project)
    return _project_out(project)


@router.get("/{project_id}", response_model=ProjectOut)
def read_project(project: Project = Depends(owned_project)) -> ProjectOut:
    return _project_out(project)


@router.patch("/{project_id}", response_model=ProjectSummary)
def update_project(payload: ProjectUpdate, project: Project = Depends(owned_project),
                   db: Session = Depends(get_db)) -> Project:
    """Autosave endpoint.

    ``revision`` is a courtesy check for two tabs editing the same project: a
    stale write is refused rather than silently clobbering the newer state.
    """
    if payload.revision is not None and payload.revision < project.revision:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Projekt wurde anderweitig geaendert (Stand {project.revision})")

    if payload.name is not None:
        project.name = payload.name
    if payload.state is not None:
        project.state = payload.state.model_dump(mode="json")
        project.revision += 1
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.put("/{project_id}/thumbnail", status_code=status.HTTP_204_NO_CONTENT,
            response_class=Response)
def set_thumbnail(payload: dict, project: Project = Depends(owned_project),
                  db: Session = Depends(get_db)) -> Response:
    data = payload.get("data_url", "")
    if not isinstance(data, str) or not data.startswith("data:image/"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kein Bild")
    if len(data) > 400_000:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            "Vorschaubild zu gross")
    project.thumbnail = data
    db.add(project)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{project_id}/duplicate", response_model=ProjectOut,
             status_code=status.HTTP_201_CREATED)
def duplicate_project(project: Project = Depends(owned_project),
                      db: Session = Depends(get_db)) -> ProjectOut:
    """Copy the document only; photos and scans stay with the original."""
    copy = Project(owner_id=project.owner_id, name=f"{project.name} (Kopie)",
                   state=project.state, revision=1,
                   thumbnail=project.thumbnail)
    db.add(copy)
    db.commit()
    db.refresh(copy)
    return _project_out(copy)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project: Project = Depends(owned_project),
                   db: Session = Depends(get_db)) -> Response:
    for image in project.images:
        storage.delete(image.storage_key)
        storage.delete(image.rectified_key)
    for scan in project.scans:
        for shot in scan.shots:
            storage.delete(shot.storage_key)
        storage.delete(scan.mesh_key)
        storage.delete(scan.voxel_key)
    db.delete(project)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
