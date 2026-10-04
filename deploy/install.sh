#!/usr/bin/env bash
# Native installer for a Debian 12/13 LXC container or VM.
#
# Installs the application under /opt, creates a service account, sets up two
# systemd units (API and worker) and an nginx reverse proxy. Safe to re-run:
# it updates an existing installation in place.

set -euo pipefail

APP_NAME="gridfinity-cutout"
APP_USER="${APP_USER:-gridfinity}"
APP_DIR="${APP_DIR:-/opt/${APP_NAME}}"
DATA_DIR="${DATA_DIR:-/var/lib/${APP_NAME}}"
PORT="${PORT:-8000}"
HTTP_PORT="${HTTP_PORT:-80}"
SERVER_NAME="${SERVER_NAME:-_}"
INSTALL_NGINX="${INSTALL_NGINX:-yes}"
# The guided 3D capture. On by default; WITH_SCAN=no drops SciPy and
# scikit-image and about 220 MB with them, and the application then says so
# where the feature would be used.
WITH_SCAN="${WITH_SCAN:-yes}"
# The segmentation model behind the "KI" and "Hybrid" tracing engines. About
# 170 MB, fetched once. WITH_AI=no leaves the paper model, which is the better
# of the two on most photographs anyway.
WITH_AI="${WITH_AI:-yes}"
AI_MODEL="${AI_MODEL:-u2net}"
# Every dependency ships a prebuilt wheel for amd64 and arm64, so no toolchain
# is installed. On another architecture, re-run with WITH_BUILD_TOOLS=yes.
WITH_BUILD_TOOLS="${WITH_BUILD_TOOLS:-no}"
# Node and the npm tree are only needed to build the frontend; both go once the
# bundle exists. Set KEEP_BUILD_DEPS=yes to develop on this machine.
KEEP_BUILD_DEPS="${KEEP_BUILD_DEPS:-no}"
# Drops the test suites NumPy, SciPy and scikit-image ship with. pip itself is
# kept, so WITH_SCAN=yes can still be added later.
SLIM="${SLIM:-no}"
# Building the frontend here costs about 415 MB of temporary space (Node, the
# npm tree and its cache), all of it released afterwards. On a container too
# tight for that peak, build frontend/dist on another machine, copy it in, and
# set this -- Node is then never installed at all.
SKIP_FRONTEND_BUILD="${SKIP_FRONTEND_BUILD:-no}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Bitte als root ausführen (sudo bash deploy/install.sh)."

log "Systempakete werden installiert"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# Deliberately short. The headless OpenCV wheel bundles its own ffmpeg, libpng
# and OpenBLAS, and NumPy/SciPy bring their own libgomp, so the usual
# libgl1/libglib2.0-0/libgomp1 trio is not needed -- together they pull in the
# Mesa stack and about 240 MB. Verified by checking which libraries the running
# process actually maps. Swapping in non-headless OpenCV would change that.
PACKAGES=(python3 python3-venv curl ca-certificates)
[[ "${INSTALL_NGINX}" == "yes" ]] && PACKAGES+=(nginx)
[[ "${WITH_BUILD_TOOLS}" == "yes" ]] && PACKAGES+=(python3-dev build-essential)
apt-get install -y -qq --no-install-recommends "${PACKAGES[@]}"

NODE_WAS_INSTALLED=no
if [[ "${SKIP_FRONTEND_BUILD}" == "yes" ]]; then
  [[ -f "${SOURCE_DIR}/frontend/dist/index.html" ]] \
    || die "SKIP_FRONTEND_BUILD=yes, aber frontend/dist fehlt. Auf einem anderen Rechner 'npm install && npm run build' ausführen und den Ordner frontend/dist hierher kopieren."
  log "Fertiges Frontend wird übernommen, Node.js wird nicht installiert"
elif ! command -v node >/dev/null 2>&1 || \
   [[ "$(node --version | sed 's/v\([0-9]*\).*/\1/')" -lt 20 ]]; then
  log "Node.js 22 wird eingerichtet (nur für den Frontend-Build)"
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null
  apt-get install -y -qq nodejs
  NODE_WAS_INSTALLED=yes
fi

if ! id "${APP_USER}" >/dev/null 2>&1; then
  log "Dienstkonto ${APP_USER} wird angelegt"
  useradd --system --create-home --home-dir "/home/${APP_USER}" \
          --shell /usr/sbin/nologin "${APP_USER}"
