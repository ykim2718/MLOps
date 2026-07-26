#!/usr/bin/env bash
# backing_ports.sh — check reachability of, or open the inbound firewall (ufw) for, one backing service port.
# __version__ = "0.0.3"  # Semantic Versioning:  Version = Major.Minor.Patch
#   check : TCP-test the port. Run from a CONSUMING host (server / worker) to see real reachability;
#           from the serving host it is a meaningless loopback (always OPEN).
#   open  : open the inbound firewall (ufw) for the port. Run on the host that SERVES it (needs sudo). Idempotent.
#
#   ./backing_ports.sh check -host 192.168.0.13 -port 5432
#   sudo ./backing_ports.sh open -host 192.168.0.13 -port 5432
set -euo pipefail

ACTION="${1:-}"; [ $# -gt 0 ] && shift
HOST=""; PORT=""
while [ $# -gt 0 ]; do
    case "$1" in
        -host) HOST="$2"; shift 2 ;;
        -port) PORT="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if { [ "$ACTION" != check ] && [ "$ACTION" != open ]; } || [ -z "$HOST" ] || [ -z "$PORT" ]; then
    echo "Usage: $0 <check|open> -host <ip> -port <port>" >&2
    exit 1
fi

if [ "$ACTION" = check ]; then
    if timeout 3 bash -c "</dev/tcp/$HOST/$PORT" 2>/dev/null; then
        echo "$HOST:$PORT OPEN"
    else
        echo "$HOST:$PORT BLOCKED"
    fi
else   # open
    subnet="${HOST%.*}.0/24"                # derive the LAN /24 from the address (192.168.0.13 -> 192.168.0.0/24)
    echo "ensuring inbound $PORT/tcp from $subnet"
    sudo ufw allow from "$subnet" to any port "$PORT" proto tcp   # idempotent: ufw skips a duplicate rule
fi
