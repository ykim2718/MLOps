# run_dispatcher.ps1 — start the Prefect dispatcher compose stack on a worker machine.
#
# Brings up prefect_dispatcher, which polls the given WorkPool. WORK_POOL/WORKER_LIMIT are read from
# this shell at "docker compose up" (compose interpolation), so they are exported below.
# (PREFECT_API_URL etc. are read directly by the container from env_file=docker-compose.env.)
# Work pools live on the server and are registered there (register_pool.ps1), not here. Before starting,
# this script checks WorkPool against the pools registered on the server; if it is missing, it lists the
# registered pools and lets you pick one (guards against typos / not-yet-registered pools).
#
#   .\run_dispatcher.ps1 -WorkPool high_performance    # a high-tier machine
#   .\run_dispatcher.ps1 -WorkPool low_performance   # a low-tier machine
#
param(
    [string]$WorkPool = 'high_performance',  # the work pool this machine polls: high_performance | low_performance
    [int]$WorkerLimit = 8                     # max pipeline_flow containers this machine spawns concurrently
)

$ErrorActionPreference = "Stop"

$compose = "docker-compose.dispatcher.yml"

# On the same host, dispatcher/pipeline_flow containers reach the server by service name over the shared mlops network.
# (For a dispatcher on another machine, remove the networks block in the dispatcher compose and set PREFECT_API_URL to http://<host IP>:4200/api.)
docker network inspect mlops *> $null
if ($LASTEXITCODE -ne 0) { docker network create mlops | Out-Null }

# --- Validate WorkPool against the pools registered on the server ------------------------------
# Query through a throwaway dispatcher container: it carries the same PREFECT_API_URL (env_file) and
# network the real worker uses, so if this can read the pools the worker will reach them too.
function Get-PoolsJsonText {
    $raw  = docker compose -f $compose run --rm --no-deps -T prefect_dispatcher prefect work-pool ls --output json 2>$null
    $text = ($raw -join "`n")
    $s = $text.IndexOf('['); $e = $text.LastIndexOf(']')
    if ($s -lt 0 -or $e -le $s) { return $null }       # no JSON => could not reach the server
    return $text.Substring($s, $e - $s + 1)
}

$jsonText = Get-PoolsJsonText
if ($null -eq $jsonText) {
    throw "Could not read work pools from the Prefect server. Start it (run_server.ps1) and check PREFECT_API_URL in docker-compose.env, then retry."
}

# This dispatcher spawns docker containers, so only docker-type pools are valid
# (a name that exists only as a process pool — e.g. one auto-created by a typo — is rejected here).
$pools = @($jsonText | ConvertFrom-Json | Where-Object { $_.type -eq 'docker' })
if ($pools.Count -eq 0) {
    throw "No docker-type work pools are registered on the server. Run register_pool.ps1 (it registers --type docker) first."
}

$match = $pools | Where-Object { $_.name -eq $WorkPool } | Select-Object -First 1
if ($match) {
    $WorkPool = $match.name                              # normalize to the exact registered name
} else {
    Write-Warning "'$WorkPool' is not a registered docker work pool."
    Write-Host "Registered docker work pools:" -ForegroundColor Cyan
    for ($i = 0; $i -lt $pools.Count; $i++) {
        Write-Host ("{0,3}) {1}" -f ($i + 1), $pools[$i].name)
    }
    $sel = Read-Host "Pick a pool number (Enter to abort)"
    $idx = 0
    if (-not [int]::TryParse($sel, [ref]$idx) -or $idx -lt 1 -or $idx -gt $pools.Count) {
        throw "Aborted: no valid work pool selected."
    }
    $WorkPool = $pools[$idx - 1].name
    Write-Host "Using work pool '$WorkPool'." -ForegroundColor Green
}

# For the dispatcher compose ${...} interpolation — export to the current shell env (applies to this docker compose up).
$env:WORK_POOL    = $WorkPool
$env:WORKER_LIMIT = "$WorkerLimit"

# Bring the dispatcher stack down (keeping volumes) and back up in the background.
# project name comes from the compose file's top-level name: (prefect-dispatcher), so down only ever touches this stack.
docker compose -f $compose down
docker compose -f $compose up -d
