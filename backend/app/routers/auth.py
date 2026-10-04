"""Registration, login and the session cookie."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import current_user
from ..models import User
from ..schemas import LoginRequest, RegisterRequest, ServerInfo, UserOut
from ..security import (COOKIE_NAME, create_token, hash_password,
                        verify_password)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_count(db: Session) -> int:
    return int(db.execute(select(func.count(User.id))).scalar_one())


def _set_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=settings.token_ttl_hours * 3600,
        httponly=True, samesite="lax", path="/",
        # Secure is not forced: a plain-HTTP LXC install on a LAN is a
        # perfectly normal deployment, and the reverse proxy adds TLS.
    )


@router.get("/info", response_model=ServerInfo)
def info(db: Session = Depends(get_db)) -> ServerInfo:
    settings = get_settings()
    count = _user_count(db)
    return ServerInfo(
        app_name=settings.app_name,
        # the very first account can always be created, otherwise nobody could
        allow_registration=settings.allow_registration or count == 0,
        has_users=count > 0,
        max_upload_mb=settings.max_upload_mb,
    )


@router.post("/register", response_model=UserOut,
             status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, response: Response,
             db: Session = Depends(get_db)) -> User:
    settings = get_settings()
    count = _user_count(db)
    if count > 0 and not settings.allow_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Registrierung ist deaktiviert")

    email = payload.email.lower()
    existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "E-Mail-Adresse ist bereits vergeben")

    user = User(
        email=email,
        display_name=payload.display_name or email.split("@")[0],
        password_hash=hash_password(payload.password),
        is_admin=(count == 0),     # first account administers the instance
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    _set_cookie(response, create_token(user.id))
    return user


@router.post("/login", response_model=UserOut)
def login(payload: LoginRequest, response: Response,
          db: Session = Depends(get_db)) -> User:
    user = db.execute(
        select(User).where(User.email == payload.email.lower())
    ).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "E-Mail oder Passwort ist falsch")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Konto ist deaktiviert")

    user.last_login = datetime.now(timezone.utc)
    db.add(user)
    db.commit()
    _set_cookie(response, create_token(user.id))
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT,
             response_class=Response)
def logout() -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> User:
    return user
