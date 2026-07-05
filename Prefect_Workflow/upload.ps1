# __version__ = "0.0.21"

$ErrorActionPreference = "Stop"

# Configuration
Write-Host "MLOps=$env:MLOps"
$catalog_path = "$env:MLOps/Prefect_Workflow/catalog.py"
$env:PYTHONPATH = "$env:MLOps/Docker/Prefect"   # so catalog.py can import credentials.py
$base_path = "f:/Z/"
$keys = @(
    "Sydney/MetalPoC/CleanData/#2/V0"
)
$spec_path = "f:/Z/Sydney-MetalALDPoC.json"
$block     = "yrocket"
$file_pattern = "*.parquet"

# Check 1: every key exists in the spec file (spec.json is { minio_key: spec, ... }).
if (-not (Test-Path -LiteralPath $spec_path)) {
    throw "spec file not found: $spec_path"
}
$spec = Get-Content -Raw -Encoding UTF8 -LiteralPath $spec_path | ConvertFrom-Json
foreach ($key in $keys) {
    if ($spec.PSObject.Properties.Name -notcontains $key) {
        throw "key not in spec ($spec_path): $key"
    }
}

# Check 2: data files exist under each key's data path.
foreach ($key in $keys) {
    $data_path = "${base_path}${key}/${file_pattern}"
    $files = Get-ChildItem -Path $data_path -File -ErrorAction SilentlyContinue
    if (-not $files) {
        throw "no data found: $data_path"
    }
    Write-Host "data ok: $key ($($files.Count) files)"
}

# Upload
foreach ($key in $keys) {
    Write-Host "minio_key=$key"
    $data_path = "${base_path}${key}/${file_pattern}"
    Write-Host "data_path=$data_path"
    python $catalog_path upload `
        $spec_path `
        --minio-key $key `
        --path $data_path `
        --minio-host 127.0.0.1 --pg-host 127.0.0.1 -b $block
    Write-Host ""
}
