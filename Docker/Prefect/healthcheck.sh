#!/usr/bin/env bash
# healthcheck.sh - health & wiring check for the Prefect MLOps stack (per prefect.md "1. Architecture").
# __version__ = "0.0.26"  # Semantic Versioning:  Version = Major.Minor.Patch  (bash port of healthcheck.ps1)
#
# Read-only. It inspects, it never changes anything. It verifies the always-on pieces are up and
# correctly wired, then prints an ASCII diagram of the architecture with live [ OK ] / [WARN] / [FAIL]:
#   docker network -> Prefect Server -> pools (routing) -> dispatchers (workers, with IP) -> deployments
#   + each pool's options (base job template) + Credentials blocks + backing services (postgres/minio/mlflow).
#
# At startup it checks the required commands are installed; if any is missing it prints how to get it and aborts.
# Requires: docker, prefect, curl, jq. Output is capped at 120 columns (tags stay visible).
# No 'set -e': health checks are expected to fail, and each failure is handled locally.
#
#   ./healthcheck.sh
#   ./healthcheck.sh --api-url http://192.168.0.101:4200/api   # a remote server
#
set -uo pipefail

RESET=$'\033[0m'
C_GREEN=$'\033[32m'
C_YELLOW=$'\033[33m'
C_RED=$'\033[31m'
C_GRAY=$'\033[90m'
C_CYAN=$'\033[36m'

nFail=0
nWarn=0
declare -A LOCALDISP

# ---------- helpers ----------------------------------------------------------
node() {
    local state="$1" text="$2" tag color
    case "$state" in
        OK)   tag="[ OK ]"; color="$C_GREEN" ;;
        WARN) tag="[WARN]"; color="$C_YELLOW"; nWarn=$((nWarn + 1)) ;;
        *)    tag="[FAIL]"; color="$C_RED";    nFail=$((nFail + 1)) ;;
    esac
    # Cap the whole line at 120 columns: 2 (indent) + text + 1 (space) + 6 (tag) <= 120 -> text <= 111.
    if [ "${#text}" -gt 111 ]; then text="${text:0:108}..."; fi
    printf '%s  %-66s %s%s\n' "$color" "$text" "$tag" "$RESET"
}

info() {
    local text="$1"
    if [ "${#text}" -gt 118 ]; then text="${text:0:115}..."; fi   # cap at 120: 2 (indent) + text
    printf '%s  %s%s\n' "$C_GRAY" "$text" "$RESET"
}

hint() { printf '%s%s%s\n' "$C_YELLOW" "$1" "$RESET"; }   # a yellow install/usage hint line

test_tcp() {
    # true if a TCP connection to host:port opens within 3s (bash /dev/tcp, no nc needed).
    timeout 3 bash -c "exec 3<>/dev/tcp/$1/$2" >/dev/null 2>&1
}

test_url() {
    # true if an HTTP GET returns a 2xx/3xx status within 5s.
    local code
    code=$(curl -s -o /dev/null -w '%{http_code}' -m 5 "$1" 2>/dev/null)
    [ "$code" -ge 200 ] 2>/dev/null && [ "$code" -lt 400 ] 2>/dev/null
}

test_prefect_health() {
    # Prefect /health returns the literal true when the API is up.
    local body
    body=$(curl -s -m 5 "$1/health" 2>/dev/null)
    case "${body,,}" in *true*) return 0 ;; *) return 1 ;; esac
}

get_workers() {
    # POST .../workers/filter with an empty filter; prints the JSON array (or nothing).
    curl -s -m 5 -X POST -H 'Content-Type: application/json' -d '{}' \
        "$1/work_pools/$2/workers/filter" 2>/dev/null
}

url_port() {
    local p
    p=$(printf '%s' "$1" | sed -nE 's#^[a-zA-Z]+://[^/:]+:([0-9]+).*#\1#p')
    [ -n "$p" ] && printf '%s' "$p" || printf '%s' "?"
}

# jq program: join Entrypoint+Cmd+Args of a `docker inspect` doc, then read the value after --pool.
POOL_JQ='((.[0].Config.Entrypoint // []) + (.[0].Config.Cmd // []) + (.[0].Args // [])) as $t
| ($t | index("--pool")) as $i | if $i == null then "" else ($t[$i + 1] // "") end'

# jq program: first docker pool's first network from its base job template (used to derive NETWORK).
NET_JQ='[.[] | select(.type == "docker")
        | .base_job_template.variables.properties.networks.default[]?] | .[0] // ""'

