"""End-to-end checks through the HTTP layer."""

import cv2
import numpy as np

from .test_vision import synthetic_photo

RECTANGLE = [[-10, -10], [10, -10], [10, 10], [-10, 10]]


def test_first_account_becomes_admin(client):
    info = client.get("/api/auth/info").json()
    assert info["allow_registration"] is True

    created = client.post("/api/auth/register",
                          json={"email": "admin@example.org",
                                "password": "geheim12345"})
    assert created.status_code == 201
    assert created.json()["is_admin"] is True


def test_login_rejects_a_wrong_password(account):
    response = account.post("/api/auth/login",
                            json={"email": "test@example.org", "password": "falsch"})
    assert response.status_code == 401


def test_project_round_trip(account):
    project = account.post("/api/projects", json={"name": "Test"}).json()
    state = {
        "bin": {"grid_x": 2, "grid_y": 1, "height_units": 4},
        "cutouts": [{"name": "A", "polygon": RECTANGLE, "depth": 8}],
    }
    saved = account.patch(f"/api/projects/{project['id']}",
                          json={"state": state, "revision": project["revision"]})
    assert saved.status_code == 200

    reloaded = account.get(f"/api/projects/{project['id']}").json()
    assert reloaded["state"]["bin"]["grid_x"] == 2
    assert len(reloaded["state"]["cutouts"]) == 1


def test_stale_write_is_refused(account):
    """Two tabs must not silently overwrite each other."""
    project = account.post("/api/projects", json={"name": "Konflikt"}).json()
    body = {"state": {"bin": {}, "cutouts": []}, "revision": project["revision"]}
    assert account.patch(f"/api/projects/{project['id']}", json=body).status_code == 200
    assert account.patch(f"/api/projects/{project['id']}", json=body).status_code == 409


def test_projects_are_private(client, account):
    project = account.post("/api/projects", json={"name": "Privat"}).json()
    account.post("/api/auth/register",
                 json={"email": "someone.else@example.org", "password": "geheim12345"})
    assert client.get(f"/api/projects/{project['id']}").status_code == 404
    # log back in for the remaining tests
    client.post("/api/auth/login",
                json={"email": "test@example.org", "password": "geheim12345"})


def test_preview_is_cached_by_etag(account):
    body = {"bin": {"grid_x": 1, "grid_y": 1}, "cutouts": [
        {"name": "A", "polygon": RECTANGLE, "depth": 6}]}
    first = account.post("/api/geometry/preview.glb", json=body)
    assert first.status_code == 200
    etag = first.headers["etag"]

    again = account.post("/api/geometry/preview.glb", json=body,
                         headers={"If-None-Match": etag})
    assert again.status_code == 304, "identische Anfrage muss 304 liefern"

    body["cutouts"][0]["depth"] = 7
    changed = account.post("/api/geometry/preview.glb", json=body,
                           headers={"If-None-Match": etag})
    assert changed.status_code == 200
    assert changed.headers["etag"] != etag


def test_exports_have_sensible_filenames(account):
    body = {"bin": {"grid_x": 2, "grid_y": 3, "height_units": 5}, "cutouts": []}
    for fmt in ("stl", "3mf"):
        response = account.post(f"/api/geometry/export.{fmt}?name=Mein Projekt",
                                json=body)
        assert response.status_code == 200
        assert "2x3x5u" in response.headers["content-disposition"]
        assert len(response.content) > 1000


def test_photo_to_cutout(account):
    project = account.post("/api/projects", json={"name": "Foto"}).json()
    photo, _ = synthetic_photo()
    blob = cv2.imencode(".jpg", photo)[1].tobytes()

    response = account.post(f"/api/projects/{project['id']}/images",
                            files={"files": ("foto.jpg", blob, "image/jpeg")})
    assert response.status_code == 201
    uploaded = response.json()["images"][0]
    assert uploaded["corners"] is not None

    rectified = account.post(
        f"/api/projects/{project['id']}/images/{uploaded['id']}/rectify",
        json={"corners": uploaded["corners"], "paper": "a4", "px_per_mm": 8.0}).json()
    assert rectified["px_per_mm"] == 8.0

    traced = account.post(
        f"/api/projects/{project['id']}/images/{uploaded['id']}/trace", json={}).json()
    assert traced["width_mm"] == __import__("pytest").approx(60.0, abs=1.5)
    assert len(traced["polygon"]) >= 3

    # and the traced outline has to produce a model
    stats = account.post("/api/geometry/stats", json={
        "bin": {"grid_x": 2, "grid_y": 2},
        "cutouts": [{"name": "Objekt", "polygon": traced["polygon"],
                     "holes": traced["holes"], "depth": 8}],
    }).json()
    assert stats["triangles"] > 0


def test_stats_warn_about_impossible_settings(account):
    stats = account.post("/api/geometry/stats", json={
        "bin": {"grid_x": 1, "grid_y": 1, "height_units": 3, "floor_thickness": 1.4},
        "cutouts": [{"name": "Zu tief", "polygon": RECTANGLE, "depth": 50}],
    }).json()
    assert any("Boden" in w for w in stats["warnings"])


def test_reconstruct_needs_enough_photos(account):
    project = account.post("/api/projects", json={"name": "Scan"}).json()
    scan = account.post(f"/api/projects/{project['id']}/scans",
                        json={"name": "S"}).json()
    response = account.post(
        f"/api/projects/{project['id']}/scans/{scan['id']}/reconstruct", json=None)
    assert response.status_code == 422


def test_board_pdf_is_a4(account):
    response = account.get("/api/scan-board.pdf")
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
    assert b"595.276 841.890" in response.content or b"595.276" in response.content


