# data_lister.ps1
# List what is currently registered/stored.
#   -Catalog        -> show catalog (registered versions in the DB, via catalog.py)
#   -ObjectStorage  -> show MinIO objects actually present (via mc)
#   (both)          -> show both sections
#   (none)          -> show this help
#
# Examples:
#   .\data_lister.ps1 -Catalog
#   .\data_lister.ps1 -ObjectStorage -DatasetId sydney_202605 -ShowVersions
#   .\data_lister.ps1 -Catalog -ObjectStorage
#
param(
    [Alias('cat')]
    [switch]$Catalog,                                  # show catalog (DB)
    [Alias('object_storage','minio','os')]
    [switch]$ObjectStorage,                            # show MinIO objects
    [string]$DatasetId = "",                           # limit to one dataset (default: all)
    [switch]$ShowVersions,                             # include all object versions (MinIO only)
    [string]$Bucket     = "datasets",
    [string]$Endpoint   = $env:MINIO_ENDPOINT,
    [string]$AccessKey  = $env:MINIO_ACCESS_KEY,
    [string]$SecretKey  = $env:MINIO_SECRET_KEY,
    [string]$CatalogDsn = $env:POSTGRESQL_CATALOG_DSN,        # postgresql://user:pass@host:5432/catalog
    [string]$Alias      = "local"
)

$ErrorActionPreference = "Stop"
$catalogPy = Join-Path $PSScriptRoot 'catalog.py'

function Show-Help {
    Write-Host @"
data_lister.ps1 - show registered datasets (Catalog) and/or stored objects (MinIO)

Usage:
  .\data_lister.ps1 -Catalog [-DatasetId <id>]
  .\data_lister.ps1 -ObjectStorage [-DatasetId <id>] [-ShowVersions]
  .\data_lister.ps1 -Catalog -ObjectStorage            # both at once

Options:
  -Catalog          show catalog = versions registered in the DB (alias: -cat)
  -ObjectStorage    show MinIO   = actual objects/files (alias: -minio, -object_storage)
  -DatasetId <id>   limit to one dataset (default: all)
  -ShowVersions     include all object versions/delete-markers (MinIO only)
  -Bucket -Endpoint -AccessKey -SecretKey -Alias   (connection overrides)
"@
}

# Nothing requested -> help and exit
if (-not $Catalog -and -not $ObjectStorage) { Show-Help; return }

# Credentials come from -params or environment (no hardcoded secrets in this script)
if (-not $Endpoint -or -not $AccessKey -or -not $SecretKey) {
    throw "MinIO connection missing. Set env MINIO_ENDPOINT / MINIO_ACCESS_KEY / MINIO_SECRET_KEY, or pass -Endpoint / -AccessKey / -SecretKey."
}
if ($Catalog -and -not $CatalogDsn) {
    throw "Catalog DB DSN missing. Set env POSTGRESQL_CATALOG_DSN or pass -CatalogDsn (e.g. postgresql://user:pass@host:5432/catalog)."
}
if ($Catalog) { $env:POSTGRESQL_CATALOG_DSN = $CatalogDsn }

function Assert-NameOk {
    param([string]$Name, [string]$Field)
    if ($Name -cnotmatch '^[a-z0-9_.]+$') {
        throw "$Field '$Name' is invalid. Allowed: lowercase a-z, digits 0-9, underscore (_), dot (.)."
    }
}
if ($DatasetId -ne "") { Assert-NameOk $DatasetId "DatasetId" }

# 1) Catalog section (needs python + psycopg2 + catalog.py; --files also needs boto3)
if ($Catalog) {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Missing: python is not on PATH." }
    python -c "import psycopg2" 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Missing Python module 'psycopg2'. Install it:  pip install psycopg2-binary" }
    python -c "import boto3" 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Missing Python module 'boto3' (needed for file-type counts). Install it:  pip install boto3" }
    if (-not (Test-Path $catalogPy)) { throw "Missing: catalog.py not found next to this script: $PSScriptRoot" }

    # MinIO creds for catalog.py's --files (file-type counting)
    $env:MINIO_ENDPOINT=$Endpoint; $env:MINIO_ACCESS_KEY=$AccessKey; $env:MINIO_SECRET_KEY=$SecretKey

    Write-Host "=== Catalog (registered in DB) ===" -ForegroundColor Cyan
    if ($DatasetId -ne "") { python $catalogPy tree --files $DatasetId } else { python $catalogPy tree --files }
}

# 2) MinIO section (needs mc)
if ($ObjectStorage) {
    if (-not (Get-Command mc -ErrorAction SilentlyContinue)) {
        throw "Missing: mc (MinIO Client) is not on PATH. Install it (see minio.md 'Installing mc')."
    }
    mc alias set $Alias $Endpoint $AccessKey $SecretKey | Out-Null
    if ($DatasetId -ne "") { $prefix = "$Alias/$Bucket/$DatasetId/" } else { $prefix = "$Alias/$Bucket/" }

    if ($Catalog) { Write-Host "" }
    Write-Host "=== MinIO objects ($prefix) ===" -ForegroundColor Cyan
    if ($ShowVersions) { mc ls --recursive --versions $prefix } else { mc ls --recursive $prefix }
}