get_local_dispatchers() {
    # Fill LOCALDISP: pool name -> newline-joined "<container> ip(<network>)=<addr>" for dispatchers here.
    local image="$1" network="$2" id insp pool ip name entry ids
    ids=$(docker ps --filter "ancestor=$image" --format '{{.ID}}' 2>/dev/null)
    for id in $ids; do
        insp=$(docker inspect "$id" 2>/dev/null) || continue
        pool=$(printf '%s' "$insp" | jq -r "$POOL_JQ")
        ip=$(printf '%s' "$insp" | jq -r --arg n "$network" '.[0].NetworkSettings.Networks[$n].IPAddress // ""')
        name=$(printf '%s' "$insp" | jq -r '.[0].Name | ltrimstr("/")')
        [ -z "$ip" ] && ip="?"
        entry="$name   ip($network)=$ip"
        if [ -n "${LOCALDISP[$pool]:-}" ]; then LOCALDISP[$pool]+=$'\n'"$entry"; else LOCALDISP[$pool]="$entry"; fi
    done
}

default_api() {
    # Default to the Prefect CLI's own setting (PREFECT_API_URL env, else the active profile); else localhost.
    if [ -n "${PREFECT_API_URL:-}" ]; then printf '%s' "$PREFECT_API_URL"; return; fi
    if command -v prefect >/dev/null 2>&1; then
        local v
        v=$(prefect config view 2>/dev/null \
            | grep -oE "PREFECT_API_URL='?[^'[:space:]]+'?" | head -n1 | sed -E "s/PREFECT_API_URL=//; s/'//g")
        if [ -n "$v" ]; then printf '%s' "$v"; return; fi
    fi
    printf '%s' "http://127.0.0.1:4200/api"
}

# ---------- config (override via flags) --------------------------------------
API_URL=""
MINIO_URL="http://127.0.0.1:9000"
MLFLOW_URL="http://127.0.0.1:5000"
POSTGRES_HOST="127.0.0.1"
POSTGRES_PORT="5432"
NETWORK=""                                # auto-derived from a pool's base job template; fallback mlops
DISP_IMAGE="prefect-dispatcher:latest"
POOLS=""                                  # expected pools to assert (empty = auto-discover whatever is registered)
MEMBERS=""

while [ $# -gt 0 ]; do
    case "$1" in
        --api-url)       API_URL="$2"; shift 2 ;;
        --minio-url)     MINIO_URL="$2"; shift 2 ;;
        --mlflow-url)    MLFLOW_URL="$2"; shift 2 ;;
        --postgres-host) POSTGRES_HOST="$2"; shift 2 ;;
        --postgres-port) POSTGRES_PORT="$2"; shift 2 ;;
        --network)       NETWORK="$2"; shift 2 ;;
        --disp-image)    DISP_IMAGE="$2"; shift 2 ;;
        --pools)         POOLS="${2//,/ }"; shift 2 ;;   # comma- or space-separated
        --members)       MEMBERS="${2//,/ }"; shift 2 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done
[ -z "$API_URL" ] && API_URL="$(default_api)"

# ---------- 0. prerequisites (abort if a required command is missing) --------
echo
printf '%sPrerequisites%s\n' "$C_CYAN" "$RESET"
missing=""
for c in docker prefect curl jq; do command -v "$c" >/dev/null 2>&1 || missing="$missing $c"; done
missing="${missing# }"
if [ -n "$missing" ]; then
    printf '%s  Missing required command(s): %s%s\n' "$C_RED" "${missing// /, }" "$RESET"
    case " $missing " in *" docker "*) hint "    docker  -> install Docker Engine, then start it." ;; esac
    if [ "${missing#*prefect}" != "$missing" ]; then
        hint "    prefect -> pip install prefect"
        hint "                 prefect config set PREFECT_API_URL=$API_URL"
    fi
    case " $missing " in *" curl "*) hint "    curl    -> install curl (apt-get install curl)." ;; esac
    case " $missing " in *" jq "*)   hint "    jq      -> install jq (apt-get install jq)." ;; esac
    printf '%s  Aborting: required commands are not on PATH.%s\n' "$C_RED" "$RESET"
    exit 1
