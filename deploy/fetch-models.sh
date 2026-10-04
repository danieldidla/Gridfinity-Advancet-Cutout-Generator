#!/usr/bin/env bash
# Downloads the segmentation model used by the "KI" and "Hybrid" tracing
# engines. Separate from the installer so it can be re-run on its own, and so
# an offline machine can be fed the file by hand.
#
#   bash deploy/fetch-models.sh [zielverzeichnis] [modell]

set -euo pipefail

TARGET="${1:-/var/lib/gridfinity-cutout/models}"
MODEL="${2:-u2net}"
BASE="https://github.com/danielgatis/rembg/releases/download/v0.0.0"

case "${MODEL}" in
  u2net|u2netp|isnet-general-use) ;;
  *) echo "Unbekanntes Modell: ${MODEL}" >&2; exit 1 ;;
esac

mkdir -p "${TARGET}"
DEST="${TARGET}/${MODEL}.onnx"

if [[ -s "${DEST}" ]]; then
  echo "Modell ist bereits vorhanden: ${DEST}"
  exit 0
fi

echo "Lade ${MODEL} nach ${DEST} ..."
# to a temporary name first, so an interrupted download is never mistaken for
# a usable model on the next start
if ! curl -fsSL --retry 3 --retry-delay 2 -o "${DEST}.part" "${BASE}/${MODEL}.onnx"; then
  rm -f "${DEST}.part"
  echo "Download fehlgeschlagen. Die Erkennung läuft auch ohne Modell," >&2
  echo "dann aber ohne die Engines „KI“ und „Hybrid“." >&2
  exit 1
fi
mv "${DEST}.part" "${DEST}"

SIZE=$(stat -c%s "${DEST}")
if (( SIZE < 1000000 )); then
  rm -f "${DEST}"
  echo "Heruntergeladene Datei ist zu klein (${SIZE} Bytes) - verworfen." >&2
  exit 1
fi
printf 'Fertig: %s (%.0f MB)\n' "${DEST}" "$(echo "${SIZE}/1048576" | bc -l)"
