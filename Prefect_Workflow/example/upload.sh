#!/usr/bin/env bash
# upload.sh — upload the Ulvac AlPVDPoC raw data and register it in the catalog.
# Author: yRocket
__version__="0.1.0.2026.7.22"  # Semantic Versioning: Major.Minor.Patch.Date(YYYY.M.D)

set -euo pipefail

CATALOG_FOLDER="/mnt/d/Wolf-Code/Python/MLOps/Prefect_Workflow"
CREDENTIALS_FOLDER="/mnt/d/Wolf-Code/Python/MLOps/Docker/Prefect"
MANIFEST="/mnt/d/Wolf-Code/Python/pjt-Hexlab/Ultah/Manifest/Ulvac-AlPVDPoC.json"
BLOCK="yrocket"
PG_HOST="192.168.0.13"          # host running postgres (same box as the Prefect server)
MINIO_HOST="127.0.0.1"          # minio runs on this machine; WSL reaches Docker Desktop via localhost

# paired by index: MINIO_KEYS[i] is uploaded from DATA_FOLDERS[i]
MINIO_KEYS=(
    "Ulvac/AlPVDPoC/RawData/#0/V0"
)
DATA_FOLDERS=(
    "/mnt/f/Z/Ultah/RawData#0V0"
)

if [ "${#MINIO_KEYS[@]}" -ne "${#DATA_FOLDERS[@]}" ]; then
    echo "upload.sh: MINIO_KEYS (${#MINIO_KEYS[@]}) and DATA_FOLDERS (${#DATA_FOLDERS[@]}) must pair up 1:1" >&2
    exit 1
fi

# put credentials.py's folder on PYTHONPATH directly (no cd; the caller's folder stays untouched)
export PYTHONPATH="$CREDENTIALS_FOLDER${PYTHONPATH:+:$PYTHONPATH}"

for i in "${!MINIO_KEYS[@]}"; do
    echo "[upload.sh] ($((i + 1))/${#MINIO_KEYS[@]}) ${MINIO_KEYS[$i]} <- ${DATA_FOLDERS[$i]}"
    python "$CATALOG_FOLDER/catalog.py" upload "$MANIFEST" \
        --minio-key "${MINIO_KEYS[$i]}" \
        --path "${DATA_FOLDERS[$i]}" \
        -b "$BLOCK" --pg-host "$PG_HOST" --minio-host "$MINIO_HOST"
done
