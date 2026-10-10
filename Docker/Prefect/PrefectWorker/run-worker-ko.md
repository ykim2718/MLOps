# run_worker.sh
Rev. 4 | Created: 2026-09-30 | Updated: 2026-10-09 23:36 CDT

> **Goal** — 한 machine 에서 Prefect worker container 를 띄워, 지정한 docker work pool 또는 그 pool 의 work queue 하나에 들어온 run 을 그 machine 이 실행하게 한다. 잘못된 pool·queue 이름으로 worker 가 run 을 하나도 받지 못하는 일은 기동 전에 막는다.
>
> **Non-Goals** — work pool 과 work queue 를 만들거나 concurrency limit 을 바꾸지 않는다. Prefect server 를 띄우지 않는다. worker image `prefect-worker:latest` 를 build 하거나 registry 에 push 하지 않는다.
>
> **Background** — worker compose 파일은 pool 이름과 한도, worker image 의 registry 를 `docker compose up` 때 셸 변수로 읽으므로, 그 값을 정해 export 하는 script 가 필요하다. Prefect API 는 worker 가 어느 machine 에서 도는지 기록하지 않아, worker 이름에 `<hostname>@<LAN IP>` 를 넣는다. 오타 난 pool·queue 이름으로 뜬 worker 는 run 을 하나도 받지 못한 채 돌기 때문에, 이름을 server 의 목록과 먼저 대조한다.

