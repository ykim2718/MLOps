# check_status.ps1 - health & wiring check for the Prefect MLOps stack (per prefect.md "1. Architecture").
# __version__ = "0.0.20"  # Semantic Versioning:  Version = Major.Minor.Patch
#
# Read-only. It inspects, it never changes anything. It verifies the always-on pieces are up and
# correctly wired, then prints an ASCII diagram of the architecture with live [ OK ] / [WARN] / [FAIL]:
#   docker network -> Prefect Server -> pools (routing) -> dispatchers (workers, with IP) -> deployments
#   + each pool's options (base job template) + Prefect Secrets + backing services (postgres/minio/mlflow).
#
# At startup it checks the required commands are installed; if any is missing it prints how to get it and aborts.
# ASCII-only output on purpose: Windows PowerShell 5.1 mangles box-drawing/Unicode under a non-UTF-8 codepage.
# Indent levels: section header = 2, item = 4, item detail = 6, sub-detail = 8.
#
#   .\check_status.ps1
#   .\check_status.ps1 -ApiUrl http://192.168.0.101:4200/api   # a remote server
#
param(
    [string]  $ApiUrl       = "http://127.0.0.1:4200/api",                                          # Prefect server API (health + CLI target)
    [string]  $MinioUrl     = "http://127.0.0.1:9000",                                              # MinIO S3 endpoint
    [string]  $MlflowUrl    = "http://127.0.0.1:5000",                                              # MLflow tracking server
    [int]     $PostgresPort = 5432,                                                                 # PostgreSQL (metadata DB) port on the host
    [string]  $Network      = "mlops",                                                              # shared docker network
    [string]  $DispImage    = "prefect-dispatcher:latest",                                          # dispatcher image (to find local containers + their IP)
    [string[]]$Pools        = @("high_performance", "low_performance"),                             # expected docker work pools
    [string[]]$Secrets      = @("minio-endpoint","minio-access-key","minio-secret-key","catalog-dsn","optuna-dsn")  # run-code credential blocks
)

$ErrorActionPreference = "Stop"
$script:nFail = 0
$script:nWarn = 0

# ---------- helpers ----------------------------------------------------------
function Node([string]$state, [string]$text) {
    switch ($state) {
        "OK"   { $tag = "[ OK ]"; $c = "Green" }
        "WARN" { $tag = "[WARN]"; $c = "Yellow"; $script:nWarn++ }
        default{ $tag = "[FAIL]"; $c = "Red";    $script:nFail++ }
    }
    Write-Host ("  {0} {1}" -f $text.PadRight(66), $tag) -ForegroundColor $c
}

function Info([string]$text) { Write-Host ("  {0}" -f $text) -ForegroundColor DarkGray }

function Test-Tcp([string]$h, [int]$p) {
    try {
        $cl = New-Object System.Net.Sockets.TcpClient
        $ar = $cl.BeginConnect($h, $p, $null, $null)
        $ok = $ar.AsyncWaitHandle.WaitOne(3000, $false)
        if ($ok) { $cl.EndConnect($ar) }
        $cl.Close()
        return $ok
    } catch { return $false }
}

function Test-Url([string]$url) {
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400)
    } catch { return $false }
}

function Test-PrefectHealth([string]$apiUrl) {
    try { return ((("{0}" -f (Invoke-RestMethod -Uri ("{0}/health" -f $apiUrl) -TimeoutSec 5))).ToLower() -eq "true") }
    catch { return $false }
}

function Get-PrefectJson([string[]]$cliArgs) {
    $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $raw = & prefect @cliArgs 2>$null } finally { $ErrorActionPreference = $old }
    if (-not $raw) { return $null }
    $text = ($raw -join "`n")
    $s = $text.IndexOfAny([char[]]@('[','{'))
    $e = [Math]::Max($text.LastIndexOf(']'), $text.LastIndexOf('}'))
    if ($s -lt 0 -or $e -le $s) { return $null }
    try { return ($text.Substring($s, $e - $s + 1) | ConvertFrom-Json) } catch { return $null }
}

function Test-PrefectObject([string[]]$cliArgs) {
    $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { & prefect @cliArgs *> $null } finally { $ErrorActionPreference = $old }
    return ($LASTEXITCODE -eq 0)
}

function Get-Workers([string]$apiUrl, [string]$pool) {
    try { return Invoke-RestMethod -Uri ("{0}/work_pools/{1}/workers/filter" -f $apiUrl, $pool) -Method Post -Body '{}' -ContentType 'application/json' -TimeoutSec 5 }
    catch { return $null }
}

