import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The settings object is built once and cached, so the data directory has to be
# pointed at a temporary location before anything imports it.
_TMP = tempfile.mkdtemp(prefix="gcg-tests-")
os.environ.setdefault("GCG_DATA_DIR", _TMP)


def _reconstruction_available() -> bool:
    from importlib.util import find_spec

    return all(find_spec(name) is not None for name in ("scipy", "skimage"))


# SciPy and scikit-image are an optional install, so the tests that need them
# skip rather than fail on a deliberately slim deployment.
needs_reconstruction = pytest.mark.skipif(
    not _reconstruction_available(),
    reason="3D-Rekonstruktion nicht installiert (SciPy/scikit-image)")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def account(client):
    client.post("/api/auth/register",
                json={"email": "test@example.org", "password": "geheim12345"})
    return client
