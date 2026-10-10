# Prefect Server
Rev. 0 | Created: 2026-10-10 | Updated: 2026-10-10 09:28 CDT

- [1. Purpose](#1-purpose)
- [2. Server Setup](#2-server-setup)
- [3. Work Pool Registration](#3-work-pool-registration)
- [4. Service Address Variables](#4-service-address-variables)
- [Appendix A. Terminology](#appendix-a-terminology)
- [Appendix B. run_server.sh](#appendix-b-run_serversh)
- [Appendix C. register_pool.sh](#appendix-c-register_poolsh)
- [Appendix D. register_variables.sh](#appendix-d-register_variablessh)

## 1. Purpose

- **Problem Statement**: Prefect server 가 work pool 과 서비스 주소 Variable 을 갖고 있어야 worker 와 flow 가 run 을 받을 수 있는데, 그 설정이 compose · pool template · script 여러 파일에 나뉘어 있습니다.
- **Goal**: 실무자가 `PrefectServer/` 의 파일로 server 를 띄우고, 두 work pool 과 서비스 주소 Variable 을 등록하고, 등록 결과를 확인할 수 있게 합니다.
- **Non-Goal**: Worker 기동과 flow image, deployment 등록은 다루지 않습니다.

## 2. Server Setup

  server 는 backend 인 `postgres` 가 먼저 떠 있어야 하므로 **PostgreSQL → (MinIO/MLflow) → Prefect server** 순으로 띄웁니다.

  #### Yaml

  ```yaml
  # docker-compose.server.yml
  # __version__ = "0.0.14"
  name: prefect-server   # compose project name baked in (replaces -p); run_server.sh relies on it
  services:
    prefect_server:
      image: prefecthq/prefect:3-latest
      command: prefect server start --host 0.0.0.0
      env_file:
        # PREFECT_SERVER_DATABASE_CONNECTION_URL + PREFECT_API_URL (host LAN IP); the UI inherits PREFECT_API_URL, so no PREFECT_UI_API_URL is needed.
        - ../docker-compose.env_example       # shared, kept at Docker/Prefect root
      ports:
        - "4200:4200"                 # dashboard/API. Clients connect on this port.
      networks:
        - mlops
      restart: unless-stopped

    worker_pruner:
      build:
        context: .
        dockerfile: Dockerfile.pruner     # bakes prune_loop.sh + curl + jq into the image (no bind mount)
      image: prefect-pruner:latest
      depends_on:
        - prefect_server
      environment:
        - PREFECT_API_URL=http://prefect_server:4200/api   # internal server API the sidecar prunes via
        - PRUNE_INTERVAL_SECONDS=3600                       # prune cadence (hourly)
      networks:
        - mlops
      restart: unless-stopped

  networks:
    mlops:
      external: true
  ```

  - `command: prefect server start --host 0.0.0.0` 은 컨테이너 밖에서도 접속하도록 모든 인터페이스에 바인딩합니다.
  - `networks: mlops` 로 `postgres` 와 서비스명으로 통신합니다. `postgres` 는 별도 compose 라 `depends_on` 대신 `restart: unless-stopped` 로 준비될 때까지 재시도합니다.
  - **UI API 주소** — UI 가 **브라우저에게** 넘길 API 주소는 `PREFECT_UI_API_URL` 인데, 따로 지정하지 않으면 `PREFECT_API_URL` 을 그대로 상속합니다. 그래서 env_file 의 `PREFECT_API_URL` 을 브라우저가 닿는 **호스트 LAN IP** (`http://<server IP>:4200/api`) 로 두면 remote 머신에서도 대시보드가 그대로 열리므로, `PREFECT_UI_API_URL` 을 따로 두지 않습니다. (도커 내부 이름 `prefect_server` 나 `localhost` 로 두면 각각 브라우저가 못 풀거나 자기 자신을 가리켜 remote 에서 빈 화면이 됩니다.)
  - `worker_pruner` 는 server 와 함께 뜨는 작은 사이드카 (alpine + curl + jq) 로, `PRUNE_INTERVAL_SECONDS` (기본 1시간) 마다 server 의 **OFFLINE (stale) worker 레코드** 를 API 로 지웁니다 (`prune_loop.sh`). Prefect 는 죽은 worker 를 OFFLINE 로 표시만 하고 지우지 않으므로, ONLINE worker 는 두고 나머지만 삭제해 목록을 깨끗이 유지합니다. `Dockerfile.pruner` 가 script 와 curl + jq 를 image 에 구워 두므로 (build 시 CR 제거 포함), container 는 (재)기동 때 host 파일 없이 뜹니다.
  - **Rebooting과 source** — server stack 은 필요한 파일을 모두 image 안에 담고 있으므로 (`prefect_server` 는 공식 image, `worker_pruner` 는 `Dockerfile.pruner` 로 bake), container/machine rebooting 시 host 의 source 파일이나 mount 가 필요 없습니다. source 는 image 를 build 할 때만 필요합니다.

  #### Dockerfile.pruner

  `worker_pruner` 사이드카의 image 정의입니다. alpine 에 curl + jq 를 설치하고 `prune_loop.sh` 를 COPY 하며, Windows 줄끝 (CR) 제거까지 build 시점에 끝냅니다. compose 의 `build:` 가 이 파일을 사용하므로 별도 build 명령은 필요 없습니다.

  ```dockerfile
  # __version__ = "0.0.1"  # Semantic Versioning:  Version = Major.Minor.Patch
  # Pruner image — alpine + curl + jq with prune_loop.sh baked in at build time.
  # No bind mount at runtime, so the container (re)starts without any host files present.
  FROM alpine:3
  RUN apk add --no-cache curl jq
  COPY prune_loop.sh /prune_loop.sh
  # Strip CR (Windows EOL) once at build time instead of on every container start.
  RUN sed -i 's/\r$//' /prune_loop.sh
  CMD ["sh", "/prune_loop.sh"]
  ```

  #### Execution Command

  `PrefectServer/` 에서 실행합니다.

  ```bash
  ./run_server.sh --yaml docker-compose.server.yml --network mlops
  ```

  - `run_server.sh` (코드는 [Appendix B](#appendix-b-run_serversh)) — 네트워크 생성과 `docker compose up` 을 한 번에 처리합니다.
  - `--yaml` — 띄울 compose 파일. 프로젝트명은 이 파일의 top-level `name:` (`prefect-server`) 이 정합니다.
  - `--network` — 붙을 공유 네트워크.

  실행 후 대시보드는 **`http://<Host IP>:4200`** 에서 열립니다 (같은 컴퓨터는 `localhost`).

## 3. Work Pool Registration

  work pool 은 **server 에 저장되는 메타데이터 (컨테이너 아님)** 라, server 가 뜨면 한 번 등록합니다. 등록된 pool 은 server DB 에 남아 이후 worker 들이 polling 으로 접근하므로 ([prefect-worker-ko.md §2](../PrefectWorker/prefect-worker-ko.md#2-role)), worker 쪽엔 pool 생성 단계가 없습니다.

  **등록에는 worker 정보가 필요 없습니다** — 등록값은 pool 이름·`--type`·base job template 뿐이고, pool 은 worker 와 독립이라 worker 가 0개여도 등록됩니다 (그동안 trigger 된 run 은 `Late` 로 대기). worker 는 나중에 `prefect worker start` 로 그 pool 에 붙습니다 ([prefect-worker-ko.md §4 Container](../PrefectWorker/prefect-worker-ko.md#4-container)).

  **Base job template** — pool 이 띄우는 모든 `pipeline_flow` 컨테이너의 공통 설정입니다. flow 컨테이너는 worker 의 마운트·네트워크를 상속하지 않으므로 **`PREFECT_API_URL` 과 네트워크를 여기서 명시** 합니다. 등급별로 `docker-pool-template-high.json`·`docker-pool-template-low.json` 두 벌을 두며 (`job_configuration` 은 같고 `variables` 의 `mem_limit` default 만 등급별로 다릅니다 — 아래는 high 예시, low 는 표 참고), `register_pool.sh` 가 이 파일을 읽어 server API 로 등록합니다 ([Appendix C](#appendix-c-register_poolsh)).

  다음은 `docker-pool-template-high.json` 입니다.

  ```json
  // PrefectServer/docker-pool-template-high.json
  {
    "variables": {
      "type": "object",
      "properties": {
        "name": { "title": "Name", "type": "string" },
        "image": {
          "title": "Image",
          "type": "string",
          "default": "pipeline-flow:latest"
        },
        "image_pull_policy": {
          "title": "Image Pull Policy",
          "type": "string",
          "enum": ["IfNotPresent", "Always", "Never"],
          "default": "Always"
        },
        "env": {
          "title": "Environment Variables",
          "type": "object",
          "additionalProperties": { "type": "string" },
          "default": {
            "PREFECT_API_URL": "http://prefect_server:4200/api"
          }
        },
        "networks": {
          "title": "Networks",
          "type": "array",
          "items": { "type": "string" },
          "default": ["mlops"]
        },
        "network_mode": { "title": "Network Mode", "type": "string" },
        "auto_remove": { "title": "Auto Remove", "type": "boolean", "default": true },
        "mem_limit": { "title": "Memory Limit", "type": "string", "default": "16g" },
        "stream_output": { "title": "Stream Output", "type": "boolean", "default": true },
        "volumes": {
          "title": "Volumes",
          "type": "array",
          "items": { "type": "string" },
          "default": []
        },
        "container_create_kwargs": {
          "title": "Container Create Kwargs",
          "type": "object",
          "default": {}
        }
      }
    },
    "job_configuration": {
      "name": "{{ name }}",
      "image": "{{ image }}",
      "image_pull_policy": "{{ image_pull_policy }}",
      "env": "{{ env }}",
      "networks": "{{ networks }}",
      "network_mode": "{{ network_mode }}",
      "auto_remove": "{{ auto_remove }}",
      "mem_limit": "{{ mem_limit }}",
      "stream_output": "{{ stream_output }}",
      "volumes": "{{ volumes }}",
      "container_create_kwargs": "{{ container_create_kwargs }}"
    }
  }
  ```

  > **`properties` vs `job_configuration`** — `variables.properties` 는 **변수 선언** (타입 + `default`) 이고, `job_configuration` 은 그 변수를 `{{ }}` 로 받아 **실제 도커 job 설정에 끼워 넣는 틀** 입니다. 같은 키가 양쪽에 보이는 건 '선언 ↔ 사용' 한 쌍이기 때문이고, 값 우선순위는 **deployment 의 `job_variables` override > 템플릿 `default`** 입니다 (override 가 없으면 `default` 가 `{{ }}` 자리에 들어갑니다).

  - `image` — flow 컨테이너로 쓸 flow image ([prefect-flow-ko.md §3](../PrefectFlow/prefect-flow-ko.md#3-image)). 태그 (`pipeline-flow:latest`) 가 곧 **런타임 버전** (라이브러리 + orchestrator) 입니다.
  - `image_pull_policy` — flow image 를 언제 pull 할지입니다. Worker 는 flow image 를 registry 에서 받고, 같은 `latest` tag 를 다시 push 해 갱신하므로 `Always` 로 둡니다. `IfNotPresent` 면 worker machine 이 처음 받은 image 를 계속 써서 새로 push 한 image 가 반영되지 않습니다. 네 값 (`IfNotPresent` · `Always` · `IfPossible` · `Never`) 의 뜻은 [prefect-registry-ko.md](../prefect-registry-ko.md) 를 따릅니다.
  - `env` — flow 컨테이너가 server·Secret 을 찾는 `PREFECT_API_URL` 을 줍니다. 이 값은 템플릿에 **하드코딩하지 않습니다** — `register_pool.sh` 가 등록 시 실행 호스트의 `docker-compose.env` 에 있는 `PREFECT_API_URL` 로 `env.default` 를 덮어씁니다. 위 JSON 의 `http://prefect_server:4200/api` 는 register_pool.sh 없이 등록할 때만 쓰이는 fallback 이고, 실제 주소는 `docker-compose.env` 한 곳에서 관리합니다.
  - `mem_limit` — flow 컨테이너 메모리 상한입니다. 등급별 pool 의 핵심 차이값입니다 (high 크게·low 작게). `16g` 의 `g` 는 기가바이트 (GiB) 를 뜻합니다.
  - `volumes` — flow 컨테이너에 mount 할 `<host path>:<container path>` 목록입니다. 기본값은 비어 있고, 필요한 deployment 가 `job_variables` 로 채웁니다.
  - `container_create_kwargs` — docker 가 flow 컨테이너를 만들 때 넘기는 추가 인자 (예: `extra_hosts`) 입니다. 기본값은 비어 있고, 필요한 deployment 가 `job_variables` 로 채웁니다.

  `networks` 는 flow 컨테이너가 붙을 네트워크로, `mlops` 면 `minio`·`prefect_server` 를 서비스명으로 찾습니다. `auto_remove: true` 면 run 이 끝날 때 컨테이너가 자동으로 삭제됩니다.

  > **`PREFECT_API_URL` 은 `docker-compose.env` 한 곳에서** — flow 컨테이너의 이 값은 register_pool.sh 가 실행 호스트의 `docker-compose.env` 에서 읽어 template 에 주입하므로, 주소를 template JSON 이나 여러 곳에 직접 넣지 않습니다. flow 컨테이너가 **server 와 같은 호스트**면 서비스명 `http://prefect_server:4200/api`, worker 가 **다른 호스트**면 서버 LAN IP (`http://<server IP>:4200/api`) 를 `docker-compose.env` 에 두고 register_pool.sh 를 (재)실행하면 됩니다. 서비스명은 server 와 같은 호스트에서만 풀리므로, 여러 호스트에 worker 가 걸치면 LAN IP 로 둡니다.

  > base job template 필드는 Prefect 버전마다 다를 수 있으니, `prefect work-pool get-default-base-job-template --type docker` 로 최신 템플릿을 받아 `image`·`env`·`networks` 의 `default` 만 채우길 권장합니다.

  > **여러 pool** — pool 마다 이 템플릿을 하나씩 등록합니다 (`docker-pool-template-high.json`·`docker-pool-template-low.json`). 등급 차이는 worker 의 `--limit` (머신당 동시 컨테이너 수) 과 템플릿의 `mem_limit` 로 주고, 이미지·repo 는 같습니다.
  >
  > | Field | Target | High | Low | Source |
  > |---|---|---|---|---|
  > | `mem_limit` | memory | `16g` | `4g` | base job template (`docker-pool-template-high.json`·`docker-pool-template-low.json`) |
  > | `--limit` | worker | `8` | `4` | `prefect worker start` (`WORKER_LIMIT`) |
  > | `--concurrency-limit` | pool | `16` | `8` | `work-pool set-concurrency-limit` (`register_pool.sh`) |

  #### Registration

  server API 를 호출해 pool 마다 등록합니다 (`PrefectServer/` 에서 실행; host 에 prefect CLI + jq 필요, server API 가 닿는 호스트면 어디서든 가능; `<Pool Name>`·`<Template File>` 변수화; 코드는 [Appendix C](#appendix-c-register_poolsh)).

  ```bash
  # Register each tier (run once, after the server is up; from PrefectServer/).
  ./register_pool.sh --pool-name high_performance --template-file docker-pool-template-high.json --concurrency-limit 16
  ./register_pool.sh --pool-name low_performance --template-file docker-pool-template-low.json  --concurrency-limit 8
  ```

  #### Verification

  등록 직후 pool 이 server 에 올라갔는지 (`docker` 타입·동시성 한도) 확인합니다.

  ```bash
  prefect work-pool ls
  ```

  `work-pool ls` 결과물 예시 — `low_performance` 가 `docker` 타입·동시성 한도 4 로 등록된 모습:

  ```text
                                        Work Pools
  ┌─────────────────┬────────┬──────────────────────────────────────┬───────────────────┐
  │ Name            │ Type   │                                   ID │ Concurrency Limit │
  ├─────────────────┼────────┼──────────────────────────────────────┼───────────────────┤
  │ low_performance │ docker │ 95e189a9-0d8d-4f74-b17c-375a01f6e70f │ 4                 │
  └─────────────────┴────────┴──────────────────────────────────────┴───────────────────┘
                                (**) denotes a paused pool
  ```

## 4. Service Address Variables

  backing service 주소 (MinIO·PostgreSQL·MLflow endpoint, 비밀 아님) 는 서버의 **Prefect Variable** 한 곳에 둡니다. flow 코드와 host 툴 (`catalog.py`) 이 모두 **서버에서** 읽으므로 (`Variable.get(...)`), docker-compose.env 를 컨테이너 밖에서 볼 필요가 없습니다. server 기동 후 `register_variables.sh` 로 한 번 등록합니다 (server 호스트에서 `docker compose exec prefect_server` — Work Pool Registration 과 같은 서버 부트스트랩 단계).

  ```bash
  ./register_variables.sh --minio http://<MINIO_IP>:9000 --postgresql <POSTGRESQL_IP>:5432 \
                          --mlflow http://<MLFLOW_IP>:5000
  ```

  각 Variable 이 **어떤 값으로** 등록됐는지 stdout 에 그대로 찍힙니다 (세 옵션은 모두 필수입니다):

  ```text
  Set variable 'minio_endpoint' to "http://<MINIO_IP>:9000"
  Set variable 'postgresql_host_port' to "<POSTGRESQL_IP>:5432"
  Set variable 'mlflow_tracking_uri' to "http://<MLFLOW_IP>:5000"
  [register_variables] set: minio_endpoint, postgresql_host_port, mlflow_tracking_uri
  ```

  | Variable | Value (LAN IP) | Used by |
  |----------|----------------|---------|
  | `minio_endpoint` | `http://<MinIO IP>:9000` | pipeline.py·catalog.py (S3) |
  | `postgresql_host_port` | `<PostgreSQL IP>:5432` | catalog·optuna DSN (host:port, 소비 코드가 분리) |
  | `mlflow_tracking_uri` | `http://<MLflow IP>:5000` | payload MLflow 로깅 |

  - 주소가 바뀌면 `register_variables.sh` 를 **다시 한 번** 돌리면 server·flow·host 툴 전부 반영됩니다.
  - `Variable.get` 은 서버가 있어야 하므로, flow 는 base job template 의 `PREFECT_API_URL` 로, host 툴은 프로필로 서버에 붙습니다 (한 곳으로 몰린 주소를 모두가 서버에서 가져감).

---

## Appendix A. Terminology

- **`PREFECT_API_URL`**: worker · client 가 server API 를 찾는 주소 (`http://<host>:4200/api`) 입니다. 같은 host 면 host 가 서비스명 `prefect_server` 입니다.
- **`prefect_server`**: API · UI · scheduler · work pool 대기열을 제공하는 중앙 진입점입니다. 메타데이터 (`prefect` DB) 만 관리하고 코드는 실행하지 않습니다.
- **base job template**: pool 이 띄우는 flow 컨테이너의 공통 설정 (image · env · network · 메모리 상한 등) 입니다.
- **compose project**: `docker compose` 가 container · network 이름 앞에 붙이는 묶음 이름입니다. `-p` 로 정하며, `down` 은 같은 project 의 container 만 내립니다.
- **concurrency limit**: 동시에 실행할 수 있는 run 수의 상한입니다. Work pool 과 work queue 에 각각 둘 수 있고, pool 의 상한은 그 pool 의 모든 queue 에 함께 걸립니다.
- **deployment**: flow 를 어떤 work pool 과 parameter 로 실행할지 묶어 server DB (`prefect`) 에 저장한 레코드입니다.
- **flow image**: Pipeline Flow 컨테이너를 띄우는 image 입니다. deployment 의 `image` (없으면 base job template 의 `image` 기본값) 가 가리키며, 이 stack 에서는 `pipeline-flow:latest` 입니다.
- **Host**: 모든 컨테이너 (server · worker · pipeline_flow · postgres · minio · mlflow) 가 올라가는 한 대의 컴퓨터입니다.
- **LAN IP**: machine 이 내부망에서 쓰는 IPv4 주소입니다.
- **registry**: image 를 보관하고 push 와 pull 을 받는 service 입니다.
- **work pool**: job 이 대기하는 큐이자 실행 방식 (type) 의 정의입니다. server 안의 메타데이터이며 컨테이너가 아닙니다.

## Appendix B. run_server.sh

제어 노드에서 Prefect server compose 스택을 띄우는 기동 스크립트입니다 ([§2 Server Setup](#2-server-setup)). 공유 `mlops` 네트워크가 없으면 만들고 `docker-compose.server.yml` 을 올립니다. work pool 등록은 별도입니다 (`register_pool.sh` — [Appendix C](#appendix-c-register_poolsh)).

```bash
#!/usr/bin/env bash
# run_server.sh — bring up the Prefect server compose stack on the Control Node.
# __version__ = "0.0.21"  # Semantic Versioning:  Version = Major.Minor.Patch
set -euo pipefail

YAML="docker-compose.server.yml"   # the server compose file (its top-level name: sets the project)
NETWORK="mlops"                    # shared external network

while [ $# -gt 0 ]; do
    case "$1" in
        --yaml)    YAML="$2"; shift 2 ;;
        --network) NETWORK="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# Create the shared network only if it does not exist yet.
docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK" >/dev/null

# --build keeps the worker_pruner sidecar image (Dockerfile.pruner) in sync with prune_loop.sh.
docker compose -f "$YAML" up -d --build   # project name comes from the compose file's top-level name: (prefect-server)
```

## Appendix C. register_pool.sh

server 에 work pool 을 등록 (또는 갱신) 하는 스크립트입니다 ([§3 Work Pool Registration](#3-work-pool-registration)).

`--overwrite` 가 **템플릿 동기** 를 맡습니다 — pool 이 이미 있으면 오류 없이 그 pool 의 **base job template 을 현재 파일** (`docker-pool-template-high.json`·`docker-pool-template-low.json`) **내용으로 갱신** 합니다 (idempotent). 그래서 템플릿을 고친 뒤 다시 실행하면 server 쪽 설정이 로컬 파일과 같아집니다 (`--overwrite` 가 없으면 이미 있는 pool 에 대해 등록이 실패).

등록은 **server API 호출** 로 합니다 — host 의 prefect CLI 가 `docker-compose.env` 의 `PREFECT_API_URL` 로 server 에 접속하므로, server 컨테이너가 없는 호스트에서도 API 만 닿으면 실행됩니다 (host 에 prefect CLI + jq 필요).

```bash
#!/usr/bin/env bash
# register_pool.sh — register (or update) one Prefect work pool via the server API.
# __version__ = "0.1.0"  # Semantic Versioning:  Version = Major.Minor.Patch
# Idempotent: --overwrite keeps the base job template in sync. Runs on any host that can reach the
# server API (needs the prefect CLI + jq locally; no server container required). PREFECT_API_URL is
# taken from docker-compose.env — it is both the API address this script calls and the address
# injected into the template's env.default, so flow containers know where the server is.
# Backing addresses (MinIO / PostgreSQL / MLflow) live as prefect Variables (register_variables.sh), not here.
#
#   ./register_pool.sh --pool-name high_performance --template-file docker-pool-template-high.json --concurrency-limit 16
#   ./register_pool.sh --pool-name low_performance  --template-file docker-pool-template-low.json  --concurrency-limit 8
#
set -euo pipefail

POOL_NAME=""                           # work pool name, e.g. high_performance | low_performance
TEMPLATE_FILE=""                       # base job template on the host, e.g. docker-pool-template-high.json
CONCURRENCY_LIMIT=0                    # pool-wide max concurrent runs (0 = no limit)
ENV_FILE="../docker-compose.env"      # shared address source; falls back to the committed _example

while [ $# -gt 0 ]; do
    case "$1" in
        --pool-name)         POOL_NAME="$2"; shift 2 ;;
        --template-file)     TEMPLATE_FILE="$2"; shift 2 ;;
        --concurrency-limit) CONCURRENCY_LIMIT="$2"; shift 2 ;;
        --env-file)          ENV_FILE="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [ -z "$POOL_NAME" ] || [ -z "$TEMPLATE_FILE" ]; then
    echo "Usage: $0 --pool-name <name> --template-file <file> [--concurrency-limit N] [--env-file file]" >&2
    exit 1
fi

command -v jq >/dev/null 2>&1 || { echo "jq is required to build the base job template env. Install jq and retry." >&2; exit 1; }
command -v prefect >/dev/null 2>&1 || { echo "the prefect CLI is required (pip install prefect). Install and retry." >&2; exit 1; }

# Use the real env if present, otherwise the committed _example (placeholders).
[ -f "$ENV_FILE" ] || ENV_FILE="../docker-compose.env_example"
[ -f "$ENV_FILE" ] || { echo "env file not found: $ENV_FILE" >&2; exit 1; }

# Load the addresses (exported) from the single source; PREFECT_API_URL now steers the prefect CLI
# below (env var beats the profile) and is injected into the template's env.default.
set -a; . "$ENV_FILE"; set +a
[ -n "${PREFECT_API_URL:-}" ] || { echo "PREFECT_API_URL missing in $ENV_FILE" >&2; exit 1; }

TMP_TPL="$(mktemp)"
trap 'rm -f "$TMP_TPL"' EXIT
jq --arg api "$PREFECT_API_URL" \
    '.variables.properties.env.default = { PREFECT_API_URL: $api }' "$TEMPLATE_FILE" > "$TMP_TPL"

# Register (or update) the pool through the server API. The API may need a moment after startup,
# so retry a few times. --overwrite keeps the base job template in sync on re-runs.
created=false
for _ in $(seq 1 10); do
    if prefect work-pool create "$POOL_NAME" --type docker \
            --base-job-template "$TMP_TPL" --overwrite; then
        created=true; break
    fi
    sleep 3
done
[ "$created" = true ] || { echo "register_pool: could not register '$POOL_NAME' at $PREFECT_API_URL" >&2; exit 1; }

# Pool-wide concurrency limit is a separate command (create does not accept it).
if [ "$CONCURRENCY_LIMIT" -gt 0 ]; then
    prefect work-pool set-concurrency-limit "$POOL_NAME" "$CONCURRENCY_LIMIT"
fi
```

## Appendix D. register_variables.sh

server 에 backing service **주소 Variable** (MinIO·PostgreSQL·MLflow endpoint, 비밀 아님) 을 등록하는 스크립트입니다 ([§4 Service Address Variables](#4-service-address-variables)).

`--overwrite` 라 재실행하면 값이 동기화됩니다 (idempotent). 등록한 각 값을 stdout 에 그대로 찍습니다. `--postgresql` 은 `host:port` 한 덩어리로 받아 **단일 Variable `postgresql_host_port`** 로 저장하고, 소비 코드 (`catalog.py`·`pipeline.py`) 가 host·port 로 분리합니다.

```bash
#!/usr/bin/env bash
# register_variables.sh — register the shared backing-service ADDRESS variables on the Prefect server.
# __version__ = "0.0.10"  # Semantic Versioning:  Version = Major.Minor.Patch
# Single, non-secret source of backing addresses (LAN IP). Flow code and host tools (catalog.py) read
# them via prefect Variables from the server, so no docker-compose.env is needed outside containers.
# Run after the server is up (run_server.sh). Idempotent (--overwrite).
#
#   ./register_variables.sh --minio http://<MINIO_IP>:9000 --postgresql <POSTGRESQL_IP>:5432 \
#                           --mlflow http://<MLFLOW_IP>:5000
#
set -euo pipefail

COMPOSE="docker-compose.server.yml"          # the server compose (its top-level name: sets the project)
MINIO_ENDPOINT=""          # MinIO S3 endpoint, e.g. http://<MINIO_IP>:9000 (data download / model upload)
POSTGRESQL_HOST_PORT=""    # PostgreSQL host:port, e.g. <POSTGRESQL_IP>:5432 (catalog / optuna DBs)
MLFLOW_TRACKING_URI=""     # MLflow tracking server, e.g. http://<MLFLOW_IP>:5000

while [ $# -gt 0 ]; do
    case "$1" in
        --minio)      MINIO_ENDPOINT="$2"; shift 2 ;;
        --postgresql) POSTGRESQL_HOST_PORT="$2"; shift 2 ;;
        --mlflow)     MLFLOW_TRACKING_URI="$2"; shift 2 ;;
        --compose)    COMPOSE="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# All three addresses are required: an empty or placeholder value would be registered silently and every
# consumer (catalog.py / pipeline.py) would then fail far from here.
if [ -z "$MINIO_ENDPOINT" ] || [ -z "$POSTGRESQL_HOST_PORT" ] || [ -z "$MLFLOW_TRACKING_URI" ]; then
    echo "Usage: $0 --minio <URL> --postgresql <HOST:PORT> --mlflow <URL> [--compose <FILE>]" >&2
    exit 1
fi

# set one variable on the server (overwrite so re-runs keep it in sync); echo the value we registered.
set_var() {
    docker compose -f "$COMPOSE" exec -T prefect_server \
        prefect variable set "$1" "$2" --overwrite >/dev/null   # hush prefect's value-less line
    echo "Set variable '$1' to \"$2\""
}

set_var minio_endpoint      "$MINIO_ENDPOINT"
set_var postgresql_host_port "$POSTGRESQL_HOST_PORT"  # host:port; consumers (catalog.py / pipeline.py) split it
set_var mlflow_tracking_uri "$MLFLOW_TRACKING_URI"
echo "[register_variables] set: minio_endpoint, postgresql_host_port, mlflow_tracking_uri"
```
