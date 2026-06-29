#!/bin/sh
# prune_loop.sh - periodically delete OFFLINE (stale) worker records from the server.
# __version__ = "0.0.21"  # Semantic Versioning:  Version = Major.Minor.Patch
# Runs as the 'worker_pruner' sidecar in the server stack (alpine + curl + jq, no python).
# Prefect marks dead workers OFFLINE but never deletes them; this prunes them so only live
# dispatchers remain. Live (ONLINE) workers are never touched.

apk add --no-cache curl jq >/dev/null 2>&1

: "${PREFECT_API_URL:=http://prefect_server:4200/api}"
: "${PRUNE_INTERVAL_SECONDS:=3600}"

echo "worker_pruner: pruning OFFLINE workers every ${PRUNE_INTERVAL_SECONDS}s via ${PREFECT_API_URL}"

while true; do
  # every docker work pool -> its workers -> delete the ones that are not ONLINE (URL-encode the name with @uri)
  for p in $(curl -sf -X POST "$PREFECT_API_URL/work_pools/filter" -H 'Content-Type: application/json' -d '{}' | jq -r '.[].name'); do
    curl -sf -X POST "$PREFECT_API_URL/work_pools/$p/workers/filter" -H 'Content-Type: application/json' -d '{}' \
      | jq -r '.[] | select((.status | ascii_upcase) != "ONLINE") | .name | @uri' \
      | while IFS= read -r w; do
          [ -n "$w" ] || continue
          curl -sf -X DELETE "$PREFECT_API_URL/work_pools/$p/workers/$w" >/dev/null && echo "worker_pruner: pruned offline $p/$w"
        done
  done
  sleep "$PRUNE_INTERVAL_SECONDS"
done
