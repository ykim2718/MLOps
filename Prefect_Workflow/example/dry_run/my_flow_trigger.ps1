# __version__ = "0.0.3"

# example/dry_run/my_flow_trigger.ps1 — verify the dry-run flow (my_flow.py) at three stages.
#   -Mode local : run my_flow.py in-process here (fastest sanity check).
#   -Mode serve : flow.serve() — a serve process on THIS machine runs my_flow.py (no work pool).
#   -Mode pool  : trigger the real pipeline deployment; pipeline.py (on a work-pool worker) git-fetches
#                 the repo and runs my_flow.py in a container - verifies the full code+data delivery path.
#
#   .\my_flow_trigger.ps1
#   .\my_flow_trigger.ps1 -Mode serve
#   .\my_flow_trigger.ps1 -Mode pool -GitRepo https://github.com/<u>/<repo>.git -Commit <sha> -MinioKey <key>
param(
    [ValidateSet("local", "serve", "pool")]
    [string]$Mode       = "local",
    [string]$ApiUrl     = "http://localhost:4200/api",
    [string]$Member     = "local",
    [string]$Commit     = "dryrun",                    # git_commit_hash (all modes)
    [string]$DataFolder = "",                          # local/serve; default <script>\data
    [string]$GitRepo    = "",                          # pool: repo pipeline.py fetches
    [string]$MinioKey   = "electric_power_consumption/v0",  # pool: dataset key pipeline.py downloads
    [string]$Deployment = "pipeline/pipelineflow-low"  # pool: registered deployment (work pool)
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $DataFolder) { $DataFolder = Join-Path $here "data" }

# Server Connection — all modes talk to this Prefect server (env var, current PowerShell only).
$env:PREFECT_API_URL = $ApiUrl
$env:PYTHONPATH = $here     # so `from my_flow import my_flow` resolves (serve mode)

switch ($Mode) {
    "local" {
        # in-process: my_flow.py runs here, now; reports to the UI if the server is up.
        python "$here\my_flow.py" --member $Member --git_commit_hash $Commit --data_folder $DataFolder
    }
    "serve" {
        # serve mode: this process serves the deployment and runs my_flow.py (Ctrl+C to stop).
        # Trigger a run from another shell: prefect deployment run "my_flow/dry-run"
        python -c "from my_flow import my_flow; my_flow.serve(name='dry-run')"
    }
    "pool" {
        # work-pool mode: pipeline.py (on a worker) git-fetches <GitRepo>@<Commit> and runs my_flow.py,
        # downloading <MinioKey> to ./data - verifies the real code+data delivery path end to end.
        if (-not $GitRepo) {
            throw "pool mode needs -GitRepo (pipeline.py git-fetches that repo at -Commit and runs my_flow.py)."
        }
        prefect deployment run "$Deployment" `
            -p member=$Member -p git_repo=$GitRepo `
            -p git_commit_hash=$Commit -p minio_key=$MinioKey
    }
}
