# __version__ = "0.0.0"

# example/dry_run/trigger.ps1 — run the dry-run flow (my_flow.py) and report it to the Prefect dashboard.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# 1) Server Connection — point the client at the Prefect server so the run shows in the UI.
#    prefect CLI (persists to the profile):
prefect config set PREFECT_API_URL="http://localhost:4200/api"
#    env-var alternative (this shell only): $env:PREFECT_API_URL = "http://localhost:4200/api"

# 2) Trigger — my_flow.py is a runnable @flow entrypoint (argparse); running it launches the flow run.
python "$here\my_flow.py" --member local --git_commit_hash dryrun --data_folder "$here\data"
