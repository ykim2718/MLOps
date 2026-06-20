# set_dispatcher.ps1 — start the Prefect dispatcher compose stack on a worker machine.
#
# Brings up prefect_dispatcher, which polls the given WorkPool. WORK_POOL/WORKER_LIMIT are read from
# this shell at "docker compose up" (compose interpolation), so they are exported below.
# (PREFECT_API_URL etc. are read directly by the container from env_file=docker-compose.env.)
# Work pools live on the server and are registered there (set_pool.ps1), not here.
#
#   .\set_dispatcher.ps1 -WorkPool high_performance    # a high-tier machine
#   .\set_dispatcher.ps1 -WorkPool lower_performance   # a low-tier machine
#
param(
    [string]$WorkPool = 'high_performance',  # the work pool this machine polls: high_performance | lower_performance
    [int]$WorkerLimit = 8,                    # max pipeline_flow containers this machine spawns concurrently
    [string]$ProjectName = 'mlops'            # docker compose project name (-p); must match the server compose
)

$ErrorActionPreference = "Stop"

# For the dispatcher compose ${...} interpolation — export to the current shell env (applies to this docker compose up).
$env:WORK_POOL    = $WorkPool
$env:WORKER_LIMIT = "$WorkerLimit"

$compose = "docker-compose.dispatcher.yml"

# On the same host, dispatcher/pipeline_flow containers reach the server by service name over the shared mlops network.
# (For a dispatcher on another machine, remove the networks block in the dispatcher compose and set PREFECT_API_URL to http://<host IP>:4200/api.)
docker network inspect mlops *> $null
if ($LASTEXITCODE -ne 0) { docker network create mlops | Out-Null }

# Bring the dispatcher stack down (keeping volumes) and back up in the background.
docker compose -p $ProjectName -f $compose down
docker compose -p $ProjectName -f $compose up -d
