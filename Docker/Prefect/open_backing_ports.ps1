# open_backing_ports.ps1 — check backing service reachability and open inbound firewall (Windows Defender) if blocked.
# __version__ = "0.0.2"  # Semantic Versioning:  Version = Major.Minor.Patch
# Run as Administrator on the host that SERVES the ports (opening inbound edits the local firewall).
#   .\open_backing_ports.ps1 -PostgreSQL 192.168.0.8:5432 -MinIO 192.168.0.8:9000 -MLflow 192.168.0.8:5000
param(
    [string]$PostgreSQL,                # host:port, e.g. 192.168.0.8:5432
    [string]$MinIO,                     # host:port, e.g. 192.168.0.8:9000
    [string]$MLflow                     # host:port, e.g. 192.168.0.8:5000
)
$ErrorActionPreference = "Stop"

$svc = [ordered]@{}                     # display name -> host:port
if ($PostgreSQL) { $svc["PostgreSQL"] = $PostgreSQL }
if ($MinIO)      { $svc["MinIO"]      = $MinIO }
if ($MLflow)     { $svc["MLflow"]     = $MLflow }

if ($svc.Count -eq 0) {
    Write-Error "Usage: .\open_backing_ports.ps1 [-PostgreSQL host:port] [-MinIO host:port] [-MLflow host:port]"
    exit 1
}

foreach ($name in $svc.Keys) {
    $hp = $svc[$name]
    $addr, $portStr = $hp.Split(":")
    $port = [int]$portStr
    $ok = (Test-NetConnection -ComputerName $addr -Port $port -WarningAction SilentlyContinue).TcpTestSucceeded
    if ($ok) {
        Write-Host "$name $hp OPEN - reachable, no rule added"
    } else {
        $subnet = ($addr -replace '\.\d+$', '.0') + "/24"   # derive the LAN /24 from the address
        $rule   = "mlops $name $port inbound"
        Write-Host "$name $hp BLOCKED - opening inbound $port/tcp from $subnet"
        if (-not (Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue)) {
            New-NetFirewallRule -DisplayName $rule -Direction Inbound `
                -Protocol TCP -LocalPort $port -Action Allow -RemoteAddress $subnet | Out-Null
        }
    }
}
