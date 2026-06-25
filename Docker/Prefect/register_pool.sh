#!/usr/bin/env bash
# register_pool.sh — register (or update) one Prefect work pool on the running server.
# Idempotent: --overwrite keeps the base job template in sync. Run after the server is up (run_server.sh).
#
#   ./register_pool.sh --pool high_performance --template docker-pool-template-high.json --concurrency-limit 16
#   ./register_pool.sh --pool low_performance  --template docker-pool-template-low.json  --concurrency-limit 4
#
set -euo pipefail

POOL_NAME=""                           # work pool name, e.g. high_performance | low_performance
TEMPLATE_FILE=""                       # base job template mounted into the server at /templates, e.g. docker-pool-template-high.json
CONCURRENCY_LIMIT=0                    # pool-wide max concurrent runs (0 = no limit)
COMPOSE="docker-compose.server.yml"   # the server compose (its top-level name: sets the project)

while [ $# -gt 0 ]; do
    case "$1" in
        --pool)              POOL_NAME="$2"; shift 2 ;;
        --template)          TEMPLATE_FILE="$2"; shift 2 ;;
        --concurrency-limit) CONCURRENCY_LIMIT="$2"; shift 2 ;;
        --compose)           COMPOSE="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [ -z "$POOL_NAME" ] || [ -z "$TEMPLATE_FILE" ]; then
    echo "Usage: $0 --pool <name> --template <file> [--concurrency-limit N] [--compose file]" >&2
    exit 1
fi

# The server container has the prefect CLI and the mounted templates (/templates/<TemplateFile>).
# The API may need a moment after startup, so retry a few times.
# --overwrite keeps the base job template in sync on re-runs.
# (work-pool create has no --concurrency-limit in Prefect 3; the pool-wide limit is set separately below.)
created=false
for _ in $(seq 1 10); do
    if docker compose -f "$COMPOSE" exec -T prefect_server \
        prefect work-pool create "$POOL_NAME" --type docker \
        --base-job-template "/templates/$TEMPLATE_FILE" --overwrite; then
        created=true; break
    fi
    sleep 3
done

# Pool-wide concurrency limit is a separate command (create does not accept it).
if [ "$created" = true ] && [ "$CONCURRENCY_LIMIT" -gt 0 ]; then
    docker compose -f "$COMPOSE" exec -T prefect_server \
        prefect work-pool set-concurrency-limit "$POOL_NAME" "$CONCURRENCY_LIMIT"
fi
