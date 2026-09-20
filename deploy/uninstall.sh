#!/usr/bin/env bash
# Removes the services and the program files. The data directory is kept
# unless --purge is given, because that is where every project lives.
set -euo pipefail

APP_NAME="gridfinity-cutout"
APP_DIR="${APP_DIR:-/opt/${APP_NAME}}"
DATA_DIR="${DATA_DIR:-/var/lib/${APP_NAME}}"

[[ $EUID -eq 0 ]] || { echo "Bitte als root ausführen." >&2; exit 1; }

systemctl disable --now "${APP_NAME}.service" "${APP_NAME}-worker.service" 2>/dev/null || true
rm -f "/etc/systemd/system/${APP_NAME}.service" \
      "/etc/systemd/system/${APP_NAME}-worker.service"
systemctl daemon-reload

rm -f "/etc/nginx/sites-enabled/${APP_NAME}" "/etc/nginx/sites-available/${APP_NAME}"
systemctl reload nginx 2>/dev/null || true

rm -rf "${APP_DIR}"

if [[ "${1:-}" == "--purge" ]]; then
  rm -rf "${DATA_DIR}" "/etc/${APP_NAME}.env"
  echo "Alles entfernt, einschließlich der Projektdaten."
else
  echo "Programm entfernt. Projektdaten liegen weiterhin unter ${DATA_DIR}."
  echo "Zum vollständigen Entfernen: $0 --purge"
fi