fi

log "Anwendung wird nach ${APP_DIR} kopiert"
mkdir -p "${APP_DIR}"
if [[ "${SOURCE_DIR}" != "${APP_DIR}" ]]; then
  # --delete keeps a re-run from leaving stale files behind, but the data
  # directory lives elsewhere so nothing of the user's is touched.
  tar -C "${SOURCE_DIR}" \
      --exclude=.git --exclude=.venv --exclude=node_modules \
      --exclude=__pycache__ --exclude='*.pyc' \
      -cf - backend frontend deploy 2>/dev/null | tar -C "${APP_DIR}" -xf -
fi

log "Python-Umgebung wird erstellt"
python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --quiet --no-cache-dir --upgrade pip

REQUIREMENTS="${APP_DIR}/backend/requirements.txt"
if [[ "${WITH_SCAN}" == "yes" ]]; then
  REQUIREMENTS="${APP_DIR}/backend/requirements-scan.txt"
  log "Mit 3D-Aufnahme"
else
  log "Ohne 3D-Aufnahme (später mit WITH_SCAN=yes nachrüstbar)"
fi

if ! "${APP_DIR}/.venv/bin/pip" install --quiet --no-cache-dir -r "${REQUIREMENTS}"; then
  die "Installation der Python-Pakete fehlgeschlagen. Auf einer Architektur ohne fertige Wheels hilft: sudo WITH_BUILD_TOOLS=yes bash deploy/install.sh"
fi

if [[ "${SKIP_FRONTEND_BUILD}" != "yes" ]]; then
  log "Frontend wird gebaut (das dauert ein bis zwei Minuten)"
  # The npm cache is another ~50 MB on top of node_modules; keeping it in a
  # temporary directory means it never counts against the container for long.
  NPM_CACHE="$(mktemp -d)"
  pushd "${APP_DIR}/frontend" >/dev/null
  npm_config_cache="${NPM_CACHE}" npm ci --no-audit --no-fund --silent \
    || npm_config_cache="${NPM_CACHE}" npm install --no-audit --no-fund --silent
  npm run build --silent
  popd >/dev/null
  rm -rf "${NPM_CACHE}"
fi

if [[ "${KEEP_BUILD_DEPS}" != "yes" ]]; then
  # The npm tree is roughly 220 MB and has done its job once dist/ exists.
  log "Build-Abhängigkeiten werden entfernt"
  rm -rf "${APP_DIR}/frontend/node_modules"
  if [[ "${NODE_WAS_INSTALLED}" == "yes" ]]; then
    apt-get purge -y -qq nodejs >/dev/null 2>&1 || true
    apt-get autoremove -y -qq >/dev/null 2>&1 || true
  fi
fi

# pip's own wheel cache survives the install and is of no further use.
rm -rf /root/.cache/pip "/home/${APP_USER}/.cache" 2>/dev/null || true

if [[ "${SLIM}" == "yes" ]]; then
  log "Mitgelieferte Test-Suites der Python-Pakete werden entfernt"
  find "${APP_DIR}/.venv" -type d \( -name tests -o -name test \) -prune \
       -exec rm -rf {} + 2>/dev/null || true
fi

mkdir -p "${DATA_DIR}"

if [[ "${WITH_AI}" == "yes" ]]; then
  if "${APP_DIR}/.venv/bin/pip" install --quiet --no-cache-dir onnxruntime; then
    # A failed download is not a failed installation: the paper model works
    # without it, and the interface says which engines are available.
    bash "${APP_DIR}/deploy/fetch-models.sh" "${DATA_DIR}/models" "${AI_MODEL}" \
      || warn "Modell konnte nicht geladen werden - die Engines „KI“ und „Hybrid“ fehlen."
  else
    warn "onnxruntime konnte nicht installiert werden - nur das Papiermodell steht bereit."
  fi
fi

chown -R "${APP_USER}:${APP_USER}" "${DATA_DIR}" "${APP_DIR}"
chmod 750 "${DATA_DIR}"

ENV_FILE="/etc/${APP_NAME}.env"
if [[ ! -f "${ENV_FILE}" ]]; then
  log "Konfiguration wird unter ${ENV_FILE} angelegt"
  SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  cat > "${ENV_FILE}" <<ENVEOF
