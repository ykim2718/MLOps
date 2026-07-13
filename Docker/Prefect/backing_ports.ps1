# backing_ports.ps1 — check reachability of, or open the inbound firewall for, one backing service port.
# __version__ = "0.0.2"  # Semantic Versioning:  Version = Major.Minor.Patch
#   check : TCP-test the port. Run from a CONSUMING host (server / dispatcher) to see real reachability;
#           from the serving host it is a meaningless loopback (always OPEN).
#   open  : open the inbound firewall (Windows Defender) for the port. Run as Administrator on the host
#           that SERVES the port. Idempotent (skips an existing rule).
#
#   .\backing_ports.ps1 check -host 192.168.0.13 -port 5432
#   .\backing_ports.ps1 open  -host 192.168.0.13 -port 5432
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("check", "open")]
    [string]$Action,
    [Parameter(Mandatory = $true)] [Alias("host")] [string]$HostName,   # backing service host (LAN IP)
    [Parameter(Mandatory = $true)] [int]$Port                           # service port, e.g. 5432 / 9000 / 5000
)
$ErrorActionPreference = "Stop"

if ($Action -eq "check") {
    $ok = (Test-NetConnection -ComputerName $HostName -Port $Port -WarningAction SilentlyContinue).TcpTestSucceeded
    if ($ok) { Write-Host "${HostName}:${Port} OPEN" }
    else     { Write-Host "${HostName}:${Port} BLOCKED" }
}
else {   # open
    $subnet = ($HostName -replace '\.\d+$', '.0') + "/24"   # derive the LAN /24 from the address
    $rule   = "mlops backing $Port inbound"
    Write-Host "ensuring inbound $Port/tcp from $subnet"
    if (-not (Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue)) {   # idempotent
        New-NetFirewallRule -DisplayName $rule -Direction Inbound `
            -Protocol TCP -LocalPort $Port -Action Allow -RemoteAddress $subnet | Out-Null
    }
}
