# run_server.ps1 — bring up the Prefect server compose stack on the Control Node.
param(
    [string]$Yaml    = 'docker-compose.server.yml', # the server compose file (its top-level name: sets the project)
    [string]$Network = 'mlops'                      # shared external network
)

$ErrorActionPreference = "Stop"

# Create the shared network only if it does not exist yet.
docker network inspect $Network *> $null
if ($LASTEXITCODE -ne 0) { docker network create $Network | Out-Null }

docker compose -f $Yaml up -d   # project name comes from the compose file's top-level name: (prefect-server)
