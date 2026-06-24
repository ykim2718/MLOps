# register_pool.ps1 — register (or update) one Prefect work pool on the running server.
# Idempotent: --overwrite keeps the base job template in sync. Run after the server is up (run_server.ps1).
#
#   .\register_pool.ps1 -PoolName high_performance  -TemplateFile docker-pool-template-high.json -ConcurrencyLimit 16
#   .\register_pool.ps1 -PoolName lower_performance -TemplateFile docker-pool-template-low.json  -ConcurrencyLimit 4
#
param(
    [Parameter(Mandatory = $true)] [string]$PoolName,      # work pool name, e.g. high_performance | lower_performance
    [Parameter(Mandatory = $true)] [string]$TemplateFile,  # base job template mounted into the server at /templates, e.g. docker-pool-template-high.json
    [int]$ConcurrencyLimit = 0,                            # pool-wide max concurrent runs (0 = no limit)
    [string]$Compose       = 'docker-compose.server.yml'   # the server compose (its top-level name: sets the project)
)

$ErrorActionPreference = "Stop"

# Build the create command. --overwrite keeps the base job template in sync on re-runs.
# (work-pool create has no --concurrency-limit in Prefect 3; the pool-wide limit is set separately below.)
$create = @('work-pool', 'create', $PoolName, '--type', 'docker',
            '--base-job-template', "/templates/$TemplateFile", '--overwrite')

# The server container has the prefect CLI and the mounted templates (/templates/<TemplateFile>).
# The API may need a moment after startup, so retry a few times.
$created = $false
for ($i = 1; $i -le 10; $i++) {
    docker compose -f $Compose exec -T prefect_server prefect @create
    if ($?) { $created = $true; break }
    Start-Sleep -Seconds 3
}

# Pool-wide concurrency limit is a separate command (create does not accept it).
if ($created -and $ConcurrencyLimit -gt 0) {
    docker compose -f $Compose exec -T prefect_server prefect work-pool set-concurrency-limit $PoolName "$ConcurrencyLimit"
}
