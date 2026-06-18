# Prefect startup script — brings up the compose stack for the given role (server/worker).
#
# The bash in the worker compose command interpolates ${CREATE_POOL}/${WORK_POOL}/${WORKER_LIMIT}
# from "this shell's environment" at docker compose up time (compose interpolation). So they are
# exported to the session env before up.
# (CONTROL_NODE_HOST, POSTGRES_*, MINIO_* etc. are read directly by the container from env_file=docker-compose.env.)
#
#   .\set_docker.ps1                                                      # server (Control Node)
#   .\set_docker.ps1 -Role worker                                         # first dispatcher — create docker-pool then start
#   .\set_docker.ps1 -Role worker -CreatePool false -WorkPool docker-gpu  # extra dispatcher — poll a dedicated pool
#
param(
    [ValidateSet('server', 'worker')]
    [string]$Role = 'server',
    [ValidateSet('true', 'false')]
    [string]$CreatePool = 'true',       # true=create pool then start dispatcher (first); false=skip create (extra dispatcher)
    [string]$WorkPool = 'docker-pool',  # docker work pool the dispatcher polls (e.g. docker-gpu for a dedicated one)
    [int]$WorkerLimit = 8               # max run containers this dispatcher spawns concurrently
)

$ErrorActionPreference = "Stop"

# For the worker compose ${...} interpolation — export to the current shell env (applies to this docker compose up).
$env:CREATE_POOL  = $CreatePool
$env:WORK_POOL    = $WorkPool
$env:WORKER_LIMIT = "$WorkerLimit"

$compose = "docker-compose.$Role.yml"

# On the same host, server/dispatcher/run containers talk by service name over the shared mlops network, so both roles need it.
# (For a Worker Node on another machine, remove the networks block in worker compose and set CONTROL_NODE_HOST to the host IP.)
docker network inspect mlops *> $null
if ($LASTEXITCODE -ne 0) { docker network create mlops | Out-Null }

# Bring the role's compose stack down (keeping volumes) and back up in the background.
docker compose -f $compose down
docker compose -f $compose up -d
