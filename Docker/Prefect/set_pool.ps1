# set_pool.ps1 — register (or update) one Prefect work pool on the running server.
# Idempotent: --overwrite keeps the base job template in sync. Run after the server is up (set_server.ps1).
#
#   .\set_pool.ps1 -PoolName high_performance  -TemplateFile high.json -ConcurrencyLimit 16
#   .\set_pool.ps1 -PoolName lower_performance -TemplateFile low.json  -ConcurrencyLimit 4
#
param(
    [Parameter(Mandatory = $true)] [string]$PoolName,      # work pool name, e.g. high_performance | lower_performance
    [Parameter(Mandatory = $true)] [string]$TemplateFile,  # base job template mounted into the server at /templates, e.g. high.json
    [int]$ConcurrencyLimit = 0,                            # pool-wide max concurrent runs (0 = no limit)
    [string]$ProjectName = 'mlops',                        # docker compose project name (-p); must match set_server.ps1
    [string]$Compose     = 'docker-compose.server.yml'     # the server compose that runs prefect_server
)

$ErrorActionPreference = "Stop"

# Build the create command; add --concurrency-limit only when a positive limit is given.
$create = @('work-pool', 'create', $PoolName, '--type', 'docker',
            '--base-job-template', "/templates/$TemplateFile", '--overwrite')
if ($ConcurrencyLimit -gt 0) { $create += @('--concurrency-limit', "$ConcurrencyLimit") }

# The server container has the prefect CLI and the mounted templates (/templates/<TemplateFile>).
# The API may need a moment after startup, so retry a few times.
for ($i = 1; $i -le 10; $i++) {
    docker compose -p $ProjectName -f $Compose exec -T prefect_server prefect @create
    if ($?) { break }
    Start-Sleep -Seconds 3
}
