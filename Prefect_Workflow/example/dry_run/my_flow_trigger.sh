#!/usr/bin/env bash
# __version__ = "0.0.9"
#
# example/dry_run/my_flow_trigger.sh — verify the dry-run flow (my_flow.py) at three stages.
#   --mode local : run my_flow.py in-process here (fastest sanity check).
#   --mode serve : flow.serve() — a serve process on THIS machine runs my_flow.py (no work pool).
#   --mode pool  : trigger the real pipeline deployment; pipeline.py (on a work-pool worker) git-fetches
#                  the repo and runs my_flow.py in a container - verifies the full code+data delivery path.
#
#   ./my_flow_trigger.sh
#   ./my_flow_trigger.sh --mode serve
#   ./my_flow_trigger.sh --mode pool --prefect-block <block> --git-repo https://github.com/<u>/<repo>.git --git-commit <sha>
set -euo pipefail

# --- defaults (mirror the .ps1 params) ---------------------------------------
mode="local"
prefect_api_url="http://localhost:4200/api"
prefect_deployment="pipeline/pipelineflow-low"   # pool: registered deployment (work pool)
submitter="local"                                # who launched it - dashboard label (all modes)
prefect_block=""                                 # pool: Credentials block name for MinIO creds (e.g. yrocket)
git_commit="dryrun"                              # git_commit_hash (pool)
data_folder=""                                   # local; default <script>/data
git_repo=""                                      # pool: repo pipeline.py fetches
minio_key="electric_power_consumption/v0/powerconsumption.csv"  # pool: full OBJECT key (not a prefix)

# --- arg parsing -------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)              mode="$2"; shift 2 ;;
        --prefect-api-url)   prefect_api_url="$2"; shift 2 ;;
        --prefect-deployment) prefect_deployment="$2"; shift 2 ;;
        --submitter)         submitter="$2"; shift 2 ;;
        --prefect-block)     prefect_block="$2"; shift 2 ;;
        --git-commit)        git_commit="$2"; shift 2 ;;
        --data-folder)       data_folder="$2"; shift 2 ;;
        --git-repo)          git_repo="$2"; shift 2 ;;
        --minio-key)         minio_key="$2"; shift 2 ;;
        -h|--help)           grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

case "$mode" in
    local|serve|pool) ;;
    *) echo "invalid --mode '$mode' (expected local|serve|pool)" >&2; exit 2 ;;
esac

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -n "$data_folder" ]] || data_folder="$here/data"

# Server Connection — all modes talk to this Prefect server (env var, current shell only).
export PREFECT_API_URL="$prefect_api_url"
export PYTHONPATH="$here"   # so `from my_flow import my_flow` resolves (serve mode)

case "$mode" in
    local)
        # in-process: my_flow.py runs here, now; reports to the UI if the server is up.
        # my_flow.py (v0.0.15) accepts only --submitter / --data_folder.
        python "$here/my_flow.py" --submitter "$submitter" --data_folder "$data_folder"
        ;;
    serve)
        # serve mode: this process serves the deployment and runs my_flow.py (Ctrl+C to stop).
        # Trigger a run from another shell: prefect deployment run "my_flow/dry-run"
        python -c "from my_flow import my_flow; my_flow.serve(name='dry-run')"
        ;;
    pool)
        # work-pool mode: pipeline.py (on a worker) git-fetches <git_repo>@<git_commit> and runs my_flow.py,
        # downloading <minio_key> to ./data - verifies the real code+data delivery path end to end.
        # submitter = dashboard label; prefect_block = Credentials block pipeline.py loads for MinIO creds.
        # --minio-key is a single OBJECT key (pipeline.py downloads one file), not a catalog prefix.
        if [[ -z "$git_repo" ]]; then
            echo "pool mode needs --git-repo (pipeline.py git-fetches that repo at --git-commit and runs my_flow.py)." >&2
            exit 1
        fi
        if [[ -z "$prefect_block" ]]; then
            echo "pool mode needs --prefect-block (Credentials block name pipeline.py loads, e.g. yrocket)." >&2
            exit 1
        fi
        prefect deployment run "$prefect_deployment" \
            -p submitter="$submitter" -p prefect_block="$prefect_block" -p git_repo="$git_repo" \
            -p git_commit_hash="$git_commit" -p minio_key="$minio_key"
        ;;
esac
