#!/usr/bin/env bash
# run_dispatcher.sh — start the Prefect dispatcher compose stack on a worker machine.
# __version__ = "0.0.20"  # Semantic Versioning:  Version = Major.Minor.Patch
#
# Brings up prefect_dispatcher, which polls the given work pool. WORK_POOL/WORKER_LIMIT are read from
# this shell at "docker compose up" (compose interpolation), so they are exported below.
# (PREFECT_API_URL etc. are read directly by the container from env_file=docker-compose.env.)
# Work pools live on the server and are registered there (register_pool.sh), not here. Before starting,
# this script checks the work pool against the pools registered on the server; if it is missing, it lists
# the registered pools and lets you pick one (guards against typos / not-yet-registered pools).
#
#   ./run_dispatcher.sh --work-pool high_performance    # a high-tier machine
#   ./run_dispatcher.sh --work-pool low_performance     # a low-tier machine
#
set -euo pipefail

WORK_POOL="high_performance"   # the work pool this machine polls: high_performance | low_performance
WORKER_LIMIT=8                 # max pipeline_flow containers this machine spawns concurrently

while [ $# -gt 0 ]; do
    case "$1" in
        --work-pool)    WORK_POOL="$2"; shift 2 ;;
        --worker-limit) WORKER_LIMIT="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

COMPOSE="docker-compose.dispatcher.yml"

command -v jq >/dev/null 2>&1 || { echo "jq is required to parse 'prefect work-pool ls --output json'. Install jq and retry." >&2; exit 1; }

# The pool validation below uses the host 'prefect' CLI, so it must be installed and on PATH.
if ! command -v prefect >/dev/null 2>&1; then
    echo "prefect CLI not found on this host (needed to validate the work pool against the server)." >&2
    echo "Install it, then retry:" >&2
    echo "  pipx install prefect && pipx ensurepath     # then open a new shell, or: export PATH=\"\$HOME/.local/bin:\$PATH\"" >&2
    echo "  export PREFECT_API_URL=http://127.0.0.1:4200/api   # point at the running server (run_server.sh)" >&2
    exit 1
fi

# On the same host, dispatcher/pipeline_flow containers reach the server by service name over the shared mlops network.
# (For a dispatcher on another machine, remove the networks block in the dispatcher compose and set PREFECT_API_URL to http://<host IP>:4200/api.)
docker network inspect mlops >/dev/null 2>&1 || docker network create mlops >/dev/null

# --- Validate the work pool against the pools registered on the server --------------------------
# Read the registered pools with the host prefect CLI (configured via its PREFECT_API_URL profile).
# stderr (progress / version warnings) is dropped so only the JSON on stdout is parsed.
pools_json="$(prefect work-pool ls --output json 2>/dev/null || true)"
if [ -z "$pools_json" ]; then
    echo "Could not read work pools via the host 'prefect' CLI. Ensure prefect is installed and PREFECT_API_URL points at a running server (run_server.sh), then retry." >&2
    exit 1
fi

# This dispatcher spawns docker containers, so only docker-type pools are valid
# (a name that exists only as a process pool — e.g. one auto-created by a typo — is rejected here).
pools=()
while IFS= read -r line; do
    [ -n "$line" ] && pools+=("$line")
done < <(printf '%s' "$pools_json" | jq -r '.[] | select(.type == "docker") | .name')

if [ "${#pools[@]}" -eq 0 ]; then
    echo "No docker-type work pools are registered on the server. Run register_pool.sh (it registers --type docker) first." >&2
    exit 1
fi

match=""
for p in "${pools[@]}"; do
    if [ "$p" = "$WORK_POOL" ]; then match="$p"; break; fi
done

if [ -n "$match" ]; then
    WORK_POOL="$match"                                   # normalize to the exact registered name
else
    echo "Warning: '$WORK_POOL' is not a registered docker work pool." >&2
    echo "Registered docker work pools:"
    i=1
    for p in "${pools[@]}"; do
        printf '%3d) %s\n' "$i" "$p"
        i=$((i + 1))
    done
    read -r -p "Pick a pool number (Enter to abort): " sel
    if ! printf '%s' "$sel" | grep -qE '^[0-9]+$' || [ "$sel" -lt 1 ] || [ "$sel" -gt "${#pools[@]}" ]; then
        echo "Aborted: no valid work pool selected." >&2
        exit 1
    fi
    WORK_POOL="${pools[$((sel - 1))]}"
    echo "Using work pool '$WORK_POOL'."
fi

# For the dispatcher compose ${...} interpolation — export so this docker compose up sees them.
export WORK_POOL
export WORKER_LIMIT

# Bring the dispatcher stack down (keeping volumes) and back up in the background.
# project name comes from the compose file's top-level name: (prefect-dispatcher), so down only ever touches this stack.
docker compose -f "$COMPOSE" down
docker compose -f "$COMPOSE" up -d
