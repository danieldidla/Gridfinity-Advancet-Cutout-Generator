"""Password hashing and signed session tokens."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from .config import get_settings

_pwd = CryptContext(schemes=["argon2"], deprecated="auto")
ALGORITHM = "HS256"
COOKIE_NAME = "gcg_session"


def hash_password(password: str) -> str:
    return _pwd.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _pwd.verify(password, hashed)
    except ValueError:
        return False


def create_token(user_id: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(hours=settings.token_ttl_hours),
    }
    return jwt.encode(payload, settings.resolved_secret(), algorithm=ALGORITHM)


def read_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, get_settings().resolved_secret(),
                             algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    subject = payload.get("sub")
    return subject if isinstance(subject, str) else None