fi
node OK "docker present   ($(docker --version))"
node OK "prefect present"

if docker info >/dev/null 2>&1; then
    node OK "docker daemon responding"
else
    node FAIL "docker daemon responding"
    printf '%s  Aborting: Docker daemon not reachable (start Docker Engine).%s\n' "$C_RED" "$RESET"
    exit 1
fi

# ---------- 1. gather live status --------------------------------------------
serverOk=false; test_prefect_health "$API_URL" && serverOk=true
poolsJson=""
$serverOk && poolsJson=$(prefect work-pool ls --output json 2>/dev/null)

# Derive the docker network from a pool's base job template (fallback: mlops).
if [ -z "$NETWORK" ]; then
    [ -n "$poolsJson" ] && NETWORK=$(printf '%s' "$poolsJson" | jq -r "$NET_JQ" 2>/dev/null)
    [ -z "$NETWORK" ] && NETWORK="mlops"
fi

netOk=false
docker network inspect "$NETWORK" >/dev/null 2>&1 && netOk=true
pgOk=false;     test_tcp "$POSTGRES_HOST" "$POSTGRES_PORT" && pgOk=true
minioOk=false;  test_url "$MINIO_URL/minio/health/live" && minioOk=true
mlflowOk=false
if test_url "$MLFLOW_URL/health"; then mlflowOk=true; elif test_url "$MLFLOW_URL"; then mlflowOk=true; fi
get_local_dispatchers "$DISP_IMAGE" "$NETWORK"

# ---------- 2. render the diagram --------------------------------------------
echo
printf '%sArchitecture status  (prefect.md  1. Architecture)%s\n' "$C_CYAN" "$RESET"
echo

if $netOk; then node OK "docker network: $NETWORK"; else node FAIL "docker network: $NETWORK"; fi
if $serverOk; then node OK "Prefect Server  $API_URL   (health=$serverOk)"
else node FAIL "Prefect Server  $API_URL   (health=$serverOk)"; fi

if ! $serverOk; then
    node WARN "  server API unreachable - pool / worker / deployment / credential checks skipped"
