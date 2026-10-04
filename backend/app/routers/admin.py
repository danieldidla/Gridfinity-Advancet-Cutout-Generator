"""Instance administration: users and housekeeping."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..models import Image, Job, Project, Scan, ScanShot, User
from ..schemas import RegisterRequest, UserOut
from ..security import hash_password

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db),
               _: User = Depends(require_admin)) -> list[User]:
    return list(db.execute(select(User).order_by(User.created_at)).scalars())


@router.post("/users", response_model=UserOut,
             status_code=status.HTTP_201_CREATED)
def create_user(payload: RegisterRequest, db: Session = Depends(get_db),
                _: User = Depends(require_admin)) -> User:
    email = payload.email.lower()
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "E-Mail bereits vergeben")
    user = User(email=email, display_name=payload.display_name or email.split("@")[0],
                password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: str, payload: dict, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Konto nicht gefunden")

    if "is_active" in payload:
        if user.id == admin.id and not payload["is_active"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Das eigene Konto kann nicht deaktiviert werden")
        user.is_active = bool(payload["is_active"])
    if "is_admin" in payload:
        if user.id == admin.id and not payload["is_admin"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Die eigenen Adminrechte können nicht entzogen werden")
        user.is_admin = bool(payload["is_admin"])
    if payload.get("password"):
        if len(payload["password"]) < 8:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Passwort zu kurz")
        user.password_hash = hash_password(payload["password"])
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: str, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)) -> Response:
    if user_id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Das eigene Konto kann nicht gelöscht werden")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Konto nicht gefunden")
    db.delete(user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/stats")
def instance_stats(db: Session = Depends(get_db),
                   _: User = Depends(require_admin)) -> dict:
    def count(model) -> int:
        return int(db.execute(select(func.count()).select_from(model)).scalar_one())

    return {
        "users": count(User),
        "projects": count(Project),
        "images": count(Image),
        "scans": count(Scan),
        "shots": count(ScanShot),
        "jobs_queued": int(db.execute(
            select(func.count()).select_from(Job).where(Job.status == "queued")
        ).scalar_one()),
        "jobs_running": int(db.execute(
            select(func.count()).select_from(Job).where(Job.status == "running")
        ).scalar_one()),
    }
