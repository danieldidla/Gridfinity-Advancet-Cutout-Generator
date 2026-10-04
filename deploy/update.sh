#!/usr/bin/env bash
# Updates a native installation in place.
#
#   cd /pfad/zum/geklonten/repo && sudo bash deploy/update.sh
#
# Keeps every setting and all project data: the configuration lives in
# /etc/gridfinity-cutout.env and the data in /var/lib/gridfinity-cutout,
# neither of which this touches. Database columns added by a new version are
# applied on the next start.

set -euo pipefail

APP_NAME="gridfinity-cutout"
DATA_DIR="${DATA_DIR:-/var/lib/${APP_NAME}}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP="${BACKUP:-yes}"

log()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Bitte als root ausführen (sudo bash deploy/update.sh)."
[[ -f "${SOURCE_DIR}/deploy/install.sh" ]] || die "Im geklonten Repository ausführen."

cd "${SOURCE_DIR}"

if [[ "${BACKUP}" == "yes" && -f "${DATA_DIR}/app.db" ]]; then
  STAMP="$(date +%Y%m%d-%H%M%S)"
  TARGET="${DATA_DIR}/backups"
  mkdir -p "${TARGET}"
  log "Datenbank wird gesichert nach ${TARGET}/app-${STAMP}.db"
  # sqlite3 may not be installed; .backup is nicer but a copy with the WAL
  # alongside is good enough while the service is about to be restarted anyway.
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "${DATA_DIR}/app.db" ".backup '${TARGET}/app-${STAMP}.db'"
  else
    systemctl stop "${APP_NAME}" "${APP_NAME}-worker" 2>/dev/null || true
    cp "${DATA_DIR}/app.db" "${TARGET}/app-${STAMP}.db"
  fi
  # keep the last ten, so this never quietly fills the disk
  ls -1t "${TARGET}"/app-*.db 2>/dev/null | tail -n +11 | xargs -r rm -f
fi

BEFORE="$(git rev-parse --short HEAD 2>/dev/null || echo unbekannt)"
if git rev-parse --git-dir >/dev/null 2>&1; then
  if [[ -n "$(git status --porcelain)" ]]; then
    warn "Es gibt lokale Änderungen im Repository - 'git pull' wird übersprungen."
  else
    log "Neue Version wird geholt"
    git pull --ff-only
  fi
fi
AFTER="$(git rev-parse --short HEAD 2>/dev/null || echo unbekannt)"

if [[ "${BEFORE}" == "${AFTER}" ]]; then
  log "Bereits auf dem neuesten Stand (${AFTER}). Installation wird trotzdem aufgefrischt."
else
  log "Aktualisiert: ${BEFORE} -> ${AFTER}"
fi

log "Installation wird aufgefrischt"
# install.sh is written to be re-runnable; it keeps the existing configuration
# and only replaces program files.
bash "${SOURCE_DIR}/deploy/install.sh"

log "Fertig. Stand: ${AFTER}"
echo
echo "  Zurückrollen:  git checkout ${BEFORE} && sudo bash deploy/install.sh"
if [[ -d "${DATA_DIR}/backups" ]]; then
  echo "  Sicherungen:   ${DATA_DIR}/backups"
fi
