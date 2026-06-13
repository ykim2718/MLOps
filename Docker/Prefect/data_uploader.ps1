# data_uploader.ps1
# Upload data to MinIO + register a "version record" in the catalog DB, in one step.
#
# Naming rules (DatasetId AND Version):
#   allowed : lowercase a-z, digits 0-9, underscore (_), dot (.)
#   NOT ok  : spaces, uppercase, dash (-), other special chars  -> script aborts
#   (these values become the MinIO path and the catalog key)
#
# Prerequisites:
#   - mc (MinIO Client) installed and on PATH
#   - python + psycopg2 available, catalog.py in the run folder
#       (if "No module named 'psycopg2'":  pip install psycopg2-binary)
#   - postgres reachable at localhost:5432 (docker-compose must expose the port)
#
# Examples:
#   .\data_uploader.ps1 -DatasetId sydney_202605 -Version v2   -Path .\out\ -Comment "fab2 CH3"
#   .\data_uploader.ps1 -DatasetId mnist         -Version v1.0 -Path .\train.parquet
#
param(
    [Parameter(Mandatory=$true)][string]$DatasetId,
    [Parameter(Mandatory=$true)][string]$Version,
    [Parameter(Mandatory=$true)][string]$Path,
    [string]$Bucket    = "datasets",
    [string]$CreatedBy = $env:USERNAME,
    [string]$Comment   = "",
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
        throw "Missing: mc (MinIO Client) is not on PATH. Install it (see README 'Installing mc')."
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

# True if the prefix already has objects in MinIO
function Test-PrefixExists {
    param([string]$Prefix)
    $o = mc ls $Prefix 2>$null
    return [bool]$o
}

Assert-NameOk $DatasetId "DatasetId"
Assert-NameOk $Version   "Version"

if (-not (Test-Path $Path)) { throw "Path not found: $Path" }

# Register mc alias (idempotent) using the provided credentials
mc alias set $Alias $Endpoint $AccessKey $SecretKey | Out-Null

$dest      = "$Alias/$Bucket/$DatasetId/$Version/"
$minioPath = "s3://$Bucket/$DatasetId/$Version/"

# Duplicate check: if DatasetId/Version already exists in MinIO, re-enter a Version or cancel
while (Test-PrefixExists $dest) {
    Write-Warning "Version already exists (duplicate): $minioPath"
    $new = Read-Host "Enter a different Version (press Enter to cancel)"
    if ([string]::IsNullOrWhiteSpace($new)) {
        throw "Aborted: duplicate version $DatasetId/$Version"
    }
    Assert-NameOk $new "Version"
    $Version   = $new
    $dest      = "$Alias/$Bucket/$DatasetId/$Version/"
    $minioPath = "s3://$Bucket/$DatasetId/$Version/"
}

# Upload; record this version's comment as object metadata (--attr)
$attrPairs = @("version=$Version", "uploaded_by=$CreatedBy")
if ($Comment -ne "") { $attrPairs += "comment=$Comment" }
$attr = ($attrPairs -join ";")

if (Test-Path $Path -PathType Container) {
    mc cp --recursive --attr $attr "$Path" $dest
} else {
    mc cp --attr $attr "$Path" $dest
}
if ($LASTEXITCODE -ne 0) { throw "MinIO upload failed (mc exit $LASTEXITCODE)." }

# Register the version record in catalog (values via env to avoid quoting/injection)
$env:DU_ID=$DatasetId; $env:DU_VER=$Version; $env:DU_PATH=$minioPath
$env:DU_BY=$CreatedBy;  $env:DU_COMMENT=$Comment
python -c "import os, catalog; catalog.ensure_schema(); catalog.register(os.environ['DU_ID'], os.environ['DU_VER'], os.environ['DU_PATH'], created_by=os.environ.get('DU_BY') or None, description=os.environ.get('DU_COMMENT') or None, metadata={'comment': os.environ.get('DU_COMMENT','')}); print('[catalog] registered', os.environ['DU_ID'], os.environ['DU_VER'], '->', os.environ['DU_PATH'])"
if ($LASTEXITCODE -ne 0) { throw "Catalog registration FAILED (check python/psycopg2: pip install psycopg2-binary). Upload succeeded but the version was NOT registered." }

Write-Host "Done: uploaded to $minioPath and registered in catalog." -ForegroundColor Green
