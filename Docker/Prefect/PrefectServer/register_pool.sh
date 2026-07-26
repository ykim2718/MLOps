#!/usr/bin/env bash
# register_pool.sh — register (or update) one Prefect work pool via the server API.
# __version__ = "0.1.0"  # Semantic Versioning:  Version = Major.Minor.Patch
# Idempotent: --overwrite keeps the base job template in sync. Runs on any host that can reach the
# server API (needs the prefect CLI + jq locally; no server container required). PREFECT_API_URL is
# taken from docker-compose.env — it is both the API address this script calls and the address
# injected into the template's env.default, so flow containers know where the server is.
# Backing addresses (MinIO / PostgreSQL / MLflow) live as prefect Variables (register_variables.sh), not here.
#
#   ./register_pool.sh --pool-name high_performance --template-file docker-pool-template-high.json --concurrency-limit 16
#   ./register_pool.sh --pool-name low_performance  --template-file docker-pool-template-low.json  --concurrency-limit 8
#
set -euo pipefail

POOL_NAME=""                           # work pool name, e.g. high_performance | low_performance
TEMPLATE_FILE=""                       # base job template on the host, e.g. docker-pool-template-high.json
CONCURRENCY_LIMIT=0                    # pool-wide max concurrent runs (0 = no limit)
ENV_FILE="../docker-compose.env"      # shared address source; falls back to the committed _example

while [ $# -gt 0 ]; do
    case "$1" in
        --pool-name)         POOL_NAME="$2"; shift 2 ;;
        --template-file)     TEMPLATE_FILE="$2"; shift 2 ;;
        --concurrency-limit) CONCURRENCY_LIMIT="$2"; shift 2 ;;
        --env-file)          ENV_FILE="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [ -z "$POOL_NAME" ] || [ -z "$TEMPLATE_FILE" ]; then
    echo "Usage: $0 --pool-name <name> --template-file <file> [--concurrency-limit N] [--env-file file]" >&2
    exit 1
fi

command -v jq >/dev/null 2>&1 || { echo "jq is required to build the base job template env. Install jq and retry." >&2; exit 1; }
command -v prefect >/dev/null 2>&1 || { echo "the prefect CLI is required (pip install prefect). Install and retry." >&2; exit 1; }

# Use the real env if present, otherwise the committed _example (placeholders).
[ -f "$ENV_FILE" ] || ENV_FILE="../docker-compose.env_example"
[ -f "$ENV_FILE" ] || { echo "env file not found: $ENV_FILE" >&2; exit 1; }

# Load the addresses (exported) from the single source; PREFECT_API_URL now steers the prefect CLI
# below (env var beats the profile) and is injected into the template's env.default.
set -a; . "$ENV_FILE"; set +a
[ -n "${PREFECT_API_URL:-}" ] || { echo "PREFECT_API_URL missing in $ENV_FILE" >&2; exit 1; }

TMP_TPL="$(mktemp)"
trap 'rm -f "$TMP_TPL"' EXIT
jq --arg api "$PREFECT_API_URL" \
    '.variables.properties.env.default = { PREFECT_API_URL: $api }' "$TEMPLATE_FILE" > "$TMP_TPL"

# Register (or update) the pool through the server API. The API may need a moment after startup,
# so retry a few times. --overwrite keeps the base job template in sync on re-runs.
created=false
for _ in $(seq 1 10); do
    if prefect work-pool create "$POOL_NAME" --type docker \
            --base-job-template "$TMP_TPL" --overwrite; then
        created=true; break
    fi
    sleep 3
done
[ "$created" = true ] || { echo "register_pool: could not register '$POOL_NAME' at $PREFECT_API_URL" >&2; exit 1; }

# Pool-wide concurrency limit is a separate command (create does not accept it).
if [ "$CONCURRENCY_LIMIT" -gt 0 ]; then
    prefect work-pool set-concurrency-limit "$POOL_NAME" "$CONCURRENCY_LIMIT"
fi
