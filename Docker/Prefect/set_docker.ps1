# Prefect startup script — brings up the compose stack for the given role (server/dispatcher).
#
# server role:     starts prefect_server, then registers the work pools via set_pool.ps1 (idempotent).
#                  Pools live on the server, so dispatchers just poll them afterwards.
# dispatcher role: starts prefect_dispatcher, which polls the given WorkPool. WORK_POOL/WORKER_LIMIT are
#                  read from this shell at "docker compose up" (compose interpolation), so they are exported below.
# (PREFECT_API_URL, POSTGRES_*, MINIO_* etc. are read directly by the container from env_file=docker-compose.env.)
#
#   .\set_docker.ps1                                                # server (Control Node): start + register pools
#   .\set_docker.ps1 -Role dispatcher -WorkPool high_performance    # a high-tier machine
#   .\set_docker.ps1 -Role dispatcher -WorkPool lower_performance   # a low-tier machine
#
param(
    [ValidateSet('server', 'dispatcher')]
    [string]$Role = 'server',
    [string]$WorkPool = 'high_performance',  # (dispatcher) the work pool this machine polls: high_performance | lower_performance
    [int]$WorkerLimit = 8,                    # (dispatcher) max pipeline_flow containers this machine spawns concurrently
    [string]$ProjectName = 'mlops'            # docker compose project name (-p)
)

$ErrorActionPreference = "Stop"

# For the dispatcher compose ${...} interpolation — export to the current shell env (applies to this docker compose up).
$env:WORK_POOL    = $WorkPool
$env:WORKER_LIMIT = "$WorkerLimit"

$compose = "docker-compose.$Role.yml"

# On the same host, server/dispatcher/pipeline_flow containers talk by service name over the shared mlops network.
# (For a dispatcher on another machine, remove the networks block in the dispatcher compose and set PREFECT_API_URL to http://<host IP>:4200/api.)
docker network inspect mlops *> $null
if ($LASTEXITCODE -ne 0) { docker network create mlops | Out-Null }

# Bring the role's compose stack down (keeping volumes) and back up in the background.
docker compose -p $ProjectName -f $compose down
docker compose -p $ProjectName -f $compose up -d

# server role: register the work pools (high/low) on the server. set_pool.ps1 retries until the API is ready.
if ($Role -eq 'server') {
    & "$PSScriptRoot\set_pool.ps1" -PoolName high_performance  -TemplateFile high.json -ConcurrencyLimit 16 -ProjectName $ProjectName
    & "$PSScriptRoot\set_pool.ps1" -PoolName lower_performance -TemplateFile low.json  -ConcurrencyLimit 4  -ProjectName $ProjectName
}
