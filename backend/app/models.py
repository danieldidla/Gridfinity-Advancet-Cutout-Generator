"""ORM models.

Project state is deliberately kept as one JSON blob plus a few indexed columns.
The editor autosaves on every change, and a single document write is both
atomic and cheap; splitting cutouts into rows would buy nothing here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    projects: Mapped[list["Project"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160), default="Neues Projekt")
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    thumbnail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now,
                                                 onupdate=_now)

    owner: Mapped[User] = relationship(back_populates="projects")
    images: Mapped[list["Image"]] = relationship(
        back_populates="project", cascade="all, delete-orphan")
    scans: Mapped[list["Scan"]] = relationship(
        back_populates="project", cascade="all, delete-orphan")


class Image(Base):
    """A reference photo plus whatever we have worked out about it."""

    __tablename__ = "images"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(255))
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    paper: Mapped[str] = mapped_column(String(16), default="a4")
    corners: Mapped[list | None] = mapped_column(JSON, nullable=True)
    rectified_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    px_per_mm: Mapped[float] = mapped_column(Float, default=0.0)
    trace: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    project: Mapped[Project] = relationship(back_populates="images")


class Scan(Base):
    """A guided multi-photo capture and its reconstruction."""

    __tablename__ = "scans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160), default="3D-Aufnahme")
    status: Mapped[str] = mapped_column(String(24), default="capturing",
                                        index=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    coverage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    mesh_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    voxel_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dimensions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now,
                                                 onupdate=_now)

    project: Mapped[Project] = relationship(back_populates="scans")
    shots: Mapped[list["ScanShot"]] = relationship(
        back_populates="scan", cascade="all, delete-orphan")


class ScanShot(Base):
    __tablename__ = "scan_shots"
    __table_args__ = (UniqueConstraint("scan_id", "sequence"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    scan_id: Mapped[str] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    storage_key: Mapped[str] = mapped_column(String(255))
    sharpness: Mapped[float] = mapped_column(Float, default=0.0)
    corner_count: Mapped[int] = mapped_column(Integer, default=0)
    azimuth: Mapped[float | None] = mapped_column(Float, nullable=True)
    elevation: Mapped[float | None] = mapped_column(Float, nullable=True)
    usable: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    scan: Mapped[Scan] = relationship(back_populates="shots")


class Job(Base):
    """A unit of background work.

    A table is enough of a queue here: one worker, jobs measured in minutes,
    and progress that the UI wants to poll anyway. Bringing in Redis and a task
    broker would add two services to every install for no benefit.
    """

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    stage: Mapped[str] = mapped_column(String(120), default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String(32), nullable=True,
                                                 index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now,
                                                 index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    heartbeat: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
