"""The database-backed job queue."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import Job

STALE_AFTER = timedelta(minutes=30)


def enqueue(db: Session, kind: str, payload: dict,
            owner_id: str | None = None) -> Job:
    job = Job(kind=kind, payload=payload, owner_id=owner_id, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def claim(db: Session) -> Job | None:
    """Take the oldest queued job.

    The UPDATE ... WHERE status='queued' is the lock: whichever worker changes
    the row first owns the job, so a second worker cannot pick up the same one.
    """
    _requeue_stale(db)
    row = db.execute(
        select(Job.id).where(Job.status == "queued")
        .order_by(Job.created_at).limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None

    now = datetime.now(timezone.utc)
    changed = db.execute(
        update(Job).where(Job.id == row, Job.status == "queued")
        .values(status="running", started_at=now, heartbeat=now,
                attempts=Job.attempts + 1)
    ).rowcount
    db.commit()
    if not changed:
        return None
    return db.get(Job, row)


def _requeue_stale(db: Session) -> None:
    cutoff = datetime.now(timezone.utc) - STALE_AFTER
    db.execute(
        update(Job)
        .where(Job.status == "running", Job.heartbeat < cutoff,
               Job.attempts < 3)
        .values(status="queued", stage="wird erneut versucht")
    )
    db.execute(
        update(Job)
        .where(Job.status == "running", Job.heartbeat < cutoff,
               Job.attempts >= 3)
        .values(status="failed", error="Verarbeitung abgebrochen (Zeitüberschreitung)",
                finished_at=datetime.now(timezone.utc))
    )
    db.commit()


def report(db: Session, job: Job, progress: float, stage: str) -> None:
    job.progress = max(0.0, min(1.0, progress))
    job.stage = stage[:120]
    job.heartbeat = datetime.now(timezone.utc)
    db.add(job)
    db.commit()


def finish(db: Session, job: Job, result: dict) -> None:
    job.status = "done"
    job.progress = 1.0
    job.result = result
    job.stage = "fertig"
    job.finished_at = datetime.now(timezone.utc)
    db.add(job)
    db.commit()


def fail(db: Session, job: Job, error: str) -> None:
    job.status = "failed"
    job.error = error[:4000]
    job.finished_at = datetime.now(timezone.utc)
    db.add(job)
    db.commit()