- [1. Pipeline](#1-pipeline)
- [2. Method](#2-method)
- [3. Input](#3-input)
- [Appendix A. Terminology](#appendix-a-terminology)
- [Appendix B. CLI (Command Line Options)](#appendix-b-cli-command-line-options)
- [Appendix C. Run Example](#appendix-c-run-example)
  - [C.1 Worker for a High-Tier Machine](#c1-worker-for-a-high-tier-machine)
  - [C.2 Worker for a Low-Tier Machine](#c2-worker-for-a-low-tier-machine)
  - [C.3 Worker with a Given LAN IP](#c3-worker-with-a-given-lan-ip)
  - [C.4 Worker for One Queue](#c4-worker-for-one-queue)
- [Appendix D. Script](#appendix-d-script)

## 1. Pipeline

`run_worker.sh` 는 아래 차례로 worker container 를 띄운다. 코드 전체는 [Appendix D](#appendix-d-script) 에 있다.

1. 옵션 읽기 — `--work-pool`, `--worker-limit`, `--worker-ip`, `--work-queue`.
2. Registry 읽기 — `../docker-compose.env` 에서 `IMAGE_REGISTRY` 한 줄만 읽고, 파일이 없으면 `../docker-compose.env_example` 을 읽는다. 값이 비었거나 `<` 가 든 자리표시자면 멈추고, 같은 파일의 `PREFECT_API_URL` 도 같은 기준으로 검사한다.
3. 도구 확인 — `jq` 와 host 의 `prefect` CLI 가 없으면 설치 방법을 출력하고 멈춘다.
4. Network 준비 — docker network `mlops` 가 없으면 만든다.
5. Pool 검증 — `prefect work-pool ls --output json` 으로 server 의 docker type pool 목록을 읽어 `--work-pool` 과 대조한다. 목록에 없으면 번호를 붙여 보여 주고 하나를 고르게 한다.
6. Queue 검증 — `--work-queue` 를 주었으면 `prefect work-queue inspect` 로 그 queue 가 pool 에 있는지 확인한다. 없으면 만드는 명령을 출력하고 멈춘다.
7. LAN IP 결정 — `--worker-ip` 가 없으면 Windows 는 default route interface (`powershell.exe`), macOS 는 default route interface 의 주소 (`route` 와 `ipconfig`), Linux 는 default route source 주소 (`ip route`) 에서 읽는다.
8. 이름 결정 — compose project, worker 이름, queue 옵션을 정한다 ([2. Method](#2-method)).
9. 기동 — 변수를 export 하고, `docker compose -p <project> pull` 로 이 machine 의 architecture 에 맞는 worker image 를 받은 뒤 `down` 하고 `up -d` 한다.

## 2. Method

`--work-queue` 유무에 따라 compose project 와 worker 이름이 갈린다.

Table 1. Names by queue option

| Queue option            | Compose project          | Worker name                     | Polls                   |
| :---------------------: | :----------------------: | :-----------------------------: | :---------------------: |
| none                    | `prefect-worker`         | `<hostname>@<LAN IP>`           | every queue of the pool |
| `--work-queue <queue>`  | `prefect-worker-<queue>` | `<hostname>-<queue>@<LAN IP>`   | `<queue>` only          |

- Compose project 가 다르므로 두 worker 는 한 machine 에서 나란히 돌고, `down` 은 자기 project 의 container 만 내린다.
- Worker 이름의 `@` 뒤는 LAN IP 여서, 이름만으로 worker 가 도는 machine 을 알 수 있다.
- `--work-queue` 는 compose 의 `WORK_QUEUE_OPTION` 변수로 `prefect worker start` 명령에 들어간다. 옵션이 없으면 이 변수는 빈 값이고 명령에서 빠진다.
- Pool 검증은 docker type pool 만 인정한다. 이 worker 는 run 마다 docker container 를 띄우므로, 같은 이름의 process pool 은 run 을 실행할 수 없다.

## 3. Input

- Host 의 `prefect` CLI — `PREFECT_API_URL` 이 Prefect server 를 가리켜야 pool·queue 검증이 된다.
- `jq` — `prefect work-pool ls --output json` 의 출력을 읽는다.
- `docker compose` — 같은 folder 의 `docker-compose.worker.yml` 을 띄운다.
- `../docker-compose.env` — script 가 읽는 `IMAGE_REGISTRY` (registry 의 `<host>:<port>`) 와, worker container 가 읽는 `PREFECT_API_URL` 을 담는다. 파일이 없으면 `../docker-compose.env_example` 을 읽지만, 그 자리표시자 값으로는 script 가 멈춘다.
- Registry 의 `prefect-worker:latest` — worker image 를 `IMAGE_REGISTRY` 에 미리 push 해 둔다. HTTP registry 면 이 machine 의 docker daemon 에 `insecure-registries` 도 있어야 pull 이 된다.
- Server 에 등록된 docker type work pool 과, `--work-queue` 를 쓸 때는 그 pool 의 work queue.

---

## Appendix A. Terminology

- **compose project**: `docker compose` 가 container·network 이름 앞에 붙이는 묶음 이름. `-p` 로 정하며, `down` 은 같은 project 의 container 만 내린다.
- **concurrency limit**: 동시에 실행할 수 있는 run 수의 상한. Work pool 과 work queue 에 각각 둘 수 있고, pool 의 상한은 그 pool 의 모든 queue 에 함께 걸린다.
- **LAN IP**: machine 이 내부망에서 쓰는 IPv4 주소.
- **registry**: image 를 보관하고 push 와 pull 을 받는 service. 여기서는 worker image 를 담는다.
- **work pool**: Prefect server 에 등록된, run 을 모아 두는 단위. Docker type pool 의 run 은 worker 가 docker container 로 실행한다.
- **work queue**: work pool 안의 대기열. Deployment 는 `work_queue_name` 으로 queue 를 정하고, 정하지 않으면 `default` queue 에 들어간다.
- **worker**: work pool 을 polling 하다가 run 을 가져가 실행하는 process. 여기서는 registry 에서 받은 `prefect-worker:latest` container 안에서 돈다.

## Appendix B. CLI (Command Line Options)

Table 2. Command line options

| Option           | Type   | Default            | Required | Description                                                     |
| :--------------: | :----: | :----------------: | :------: | :-------------------------------------------------------------: |
| `--work-pool`    | string | `high_performance` | no       | Docker work pool to poll                                        |
| `--worker-limit` | int    | `8`                | no       | Max run containers this worker starts at once                   |
| `--worker-ip`    | IPv4   | detected           | no       | LAN IP of this machine, when detection fails                    |
| `--work-queue`   | string | none (every queue) | no       | One work queue of the pool to poll, as its own compose project  |

## Appendix C. Run Example

모든 예시는 `PrefectWorker/` folder 에서 실행한다.

### C.1 Worker for a High-Tier Machine

`high_performance` pool 의 모든 queue 를 polling 하는 worker 를 한도 8 로 띄운다.

```bash
./run_worker.sh --work-pool high_performance --worker-limit 8
```

### C.2 Worker for a Low-Tier Machine

`low_performance` pool 의 모든 queue 를 polling 하는 worker 를 한도 4 로 띄운다.

```bash
./run_worker.sh --work-pool low_performance --worker-limit 4
```

### C.3 Worker with a Given LAN IP

LAN IP 를 자동으로 읽지 못하는 machine 에서 worker 이름에 넣을 IP 를 직접 준다.

```bash
./run_worker.sh --work-pool low_performance --worker-ip <LAN_IP>
```

### C.4 Worker for One Queue

`low_performance` pool 의 `urgent` queue 만 polling 하는 worker 를, pool 전체를 맡는 worker 옆에 한도 2 로 띄운다. `urgent` queue 를 만들고 pool 한도를 `default` queue 로 옮기는 절차는 [prefect-work-queue-ko.md](../prefect-work-queue-ko.md) 를 따르며, queue 가 server 에 먼저 있어야 한다.

```bash
./run_worker.sh --work-pool low_performance --work-queue urgent --worker-limit 2
```

## Appendix D. Script

`run_worker.sh` 의 전체 code 이다 ([1. Pipeline](#1-pipeline)).

```bash
#!/usr/bin/env bash
# run_worker.sh — start the Prefect worker compose stack on a worker machine.
# __version__ = "0.0.27"  # Semantic Versioning:  Version = Major.Minor.Patch
#
# Brings up prefect_worker, which polls the given work pool. WORK_POOL/WORKER_LIMIT are read from
# this shell at "docker compose up" (compose interpolation), so they are exported below.
# (PREFECT_API_URL etc. are read by the container from the env file this script picks, exported as WORKER_ENV_FILE.)
# Runs on Windows (Git Bash / WSL), Linux and macOS; each finds the LAN IP its own way (see below).
# Work pools live on the server and are registered there (register_pool.sh), not here. Before starting,
# this script checks the work pool against the pools registered on the server; if it is missing, it lists
# the registered pools and lets you pick one (guards against typos / not-yet-registered pools).
#
#   ./run_worker.sh --work-pool high_performance    # a high-tier machine
#   ./run_worker.sh --work-pool low_performance     # a low-tier machine
#   ./run_worker.sh --work-pool low_performance --worker-ip <LAN_IP>   # when the LAN IP is not detected
#   ./run_worker.sh --work-pool low_performance --work-queue urgent --worker-limit 2   # a second worker, one queue only
#
# The worker is named '<hostname>@<LAN IP>' so the Prefect server (and dashboards reading it) can tell
# which machine each worker runs on; the Prefect API records no host for a worker otherwise.
# With --work-queue the worker polls that queue of the pool only, is named '<hostname>-<queue>@<LAN IP>', and runs
# as its own compose project (prefect-worker-<queue>), so it starts and stops beside the pool-wide worker.
#
# The worker image is pulled from IMAGE_REGISTRY (read from ../docker-compose.env, else the _example), so a new
# machine needs no local build; re-running this script pulls the latest pushed image.
#
set -euo pipefail

WORK_POOL="high_performance"   # the work pool this machine polls: high_performance | low_performance
WORKER_LIMIT=8                 # max pipeline_flow containers this machine spawns concurrently
WORKER_IP=""                   # LAN IP of this machine; empty = detected below
WORK_QUEUE=""                  # one work queue of the pool to poll; empty = every queue of the pool

while [ $# -gt 0 ]; do
    case "$1" in
        --work-pool)    WORK_POOL="$2"; shift 2 ;;
        --worker-limit) WORKER_LIMIT="$2"; shift 2 ;;
        --worker-ip)    WORKER_IP="$2"; shift 2 ;;
        --work-queue)   WORK_QUEUE="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

COMPOSE="docker-compose.worker.yml"
ENV_FILE="../docker-compose.env"   # shared address source; falls back to the committed _example

# --- Registry of the worker image: read only IMAGE_REGISTRY (sourcing the whole file would override the
# host's PREFECT_API_URL with a possible placeholder) ------------------------------------------------
[ -f "$ENV_FILE" ] || ENV_FILE="../docker-compose.env_example"
[ -f "$ENV_FILE" ] || { echo "env file not found: $ENV_FILE" >&2; exit 1; }
IMAGE_REGISTRY="$(sed -n 's/^IMAGE_REGISTRY=//p' "$ENV_FILE" | tail -n 1 | tr -d '\r')"
if [ -z "$IMAGE_REGISTRY" ] || [[ "$IMAGE_REGISTRY" == *"<"* ]]; then
    echo "IMAGE_REGISTRY missing or still a placeholder in $ENV_FILE (got '$IMAGE_REGISTRY')." >&2
    echo "Set it to the registry <host>:<port>; an HTTP registry also needs 'insecure-registries' in the docker daemon." >&2
    exit 1
fi

# The worker container reads PREFECT_API_URL from this same env file; a placeholder would start a worker that
# never reaches the server, so it is rejected here rather than inside the container.
CONTAINER_API_URL="$(sed -n 's/^PREFECT_API_URL=//p' "$ENV_FILE" | tail -n 1 | tr -d '\r')"
if [ -z "$CONTAINER_API_URL" ] || [[ "$CONTAINER_API_URL" == *"<"* ]]; then
    echo "PREFECT_API_URL missing or still a placeholder in $ENV_FILE (got '$CONTAINER_API_URL')." >&2
    echo "Copy ../docker-compose.env_example to ../docker-compose.env and set the server address there." >&2
    exit 1
fi
WORKER_ENV_FILE="$ENV_FILE"   # compose env_file; relative to this folder, which is also the compose file's folder

command -v jq >/dev/null 2>&1 || { echo "jq is required to parse 'prefect work-pool ls --output json'. Install jq and retry." >&2; exit 1; }

# The pool validation below uses the host 'prefect' CLI, so it must be installed and on PATH.
if ! command -v prefect >/dev/null 2>&1; then
    echo "prefect CLI not found on this host (needed to validate the work pool against the server)." >&2
    echo "Install it, then retry:" >&2
    echo "  pipx install prefect && pipx ensurepath     # then open a new shell, or: export PATH=\"\$HOME/.local/bin:\$PATH\"" >&2
    echo "  export PREFECT_API_URL=http://127.0.0.1:4200/api   # point at the running server (run_server.sh)" >&2
    exit 1
fi

# On the same host, worker/pipeline_flow containers reach the server by service name over the shared mlops network.
# (For a worker on another machine, remove the networks block in the worker compose and set PREFECT_API_URL to http://<host IP>:4200/api.)
docker network inspect mlops >/dev/null 2>&1 || docker network create mlops >/dev/null

# --- Validate the work pool against the pools registered on the server --------------------------
# Read the registered pools with the host prefect CLI (configured via its PREFECT_API_URL profile).
# stderr (progress / version warnings) is dropped so only the JSON on stdout is parsed.
pools_json="$(prefect work-pool ls --output json 2>/dev/null || true)"
if [ -z "$pools_json" ]; then
    echo "Could not read work pools via the host 'prefect' CLI. Ensure prefect is installed and PREFECT_API_URL points at a running server (run_server.sh), then retry." >&2
    exit 1
fi

# This worker spawns docker containers, so only docker-type pools are valid
# (a name that exists only as a process pool — e.g. one auto-created by a typo — is rejected here).
pools=()
while IFS= read -r line; do
    [ -n "$line" ] && pools+=("$line")
done < <(printf '%s' "$pools_json" | jq -r '.[] | select(.type == "docker") | .name')

if [ "${#pools[@]}" -eq 0 ]; then
    echo "No docker-type work pools are registered on the server. Run register_pool.sh (it registers --type docker) first." >&2
    exit 1
fi

match=""
for p in "${pools[@]}"; do
    if [ "$p" = "$WORK_POOL" ]; then match="$p"; break; fi
done

if [ -n "$match" ]; then
    WORK_POOL="$match"                                   # normalize to the exact registered name
else
    echo "Warning: '$WORK_POOL' is not a registered docker work pool." >&2
    echo "Registered docker work pools:"
    i=1
    for p in "${pools[@]}"; do
        printf '%3d) %s\n' "$i" "$p"
        i=$((i + 1))
    done
    read -r -p "Pick a pool number (Enter to abort): " sel
    if ! printf '%s' "$sel" | grep -qE '^[0-9]+$' || [ "$sel" -lt 1 ] || [ "$sel" -gt "${#pools[@]}" ]; then
        echo "Aborted: no valid work pool selected." >&2
        exit 1
    fi
    WORK_POOL="${pools[$((sel - 1))]}"
    echo "Using work pool '$WORK_POOL'."
fi

# --- Validate the work queue: prefect worker start would silently create a mistyped queue ------------
if [ -n "$WORK_QUEUE" ] && ! prefect work-queue inspect "$WORK_QUEUE" --pool "$WORK_POOL" >/dev/null 2>&1; then
    echo "Work queue '$WORK_QUEUE' is not in work pool '$WORK_POOL'. Create it first, e.g.:" >&2
    echo "  prefect work-queue create $WORK_QUEUE --pool $WORK_POOL --priority 1" >&2
    exit 1
fi

# --- Name the worker after this machine: <hostname>@<LAN IP> ---------------------------------------
# On Windows (Git Bash, or WSL whose own IP is internal) the LAN IP comes from the Windows default-route
# interface; on macOS (no powershell.exe, no ip) from the address of the default-route interface;
# on Linux from the source address of the default route.
if [ -z "$WORKER_IP" ] && command -v powershell.exe >/dev/null 2>&1; then
    WORKER_IP="$(powershell.exe -NoProfile -Command \
        "(Get-NetIPConfiguration | Where-Object IPv4DefaultGateway | Select-Object -First 1).IPv4Address.IPAddress" \
        2>/dev/null | tr -d '\r' || true)"
fi
if [ -z "$WORKER_IP" ] && [ "$(uname -s)" = "Darwin" ]; then
    default_iface="$(route -n get default 2>/dev/null | awk '/interface:/ {print $2; exit}' || true)"
    if [ -n "$default_iface" ]; then
        WORKER_IP="$(ipconfig getifaddr "$default_iface" 2>/dev/null || true)"
    fi
fi
if [ -z "$WORKER_IP" ] && command -v ip >/dev/null 2>&1; then
    WORKER_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") {print $(i + 1); exit}}')"
fi
if ! printf '%s' "$WORKER_IP" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo "Could not detect this machine's LAN IP (got '$WORKER_IP'); pass it with --worker-ip <ip>." >&2
    exit 1
fi
PROJECT="prefect-worker"       # the compose file's top-level name
WORK_QUEUE_OPTION=""
WORKER_NAME="$(hostname)@${WORKER_IP}"
if [ -n "$WORK_QUEUE" ]; then
    PROJECT="prefect-worker-${WORK_QUEUE}"
    WORK_QUEUE_OPTION="--work-queue ${WORK_QUEUE}"
    WORKER_NAME="$(hostname)-${WORK_QUEUE}@${WORKER_IP}"
fi
echo "Worker name: $WORKER_NAME"

# For the worker compose ${...} interpolation — export so this docker compose up sees them.
export WORK_POOL
export WORKER_LIMIT
export WORKER_NAME
export WORK_QUEUE_OPTION
export IMAGE_REGISTRY
export WORKER_ENV_FILE

# Pull the latest worker image (the arch of this machine) before restarting, so a re-run picks up a new push.
docker compose -p "$PROJECT" -f "$COMPOSE" pull

# Bring the worker stack down (keeping volumes) and back up in the background.
# -p names the project, so down only ever touches this stack (the pool-wide worker or one queue's worker).
docker compose -p "$PROJECT" -f "$COMPOSE" down
docker compose -p "$PROJECT" -f "$COMPOSE" up -d
```
