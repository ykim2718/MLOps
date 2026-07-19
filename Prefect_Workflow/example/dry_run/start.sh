#!/usr/bin/env bash
# __version__ = "0.0.7"  # Semantic Versioning:  Version = Major.Minor.Patch  (bash port of trigger.bat)
#
# start.sh — one-shot pool trigger. Calls `prefect deployment run` directly (no trigger.sh),
# with every parameter pre-filled, so a single run kicks off the real deployment.
#
#   ./start.sh
#
# Bump GIT_COMMIT after every payload change (the pool runs the pinned SHA, not repo HEAD).
set -euo pipefail

PREFECT_API_URL_ARG="http://192.168.0.13:4200/api"
PREFECT_DEPLOYMENT="pipeline/low_deployment"
PREFECT_BLOCK="yrocket"
GIT_REPO="https://github.com/ykim2718/SandBox4Git.git"
GIT_COMMIT="1e0f8f0280c871d9bc12d7fa08e772bf07db30eb"
MINIO_KEY="electric_power_consumption/v0/powerconsumption.csv"
PAYLOAD="dry_run/experiment_1/other_flow.py"

# submitter = dashboard label: yRocket-<yyyymmdd-HHMM>-<tz abbr>  (date +%Z already reflects DST)
SUBMITTER="yRocket-$(date +%Y%m%d-%H%M)-$(date +%Z)"

# talk to this Prefect server (env var, this process only).
export PREFECT_API_URL="$PREFECT_API_URL_ARG"

# work-pool run: pipeline.py (on a worker) git-fetches <GIT_REPO>@<GIT_COMMIT> and runs the payload,
# downloading <MINIO_KEY> to ./data - verifies the real code+data delivery path end to end.
# prefect_block = Credentials block name pipeline.py loads for MinIO creds.
# minio_key is a single OBJECT key (pipeline.py downloads one file), not a catalog prefix.
prefect deployment run "$PREFECT_DEPLOYMENT" \
    -p submitter="$SUBMITTER" -p prefect_block="$PREFECT_BLOCK" -p git_repo="$GIT_REPO" \
    -p git_commit_hash="$GIT_COMMIT" -p minio_key="$MINIO_KEY" -p payload="$PAYLOAD"

#  1e0f8f0280c871d9bc12d7fa08e772bf07db30eb   >> dry_run/my_flow.py, dry_run/experiment_1/other_flow.py
#   953096e750decf88a47520f336e4269ee1915b6e    << ~8 min
#   0d19d46e2ed3b5144d2a4197b0f77ba969475678    << error
#   95153312753021be0e4c09d04a387d1864de9569    << ~5 sec