# Konfiguration des ${APP_NAME}. Nach Änderungen:
#   systemctl restart ${APP_NAME} ${APP_NAME}-worker
GCG_DATA_DIR=${DATA_DIR}
GCG_SECRET_KEY=${SECRET}
GCG_ALLOW_REGISTRATION=true
GCG_APP_NAME=Gridfinity Cutout Generator
GCG_MAX_UPLOAD_MB=40
GCG_SCAN_VOXEL_MM=0.5
ENVEOF
  chmod 640 "${ENV_FILE}"
  chown root:"${APP_USER}" "${ENV_FILE}"
else
  log "Vorhandene Konfiguration ${ENV_FILE} bleibt unverändert"
fi

log "systemd-Units werden geschrieben"
cat > "/etc/systemd/system/${APP_NAME}.service" <<UNIT
[Unit]
Description=Gridfinity Cutout Generator (API)
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}/backend
EnvironmentFile=${ENV_FILE}
ExecStart=${APP_DIR}/.venv/bin/python -m uvicorn app.main:app \\
          --host 127.0.0.1 --port ${PORT} --proxy-headers \\
          --forwarded-allow-ips='*'
Restart=on-failure
RestartSec=3

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${DATA_DIR}
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true

[Install]
WantedBy=multi-user.target
UNIT

cat > "/etc/systemd/system/${APP_NAME}-worker.service" <<UNIT
[Unit]
Description=Gridfinity Cutout Generator (3D-Rekonstruktion)
After=${APP_NAME}.service
Wants=${APP_NAME}.service

[Service]
Type=exec
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}/backend
EnvironmentFile=${ENV_FILE}
ExecStart=${APP_DIR}/.venv/bin/python -m app.worker
Restart=on-failure
RestartSec=5

# Reconstruction saturates every core it is given. Keeping the worker below
# the API in priority means a running scan never makes the editor stutter.
Nice=5
CPUWeight=50

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${DATA_DIR}

[Install]
WantedBy=multi-user.target
UNIT

if [[ "${INSTALL_NGINX}" == "yes" ]]; then
  log "nginx wird konfiguriert"
  sed -e "s|__PORT__|${PORT}|g" \
      -e "s|__HTTP_PORT__|${HTTP_PORT}|g" \
      -e "s|__SERVER_NAME__|${SERVER_NAME}|g" \
      "${APP_DIR}/deploy/nginx.conf" > "/etc/nginx/sites-available/${APP_NAME}"
  ln -sf "/etc/nginx/sites-available/${APP_NAME}" \
         "/etc/nginx/sites-enabled/${APP_NAME}"
  rm -f /etc/nginx/sites-enabled/default
  nginx -t
  systemctl reload nginx || systemctl restart nginx
fi

log "Dienste werden gestartet"
systemctl daemon-reload
systemctl enable --now "${APP_NAME}.service" "${APP_NAME}-worker.service"

sleep 3
if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null; then
  ADDRESS="$(hostname -I 2>/dev/null | awk '{print $1}')"
  log "Fertig."
  echo
  echo "  Aufrufen unter:  http://${ADDRESS:-<IP-des-Containers>}${HTTP_PORT:+:${HTTP_PORT}}/"
  echo "  Das erste angelegte Konto wird automatisch Administrator."
  echo
  echo "  Logs:      journalctl -u ${APP_NAME} -f"
  echo "  Worker:    journalctl -u ${APP_NAME}-worker -f"
  echo "  Einstellungen: ${ENV_FILE}"
  echo
  echo "  Belegt:    $(du -sh "${APP_DIR}" 2>/dev/null | cut -f1) unter ${APP_DIR}"
  if [[ "${WITH_SCAN}" != "yes" ]]; then
    echo "  3D-Aufnahme ist nicht eingerichtet. Nachrüsten:"
    echo "    sudo WITH_SCAN=yes bash deploy/install.sh"
  fi
  if [[ "${WITH_AI}" == "yes" && ! -s "${DATA_DIR}/models/${AI_MODEL}.onnx" ]]; then
    echo "  Erkennungsmodell fehlt. Nachholen:"
    echo "    bash deploy/fetch-models.sh ${DATA_DIR}/models ${AI_MODEL}"
  fi
else
  warn "Der Dienst antwortet noch nicht. Bitte prüfen:"
  warn "  journalctl -u ${APP_NAME} -n 50 --no-pager"
  exit 1
fi