def test_upload_rejects_rubbish(account):
    project = account.post("/api/projects", json={"name": "Müll"}).json()
    response = account.post(f"/api/projects/{project['id']}/images",
                            files={"files": ("x.jpg", b"not an image", "image/jpeg")})
    assert response.status_code == 400


def test_upload_takes_a_batch_and_reports_what_it_skipped(account):
    """Photographs arrive from a phone in bulk; one bad file must not sink the lot."""
    import cv2

    from .test_vision import synthetic_photo

    project = account.post("/api/projects", json={"name": "Stapel"}).json()
    photo, _ = synthetic_photo()
    good = cv2.imencode(".jpg", photo)[1].tobytes()

    response = account.post(f"/api/projects/{project['id']}/images", files=[
        ("files", ("a.jpg", good, "image/jpeg")),
        ("files", ("kaputt.jpg", b"not an image", "image/jpeg")),
        ("files", ("b.jpg", good, "image/jpeg")),
    ])
    assert response.status_code == 201
    body = response.json()
    assert len(body["images"]) == 2
    assert len(body["failed"]) == 1
    assert body["failed"][0]["filename"] == "kaputt.jpg"

    listed = account.get(f"/api/projects/{project['id']}/images").json()
    assert len(listed) == 2


def test_photos_carry_a_note_and_a_processed_flag(account):
    """A photo taken on a phone is worked on later, so it has to be findable."""
    import cv2

    from .test_vision import synthetic_photo

    project = account.post("/api/projects", json={"name": "Notizen"}).json()
    photo, _ = synthetic_photo()
    blob = cv2.imencode(".jpg", photo)[1].tobytes()
    image = account.post(f"/api/projects/{project['id']}/images",
                         files={"files": ("c.jpg", blob, "image/jpeg")}).json()["images"][0]
    assert image["note"] == "" and image["processed"] is False

    updated = account.patch(
        f"/api/projects/{project['id']}/images/{image['id']}",
        json={"note": "Messschieber", "processed": True}).json()
    assert updated["note"] == "Messschieber"
    assert updated["processed"] is True

    reloaded = account.get(f"/api/projects/{project['id']}/images").json()[0]
    assert reloaded["note"] == "Messschieber"


def test_stats_warn_when_a_cutout_breaches_the_wall(account):
    """Placing a pocket over the edge opens the side of the bin; say so."""
    stats = account.post("/api/geometry/stats", json={
        "bin": {"grid_x": 3, "grid_y": 2, "height_units": 4, "solid": True},
        "cutouts": [{"name": "Slot", "depth": 14, "clearance": 0.5, "y": 33,
                     "polygon": [[-52, -9], [52, -9], [52, 9], [-52, 9]]}],
    }).json()
    assert any("Außenwand" in w for w in stats["warnings"])


def test_stats_stay_quiet_for_a_sensible_layout(account):
    stats = account.post("/api/geometry/stats", json={
        "bin": {"grid_x": 3, "grid_y": 2, "height_units": 4, "solid": True},
        "cutouts": [{"name": "Mitte", "depth": 10, "polygon": RECTANGLE}],
    }).json()
    assert stats["warnings"] == []


def test_rotation_is_accounted_for_in_the_edge_check(account):
    """A long pocket that fits lying flat hangs out once turned across a narrow bin."""
    body = {
        # 3x1 is 125.5 x 41.5 mm, so the orientation genuinely matters here
        "bin": {"grid_x": 3, "grid_y": 1, "height_units": 4, "solid": True},
        "cutouts": [{"name": "Lang", "depth": 10, "rotation": 0,
                     "polygon": [[-38, -6], [38, -6], [38, 6], [-38, 6]]}],
    }
    assert account.post("/api/geometry/stats", json=body).json()["warnings"] == []

    body["cutouts"][0]["rotation"] = 90
    warnings = account.post("/api/geometry/stats", json=body).json()["warnings"]
    assert any("Rand" in w for w in warnings)


def test_edge_check_does_not_cry_wolf_over_a_notch(account):
    """A finger notch bites one wall only; it must not be treated as a
    margin on all four sides, or every notched pocket reports a breach."""
    circle = [[__import__("math").cos(t) * 17, __import__("math").sin(t) * 17]
              for t in [i * 2 * 3.14159265 / 48 for i in range(48)]]
    body = {
        "bin": {"grid_x": 3, "grid_y": 2, "height_units": 4, "solid": True},
        "cutouts": [{"name": "Rund", "polygon": circle, "x": -38, "y": -12,
                     "depth": 18, "clearance": 0.4, "draft_angle": 3,
                     "finger_notch": True, "finger_notch_diameter": 20}],
    }
    assert account.post("/api/geometry/stats", json=body).json()["warnings"] == []

    # moved against the wall, the same notch really does break through
    body["cutouts"][0]["y"] = -28
    warnings = account.post("/api/geometry/stats", json=body).json()["warnings"]
    assert any("Außenwand" in w for w in warnings)


def test_draft_angle_counts_towards_the_edge_check(account):
    """The pocket is widest at the surface, and that is what has to fit."""
    body = {
        "bin": {"grid_x": 2, "grid_y": 2, "height_units": 6, "solid": True},
        "cutouts": [{"name": "Schräg", "depth": 30, "draft_angle": 0,
                     "polygon": [[-38, -38], [38, -38], [38, 38], [-38, 38]]}],
    }
    assert account.post("/api/geometry/stats", json=body).json()["warnings"] == []

    body["cutouts"][0]["draft_angle"] = 10
    warnings = account.post("/api/geometry/stats", json=body).json()["warnings"]
    assert any("Rand" in w for w in warnings)