else
    info "POOLS (routing) + DISPATCHERS (workers):"
    registered=""
    [ -n "$poolsJson" ] && registered=$(printf '%s' "$poolsJson" | jq -c '.[] | select(.type == "docker")' 2>/dev/null)

    while IFS= read -r p; do
        [ -z "$p" ] && continue
        name=$(printf '%s' "$p" | jq -r '.name')
        st=$(printf '%s' "$p" | jq -r '(.status // "") | ascii_upcase')
        cc=$(printf '%s' "$p" | jq -r '(.concurrency_limit // "none") | tostring')
        expected=false; [ -z "$POOLS" ] && expected=true   # no list = auto-discover (all expected)
        for e in $POOLS; do [ "$e" = "$name" ] && expected=true; done

        workers=$(get_workers "$API_URL" "$name")
        printf '%s' "$workers" | jq -e 'type == "array"' >/dev/null 2>&1 || workers=""
        if [ -n "$workers" ]; then
            wAll=$(printf '%s' "$workers" | jq 'length')
            wOn=$(printf '%s' "$workers" | jq '[.[] | select((.status // "" | ascii_upcase) == "ONLINE")] | length')
            [ "$wOn" -gt 0 ] && ready=true || ready=false
            wOff=$((wAll - wOn))
            wLine="dispatchers (server records): $wOn online, $wOff offline(stale) / $wAll total"
        else
            [ "$st" = "READY" ] && ready=true || ready=false
            wLine="dispatchers: status=$st (live count via API unavailable)"
        fi

        if ! $expected; then
            node WARN "  pool $name  UNEXPECTED (typo?) - delete: prefect work-pool delete $name"
        elif $ready; then
            node OK "  pool $name"
        else
            node WARN "  pool $name  registered but $st (no live worker: run_dispatcher.sh)"
        fi

        info "    concurrency_limit=$cc   status=$st"
        info "    $wLine"
        if [ -n "$workers" ]; then
            while IFS= read -r w; do
                [ -z "$w" ] && continue
                wn=$(printf '%s' "$w" | jq -r '.name')
                hb=$(printf '%s' "$w" | jq -r '.last_heartbeat_time // ""')
                info "      online worker: $wn   last_heartbeat=$hb"
            done < <(printf '%s' "$workers" | jq -c '.[] | select((.status // "" | ascii_upcase) == "ONLINE")')
        fi
        if [ -n "${LOCALDISP[$name]:-}" ]; then
            info "    local dispatcher container(s) on this host:"
            while IFS= read -r d; do info "      - $d"; done <<< "${LOCALDISP[$name]}"
        else
            info "    local dispatcher container(s) on this host: none (dispatcher may be on another machine)"
        fi
        prop=$(printf '%s' "$p" | jq -c '.base_job_template.variables.properties // {}')
        img=$(printf '%s' "$prop" | jq -r '.image.default // "?"')
        mem=$(printf '%s' "$prop" | jq -r '.mem_limit.default // "?"')
        auto=$(printf '%s' "$prop" | jq -r '.auto_remove.default // "?"')
        netd=$(printf '%s' "$prop" | jq -r '(.networks.default // []) | join(",")' 2>/dev/null)
        [ -z "$netd" ] && netd="?"
        api=$(printf '%s' "$prop" | jq -r '.env.default.PREFECT_API_URL // ""')
        info "    options: image=$img  mem_limit=$mem  networks=$netd"
        info "             auto_remove=$auto  env.PREFECT_API_URL=$api"

        tier="${name%%_*}"
        dep="pipeline/pipelineflow-$tier"
        if prefect deployment inspect "$dep" >/dev/null 2>&1; then
            node OK "    deployment $dep"
        else
            node FAIL "    deployment $dep  (not registered - prefect deploy)"
        fi
    done <<< "$registered"

    for name in $POOLS; do
        if ! printf '%s' "$registered" | jq -e --arg n "$name" 'select(.name == $n)' >/dev/null 2>&1; then
            node FAIL "  pool $name  MISSING - register with register_pool.sh"
        fi
    done

    # Run-code credentials: one Credentials-type block per team member (block name = lowercase member),
    # server-wide and independent of any pool. Member names are dynamic, so discover them from block ls.
    echo
    info "CREDENTIALS (run-code credentials; one Credentials block per member, server-wide):"
    found=$(prefect block ls 2>/dev/null | grep -oE 'credentials/[a-z0-9-]+' | sed 's#credentials/##' | sort -u)
    if [ -n "$found" ]; then
        members_csv=$(printf '%s' "$found" | paste -sd ',' - | sed 's/,/, /g')
        node OK "  Credentials blocks present; members: $members_csv"
    elif prefect block type inspect credentials >/dev/null 2>&1; then
        node WARN "  Credentials type registered, but no member block yet (register with credentials.py)"
    else
        node FAIL "  no Credentials block (register a member with credentials.py)"
    fi
    for m in $MEMBERS; do
        if printf '%s\n' "$found" | grep -qx "$m"; then
            node OK "  member block credentials/$m"
        else
            node FAIL "  member block credentials/$m  MISSING - register with credentials.py"
        fi
    done
fi

# backing services (own compose stacks; checked by endpoint, not by container name)
echo
info "BACKING SERVICES:"
if $pgOk; then node OK "  postgres  :$POSTGRES_PORT   (metadata DB)"
else node FAIL "  postgres  :$POSTGRES_PORT   (metadata DB)"; fi
minioPort=$(url_port "$MINIO_URL")
mlflowPort=$(url_port "$MLFLOW_URL")
if $minioOk; then node OK "  minio     :$minioPort  (object storage)"
else node FAIL "  minio     :$minioPort  (object storage)"; fi
if $mlflowOk; then node OK "  mlflow    :$mlflowPort  (tracking)"
else node FAIL "  mlflow    :$mlflowPort  (tracking)"; fi

# ---------- 3. summary + exit code -------------------------------------------
echo
if [ "$nFail" -eq 0 ] && [ "$nWarn" -eq 0 ]; then
    printf '%sAll checks passed.%s\n' "$C_GREEN" "$RESET"; exit 0
elif [ "$nFail" -eq 0 ]; then
    printf '%sDone with %d warning(s), 0 failure(s).%s\n' "$C_YELLOW" "$nWarn" "$RESET"; exit 0
else
    printf '%sDone with %d failure(s), %d warning(s).%s\n' "$C_RED" "$nFail" "$nWarn" "$RESET"; exit 1
fi
