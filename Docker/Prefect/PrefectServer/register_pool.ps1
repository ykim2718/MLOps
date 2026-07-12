# register_pool.ps1 — register (or update) one Prefect work pool on the running server.
# __version__ = "0.0.21"  # Semantic Versioning:  Version = Major.Minor.Patch
# Idempotent: --overwrite keeps the base job template in sync. Run after the server is up (run_server.ps1).
# The base job template env PREFECT_API_URL is filled from docker-compose.env, so flow containers know
# where the server is. Backing addresses (MinIO / PostgreSQL / MLflow) live as prefect Variables
# (register_variables.ps1), not here.
#
#   .\register_pool.ps1 -PoolName high_performance  -TemplateFile docker-pool-template-high.json -ConcurrencyLimit 16
#   .\register_pool.ps1 -PoolName low_performance -TemplateFile docker-pool-template-low.json  -ConcurrencyLimit 8
#
param(
    [Parameter(Mandatory = $true)] [string]$PoolName,      # work pool name, e.g. high_performance | low_performance
    [Parameter(Mandatory = $true)] [string]$TemplateFile,  # base job template on the host, e.g. docker-pool-template-high.json
    [int]$ConcurrencyLimit = 0,                            # pool-wide max concurrent runs (0 = no limit)
    [string]$Compose       = 'docker-compose.server.yml',  # the server compose (its top-level name: sets the project)
    [string]$EnvFile       = '..\docker-compose.env'       # shared address source; falls back to the _example
)

$ErrorActionPreference = "Stop"

# Use the real env if present, otherwise the committed _example (placeholders).
if (-not (Test-Path $EnvFile)) { $EnvFile = '..\docker-compose.env_example' }
if (-not (Test-Path $EnvFile)) { Write-Error "env file not found: $EnvFile"; exit 1 }

# Read PREFECT_API_URL from the single source.
$apiUrl = ''
foreach ($line in Get-Content $EnvFile) {
    if ($line -match '^\s*PREFECT_API_URL\s*=\s*(.+?)\s*$') { $apiUrl = $Matches[1] }
}

# Build the effective base job template: fill env.default with PREFECT_API_URL from the env.
$tpl = Get-Content $TemplateFile -Raw | ConvertFrom-Json
$tpl.variables.properties.env.default = [ordered]@{ PREFECT_API_URL = $apiUrl }
$tplJson = $tpl | ConvertTo-Json -Depth 20

# Register (or update) the pool with the generated template. The API may need a moment after startup,
# so retry a few times. The template is pushed into the server container, then created from there.
$created = $false
for ($i = 1; $i -le 10; $i++) {
    $tplJson | docker compose -f $Compose exec -T prefect_server sh -c 'cat > /tmp/pool-template.json'
    docker compose -f $Compose exec -T prefect_server prefect work-pool create $PoolName --type docker --base-job-template /tmp/pool-template.json --overwrite
    if ($?) { $created = $true; break }
    Start-Sleep -Seconds 3
}

# Pool-wide concurrency limit is a separate command (create does not accept it).
if ($created -and $ConcurrencyLimit -gt 0) {
    docker compose -f $Compose exec -T prefect_server prefect work-pool set-concurrency-limit $PoolName "$ConcurrencyLimit"
}
