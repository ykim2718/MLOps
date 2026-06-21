# data_downloader.ps1
# Look up a dataset version in the catalog DB and download its minio_path from MinIO.
# (Reverse of data_uploader.ps1; "search -> select -> download" pattern.)
#
# Naming rules (DatasetId / Version): lowercase a-z, digits 0-9, underscore (_), dot (.) only.
#
# Prerequisites:
#   - mc on PATH; python + psycopg2 (pip install psycopg2-binary); catalog.py in run folder
#   - postgres reachable at localhost:5432
#
# Examples:
#   .\data_downloader.ps1 -DatasetId sydney_202605 -Version v2 -Dest .\download
#   .\data_downloader.ps1 -DatasetId mnist                 # latest version when omitted
#
param(
    [Parameter(Mandatory=$true)][string]$DatasetId,
    [string]$Version   = "",
    [string]$Dest      = "",
    [string]$Endpoint   = $env:MINIO_ENDPOINT,     # or pass -Endpoint
    [string]$AccessKey  = $env:MINIO_ACCESS_KEY,   # MinIO username (access key)
    [string]$SecretKey  = $env:MINIO_SECRET_KEY,   # MinIO password (secret key)
    [string]$CatalogDsn = $env:POSTGRESQL_CATALOG_DSN,        # postgresql://user:pass@host:5432/catalog
    [string]$Alias      = "local"
)

$ErrorActionPreference = "Stop"

# Make catalog.py (next to this script) importable regardless of current directory
$env:PYTHONPATH = $PSScriptRoot

# Verify required tools/modules up front; show an install hint and abort if missing.
function Assert-Prereqs {
    if (-not (Get-Command mc -ErrorAction SilentlyContinue)) {
        throw "Missing: mc (MinIO Client) is not on PATH. Install it (see minio.md 'mc Installation')."
    }
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw "Missing: python is not on PATH."
    }
    python -c "import psycopg2" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Missing Python module 'psycopg2'. Install it:  pip install psycopg2-binary"
    }
    if (-not (Test-Path (Join-Path $PSScriptRoot 'catalog.py'))) {
        throw "Missing: catalog.py not found next to this script: $PSScriptRoot"
    }
}
Assert-Prereqs

# Credentials come from -params or environment (no hardcoded secrets in this script)
if (-not $Endpoint -or -not $AccessKey -or -not $SecretKey) {
    throw "MinIO connection missing. Set env MINIO_ENDPOINT / MINIO_ACCESS_KEY / MINIO_SECRET_KEY, or pass -Endpoint / -AccessKey / -SecretKey."
}
if (-not $CatalogDsn) {
    throw "Catalog DB DSN missing. Set env POSTGRESQL_CATALOG_DSN or pass -CatalogDsn (e.g. postgresql://user:pass@host:5432/catalog)."
}
$env:POSTGRESQL_CATALOG_DSN = $CatalogDsn

# Name rule: lowercase / digits / underscore / dot only (case-sensitive to reject uppercase)
function Assert-NameOk {
    param([string]$Name, [string]$Field)
    if ($Name -cnotmatch '^[a-z0-9_.]+$') {
        throw "$Field '$Name' is invalid. Allowed: lowercase a-z, digits 0-9, underscore (_), dot (.). Not allowed: spaces, uppercase, dash (-), other special chars."
    }
}

Assert-NameOk $DatasetId "DatasetId"
if ($Version -ne "") { Assert-NameOk $Version "Version" }

# 1) Resolve minio_path from catalog (latest when Version empty); pass values via env
$env:DD_ID=$DatasetId; $env:DD_VER=$Version
$minioPath = (python -c "import os, catalog; r=catalog.get(os.environ['DD_ID'], os.environ.get('DD_VER') or None); print(r['minio_path'] if r else '')").Trim()
if ($LASTEXITCODE -ne 0) { throw "Catalog lookup failed (check python/psycopg2: pip install psycopg2-binary)." }
if (-not $minioPath) { throw "Not found in catalog: '$DatasetId' (version='$Version')." }

# 2) s3://bucket/key/ -> mc path local/bucket/key/
$src = "$Alias/" + ($minioPath -replace '^s3://', '')

# 3) Prepare destination folder (default: .\<DatasetId>)
if (-not $Dest) { $Dest = ".\$DatasetId" }
New-Item -ItemType Directory -Force -Path $Dest | Out-Null

# 4) Set alias + download
mc alias set $Alias $Endpoint $AccessKey $SecretKey | Out-Null
mc cp --recursive $src $Dest
if ($LASTEXITCODE -ne 0) { throw "MinIO download failed (mc exit $LASTEXITCODE)." }

Write-Host "Done: $minioPath -> $Dest" -ForegroundColor Green
