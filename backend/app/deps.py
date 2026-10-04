"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from .db import get_db
from .models import Project, User
from .security import COOKIE_NAME, read_token


def current_user(
    session_cookie: str | None = Cookie(default=None, alias=COOKIE_NAME),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    token = session_cookie
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nicht angemeldet")

    user_id = read_token(token)
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sitzung abgelaufen")
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Konto nicht verfügbar")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Adminrechte notwendig")
    return user


def owned_project(project_id: str, db: Session = Depends(get_db),
                  user: User = Depends(current_user)) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Projekt nicht gefunden")
    return project
