#!/usr/bin/env bash
# open_backing_ports.sh — check backing service reachability and open inbound firewall (ufw) if blocked.
# __version__ = "0.0.2"  # Semantic Versioning:  Version = Major.Minor.Patch
# Run on the host that SERVES the ports (opening inbound edits the local ufw firewall). Needs sudo.
#   sudo ./open_backing_ports.sh --postgresql 192.168.0.8:5432 --minio 192.168.0.8:9000 --mlflow 192.168.0.8:5000
set -euo pipefail

declare -A SVC                          # display name -> host:port

while [ $# -gt 0 ]; do
    case "$1" in
        --postgresql) SVC[PostgreSQL]="$2"; shift 2 ;;
        --minio)      SVC[MinIO]="$2";      shift 2 ;;
        --mlflow)     SVC[MLflow]="$2";     shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

[ ${#SVC[@]} -gt 0 ] || {
    echo "Usage: $0 [--postgresql host:port] [--minio host:port] [--mlflow host:port]" >&2
    exit 1
}

for name in "${!SVC[@]}"; do
    hp="${SVC[$name]}"
    host="${hp%:*}"; port="${hp#*:}"
    if timeout 3 bash -c "</dev/tcp/$host/$port" 2>/dev/null; then
        echo "$name $hp OPEN — reachable, no rule added"
    else
        subnet="${host%.*}.0/24"        # derive the LAN /24 from the address (192.168.0.8 -> 192.168.0.0/24)
        echo "$name $hp BLOCKED — opening inbound $port/tcp from $subnet"
        sudo ufw allow from "$subnet" to any port "$port" proto tcp
    fi
done
