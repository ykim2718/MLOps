# set_server.ps1 — bring up the Prefect server compose stack on the Control Node.
param(
    [string]$ProjectName = 'mlops',                     # docker compose project name (-p); must match set_pool.ps1
    [string]$Yaml        = 'docker-compose.server.yml', # the server compose file
    [string]$Network     = 'mlops'                      # shared external network
)

$ErrorActionPreference = "Stop"

# Create the shared network only if it does not exist yet.
docker network inspect $Network *> $null
if ($LASTEXITCODE -ne 0) { docker network create $Network | Out-Null }

docker compose -p $ProjectName -f $Yaml up -d
