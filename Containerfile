# Two stages: build the frontend with Node, then run everything from Python.
# The image ships the built SPA next to the API so a single container serves
# the whole application.

FROM docker.io/library/node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build


FROM docker.io/library/python:3.11-slim-bookworm AS runtime

# OpenCV and trimesh need a handful of shared libraries even in headless form.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    GCG_DATA_DIR=/data

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY --from=frontend /build/dist ./frontend/dist

RUN useradd --system --uid 10001 --create-home --home-dir /home/gridfinity gridfinity \
    && mkdir -p /data && chown -R gridfinity:gridfinity /data /app
USER gridfinity

WORKDIR /app/backend
EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
