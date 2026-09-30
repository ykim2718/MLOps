#!/usr/bin/env bash
# register_variables.sh — register the shared backing-service ADDRESS variables on the Prefect server.
# __version__ = "0.0.10"  # Semantic Versioning:  Version = Major.Minor.Patch
# Single, non-secret source of backing addresses (LAN IP). Flow code and host tools (catalog.py) read
# them via prefect Variables from the server, so no docker-compose.env is needed outside containers.
# Run after the server is up (run_server.sh). Idempotent (--overwrite).
#
#   ./register_variables.sh --minio http://<MINIO_IP>:9000 --postgresql <POSTGRESQL_IP>:5432 \
#                           --mlflow http://<MLFLOW_IP>:5000
#
set -euo pipefail

COMPOSE="docker-compose.server.yml"          # the server compose (its top-level name: sets the project)
MINIO_ENDPOINT=""          # MinIO S3 endpoint, e.g. http://<MINIO_IP>:9000 (data download / model upload)
POSTGRESQL_HOST_PORT=""    # PostgreSQL host:port, e.g. <POSTGRESQL_IP>:5432 (catalog / optuna DBs)
MLFLOW_TRACKING_URI=""     # MLflow tracking server, e.g. http://<MLFLOW_IP>:5000

while [ $# -gt 0 ]; do
    case "$1" in
        --minio)      MINIO_ENDPOINT="$2"; shift 2 ;;
        --postgresql) POSTGRESQL_HOST_PORT="$2"; shift 2 ;;
        --mlflow)     MLFLOW_TRACKING_URI="$2"; shift 2 ;;
        --compose)    COMPOSE="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# All three addresses are required: an empty or placeholder value would be registered silently and every
# consumer (catalog.py / pipeline.py) would then fail far from here.
if [ -z "$MINIO_ENDPOINT" ] || [ -z "$POSTGRESQL_HOST_PORT" ] || [ -z "$MLFLOW_TRACKING_URI" ]; then
    echo "Usage: $0 --minio <URL> --postgresql <HOST:PORT> --mlflow <URL> [--compose <FILE>]" >&2
    exit 1
fi

# set one variable on the server (overwrite so re-runs keep it in sync); echo the value we registered.
set_var() {
    docker compose -f "$COMPOSE" exec -T prefect_server \
        prefect variable set "$1" "$2" --overwrite >/dev/null   # hush prefect's value-less line
    echo "Set variable '$1' to \"$2\""
}

set_var minio_endpoint      "$MINIO_ENDPOINT"
set_var postgresql_host_port "$POSTGRESQL_HOST_PORT"  # host:port; consumers (catalog.py / pipeline.py) split it
set_var mlflow_tracking_uri "$MLFLOW_TRACKING_URI"
echo "[register_variables] set: minio_endpoint, postgresql_host_port, mlflow_tracking_uri"
