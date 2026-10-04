"""Background worker: long reconstructions, out of the request path.

Run as a separate process (``python -m app.worker``). It polls the job table,
so it can be restarted independently of the API and a crash mid-job leaves the
row to be retried rather than losing it.
"""

from __future__ import annotations

import logging
import signal
import sys
import time

import numpy as np

from .config import get_settings
from .db import SessionLocal, init_db
from .models import Job, Scan
from .scan import board as board_module
from .scan import carve
from .schemas import ScanSettings
from .services import jobs, storage

log = logging.getLogger("gcg.worker")
_running = True


def _stop(signum, _frame):
    global _running
    log.info("Signal %s empfangen, Worker beendet sich", signum)
    _running = False


def reconstruct_scan(db, job: Job) -> dict:
    scan_id = job.payload.get("scan_id")
    scan = db.get(Scan, scan_id)
    if scan is None:
        raise ValueError("Aufnahme existiert nicht mehr")

    carve.require_reconstruction()

    settings = ScanSettings(**(scan.settings or {}))
    spec = board_module.DEFAULT_BOARD

    shots = sorted([s for s in scan.shots if s.usable], key=lambda s: s.sequence)
    if len(shots) < 8:
        raise ValueError("zu wenige verwertbare Aufnahmen")

    def note(progress: float, stage: str) -> None:
        jobs.report(db, job, progress, stage)
        scan.message = stage
        db.add(scan)
        db.commit()

    # Photographs are read one at a time and released again. Holding forty
    # decoded 2000 px images would be some 350 MB of resident memory, which is
    # the difference between this running in a small container and not; the
    # masks alone are an order of magnitude smaller.
    note(0.02, "Bilder werden gelesen")
    detections: list[carve.Detection] = []
    for n, shot in enumerate(shots):
        image = storage.load_image(shot.storage_key)
        detections.append(carve.detect(image, spec, n))
        del image
        if n % 5 == 0:
            note(0.02 + 0.18 * (n + 1) / len(shots),
                 f"Board erkannt {n + 1}/{len(shots)}")

    note(0.22, "Kamera wird kalibriert")
    calib = carve.calibrate(detections, spec)

    note(0.3, "Silhouetten werden bestimmt")
    template = board_module.render_board(spec, px_per_mm=6.0, with_margin=False)
    masks: dict[int, np.ndarray] = {}
    for n, pose in enumerate(calib.poses):
        image = storage.load_image(shots[pose.index].storage_key)
        masks[pose.index] = carve.object_mask(
            image, calib, pose, spec,
            threshold=settings.threshold, template=template,
            extend_beyond_board=settings.extend_beyond_board)
        del image
        if n % 4 == 0:
            note(0.3 + 0.2 * (n + 1) / len(calib.poses),
                 f"Silhouette {n + 1}/{len(calib.poses)}")

    def carve_progress(fraction: float, stage: str) -> None:
        note(0.5 + 0.35 * fraction, stage)

    result = carve.carve(masks, calib, spec, voxel_mm=settings.voxel_mm,
                         max_height_mm=settings.max_height_mm,
                         extent_mm=settings.extent_mm,
                         progress=carve_progress)

    note(0.88, "Oberfläche wird erzeugt")
    mesh = carve.to_mesh(result.voxels, result.origin, result.voxel_mm,
                         smooth=settings.smooth)
    mesh = carve.recentre(mesh)

    note(0.94, "wird gespeichert")
    mesh_key = storage.new_key("meshes", ".stl")
    storage.write_bytes(mesh_key, mesh.export(file_type="stl"))

    voxel_key = storage.new_key("meshes", ".npz")
    import io
    buffer = io.BytesIO()
    np.savez_compressed(buffer, voxels=np.packbits(result.voxels),
                        shape=np.asarray(result.voxels.shape),
                        origin=result.origin,
                        voxel_mm=np.asarray([result.voxel_mm]))
    storage.write_bytes(voxel_key, buffer.getvalue())

    storage.delete(scan.mesh_key)
    storage.delete(scan.voxel_key)
    scan.mesh_key = mesh_key
    scan.voxel_key = voxel_key
    scan.status = "ready"
    scan.coverage = carve.coverage(calib.poses, spec)
    extents = mesh.extents
    scan.dimensions = {
        "width_mm": round(float(extents[0]), 2),
        "depth_mm": round(float(extents[1]), 2),
        "height_mm": round(float(extents[2]), 2),
        "volume_mm3": round(float(mesh.volume), 1),
        "views": result.used_views,
        "rms_px": round(calib.rms, 3),
        "warnings": result.warnings,
    }
    scan.message = "fertig"
    db.add(scan)
    db.commit()

    return {"scan_id": scan.id, "mesh_key": mesh_key,
            "dimensions": scan.dimensions}


HANDLERS = {"scan.reconstruct": reconstruct_scan}


def run_once(db) -> bool:
    job = jobs.claim(db)
    if job is None:
        return False

    handler = HANDLERS.get(job.kind)
    if handler is None:
        jobs.fail(db, job, f"Unbekannter Auftragstyp: {job.kind}")
        return True

    log.info("Auftrag %s (%s) gestartet", job.id, job.kind)
    try:
        result = handler(db, job)
    except Exception as exc:                      # noqa: BLE001
        log.exception("Auftrag %s fehlgeschlagen", job.id)
        db.rollback()
        jobs.fail(db, job, str(exc))
        scan_id = (job.payload or {}).get("scan_id")
        if scan_id:
            scan = db.get(Scan, scan_id)
            if scan is not None:
                scan.status = "failed"
                scan.message = str(exc)[:500]
                db.add(scan)
                db.commit()
    else:
        jobs.finish(db, job, result)
        log.info("Auftrag %s fertig", job.id)
    return True


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    settings = get_settings()
    init_db()
    log.info("Worker läuft, Daten unter %s", settings.data_dir)

    while _running:
        db = SessionLocal()
        try:
            busy = run_once(db)
        except Exception:                          # noqa: BLE001
            log.exception("Worker-Schleife gestoert")
            busy = False
        finally:
            db.close()
        if not busy:
            time.sleep(settings.worker_poll_seconds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
