#!/usr/bin/env bash
# register_pool.sh — register (or update) one Prefect work pool on the running server.
# __version__ = "0.0.22"  # Semantic Versioning:  Version = Major.Minor.Patch
# Idempotent: --overwrite keeps the base job template in sync. Run after the server is up (run_server.sh).
# The base job template env PREFECT_API_URL is filled from docker-compose.env, so flow containers know
# where the server is. Backing addresses (MinIO / PostgreSQL / MLflow) live as prefect Variables
# (register_variables.sh), not here.
#
#   ./register_pool.sh --pool-name high_performance --template-file docker-pool-template-high.json --concurrency-limit 16
#   ./register_pool.sh --pool-name low_performance  --template-file docker-pool-template-low.json  --concurrency-limit 8
#
set -euo pipefail

POOL_NAME=""                           # work pool name, e.g. high_performance | low_performance
TEMPLATE_FILE=""                       # base job template on the host, e.g. docker-pool-template-high.json
CONCURRENCY_LIMIT=0                    # pool-wide max concurrent runs (0 = no limit)
COMPOSE="docker-compose.server.yml"   # the server compose (its top-level name: sets the project)
ENV_FILE="../docker-compose.env"      # shared address source; falls back to the committed _example

while [ $# -gt 0 ]; do
    case "$1" in
        --pool-name)         POOL_NAME="$2"; shift 2 ;;
        --template-file)     TEMPLATE_FILE="$2"; shift 2 ;;
        --concurrency-limit) CONCURRENCY_LIMIT="$2"; shift 2 ;;
        --compose)           COMPOSE="$2"; shift 2 ;;
        --env-file)          ENV_FILE="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [ -z "$POOL_NAME" ] || [ -z "$TEMPLATE_FILE" ]; then
    echo "Usage: $0 --pool-name <name> --template-file <file> [--concurrency-limit N] [--compose file] [--env-file file]" >&2
    exit 1
fi

command -v jq >/dev/null 2>&1 || { echo "jq is required to build the base job template env. Install jq and retry." >&2; exit 1; }

# Use the real env if present, otherwise the committed _example (placeholders).
[ -f "$ENV_FILE" ] || ENV_FILE="../docker-compose.env_example"
[ -f "$ENV_FILE" ] || { echo "env file not found: $ENV_FILE" >&2; exit 1; }

# Load the addresses (exported) from the single source, then inject them into the template's env.default.
set -a; . "$ENV_FILE"; set +a

TPL_JSON="$(jq \
    --arg api "${PREFECT_API_URL:-}" \
    '.variables.properties.env.default = { PREFECT_API_URL: $api }' "$TEMPLATE_FILE")"

# Register (or update) the pool with the generated template. The API may need a moment after startup,
# so retry a few times. The template is pushed into the server container, then created from there.
# --overwrite keeps the base job template in sync on re-runs.
created=false
for _ in $(seq 1 10); do
    if printf '%s' "$TPL_JSON" | docker compose -f "$COMPOSE" exec -T prefect_server sh -c 'cat > /tmp/pool-template.json' \
       && docker compose -f "$COMPOSE" exec -T prefect_server \
            prefect work-pool create "$POOL_NAME" --type docker \
            --base-job-template /tmp/pool-template.json --overwrite; then
        created=true; break
    fi
    sleep 3
done

# Pool-wide concurrency limit is a separate command (create does not accept it).
if [ "$created" = true ] && [ "$CONCURRENCY_LIMIT" -gt 0 ]; then
    docker compose -f "$COMPOSE" exec -T prefect_server \
        prefect work-pool set-concurrency-limit "$POOL_NAME" "$CONCURRENCY_LIMIT"
fi
