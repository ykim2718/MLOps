#!/usr/bin/env bash
# run_server.sh — bring up the Prefect server compose stack on the Control Node.
set -euo pipefail

YAML="docker-compose.server.yml"   # the server compose file (its top-level name: sets the project)
NETWORK="mlops"                    # shared external network

while [ $# -gt 0 ]; do
    case "$1" in
        --yaml)    YAML="$2"; shift 2 ;;
        --network) NETWORK="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# Create the shared network only if it does not exist yet.
docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK" >/dev/null

docker compose -f "$YAML" up -d   # project name comes from the compose file's top-level name: (prefect-server)