function Tdefault($p, [string]$key) {
    try {
        $props = $p.base_job_template.variables.properties
        if ($null -ne $props -and ($props.PSObject.Properties.Name -contains $key)) { return $props.$key.default }
    } catch {}
    return $null
}

function Get-LocalDispatchers([string]$image, [string]$network) {
    # map: pool name -> array of "<container-name> ip(<network>)=<addr>" for dispatcher containers on THIS host.
    $map = @{}
    try {
        $ids = @(docker ps --filter ("ancestor={0}" -f $image) --format "{{.ID}}" 2>$null) | Where-Object { $_ }
        foreach ($id in $ids) {
            $insp = @(docker inspect $id 2>$null | ConvertFrom-Json)[0]
            $tokens = @()
            if ($insp.Config.Entrypoint) { $tokens += @($insp.Config.Entrypoint) }
            if ($insp.Config.Cmd)        { $tokens += @($insp.Config.Cmd) }
            if ($insp.Args)              { $tokens += @($insp.Args) }
            $pool = ""
            for ($i = 0; $i -lt $tokens.Count - 1; $i++) { if ($tokens[$i] -eq '--pool') { $pool = $tokens[$i + 1]; break } }
            $ip = ""
            try { $ip = $insp.NetworkSettings.Networks.$network.IPAddress } catch {}
            $name = ($insp.Name -replace '^/', '')
            $entry = ("{0}   ip({1})={2}" -f $name, $network, $(if ($ip) { $ip } else { "?" }))
            if (-not $map.ContainsKey($pool)) { $map[$pool] = @() }
            $map[$pool] += $entry
        }
    } catch {}
    return $map
}

# ---------- 0. prerequisites (abort if a required command is missing) --------
Write-Host ""
Write-Host "Prerequisites" -ForegroundColor Cyan
$required = @('docker', 'prefect')
$missing  = @($required | Where-Object { -not (Get-Command $_ -ErrorAction SilentlyContinue) })
if ($missing.Count -gt 0) {
    Write-Host ("  Missing required command(s): {0}" -f ($missing -join ', ')) -ForegroundColor Red
    if ($missing -contains 'docker')  { Write-Host "    docker  -> install Docker Desktop, then start it." -ForegroundColor Yellow }
    if ($missing -contains 'prefect') { Write-Host ("    prefect -> pip install prefect ; prefect config set PREFECT_API_URL={0}" -f $ApiUrl) -ForegroundColor Yellow }
    Write-Host "  Aborting: required commands are not on PATH." -ForegroundColor Red
    exit 1
}
Node "OK" ("docker present   ({0})" -f (docker --version))
Node "OK"  "prefect present"

$dockerUp = $false
try { docker info *> $null; $dockerUp = ($LASTEXITCODE -eq 0) } catch { $dockerUp = $false }
if (-not $dockerUp) { Node "FAIL" "docker daemon responding"; Write-Host "  Aborting: Docker daemon not reachable (start Docker Desktop)." -ForegroundColor Red; exit 1 }
Node "OK" "docker daemon responding"

# ---------- 1. gather live status --------------------------------------------
$netOk = $false
try { docker network inspect $Network *> $null; $netOk = ($LASTEXITCODE -eq 0) } catch {}

$serverOk = Test-PrefectHealth $ApiUrl
$pgOk     = Test-Tcp "127.0.0.1" $PostgresPort
$minioOk  = Test-Url ("{0}/minio/health/live" -f $MinioUrl)
$mlflowOk = Test-Url ("{0}/health" -f $MlflowUrl)
if (-not $mlflowOk) { $mlflowOk = Test-Url $MlflowUrl }

$localDisp = Get-LocalDispatchers $DispImage $Network
$poolsJson = $null
if ($serverOk) { $poolsJson = Get-PrefectJson @('work-pool','ls','--output','json') }

# ---------- 2. render the diagram --------------------------------------------
Write-Host ""
Write-Host "Architecture status  (prefect.md  1. Architecture)" -ForegroundColor Cyan
Write-Host ""

Node ($(if ($netOk)    { "OK" } else { "FAIL" })) ("docker network: {0}" -f $Network)
Node ($(if ($serverOk) { "OK" } else { "FAIL" })) ("Prefect Server  {0}   (health={1})" -f $ApiUrl, ("{0}" -f $serverOk).ToLower())

