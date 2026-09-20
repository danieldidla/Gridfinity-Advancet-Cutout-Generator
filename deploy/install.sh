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
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Bitte als root ausführen (sudo bash deploy/install.sh)."

log "Systempakete werden installiert"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# libgl1 and libglib2.0-0 are what the headless OpenCV wheel links against.
PACKAGES=(python3 python3-venv python3-dev build-essential
          libgl1 libglib2.0-0 libgomp1 curl ca-certificates git)
[[ "${INSTALL_NGINX}" == "yes" ]] && PACKAGES+=(nginx)
apt-get install -y -qq "${PACKAGES[@]}"

if ! command -v node >/dev/null 2>&1 || \
   [[ "$(node --version | sed 's/v\([0-9]*\).*/\1/')" -lt 20 ]]; then
  log "Node.js 22 wird eingerichtet (für den Frontend-Build)"
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null
  apt-get install -y -qq nodejs
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
      --exclude=frontend/dist --exclude=__pycache__ --exclude='*.pyc' \
      -cf - backend frontend deploy 2>/dev/null | tar -C "${APP_DIR}" -xf -
fi

log "Python-Umgebung wird erstellt"
python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --quiet --upgrade pip wheel
"${APP_DIR}/.venv/bin/pip" install --quiet -r "${APP_DIR}/backend/requirements.txt"

log "Frontend wird gebaut (das dauert ein bis zwei Minuten)"
pushd "${APP_DIR}/frontend" >/dev/null
npm install --no-audit --no-fund --silent
npm run build --silent
popd >/dev/null

mkdir -p "${DATA_DIR}"
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
else
  warn "Der Dienst antwortet noch nicht. Bitte prüfen:"
  warn "  journalctl -u ${APP_NAME} -n 50 --no-pager"
  exit 1
fi
