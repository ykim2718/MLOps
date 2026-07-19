#!/usr/bin/env bash
# __version__ = "0.0.7"  # Semantic Versioning:  Version = Major.Minor.Patch  (bash port of my_trigger.bat)
#
# start.sh — one-shot pool trigger. Calls `prefect deployment run` directly (no my_trigger.sh),
# with every parameter pre-filled, so a single run kicks off the real deployment.
#
#   ./start.sh
#
# Bump GIT_COMMIT after every payload change (the pool runs the pinned SHA, not repo HEAD).
set -euo pipefail

PREFECT_API_URL_ARG="http://192.168.0.13:4200/api"
PREFECT_DEPLOYMENT="pipeline/low_deployment"
PREFECT_BLOCK="yrocket"
GIT_REPO="https://github.com/ykim2718/MLOps.git"
GIT_COMMIT="5c95bbd2a81ee5652b6792c48d4161405a841102"
MINIO_KEY="electric_power_consumption/v0/powerconsumption.csv"
PAYLOAD="Prefect_Workflow/example/Kaggle_EPC/my_flow.py"

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