if (-not $serverOk) {
    Node "WARN" "  server API unreachable - pool / worker / deployment / secret checks skipped"
} else {
    Info "POOLS (routing) + DISPATCHERS (workers):"
    $registered = @()
    if ($poolsJson) { $registered = @($poolsJson | Where-Object { $_.type -eq 'docker' }) }

    foreach ($p in $registered) {
        $name = $p.name
        $expected = ($Pools -contains $name)
        $st = ("{0}" -f $p.status).ToUpper()
        $cc = $(if ($null -eq $p.concurrency_limit) { "none" } else { $p.concurrency_limit })

        $workers = Get-Workers $ApiUrl $name
        if ($null -ne $workers) {
            $wAll = @($workers)
            $wOn  = @($wAll | Where-Object { ("{0}" -f $_.status).ToUpper() -eq 'ONLINE' })
            $ready = ($wOn.Count -gt 0)
            $wLine = ("dispatchers (server records): {0} online, {1} offline(stale) / {2} total" -f $wOn.Count, ($wAll.Count - $wOn.Count), $wAll.Count)
        } else {
            $ready = ($st -eq 'READY')
            $wLine = ("dispatchers: status={0} (live count via API unavailable)" -f $st)
        }

        if (-not $expected)  { Node "WARN" ("  pool {0}  UNEXPECTED (typo?) - delete: prefect work-pool delete {0}" -f $name) }
        elseif ($ready)      { Node "OK"   ("  pool {0}" -f $name) }
        else                 { Node "WARN" ("  pool {0}  registered but {1} (no live worker: run_dispatcher.ps1)" -f $name, $st) }

        Info ("    concurrency_limit={0}   status={1}" -f $cc, $st)
        Info ("    {0}" -f $wLine)
        if ($null -ne $workers) {
            foreach ($w in @($workers | Where-Object { ("{0}" -f $_.status).ToUpper() -eq 'ONLINE' })) {
                Info ("      online worker: {0}   last_heartbeat={1}" -f $w.name, $w.last_heartbeat_time)
            }
        }
        if ($localDisp.ContainsKey($name) -and $localDisp[$name].Count -gt 0) {
            Info  "    local dispatcher container(s) on this host:"
            foreach ($d in $localDisp[$name]) { Info ("      - {0}" -f $d) }
        } else {
            Info  "    local dispatcher container(s) on this host: none (dispatcher may be on another machine)"
        }
        $img = Tdefault $p 'image'; $mem = Tdefault $p 'mem_limit'; $auto = Tdefault $p 'auto_remove'
        $net = Tdefault $p 'networks'; $envd = Tdefault $p 'env'
        $netStr = $(if ($net) { ($net -join ',') } else { '?' })
        $api = $null; if ($envd) { try { $api = $envd.PREFECT_API_URL } catch {} }
        Info ("    options: image={0}  mem_limit={1}  networks={2}  auto_remove={3}  env.PREFECT_API_URL={4}" -f $img, $mem, $netStr, $auto, $api)

        $tier = ($name -split '_')[0]
        $dep  = "pipeline/pipelineflow-$tier"
        if (Test-PrefectObject @('deployment','inspect',$dep)) { Node "OK" ("    deployment $dep") }
        else { Node "FAIL" ("    deployment $dep  (not registered - prefect deploy)") }
    }

    foreach ($name in $Pools) {
        if (-not ($registered | Where-Object { $_.name -eq $name })) {
            Node "FAIL" ("  pool $name  MISSING - register with register_pool.ps1")
        }
    }

    # Prefect Secrets are server-wide blocks, independent of any pool.
    Write-Host ""
    Info "PREFECT SECRETS (run-code credentials; server-wide, independent of pools):"
    foreach ($s in $Secrets) {
        if (Test-PrefectObject @('block','inspect',"secret/$s")) { Node "OK" ("  secret $s") }
        else { Node "FAIL" ("  secret $s  (missing - create the Secret block)") }
    }
}

# backing services (own compose stacks; checked by endpoint, not by container name)
Write-Host ""
Info "BACKING SERVICES:"
Node ($(if ($pgOk)     { "OK" } else { "FAIL" })) ("  postgres  :{0}   (metadata DB)" -f $PostgresPort)
Node ($(if ($minioOk)  { "OK" } else { "FAIL" }))  "  minio     :9000  (object storage)"
Node ($(if ($mlflowOk) { "OK" } else { "FAIL" }))  "  mlflow    :5000  (tracking)"

# ---------- 3. summary + exit code -------------------------------------------
Write-Host ""
if ($script:nFail -eq 0 -and $script:nWarn -eq 0) {
    Write-Host "All checks passed." -ForegroundColor Green
    exit 0
} elseif ($script:nFail -eq 0) {
    Write-Host ("Done with {0} warning(s), 0 failure(s)." -f $script:nWarn) -ForegroundColor Yellow
    exit 0
} else {
    Write-Host ("Done with {0} failure(s), {1} warning(s)." -f $script:nFail, $script:nWarn) -ForegroundColor Red
    exit 1
}
