# data_remover.ps1
# PERMANENTLY remove a dataset (or one version) from BOTH MinIO and the catalog DB.
#   - MinIO : deletes ALL object versions (mc rm --recursive --force --versions) -> not recoverable
#   - catalog: deletes the matching rows in the `datasets` table
#
# Naming rules (DatasetId / Version): lowercase a-z, digits 0-9, underscore (_), dot (.) only.
#
# Prerequisites:
#   - mc on PATH; python + psycopg2 (pip install psycopg2-binary); catalog.py in run folder
#   - postgres reachable at localhost:5432
#
# Examples:
#   .\data_remover.ps1 -DatasetId sydney_202605 -Version 0          # one version
#   .\data_remover.ps1 -DatasetId sydney_202605                     # whole dataset (all versions)
#   .\data_remover.ps1 -DatasetId sydney_202605 -Version 0 -Force   # skip confirmation
#
param(
    [Parameter(Mandatory=$true)][string]$DatasetId,
    [string]$Version   = "",                 # empty => remove the ENTIRE dataset (all versions)
    [string]$Bucket     = "datasets",
    [string]$Endpoint   = $env:MINIO_ENDPOINT,     # or pass -Endpoint
    [string]$AccessKey  = $env:MINIO_ACCESS_KEY,   # MinIO username (access key)
    [string]$SecretKey  = $env:MINIO_SECRET_KEY,   # MinIO password (secret key)
    [string]$CatalogDsn = $env:POSTGRESQL_CATALOG_DSN,        # postgresql://user:pass@host:5432/catalog
    [string]$Alias      = "local",
    [switch]$Force                            # skip the confirmation prompt
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

Assert-NameOk $DatasetId "DatasetId"
if ($Version -ne "") { Assert-NameOk $Version "Version" }

# Resolve target prefix / display path
mc alias set $Alias $Endpoint $AccessKey $SecretKey | Out-Null
if ($Version -ne "") {
    $prefix = "$Alias/$Bucket/$DatasetId/$Version/"
    $shown  = "s3://$Bucket/$DatasetId/$Version/  (single version)"
} else {
    $prefix = "$Alias/$Bucket/$DatasetId/"
    $shown  = "s3://$Bucket/$DatasetId/  (ENTIRE dataset, all versions)"
}

# Preview what exists (including all object versions / delete markers)
Write-Host "Target: $shown" -ForegroundColor Yellow
Write-Host "--- MinIO objects/versions ---"
mc ls --recursive --versions $prefix
Write-Host "--- catalog rows ---"
$env:DR_ID=$DatasetId; $env:DR_VER=$Version
python -c "import os,catalog; rows=[r for r in catalog.versions(os.environ['DR_ID']) if (not os.environ.get('DR_VER')) or r['version']==os.environ['DR_VER']]; [print(' ', r['version'], r['minio_path']) for r in rows] or print('  (none)')"

# Confirm (permanent!). -Force skips this.
if (-not $Force) {
    Write-Warning "This PERMANENTLY deletes the above from MinIO (all versions) AND catalog."
    $ans = Read-Host "Type DELETE to confirm"
    if ($ans -cne 'DELETE') { throw "Cancelled (you did not type DELETE)." }
}

# 1) MinIO: purge all versions (permanent)
mc rm --recursive --force --versions $prefix
if ($LASTEXITCODE -ne 0) { Write-Warning "mc rm returned $LASTEXITCODE (maybe nothing to delete in MinIO)." }

# 2) catalog: delete matching rows (by dataset_id [+ version])
python -c "import os,catalog,psycopg2; ds=os.environ['DR_ID']; ver=os.environ.get('DR_VER','') or None; c=psycopg2.connect(catalog.DSN); cur=c.cursor(); (cur.execute('DELETE FROM datasets WHERE dataset_id=%s AND version=%s',(ds,ver)) if ver else cur.execute('DELETE FROM datasets WHERE dataset_id=%s',(ds,))); c.commit(); print('[catalog] deleted rows:', cur.rowcount)"
if ($LASTEXITCODE -ne 0) { throw "Catalog deletion failed (check python/psycopg2)." }

Write-Host "Done: removed $shown from MinIO and catalog." -ForegroundColor Green
