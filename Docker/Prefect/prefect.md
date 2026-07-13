# Prefect Pipeline Orchestration on Docker

<sub>rev. 585</sub>

<img src="assets/prefect-wordmark.png" alt="Prefect" height="100">

> 공식 사이트: [https://www.prefect.io/](https://www.prefect.io/)

Prefect stack 을 한 호스트에서 **세 구성요소 (Prefect Server · Prefect Dispatcher · Pipeline Flow)** 로 나눠 도커로 실행합니다. Prefect stack 의 backing service 는 PostgreSQL · MinIO · MLflow 가 있습니다. **AI/ML flow 의 실행은 하나의 python docker 이미지** (`pipeline-flow:latest`) **로만 하고, 그 flow 이미지는 dispatcher 이미지와 분리** 합니다. job 마다 그 이미지로 **일시적 컨테이너 (ephemeral)** 를 띄웠다 파괴하며, **여러 팀원이 동시에 다수 job 을 trigger** 하는 환경을 전제로 Prefect 의 **Docker work pool** 로 구현합니다.

Prefect work pool 의 type 은 `process` · `docker` · `kubernetes` 가 있는데 ([Appendix C](#appendix-c-execution-architecture)), 이 스택은 **`docker`** 를 씁니다 — flow 를 dispatcher 와 **분리된 별도 컨테이너** 에서 실행하기 위함입니다.

Prefect server (`prefect_server`) 는 job 을 수집·스케줄링하는 **단일 진입점** 입니다. 단 **코드는 실행하지 않습니다** — 실행은 항상 Pipeline Flow 컨테이너 안에서 일어납니다.

## 1. Architecture

기본 구성은 한 호스트에서 공유 네트워크 `mlops` 로 묶입니다. `prefect_server` 와 `prefect_dispatcher` 가 상시 떠 있고, job 마다 **`pipeline_flow` 컨테이너** 가 일시적으로 실행됩니다. Work pool 은 server 에 등록된 메타데이터입니다 (컨테이너가 아닙니다).

| Component | Prefect term | Role | Lifetime |
|----------|--------------|------|----------|
| **Prefect Server** | server | job 수집·스케줄링·UI·**work pool 등록**.<br>실행 파라미터를 entrypoint 에 전달.<br>코드는 실행하지 않습니다. | 상시 |
| **Prefect Dispatcher** | dispatcher | pool 을 polling 해 job 마다<br>`pipeline_flow` 컨테이너를 띄웁니다.<br>코드는 실행하지 않습니다. | 상시 |
| **Pipeline Flow** | execution unit | flow (코드) 가 실행되는 곳입니다.<br>job 마다 뜨는 전용 일시적 컨테이너입니다. | 일시적 |

**구성 수 (cardinality)** — server 를 정점으로 부채꼴로 퍼집니다.

- **server = 1** — 중앙 진입점입니다.
- **pool / server = n_pool** (n_pool ≥ 1) — 라우팅 구분마다 1개입니다.
- **dispatcher / pool = n_dispatcher** (n_dispatcher ≥ 1) — dispatcher 하나는 pool 하나를 polling 합니다.
- **flow / dispatcher = n_flow** — 동시 실행 시 1 ≤ n_flow ≤ limit (= 8), 유휴 시 0입니다.

**성능 등급별 pool 예시 (2 pools · dispatcher 마다 flow 2개):**

```
                         +---------------------+
                         |  Prefect Server (1) |   route each run to a pool by work_pool_name
                         +----------+----------+
                                    |
              +---------------------+---------------------+
              v                                           v
     pool: low_performance                     pool: high_performance
              |                                           |
              v                              +------------+------------+
      +--------------+                       v                         v
      | dispatcher L1|               +--------------+          +--------------+
      |  (machine 1) |               | dispatcher H1|          | dispatcher H2|
      +------+-------+               +------+-------+          +------+-------+
         |       |                      |       |                 |       |
         v       v                      v       v                 v       v
      +----+  +----+                 +----+  +----+            +----+  +----+
      |flow|  |flow|                 |flow|  |flow|            |flow|  |flow|
      +----+  +----+                 +----+  +----+            +----+  +----+
```

- **pool = 라우팅 라벨** — server 가 run 을 `work_pool_name` 으로 해당 등급 pool 에 보냅니다 (pool 은 큐일 뿐 컨테이너가 아닙니다).
- **dispatcher = 머신마다 1개** — 각 컴퓨터가 자기 등급 pool 의 dispatcher 를 띄웁니다. 한 등급에 머신이 여럿이면 그 pool 에 dispatcher 가 여럿 붙어 큐를 나눕니다 (위 그림: high 는 2대 → dispatcher 2개).
- **dispatcher 마다 flow 여럿** — 각 dispatcher 가 `--limit` 까지 pipeline_flow 컨테이너를 동시에 띄웁니다 (그림은 2개씩).
- **deployment = 등급별 등록** — **deployment** (flow 를 어떤 pool·파라미터로 실행할지 server 에 등록한 실행 정의) 은 pool 하나에 바인딩되므로, 같은 flow 를 등급마다 등록해 (`pipeline/high_deployment`·`pipeline/low_deployment`) job 을 보낼 등급을 고릅니다 (등록 방법은 [§6.2](#62-deployment)).

각 서비스의 역할입니다.

| Service | Endpoint | Role |
|---------|----------|------|
| `postgres` | `:5432` | Metadata DB · `prefect`/`mlflow`/`optuna`/`catalog` 4 논리 DB |
| `minio` | `:9000` (S3 API) · `:9001` (console) | Object storage · `datasets`/`models`/`mlflow` 3 buckets |
| `mlflow` | `:5000` | 실험 추적 + 모델 레지스트리 · backend `postgres` · artifact `minio` |
| `prefect_server` | `:4200` | Prefect server + 대시보드 (UI) · backend `postgres` |
| `prefect_dispatcher` | — | job polling · dispatch · reporting · cleanup |

> `postgres`·`minio`·`mlflow` 는 각자 폴더의 compose 로 띄웁니다. 이 문서는 **Prefect server·dispatcher 와 `pipeline_flow` 이미지** 에 집중합니다.

## 2. Installation

설치는 **2 routings** (docker · pool) + **3 dockers** (server → dispatcher → pipeline_flow) 입니다. [Installation Sequence](#installation-sequence) 가 설치 순서와 단계별 configuration 을, [Setup Files](#setup-files) 가 구성요소별 파일과 실행 명령을 정리합니다.

### Installation Sequence

  2 routings (docker · pool) + 3 dockers 의 설치 순서와, 각 단계가 요구하는 configuration 입니다 (파일 전체와 실행 명령은 아래 [Setup Files](#setup-files)).

  ```text
  NETWORK ── docker network create mlops          # routing 1 — docker routing: container ↔ container
             shared external network; all 3 dockers attach by service name

  ══ DOCKER 1 ── PREFECT SERVER ════════════════════════════════════════════
     dir    : PrefectServer/
     files  : docker-compose.server.yml · run_server.ps1 · register_pool.ps1
              docker-pool-template-high.json · docker-pool-template-low.json · prune_loop.sh
     run    : run_server.ps1                      # in PrefectServer/: create network + compose up -d
     config → ../docker-compose.env
              PREFECT_SERVER_DATABASE_CONNECTION_URL = 192.168.0.13:5432/prefect
              PREFECT_API_URL                        = http://<server IP>:4200/api   # UI inherits this
       │
       └─ Work Pool Registration ── register_pool.ps1   # routing 2 — pool routing: run → pool (once, after server up)
          config → base job template (docker-pool-template-{high,low}.json)
                   image    = pipeline-flow:latest
                   env      = { PREFECT_API_URL: http://prefect_server:4200/api }
                   networks = [mlops]   auto_remove = true   mem_limit = 16g | 4g
                   concurrency-limit (pool) = 16 | 8
       ▼
  ══ DOCKER 2 ── PREFECT DISPATCHER ════════════════════════════════════════
     dir    : PrefectDispatcher/
     files  : Dockerfile.dispatcher · docker-compose.dispatcher.yml · run_dispatcher.ps1
     run    : docker build -f Dockerfile.dispatcher -t prefect-dispatcher:latest .   # in PrefectDispatcher/
              run_dispatcher.ps1 -WorkPool <tier>  # compose up -d
     config → ../docker-compose.env + shell
              PREFECT_API_URL = http://prefect_server:4200/api
              WORK_POOL = high_performance | low_performance
              WORKER_LIMIT = 8 | 4                 # worker --limit
       ▼
  ══ DOCKER 3 ── PIPELINE FLOW ═════════════════════════════════════════════
     dir    : PipelineFlow/
     files  : Dockerfile.pipeline_flow · requirements.txt · pipeline.py
              high_deployment.yml · low_deployment.yml
     run    : docker build -f Dockerfile.pipeline_flow -t pipeline-flow:latest .   # in PipelineFlow/
              prefect deploy --prefect-file <tier>_deployment.yml --name <tier>_deployment --no-prompt
     config → deployment parameters ({high,low}-deployment.yml)
              git_repo · git_commit_hash · minio_key · minio_bucket · submitter · payload
       │
       └─ Credential blocks (admin, once)         # Credentials blocks on server; needed before first run
          files  : credentials.py · <name>.json (e.g. yrocket.json)
          run    : python credentials.py --json-path yrocket.json --block-name yrocket   # block name = any lowercase id
          config → run-code credentials (one or more blocks, nested)
                   <name> { minio · postgresql_catalog · postgresql_optuna }   # block name = any lowercase id (not tied to a person)

  shared : docker-compose.env                      # at Docker/Prefect/ root; server & dispatcher read ../docker-compose.env
  ```

  > 전제 — 이 3 docker 앞에 **PostgreSQL → (MinIO/MLflow)** 가 먼저 떠 있어야 합니다. `docker-compose.env` 의 DB URL 과 Secret 의 MinIO 키가 그 스택을 가리키므로, 각 폴더 compose 로 먼저 띄웁니다 (이 문서 범위 밖).

### Setup Files

  설치 파일은 세 구성요소 + 자격증명 + 공유 env 로 나뉩니다. 각 묶음의 파일과 실행 명령을 함께 적습니다.

  1) **[PREFECT SERVER](#4-prefect-server-container)** — 제어 노드 1대 · 공식 이미지라 빌드 없음

     ```
     PrefectServer/
     ├─ docker-compose.server.yml      server container definition (port 4200 · mounts the base job templates)
     ├─ run_server.ps1                 start: create network + compose up
     ├─ register_variables.ps1         register backing-address variables (once, after the server is up)
     ├─ register_pool.ps1              register work pools (once, after the server is up)
     ├─ prune_loop.sh                  worker_pruner sidecar loop (prunes OFFLINE worker records)
     ├─ docker-pool-template-high.json   high-tier base job template (mem_limit 16g · = flow container settings)
     └─ docker-pool-template-low.json    low-tier base job template (mem_limit 4g)
     ```

     Run (from `PrefectServer/`):

     ```powershell
     .\run_server.ps1 -Yaml docker-compose.server.yml -Network mlops
     .\register_variables.ps1 -Minio http://192.168.0.8:9000 -Postgresql 192.168.0.13:5432 -Mlflow http://192.168.0.8:5000
     .\register_pool.ps1 -PoolName high_performance  -TemplateFile docker-pool-template-high.json -ConcurrencyLimit 16 -Compose docker-compose.server.yml
     .\register_pool.ps1 -PoolName low_performance -TemplateFile docker-pool-template-low.json  -ConcurrencyLimit 8  -Compose docker-compose.server.yml
     ```

  2) **[PREFECT DISPATCHER](#5-prefect-dispatcher-container)** — 작업 머신마다 1대 · 직접 빌드

     ```
     PrefectDispatcher/
     ├─ Dockerfile.dispatcher          image recipe (python + prefect + prefect-docker)
     ├─ docker-compose.dispatcher.yml  container definition (mounts docker.sock)
     └─ run_dispatcher.ps1             start: compose up
     ```

     Run (from `PrefectDispatcher/`):

     ```powershell
     docker build -f Dockerfile.dispatcher -t prefect-dispatcher:latest .    # build the image once
     .\run_dispatcher.ps1 -WorkPool high_performance -WorkerLimit 8
     .\run_dispatcher.ps1 -WorkPool low_performance -WorkerLimit 4
     ```

  3) **[PIPELINE FLOW](#6-pipeline-flow-container)** — job 마다 떴다 사라지는 컨테이너 · 직접 빌드

     ```
     PipelineFlow/
     ├─ Dockerfile.pipeline_flow       flow image recipe (FROM python:3.11.15)
     ├─ requirements.txt               team libraries (torch · mlflow · optuna …)
     ├─ pipeline.py                    orchestrator (copied into the image)
     └─ {high,low}-deployment.yml    deployment definitions (admin registers once)
     ```

     Run (from `PipelineFlow/`):

     ```powershell
     docker build -f Dockerfile.pipeline_flow -t pipeline-flow:latest .   # build the image once
     prefect deploy --prefect-file high_deployment.yml --name high_deployment --no-prompt   # register a deployment (host shell, once; repeat for low_deployment)
     ```

  4) **[Credentials](#7-credentials)** — 자격증명 블록 (admin · 블록마다 1회) · `Docker/Prefect/` 루트

     ```
     credentials.py                    Credentials block class + JSON register CLI ([Appendix I](#appendix-i-credentialspy))
     <name>.json                       credential JSON (e.g. yrocket.json)
     ```

     Run (from `Docker/Prefect/`, `PREFECT_API_URL` → server):

     ```powershell
     python credentials.py --json-path yrocket.json --block-name yrocket     # save a block named "yrocket" (lowercase)
     ```

  - **공유** — `Docker/Prefect/` 루트에 두고 server·dispatcher compose 가 `../docker-compose.env` 로 읽음

     ```
     docker-compose.env             credentials · PREFECT_API_URL   (Docker/Prefect/ root)
     ```

## 3. Network

이 스택은 여러 머신에 걸쳐 있어, 통신이 되려면 두 가지가 갖춰져야 합니다 — ① 원격 backing service 포트가 방화벽 너머로 **도달 가능**해야 하고, ② 컨테이너를 띄우는 **각 호스트**에 로컬 docker network `mlops` 가 있어야 합니다. stack 을 올리기 전에 이 순서로 확인합니다.

### Reachability to backing service

  **LAN IP 모델** 에서는 원격 backing service (PostgreSQL·MinIO·MLflow) 를 호스트의 LAN IP와 port로 부릅니다. 이때 **호스트 방화벽**을 점검해야 합니다. 특히 Docker 가 `0.0.0.0:<port>` 로 게시해도 backing 호스트 (특히 **Windows + Docker Desktop**) 는 LAN 인바운드를 기본 차단하는 경우가 많습니다. 막혀 있으면 예컨대 prefect_server 는 DB 에 못 붙어 migration `TimeoutError` 로 crash-loop 합니다.

  방화벽 열기와 도달성 검증은 **서로 다른 호스트**의 일입니다 — 여는 것은 그 backing 호스트의 로컬 방화벽이라 거기서, 검증은 자기 자신이 아닌 **소비 호스트**에서 해야 실제 네트워크 도달성을 봅니다 (backing 호스트에서 자기 LAN IP 로의 접속은 loopback 이라 방화벽과 무관하게 늘 열린 것처럼 보입니다). 순서대로:

  `backing_ports` 스크립트에 action (`open` · `check`) 과 `-host`·`-port` 를 줘서 포트 하나씩 처리합니다 (Windows 는 `.ps1`, Linux 는 `./backing_ports.sh` 로 grammar 동일). 코드는 [Appendix D](#appendix-d-backing_portsps1).

  **① backing 호스트에서 인바운드 열기** (`open`, 멱등) — 주소에서 뽑은 LAN subnet 으로 제한합니다.

  ```powershell
  # on the backing host (Windows: admin PowerShell) — Linux: sudo ./backing_ports.sh open -host ... -port ...
  .\backing_ports.ps1 open -host 192.168.0.13 -port 5432  # PostgreSQL
  .\backing_ports.ps1 open -host 192.168.0.8 -port 9000  # MinIO
  .\backing_ports.ps1 open -host 192.168.0.8 -port 5000  # MLflow
  ```

  **② 소비 호스트 (server·dispatcher) 에서 도달성 검증** (`check`) — backing 호스트가 **아닌** 다른 호스트에서 실행해야 loopback 이 아닌 실제 도달성을 봅니다.

  ```powershell
  # on a consuming host (NOT the backing host) — Linux: ./backing_ports.sh check -host ... -port ...
  .\backing_ports.ps1 check -host 192.168.0.13 -port 5432  # PostgreSQL
  .\backing_ports.ps1 check -host 192.168.0.8 -port 9000  # MinIO
  .\backing_ports.ps1 check -host 192.168.0.8 -port 5000  # MLflow
  ```

  모든 포트가 `OPEN` 이면 다음으로 넘어갑니다 (backing service 자체의 설치·포트 게시는 각 서비스 문서를 따릅니다).

### Docker Network

  Prefect stack 의 컨테이너들은 docker network `mlops` 로 통신합니다. 접근 방식은 컨테이너가 **같은 머신**인지 **다른 머신**인지에 따라 갈립니다 (**LAN IP 모델**):

  - **같은 머신** → docker **서비스 이름** (`prefect_server`·`minio`·`postgres`·`mlflow`). 같은 호스트의 `mlops` 에 붙은 컨테이너끼리 이름으로 바로 찾습니다.
  - **다른 머신** → 그 서비스가 있는 **호스트의 LAN IP + 게시 포트** (예: `http://192.168.0.13:4200/api`, `<MinIO 호스트 IP>:9000`).

  왜 다른 머신은 이름이 안 되나 — 기본 `bridge` network 는 **호스트 로컬**이라, 각 머신에 같은 이름 `mlops` 를 만들어도 **이름만 같을 뿐 별개의 network** 입니다. docker 서비스 이름은 그 호스트의 network 안에서만 해석되므로 **머신을 넘지 못합니다.** 그래서 크로스머신 접근은 LAN IP 로 합니다.

  > docker 이름을 **머신을 넘어** 쓰려면 Docker Swarm 의 **overlay network** 가 필요하지만, 전 노드가 **LAN-native Linux** 여야 동작합니다 (Windows/macOS 의 Docker Desktop 노드는 불가 — [docker_network.md §2 Swarm Overlay Network](../docker_network.md#2-swarm-overlay-network)). 이 스택은 OS 혼합·단순성을 위해 기본적으로 **LAN IP 모델** 을 씁니다.

#### Create the Network

  컨테이너를 띄울 **각 호스트**에서 로컬 bridge `mlops` 를 한 번 만듭니다 (이미 있으면 무해).

  ```bash
  docker network create mlops        # local bridge; run once per host
  docker network ls | grep mlops     # DRIVER = bridge, SCOPE = local
  ```

  이후 절의 모든 compose 는 이 `mlops` 를 external network 로 참조합니다. 같은 호스트의 컨테이너는 **서비스 이름**으로, 다른 호스트의 서비스는 **LAN IP** 로 접근합니다 (`PREFECT_API_URL`·credential endpoint 등에서 지정).

### Server Connection

  어느 Prefect server 에 연결할지 (`PREFECT_API_URL`) 를 최초 1회 설정하면 이후 모든 client 명령이 이 server 를 향합니다. 설정 방법은 두 가지이며, 환경변수가 프로필보다 우선합니다 (환경변수 > 프로필 > 기본값). 같은 컴퓨터면 `<Host IP>` 는 `localhost`.

  1) **환경변수** — OS 환경변수로 지정. Windows 에서 영구 등록은 `setx` (또는 시스템 속성), 현재 셸에만 임시로 줄 땐 `$env:`.

  ```powershell
  setx PREFECT_API_URL "http://<Host IP>:4200/api"     # persist (User scope) — applies to newly opened shells
  $env:PREFECT_API_URL = "http://<Host IP>:4200/api"   # temporary - current PowerShell only
  ```

  2) **prefect CLI** — Prefect 프로필 (`~/.prefect/profiles.toml`) 에 저장.

  ```powershell
  prefect config set PREFECT_API_URL="http://<Host IP>:4200/api"
  ```

  이 주소는 job 을 trigger 할 때 (`prefect deployment run ...`), deployment 를 등록할 때, Prefect Secret 블록을 등록/조회할 때 등 server 와 통신하는 client 작업 전반에 쓰입니다. 단 이 값은 접속 주소일 뿐이라, 그 URL 에 Prefect server 가 실제로 떠 있어야 합니다.

## 4. Prefect Server Container

### Server Setup

  server 는 backend 인 `postgres` 가 먼저 떠 있어야 하므로 **PostgreSQL → (MinIO/MLflow) → Prefect server** 순으로 띄웁니다.

  #### Yaml

  ```yaml
  # docker-compose.server.yml
  # __version__ = "0.0.11"
  name: prefect-server   # compose project name baked in (replaces -p); run_server.ps1 / register_pool.ps1 rely on it
  services:
    prefect_server:
      image: prefecthq/prefect:3-latest
      command: prefect server start --host 0.0.0.0
      env_file:
        # PREFECT_SERVER_DATABASE_CONNECTION_URL + PREFECT_API_URL (host LAN IP); the UI inherits PREFECT_API_URL, so no PREFECT_UI_API_URL is needed.
        - ../docker-compose.env_example       # shared, kept at Docker/Prefect root
      ports:
        - "4200:4200"                 # dashboard/API. Clients connect on this port.
      volumes:
        - ./docker-pool-template-high.json:/templates/docker-pool-template-high.json:ro   # base job template for the high_performance pool
        - ./docker-pool-template-low.json:/templates/docker-pool-template-low.json:ro     # base job template for the low_performance pool
      networks:
        - mlops
      restart: unless-stopped

    worker_pruner:
      image: alpine:3                     # tiny; installs curl + jq at start (no python image)
      depends_on:
        - prefect_server
      environment:
        - PREFECT_API_URL=http://prefect_server:4200/api   # internal server API the sidecar prunes via
        - PRUNE_INTERVAL_SECONDS=3600                       # prune cadence (hourly)
      volumes:
        - ./prune_loop.sh:/prune_loop.sh:ro
      command: ["sh", "-c", "tr -d '\\r' < /prune_loop.sh | sh"]   # strip CR (Windows EOL) then run
      networks:
        - mlops
      restart: unless-stopped

  networks:
    mlops:
      external: true
  ```

  - `command: prefect server start --host 0.0.0.0` 은 컨테이너 밖에서도 접속하도록 모든 인터페이스에 바인딩합니다.
  - `networks: mlops` 로 `postgres` 와 서비스명으로 통신합니다. `postgres` 는 별도 compose 라 `depends_on` 대신 `restart: unless-stopped` 로 준비될 때까지 재시도합니다.
  - **UI API 주소** — UI 가 **브라우저에게** 넘길 API 주소는 `PREFECT_UI_API_URL` 인데, 따로 지정하지 않으면 `PREFECT_API_URL` 을 그대로 상속합니다. 그래서 env_file 의 `PREFECT_API_URL` 을 브라우저가 닿는 **호스트 LAN IP** (`http://<server IP>:4200/api`) 로 두면 remote 머신에서 대시보드를 열어도 정상 동작하므로, `PREFECT_UI_API_URL` 을 따로 두지 않습니다. (도커 내부 이름 `prefect_server` 나 `localhost` 로 두면 각각 브라우저가 못 풀거나 자기 자신을 가리켜 remote 에서 빈 화면이 됩니다.)
  - `worker_pruner` 는 server 와 함께 뜨는 작은 사이드카 (alpine + curl + jq) 로, `PRUNE_INTERVAL_SECONDS` (기본 1시간) 마다 server 의 **OFFLINE (stale) 워커 레코드** 를 API 로 지웁니다 (`prune_loop.sh`). Prefect 는 죽은 워커를 OFFLINE 로 표시만 하고 지우지 않으므로, ONLINE 워커는 두고 나머지만 삭제해 목록을 깨끗이 유지합니다. `command` 의 `tr -d '\r'` 는 Windows 줄끝 (CR) 을 걸러 셸이 깨지지 않게 합니다.

  #### Execution Command

  `PrefectServer/` 에서 실행합니다.

  ```powershell
  .\run_server.ps1 -Yaml docker-compose.server.yml -Network mlops
  ```

  - `run_server.ps1` (코드는 [Appendix E](#appendix-e-run_serverps1)) — 네트워크 생성과 `docker compose up` 을 한 번에 처리합니다.
  - `-Yaml` — 띄울 compose 파일. 프로젝트명은 이 파일의 top-level `name:` (`prefect-server`) 이 정합니다.
  - `-Network` — 붙을 공유 네트워크.

  실행 후 대시보드는 **`http://<Host IP>:4200`** 에서 열립니다 (같은 컴퓨터는 `localhost`).

### Work Pool Registration

  work pool 은 **server 에 저장되는 메타데이터 (컨테이너 아님)** 라, server 가 뜨면 한 번 등록합니다. 등록된 pool 은 server DB 에 남아 이후 dispatcher 들이 polling 으로 접근하므로 ([§5](#5-prefect-dispatcher-container)), dispatcher 쪽엔 pool 생성 단계가 없습니다.

  **등록에는 dispatcher 정보가 필요 없습니다** — 등록값은 pool 이름·`--type`·base job template 뿐이고, pool 은 dispatcher 와 독립이라 dispatcher 가 0개여도 등록됩니다 (그동안 trigger 된 run 은 `Late` 로 대기). dispatcher 는 나중에 `prefect worker start` 로 그 pool 에 붙습니다 ([§5.2 Container](#52-container)).

  **Base job template** — pool 이 띄우는 모든 `pipeline_flow` 컨테이너의 공통 설정입니다. flow 컨테이너는 dispatcher 의 마운트·네트워크를 상속하지 않으므로 **`PREFECT_API_URL` 과 네트워크를 여기서 명시** 합니다. 등급별로 `docker-pool-template-high.json`·`docker-pool-template-low.json` 두 벌을 두며 (`job_configuration` 은 같고 `variables` 의 `mem_limit` default 만 등급별로 다릅니다 — 아래는 high 예시, low 는 표 참고), 위 server compose 가 이를 server 컨테이너에 마운트해 둡니다.

  다음은 `docker-pool-template-high.json` 입니다.

  ```json
  {
    "variables": {
      "type": "object",
      "properties": {
        "image":   { "type": "string", "default": "pipeline-flow:latest" },
        "env":     { "type": "object", "additionalProperties": { "type": "string" },
                     "default": { "PREFECT_API_URL": "http://prefect_server:4200/api" } },
        "networks":{ "type": "array",  "items": { "type": "string" }, "default": ["mlops"] },
        "auto_remove": { "type": "boolean", "default": true },
        "mem_limit":   { "type": "string", "default": "16g" }
      }
    },
    "job_configuration": {
      "image":       "{{ image }}",
      "env":         "{{ env }}",
      "networks":    "{{ networks }}",
      "auto_remove": "{{ auto_remove }}",
      "mem_limit":   "{{ mem_limit }}"
    }
  }
  ```

  > **`properties` vs `job_configuration`** — `variables.properties` 는 **변수 선언** (타입 + `default`) 이고, `job_configuration` 은 그 변수를 `{{ }}` 로 받아 **실제 도커 job 설정에 끼워 넣는 틀** 입니다. 같은 키가 양쪽에 보이는 건 '선언 ↔ 사용' 한 쌍이기 때문이고, 값 우선순위는 **deployment 의 `job_variables` override > 템플릿 `default`** 입니다 (override 가 없으면 `default` 가 `{{ }}` 자리에 들어갑니다).

  - `image` — flow 컨테이너로 쓸 Pipeline Flow 이미지 ([§6.1](#61-image)). 태그 (`pipeline-flow:latest`) 가 곧 **런타임 버전** (라이브러리 + orchestrator) 입니다.
  - `env` — flow 컨테이너가 server·Secret 을 찾는 `PREFECT_API_URL` 을 줍니다.
  - `mem_limit` — flow 컨테이너 메모리 상한입니다. 등급별 pool 의 핵심 차이값입니다 (high 크게·low 작게). `16g` 의 `g` 는 기가바이트 (GiB) 를 뜻합니다.

  `networks` 는 flow 컨테이너가 붙을 네트워크로, `mlops` 면 `minio`·`prefect_server` 를 서비스명으로 찾습니다. `auto_remove: true` 면 run 이 끝날 때 컨테이너가 자동으로 삭제됩니다.

  > base job template 필드는 Prefect 버전마다 다를 수 있으니, `prefect work-pool get-default-base-job-template --type docker` 로 최신 템플릿을 받아 `image`·`env`·`networks` 의 `default` 만 채우길 권장합니다.

  > **여러 pool** — pool 마다 이 템플릿을 하나씩 등록합니다 (`docker-pool-template-high.json`·`docker-pool-template-low.json`). 등급 차이는 dispatcher 의 `--limit` (머신당 동시 컨테이너 수) 과 템플릿의 `mem_limit` 로 주고, 이미지·repo 는 같습니다.
  >
  > | Field | Target | High | Low | Source |
  > |---|---|---|---|---|
  > | `mem_limit` | memory | `16g` | `4g` | base job template (`docker-pool-template-high.json`·`docker-pool-template-low.json`) |
  > | `--limit` | dispatcher | `8` | `4` | `prefect worker start` (`WORKER_LIMIT`) |
  > | `--concurrency-limit` | pool | `16` | `8` | `work-pool set-concurrency-limit` (`register_pool.ps1`) |

  #### Registration

  server 안 prefect CLI 로 pool 마다 등록합니다 (`PrefectServer/` 에서 실행; `<Pool Name>`·`<Template File>` 변수화; 코드는 [Appendix F](#appendix-f-register_poolps1)).

  ```powershell
  # Register each tier (run once, after the server is up; from PrefectServer/).
  .\register_pool.ps1 -PoolName high_performance  -TemplateFile docker-pool-template-high.json -ConcurrencyLimit 16
  .\register_pool.ps1 -PoolName low_performance -TemplateFile docker-pool-template-low.json  -ConcurrencyLimit 8
  ```

  #### Verification

  등록 직후 pool 이 server 에 올라갔는지 (`docker` 타입·동시성 한도) 확인합니다.

  ```powershell
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

### Service Address Variables

  backing service 주소 (MinIO·PostgreSQL·MLflow endpoint, 비밀 아님) 는 서버의 **Prefect Variable** 한 곳에 둡니다. flow 코드와 host 툴 (`catalog.py`) 이 모두 **서버에서** 읽으므로 (`Variable.get(...)`), docker-compose.env 를 컨테이너 밖에서 볼 필요가 없습니다. server 기동 후 `register_variables.sh` 로 한 번 등록합니다 (server 호스트에서 `docker compose exec prefect_server` — Work Pool Registration 과 같은 서버 부트스트랩 단계).

  ```bash
  ./register_variables.sh --minio http://192.168.0.8:9000 --postgresql 192.168.0.13:5432 \
                          --mlflow http://192.168.0.8:5000
  ```

  각 Variable 이 **어떤 값으로** 등록됐는지 stdout 에 그대로 찍힙니다 (인자 없이 실행하면 default 값):

  ```text
  Set variable 'minio_endpoint' to "http://192.168.0.8:9000"
  Set variable 'postgresql_host_port' to "192.168.0.13:5432"
  Set variable 'mlflow_tracking_uri' to "http://192.168.0.8:5000"
  [register_variables] set: minio_endpoint, postgresql_host_port, mlflow_tracking_uri
  ```

  | Variable | Value (LAN IP) | Used by |
  |----------|----------------|---------|
  | `minio_endpoint` | `http://<MinIO IP>:9000` | pipeline.py·catalog.py (S3) |
  | `postgresql_host_port` | `<PostgreSQL IP>:5432` | catalog·optuna DSN (host:port, 소비 코드가 분리) |
  | `mlflow_tracking_uri` | `http://<MLflow IP>:5000` | payload MLflow 로깅 |

  - 주소가 바뀌면 `register_variables.sh` 를 **다시 한 번** 돌리면 server·flow·host 툴 전부 반영됩니다.
  - `Variable.get` 은 서버가 있어야 하므로, flow 는 base job template 의 `PREFECT_API_URL` 로, host 툴은 프로필로 서버에 붙습니다 (한 곳으로 몰린 주소를 모두가 서버에서 가져감).

## 5. Prefect Dispatcher Container

dispatcher (`prefect_dispatcher`) 는 **네 가지 일**을 합니다.

- **job polling** — **server 에 있는 work pool** (큐) 을 polling 해 job 을 가져옵니다.
- **job dispatch** — 가져온 job 을 실행 환경으로 보내 실행합니다.
- **reporting** — 실행 중 상태·로그를 server 에 보고합니다.
- **cleanup** — 실행이 끝나면 정리합니다.

dispatcher 는 **`docker` work pool** 을 polling 해 job 마다 `pipeline_flow` 컨테이너를 띄웠다 정리합니다 — flow 코드는 **그 컨테이너가** 실행하고 dispatcher 자신은 실행하지 않습니다. 이 스택의 `high_performance`·`low_performance` 는 [§4](#work-pool-registration) 에서 `--type docker` 로 등록합니다.

준비물은 **dispatcher compose** 하나입니다 — base job template 등록은 server [§4](#4-prefect-server-container), Pipeline Flow 이미지는 [§6](#6-pipeline-flow-container) 입니다.

### 5.1 Image

  docker dispatcher 는 `prefect`·`prefect-docker` 가 필요한데, 부팅 때 설치하지 않고 **전용 이미지를 1회 빌드** 해 씁니다.

  #### Dockerfile

  ```dockerfile
  # Dockerfile.dispatcher
  FROM python:3.11.15-slim
  RUN pip install --no-cache-dir "prefect>=3,<4" prefect-docker
  ```

  - `FROM python:3.11.15-slim` — slim 베이스입니다 (`prefect`·`prefect-docker` 는 순수 python wheel 이라 slim 으로 충분하고 이미지가 가볍습니다).
  - `RUN pip install --no-cache-dir "prefect>=3,<4" prefect-docker` — dispatcher 에 필요한 prefect·prefect-docker 를 이미지에 굽습니다 (부팅 때 설치하지 않습니다).

  #### Execution Command

  `PrefectDispatcher/` 에서 `docker build` 를 1회 합니다.

  ```powershell
  docker build -f Dockerfile.dispatcher -t prefect-dispatcher:latest .
  ```

  - `docker build CLI -f` — 빌드할 Dockerfile.
  - `docker build CLI -t` — image tag. 이미지에 붙이는 이름:태그 (`prefect-dispatcher:latest`) 로, dispatcher compose (`run_dispatcher.ps1`) 가 이 이름으로 컨테이너를 띄웁니다.
  - `docker build CLI .` — build context. 빌드 시 Docker 데몬에 보내는 파일 루트입니다 (`.` 는 현재 폴더; 이 Dockerfile 은 `COPY` 가 없어 보낼 파일은 없지만 인자는 필요).

### 5.2 Container

  dispatcher 는 호스트 도커 소켓을 마운트해 `pipeline_flow` 컨테이너를 띄웁니다.

  #### Yaml

  ```yaml
  # docker-compose.dispatcher.yml
  name: prefect-dispatcher   # compose project name baked in (replaces -p); run_dispatcher.ps1 relies on it
  services:
    prefect_dispatcher:
      image: prefect-dispatcher:latest   # built once from Dockerfile.dispatcher (prefect + prefect-docker)
      env_file:
        - ../docker-compose.env_example       # PREFECT_API_URL (shared, at Docker/Prefect root)
      command: prefect worker start --type docker --pool ${WORK_POOL:-high_performance} --limit ${WORKER_LIMIT:-8} --no-create-pool-if-not-found
      volumes:
        - /var/run/docker.sock:/var/run/docker.sock   # host docker socket, to spawn sibling containers
      networks:
        - mlops
      restart: unless-stopped

  networks:
    mlops:
      external: true
  ```

  - `volumes: /var/run/docker.sock` — dispatcher 가 호스트 도커로 `pipeline_flow` 컨테이너를 띄우는 통로입니다. Windows 도 같은 줄로 됩니다 — Docker Desktop 이 Linux 컨테이너용으로 이 경로에 도커 소켓을 노출하기 때문입니다 (호스트의 named pipe `\\.\pipe\docker_engine` 을 컨테이너 안 `/var/run/docker.sock` 로 연결).
  - `command` — `prefect worker start` 만 합니다. prefect·prefect-docker 는 **이미지에 구워져** 있고 `PREFECT_API_URL` 은 env_file 이 주므로, 부팅 때 설치·export 가 없습니다 (`bash -c` 도 불필요). `--type docker` 로 docker worker 임을 고정하고, `--no-create-pool-if-not-found` 로 **없는 pool 을 자동 생성하지 않습니다** (오타 이름이 들어와도 process pool 이 몰래 생기지 않고 오류로 멈춤; pool 은 server [§4](#4-prefect-server-container) 가 이미 등록). `WORK_POOL`·`WORKER_LIMIT` 는 `docker compose up` 시 셸에서 읽는 변수입니다.
  - `--limit` 은 이 dispatcher 가 **동시에 띄우는 컨테이너 수의 상한** 입니다 (동시성 세 층은 [§4 Work Pool Registration](#work-pool-registration) 의 여러 pool 표 참고).

  #### Execution Command

  `PrefectDispatcher/` 에서 실행합니다.

  ```powershell
  .\run_dispatcher.ps1 -WorkPool <tier>
  ```

  - `run_dispatcher.ps1 -WorkPool <tier>` (코드는 [Appendix H](#appendix-h-run_dispatcherps1)) — yaml 을 띄웁니다 (머신마다 1회).
  - `-WorkPool <tier>` — 이 dispatcher 가 붙을 work pool 등급입니다 (예: `high_performance`).
  - **pool 검증** — 기동 전에 server 에 등록된 **docker 타입** work pool 목록과 대조해, 없는 이름이면 목록을 번호로 보여주고 그중에서 고르게 합니다 (오타·미등록 pool, 그리고 자동 생성된 process pool 까지 걸러 헛도는 것을 막습니다). 조회는 host 의 `prefect` CLI (`work-pool ls --output json`) 로 합니다.
  - `docker compose up` (스크립트 내부) — 컨테이너가 뜨면 그 `command` 인 `prefect worker start` 가 컨테이너 안에서 실행됩니다.

  **머신마다 실행** — 같은 compose 를 각 컴퓨터에서 자기 등급 `WORK_POOL` 로 띄웁니다. pool 이 server 에 이미 있으니 (§4) dispatcher 는 polling 만 하며, 등급별 첫 머신/추가 머신 구분이 없습니다.

  worker 가 뜨는 **그 순간** server 에 자기를 알리며 (heartbeat 시작) 해당 work pool 에 **자동 등록**됩니다 — **polling 시작 = 등록** 이라 별도 절차가 없습니다. heartbeat 가 끊기면 잠시 뒤 **OFFLINE** 으로 바뀝니다 (dispatcher 등록은 deployment 등록과 별개).

  > **보안 주의** — 도커 소켓 마운트는 dispatcher 에 호스트 도커 전체 제어권 (사실상 root) 을 줍니다. 신뢰된 내부망·스터디 용도로 한정하고, 더 강한 격리는 Kubernetes work pool 을 고려합니다 ([Appendix L](#appendix-l-orchestrator-benchmarking)).

### 5.3 Scaling

  **처리량·확장** — `--limit` 을 키우거나, **다른 머신에서 dispatcher 를 더 띄워 같은 pool 에 붙입니다** (그 머신은 `docker-compose.env` 의 `PREFECT_API_URL`=`http://<server IP>:4200/api`, `docker-compose.dispatcher.yml` 의 `networks:` 블록 제거). 여러 dispatcher 는 같은 prefect server 에 있는 pool 의 큐를 나눠 가집니다.

### 5.4 Verification

  dispatcher 가 ONLINE 인지 확인합니다 (pool 등록 확인은 [§4 Work Pool Registration](#work-pool-registration)).

  ```powershell
  prefect work-pool inspect high_performance
  ```

  `inspect` 의 `status` 가 `READY` 면 그 pool 을 polling 하는 dispatcher 가 1개 이상 떠 있다는 뜻입니다 — pool 단위 간접 확인입니다. **어느 dispatcher 가 ONLINE 인지**·마지막 heartbeat 는 UI 의 Work Pools → 해당 pool → **Workers 탭** 에서 봅니다 ([§9](#9-prefect-ui)).

## 6. Pipeline Flow Container

Pipeline Flow 는 dispatcher 가 job 마다 띄우는 per-flow 컨테이너입니다. dispatcher 하나가 동시 job 수만큼 **여러 개 (n 개)** 를 띄우며 (상한 `--limit`, 현재 8), 각 컨테이너는 독립입니다. 세 가지를 다룹니다 — 컨테이너가 쓰는 **이미지** ([§6.1](#61-image)), 그 이미지로 무엇을 실행할지 server 에 등록하는 **deployment** ([§6.2](#62-deployment)), 컨테이너 안에서 generic flow orchestrator 역할을 하는 `pipeline.py` ([§6.3](#63-pipelinepy)). dispatcher 자신은 flow 를 실행하지 않으므로 flow 는 **별도 이미지** 를 쓰며 ([§5.1](#51-image)), 팀 라이브러리는 이 flow 이미지에만 둡니다. 실행이 server UI 에 어떻게 보이는지는 [§9](#9-prefect-ui) 입니다.

### 6.1 Image

  job 마다 뜨는 컨테이너의 python 환경입니다. **라이브러리와 orchestrator (`pipeline.py`) 만** 굽습니다. 팀 코드는 런타임에 그 커밋만 받는 **shallow `git fetch`** + `worktree` 로 (`git_commit_hash` 으로 특정 커밋에 고정) 컨테이너의 사설 `script/` 에 펼칩니다. 이미지가 한 번 빌드로 고정되어 모두 같은 런타임을 씁니다.

  #### Dockerfile

  ```dockerfile
  # Dockerfile.pipeline_flow — shared team Pipeline Flow image (libraries + orchestrator)
  FROM python:3.11.15
  RUN apt-get update && apt-get install -y --no-install-recommends git \
      && rm -rf /var/lib/apt/lists/*

  WORKDIR /work
  # requirements.txt — required: prefect, boto3
  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt

  # pipeline.py — orchestrator (deployment entrypoint); team repo is shallow-fetched at runtime into a per-run script/
  COPY pipeline.py .
  ```

  - `FROM python:3.11.15` + `apt-get install git` — 베이스 이미지에 런타임 `git fetch`·`worktree` 용 git 을 더합니다.
  - `COPY requirements.txt` → `pip install` — 팀 라이브러리를 설치합니다 (코드보다 먼저 복사해 레이어 캐시를 살립니다). required: `prefect`·`boto3` · payload: `mlflow`·`optuna`·`scikit-learn`·`numpy`·`pyarrow` · optional: `pandas`·`torch`·`psycopg2-binary`.
  - `COPY pipeline.py` — orchestrator 만 이미지에 굽습니다. 팀 코드는 런타임에 shallow `git fetch` 로 받습니다.

  #### Execution Command

  `PipelineFlow/` 에서 `docker build` 를 셋업 때 1회 합니다.

  ```powershell
  docker build -f Dockerfile.pipeline_flow -t pipeline-flow:latest .
  ```

  - `docker CLI -f` — 빌드할 Dockerfile.
  - `docker CLI -t` — image tag. 이미지에 붙이는 이름:태그 표식이며 (`pipeline-flow:latest`), deployment·base job template 이 이 이름으로 컨테이너를 띄웁니다.
  - `docker CLI .` — build context. 빌드 시 Docker 데몬에 보내는 파일 루트로 (`.` 는 현재 폴더), `COPY` 소스가 이 안에서 해석됩니다.

  **GPU** — 이 이미지로 GPU 를 쓰려면 `requirements.txt` 의 torch 를 CUDA 휠로 설치합니다 (CUDA 런타임이 휠에 번들되어 호스트 드라이버만 맞으면 동작). 더해 호스트에 NVIDIA 드라이버·nvidia-container-toolkit 을 두고, base job template 에서 GPU 를 요청합니다 ([§4 Work Pool Registration](#work-pool-registration)). 드라이버와 CUDA 버전이 안 맞으면 베이스 이미지를 `nvidia/cuda` 계열로 바꿉니다. GPU job 은 무거우므로 그 등급 dispatcher 의 `--limit` 을 1–2 로 낮춰 동시 실행을 제한합니다.

### 6.2 Deployment

  work pool 등록은 **실행 방식** (routing lane 을 만드는 인프라) 이고, deployment 는 **실행 내용의 정의** 입니다.

  server 에 deployment 를 관리자가 container 밖에서 1회 등록합니다. Deployment 는 yaml 로 entrypoint, work pool, pipeline flow image 를 정의합니다. 팀원이 작성하는 학습 스크립트 (`my_flow.py`) 와는 무관합니다.

  #### Yaml

  ```yaml
  # high_deployment.yml - high-tier deployment definition
  deployments:
    - name: high_deployment
      entrypoint: pipeline.py:pipeline       # <file>:<@flow function>
      work_pool:
        name: high_performance
        job_variables:
          image: pipeline-flow:latest
      parameters:
        payload: my_flow.py
  ```

  - `name: high_deployment` — deployment 이름입니다 (등급별로 `high_deployment`·`low_deployment`).
  - `entrypoint: pipeline.py:pipeline` — 실행할 flow 를 `<파일>:<@flow 함수>` 로 가리킵니다 (어떻게 `pipeline.py` 가 되는지는 [§6.3](#63-pipelinepy)).
  - `work_pool.name: high_performance` — 이 deployment 가 제출될 work pool 입니다.
  - `job_variables.image: pipeline-flow:latest` — flow 를 띄울 이미지입니다 ([§6.1](#61-image)). 이 `job_variables` 블록은 `work_pool.name` 으로 등록된 work pool 의 **base job template 을 override** 합니다. `job_variables.image` 는 `job_configuration.image` 를 override 합니다 ([§4](#work-pool-registration)).
  - `parameters.payload: my_flow.py` — flow 파라미터 기본값입니다 (`git_repo`·`git_commit_hash`·`minio_key`·`submitter`·`prefect_block` 은 trigger 때 줍니다).

  `job_variables.image` 가 base job template 을 덮어쓰는 흐름 — template 은 `image` 변수 (기본값 `pipeline-flow:latest`) 를 선언하고 `job_configuration` 에서 `"image": "{{ image }}"` 로 받습니다. job 제출 때 Prefect 가 그 `{{ image }}` 자리를 채우는데, deployment 에 `job_variables.image` 가 있으면 **템플릿 `default` 대신 이 값** 이 들어가 컨테이너가 그 이미지로 뜹니다 (`cpu`·`mem_limit`·`env` 등 다른 변수도 같은 방식; 우선순위 `job_variables` > `default` 는 [§4](#work-pool-registration)).

  #### Execution Command

  `prefect deploy` 는 yaml 정의를 server 에 등록합니다. 실행 폴더에는 `pipeline.py` 와 `high_deployment.yml` 가 있어야 합니다.

  ```powershell
  cd PipelineFlow                                      # the folder with pipeline.py and high_deployment.yml
  prefect deploy --prefect-file high_deployment.yml --name high_deployment --no-prompt
  ```

  - `prefect CLI --prefect-file` — 정의 파일.
  - `prefect CLI --name` — 등록할 deployment.
  - `prefect CLI --no-prompt` — 대화형 질문을 끄고 yaml 정의대로 등록합니다 (이미지 빌드·스케줄 프롬프트 안 뜸).

  `prefect deploy` 는 DB 에 직접 쓰지 않고 server API 로 등록을 보냅니다 (server 가 Postgres `prefect` DB 에 저장). 등급마다 `high`·`low` yaml 로 두 벌 등록합니다.

  > **중요** — `prefect deploy` 는 entrypoint 인 `pipeline.py` 의 `pipeline` 함수 **시그니처를 introspect** 해 파라미터 스키마를 server DB (`prefect`) 에 저장합니다. 따라서 `prefect deploy` 는 `pipeline.py` 가 있는 폴더에서 실행하여야 하며, `pipeline` 함수가 바뀌면 이미지 `docker build` 와 함께 **`prefect deploy` 도 반드시** 다시 해야 합니다 (그래야 server 의 파라미터 스키마·UI Run 폼·trigger 검증이 새 시그니처와 맞습니다).

  #### Verification

  deployment 이 server 에 등록됐는지 확인합니다.

  ```powershell
  prefect deployment ls
  prefect deployment inspect "pipeline/low_deployment"
  ```

  `deployment ls` 결과물 예시 — `pipeline/low_deployment` 가 `low_performance` pool 로 등록된 모습:

  ```text
                                       Deployments
  ┌───────────────────────────┬──────────────────────────────────────┬─────────────────┐
  │ Name                      │ ID                                   │ Work Pool       │
  ├───────────────────────────┼──────────────────────────────────────┼─────────────────┤
  │ pipeline/low_deployment │ a1b2c3d4-5e6f-7081-92a3-b4c5d6e7f809 │ low_performance │
  └───────────────────────────┴──────────────────────────────────────┴─────────────────┘
  ```

### 6.3 pipeline.py

  orchestrator (`pipeline.py`) 는 **"커밋 받아 → 팀원 코드 실행"** 만 하는 얇은 python 골격 (`@flow` 함수) 으로, [§6.1](#61-image) 이미지에 구워집니다. 관리자가 관리하는 스크립트이며 팀원이 작성하지 않습니다 — 팀원은 자기 학습 스크립트 (`my_flow.py` 등) 만 작성해 `payload` 파라미터로 지정합니다.

  ```python
  # pipeline.py — orchestrator; Prefect runs this as the deployment entrypoint.
  import os
  import shutil
  import subprocess
  import tempfile
  from pathlib import Path

  import boto3
  from prefect import flow, get_run_logger
  from prefect.blocks.core import Block
  from prefect.blocks.fields import SecretDict
  from prefect.variables import Variable

  __version__ = "0.0.29"  # Semantic Versioning:  Version = Major.Minor.Patch


  class Credentials(Block):              # ONE block holds a credential set as nested dicts (values hidden);
      minio: SecretDict                  # access_key, secret_key        (endpoint is a prefect Variable)
      postgresql_catalog: SecretDict     # username, password, database  (host:port is the prefect Variable 'postgresql_host_port')
      postgresql_optuna: SecretDict      # username, password, database  (host:port is the prefect Variable 'postgresql_host_port')


  # flow_run_name shows who submitted the run (e.g. alice@a1b2c3d).
  @flow(name="pipeline", flow_run_name="{submitter}@{git_commit_hash}")
  def pipeline(*, submitter: str = "", payload: str = "my_flow.py", prefect_block: str = "",
               git_repo: str, git_commit_hash: str, minio_key: str, minio_bucket: str = "datasets") -> None:
      log = get_run_logger()                         # writes to this run's UI logs
      base = Path(tempfile.mkdtemp(prefix="run-"))   # per-run temp dir (removed in finally)
      repo = base / "repo"                           # git database (.git + the fetched commit)
      script = base / "script"                       # worktree: team repo snapshot at the commit
      data = base / "data"                           # MinIO download target
      try:
          # repo/: git database - init, add remote, shallow-fetch the one commit
          subprocess.run(["git", "init", repo], check=True)
          subprocess.run(["git", "-C", repo, "remote", "add", "origin", git_repo], check=True)
          subprocess.run(["git", "-C", repo, "fetch", "--depth", "1", "origin", git_commit_hash], check=True)
          # script/: expand the fetched commit into a clean detached worktree
          subprocess.run(["git", "-C", repo, "worktree", "add", "--detach", script, git_commit_hash], check=True)

          data.mkdir(parents=True, exist_ok=True)  # data/: MinIO download target (git didn't create it)
          # this run's prefect_block -> its SECRETS (§7); service addresses are prefect Variables (§4).
          creds = Credentials.load(prefect_block)
          minio = creds.minio.get_secret_value()
          s3 = boto3.client("s3", endpoint_url=Variable.get("minio_endpoint"),
                            aws_access_key_id=minio["access_key"],
                            aws_secret_access_key=minio["secret_key"])
          # minio_key -> data/: download every object under the key (works for a single file or a whole prefix).
          paginator = s3.get_paginator("list_objects_v2")
          n = 0
          for page in paginator.paginate(Bucket=minio_bucket, Prefix=minio_key):
              for obj in page.get("Contents", []):
                  key = obj["Key"]
                  rel = key[len(minio_key):].lstrip("/") or Path(key).name  # path under the prefix
                  dest = data / rel
                  dest.parent.mkdir(parents=True, exist_ok=True)
                  s3.download_file(minio_bucket, key, str(dest))
                  n += 1
          if n == 0:
              raise FileNotFoundError(f"no objects under s3://{minio_bucket}/{minio_key}")
          log.info(f"downloaded {n} object(s) from s3://{minio_bucket}/{minio_key} to {data}")

          # bridge addresses (prefect Variables) to the payload via env: the MLflow tracking URI so
          # my_flow.py logs to the MLflow server (not a local ./mlruns), and the optuna study DSN
          # (Variable host/port + block creds) so a payload using Optuna hits the shared study DB.
          env = os.environ.copy()
          mlflow_uri = Variable.get("mlflow_tracking_uri")
          if mlflow_uri:
              env["MLFLOW_TRACKING_URI"] = mlflow_uri
          opt = creds.postgresql_optuna.get_secret_value()
          opt_host, _, opt_port = (Variable.get("postgresql_host_port") or "").partition(":")
          opt_port = opt_port or "5432"                                # tolerate a bare host with no ':port'
          env["POSTGRESQL_OPTUNA_DSN"] = (f"postgresql://{opt['username']}:{opt['password']}"
                                          f"@{opt_host}:{opt_port}/{opt['database']}")
          # run the team's payload in script/; run identity passed as CLI args; output streams to this run's logs.
          subprocess.run(["python", payload, "--submitter", submitter,
                          "--data_folder", data], cwd=script, env=env, check=True)
      except subprocess.CalledProcessError as e:     # payload exited non-zero (crashed)
          # tag the failure with whose run + message; re-raise -> run marked Failed, logs kept in the UI.
          log.error(f"payload {payload} crashed (exit {e.returncode}) for {submitter}@{git_commit_hash}: {e}")
          raise
      finally:
          shutil.rmtree(base, ignore_errors=True)    # one cleanup removes repo/ + script/ + data/
  ```

  - **자유로운 코드** — `payload` 로 팀원이 자기 스크립트를 지정하므로 코드를 정해진 틀에 맞출 필요가 없습니다. 입력은 CLI 인자 (`--submitter`·`--data_folder`) 로 받으므로, 팀원 스크립트는 `argparse` 로 그 값만 읽으면 됩니다. (payload 는 이미 체크아웃된 `script/` 안에서 돌므로 git 정보는 넘기지 않고, MLflow 서버 주소만 Variable `mlflow_tracking_uri` 를 `MLFLOW_TRACKING_URI` 환경변수로 넘깁니다.)
  - **데이터 이력** — `minio_bucket`·`minio_key` 가 **flow 파라미터** 라서 Prefect 가 run 마다 입력값을 `prefect` DB 에 자동 저장합니다 (어느 버킷·객체를 썼는지 lineage 로 남습니다).
  - **crash 확인** — payload 가 0 이 아닌 코드로 끝나면 `subprocess.run(check=True)` 가 `CalledProcessError` 를 던지고, `pipeline` 가 `submitter@commit` 을 단 에러를 run 로그에 남긴 뒤 다시 raise 해 run 이 **Failed** 로 표시됩니다. payload 의 stdout·stderr 는 실행 중 이 run 의 로그로 흘러 들어가므로, 팀원은 자기 이름이 붙은 run (`alice@a1b2c3d`) 의 **Logs** 에서 crash 원인을 봅니다. payload 가 `@task` 를 쓰면 자기 flow run ([§9](#9-prefect-ui)) 에서 **어느 단계** 가 깨졌는지까지 보입니다.
  - **이력 자동 저장** — `@flow` 진입 시 Prefect 가 run 의 상태·로그·파라미터를 자동 기록합니다. 지표·모델은 팀원 코드가 MLflow 로 로깅하면 함께 남습니다 — pipeline.py 가 Variable `mlflow_tracking_uri` 를 `MLFLOW_TRACKING_URI` env 로 넘기므로 payload 는 그 tracking 서버로 로깅합니다 (없으면 로컬 `./mlruns` 로 빠지니 `mlflow_tracking_uri` Variable 을 등록해야 대시보드에 뜹니다). 마찬가지로 블록의 `postgresql_optuna` 비밀 + Variable `postgresql_host_port` 로 DSN 을 조립해 `POSTGRESQL_OPTUNA_DSN` env 로 넘기므로, Optuna 를 쓰는 payload 는 공유 postgres study 에 연결합니다 ([Appendix M](#appendix-m-prefect-task)).

  [§6.2](#62-deployment) 의 deployment 가 entrypoint 를 **`pipeline.py:pipeline`** 로 가리킵니다. 이 문자열은 server 의 deployment 레코드 (`prefect` DB) 에 저장되고, dispatcher 가 띄운 컨테이너 안에서 Prefect 런타임이 이미지 작업 디렉터리 (`/work`, `Dockerfile.pipeline_flow` 가 `pipeline.py` 를 COPY 한 곳) 기준으로 `pipeline.py` 를 import 해 콜론 뒤 **`@flow` 함수 `pipeline`** 을 run 파라미터 (`git_repo`·`git_commit_hash`·`minio_key`·`minio_bucket`·`submitter`·`prefect_block`·`payload`) 와 함께 호출합니다. 그래서 deployment entrypoint 가 곧 이 `pipeline.py` 입니다.

  `pipeline` 함수에 전달한 run 파라미터 **값** 은 **trigger 할 때** 지정합니다 — trigger 주체는 보통 **팀원** (또는 스케줄·automation) 입니다. 팀원이 자기 머신·CI 에서 CLI `prefect deployment run "pipeline/high_deployment" -p git_repo=… -p git_commit_hash=… -p minio_key=… -p submitter=… -p prefect_block=…` 을 실행하거나 (CLI 는 [Appendix B](#appendix-b-prefect-cli)), server UI 의 Run 폼, 스케줄·automation, 또는 `run_deployment(name, parameters={…})` 로 ([§8.2](#82-python-sdk)) trigger 합니다.

  `pipeline.py` 가 **`pipeline_flow` 컨테이너 안에서** run 마다 만드는 폴더 구조입니다 (끝나면 통째로 삭제 — 컨테이너 자체가 일시적이라 함께 사라집니다).

  ```text
  /tmp/run-<rand>/                 # per-run temp dir (base; removed after the run)
  ├─ repo/                         # git init + fetch --depth 1 origin <git_commit_hash> (shallow git db)
  ├─ script/                       # git worktree add --detach script <git_commit_hash> (clean worktree at the commit)
  │  ├─ my_flow.py                 # payload — my entry (run: python my_flow.py --data_folder ../data ...)
  │  └─ ...                        # the rest of my repo at <git_commit_hash>
  └─ data/                         # MinIO download target (bucket/key → here)
     └─ <object>                   # files or folders/files
  ```

  - **팀원별 repo** — `git_repo` 가 **flow 파라미터** 라 deployment 마다 다른 repo 를 기본값으로 등록할 수 있습니다. 팀원은 각자 repo·커밋을 쓰고, run 마다 사설 `script/` 에 펼쳐져 서로 간섭하지 않습니다. Prefect 가 `git_repo`·`git_commit_hash` 을 run 파라미터로 자동 기록해 재현·lineage 가 남습니다.
  - **데이터 준비** — `pipeline.py` 가 MinIO 에서 `minio_bucket`/`minio_key` 객체를 `data/` 로 미리 내려받고 `--data_folder` 로 경로를 넘깁니다. 접속 자격증명 (그 블록의 `minio` 섹션) 은 [§7](#7-credentials) 의 Credential Blocks 로 받습니다. 팀원 코드는 자격증명·다운로드를 각자 짤 필요 없이 `--data_folder` 폴더의 파일을 읽기만 하면 됩니다 (`pipeline.py` 가 `boto3` 로 받으므로 flow 이미지에 `boto3` 가 있어야 합니다 — [§6.1](#61-image)).

## 7. Credentials

설정 값은 **네 곳** 으로 나뉘고 서로 겹치지 않습니다 — ① server·dispatcher **부트스트랩** (backend DB URL·server 주소) 은 `docker-compose.env_example`, ② `pipeline_flow` 컨테이너의 **기동 설정** (`PREFECT_API_URL`·`mem_limit` 등, 비밀 아님) 은 **base job template** (§4), ③ **backing service 주소** (MinIO·PostgreSQL·MLflow endpoint, 비밀 아님) 은 서버의 **Prefect Variable** (`register_variables`, [§4](#service-address-variables)), ④ **run 코드용 비밀** (MinIO 키·DB 비번) 만 **Credential 블록** (Prefect Secret) 입니다. **주소(③)와 비밀(④)을 분리** — 주소는 한 곳(Variable)에서 관리하고 비밀만 블록에 둡니다. dispatcher 는 자격증명을 들지 않습니다.

### docker-compose.env_example

  **server·dispatcher 부트스트랩 값** (server 주소·backend DB URL) 만 `docker-compose.env_example` 에 모읍니다 (컨테이너가 `env_file` 로 읽음). backing 주소는 여기 없고 서버 Variable 에 있습니다 ([§4 Service Address Variables](#service-address-variables)).

  ```dotenv
  # docker-compose.env_example  (Prefect stack — server/dispatcher bootstrap config)
  # __version__ = "0.0.13"
  # Container-only config: read via env_file by prefect_server and prefect_dispatcher. NOT used by host
  # tools. Backing-service addresses (MinIO / PostgreSQL / MLflow) live on the server as prefect Variables
  # (register_variables.sh) — a single, non-secret source read by the flow and by host tools alike.
  # The real docker-compose.env is git-ignored; only this _example is committed. Secrets stay CHANGE_ME.

  # -- Prefect server address (bootstrap) -------------------------------------
  # Server API address — used by the dispatcher, by flow containers (via the base job template), and by
  # in-container CLI (register_pool). Set to the prefect_server host LAN IP.
  PREFECT_API_URL=http://192.168.0.13:4200/api
  # API address the server hands to browsers for the dashboard (browsers live outside docker).
  PREFECT_UI_API_URL=http://192.168.0.13:4200/api

  # -- Prefect metadata DB (bootstrap) ----------------------------------------
  # Where the server stores flow runs / deployments / logs. Host = the PostgreSQL host LAN IP.
  PREFECT_SERVER_DATABASE_CONNECTION_URL=postgresql+asyncpg://CHANGE_ME:CHANGE_ME@192.168.0.13:5432/prefect
  ```

  - **메타 DB 호스트** 는 PostgreSQL 이 있는 머신의 **LAN IP** (여기선 `192.168.0.13`) — IP 로 두면 server 와 같은 머신이든 다른 머신이든 동작합니다 (같은 머신·같은 `mlops` 망이면 서비스 이름 `postgres` 도 가능).
  - `PREFECT_UI_API_URL` — 브라우저는 docker network 밖이라 `prefect_server` 대신 **LAN IP**.
  - **backing 주소 (MinIO·PostgreSQL·MLflow) 는 여기 없습니다** — 서버 Variable 로 관리합니다 ([§4 Service Address Variables](#service-address-variables)). dispatcher 는 자격증명·주소를 들지 않습니다.

### Credential Blocks

  코드가 **MinIO** 와 PostgreSQL 의 `catalog`·`optuna` DB 에 접속할 **비밀** 을 **한 블록** 에 모읍니다 — `minio`·`postgresql_catalog`·`postgresql_optuna` 세 묶음의 **비밀만** (주소·endpoint 는 위 Variable). 비밀 값은 `SecretDict` 로 가립니다. server 에 한 번 저장하면 컨테이너·머신마다 따로 넣지 않아도 됩니다.

  블록 클래스는 `Credentials` **하나** (`minio`·`postgresql_catalog`·`postgresql_optuna` 세 `SecretDict` 필드) 이고, **블록 이름은 임의의 소문자 식별자** 입니다 — 자격증명 세트마다 블록을 하나 만듭니다 (예시 `yrocket`; 팀원 이름과 무관, 이름은 자유). **`pipeline.py`** 와 **`catalog.py`** (공통 라이브러리) 가 같은 클래스를 정의해 쓰므로 한쪽 `save`, 다른 쪽 `load` 가 맞물립니다. 코드는 run 이 지정한 블록 이름으로 `Credentials.load(<name>)` 해 그 **비밀** 을 받습니다 (주소는 Variable).

  ```text
  yrocket                     # block name = any lowercase id (e.g. yrocket); load it -> SECRETS only
  ├─ minio              : access_key, secret_key
  ├─ postgresql_catalog : username, password, database
  └─ postgresql_optuna  : username, password, database
  ```

  자격증명을 **JSON 파일** 로 적고 `credentials.py` 로 등록합니다 — 블록 이름은 Prefect 규칙상 **소문자·숫자·하이픈만** 가능하므로 `--block-name` 으로 소문자 이름을 지정합니다 (예: 파일 `yrocket.json` → 블록 이름 `yrocket`). `credentials.py` 코드는 [Appendix I](#appendix-i-credentialspy).

  `yrocket.json`:

  ```json
  {
    "minio": {
      "access_key": "<MINIO_ACCESS_KEY>",
      "secret_key": "<MINIO_SECRET_KEY>"
    },
    "postgresql_catalog": {
      "username": "catalog_user",
      "password": "<CATALOG_DB_PASSWORD>",
      "database": "catalog"
    },
    "postgresql_optuna": {
      "username": "optuna_user",
      "password": "<OPTUNA_DB_PASSWORD>",
      "database": "optuna"
    }
  }
  ```

  ```powershell
  # Register a Credentials block (admin) — PREFECT_API_URL must point at the server.
  # Block name must be lowercase (Prefect rule); pass --block-name (any lowercase id).
  prefect block delete credentials/yrocket                              # drop the old block first (clears stale fields)
  python credentials.py --json-path yrocket.json --block-name yrocket   # save a block named "yrocket"
  ```

  등록이 성공하면 `[credentials] saved block 'yrocket'` 이 찍힙니다. 블록은 server DB 에 저장되므로, 등록에 쓴 **같은 프로필** (`PREFECT_API_URL` → server) 로 확인합니다. slug 는 `<block-type-slug>/<block-document-name>` 이라 클래스 `Credentials` → `credentials/yrocket` 입니다.

  ```powershell
  prefect config view                       # PREFECT_API_URL 이 server 를 가리키는지 확인
  prefect block ls                            # Name=yrocket, Type=Credentials (Slug 열에 credentials/yrocket)
  prefect block inspect credentials/yrocket   # 세 섹션 확인 (SecretDict 라 비밀 값은 *** 로 가려짐)
  python -c "from credentials import Credentials as cr; print(cr.load('yrocket').minio.get_secret_value())"
  ```

  UI 로는 `http://<Host IP>:4200` → **Blocks** 에서도 같은 블록이 보입니다.

  `pipeline.py` 는 블록의 `minio` **비밀** + Variable **주소** 로 다운로드하고, `catalog.py` 는 `minio`·`postgresql_catalog`·`postgresql_optuna` **비밀** + Variable **주소** 를 씁니다 (실제 load 예시는 [§6.3](#63-pipelinepy) 의 `pipeline.py`).

  > flow 컨테이너는 base job template 의 `PREFECT_API_URL` 로 server 에 연결돼야 블록을 받습니다 ([§4 Work Pool Registration](#work-pool-registration)). `mlflow`·`prefect` DB 는 사용자 코드가 직접 접속하지 않으므로, 사용자 role 에는 `catalog`·`optuna` 권한만 있으면 됩니다.

## 8. Job Triggering

등록된 deployment 를 실제로 돌리는 (trigger) 방법은 여러 가지지만, 결국 모두 **server 의 Prefect API 에 "flow run 생성" 요청을 보내는 것**입니다 — 코드가 아니라 **deployment 이름 + 파라미터 값** 만 보냅니다. **trigger 인터페이스 (CLI·SDK) 는 실행 모드와 무관하게 같고**, 실제 실행 주체는 **실행 모드** 가 정합니다 — 이 스택의 **work pool mode** (server 가 run 을 work pool 에 얹고 dispatcher 가 `pipeline_flow` 컨테이너를 띄워 그 안에서 `pipeline(**parameters)` 실행, [§6.3](#63-pipelinepy)) 와 단일 머신 대안인 **serve mode** ([§8.3](#83-serve-mode) · [Appendix C](#appendix-c-execution-architecture)) 입니다. 그래서 아래 §8.1·§8.2 는 두 모드 공통의 trigger 인터페이스이고, §8.3 이 serve mode 의 차이를 다룹니다.

> ⚠️ `pipeline(...)` 함수를 파이썬에서 직접 호출하는 것은 trigger 가 **아닙니다** — server·work pool 을 거치지 않고 그 자리에서 로컬 실행되어 컨테이너 격리·lineage 가 없습니다. 아래 [§8.2](#82-python-sdk) 는 반드시 `run_deployment` 를 말합니다.

| Aspect | Prefect CLI | Python SDK |
|--------|-------------|------------|
| 호출 | `prefect deployment run "<flow>/<deployment>"` | `run_deployment(name=…)` |
| 파라미터 | `-p key=value` (문자열) | `parameters={…}` (파이썬 타입) |
| 반환 | run id 출력 후 종료 | `FlowRun` 객체 |
| 완료 대기 | 기본 안 함 (`--watch` 로 따라감) | 기본 대기 (`timeout=0` 이면 즉시) |
| 주 용도 | 수동·셸·CI 스텝 | 코드 내 자동 trigger·chaining |

### 8.1 Prefect CLI

  사람이 셸에서, 또는 CI 의 한 스텝으로 직접 trigger 합니다. 필요한 것은 그 셸의 `prefect` CLI 와 `PREFECT_API_URL` 설정뿐입니다.

  ```powershell
  prefect deployment run "pipeline/high_deployment" `
    -p git_repo=https://github.com/team/repo.git -p git_commit_hash=a1b2c3d `
    -p minio_key="SYDNEY/Bennelong Point" -p submitter=alice -p prefect_block=yrocket
  ```

  - **파라미터** — `-p key=value` 로 하나씩 **문자열** 로 줍니다. server 가 `pipeline` 시그니처 스키마로 타입을 변환·검증합니다.
  - **반환·제어** — run 을 만들고 **id 만 출력한 뒤 바로 끝납니다** (완료를 기다리지 않음). 진행을 따라가려면 `--watch` 를 붙입니다.
  - **주 용도** — 사람이 수동으로 한 번, 셸 스크립트, CI/CD 의 한 스텝, 빠른 테스트입니다 (CLI 목록은 [Appendix B](#appendix-b-prefect-cli)).

### 8.2 Python SDK

  다른 파이썬 코드 (앱·서비스·또 다른 flow) 가 프로그램적으로 trigger 합니다.

  ```python
  from prefect.deployments import run_deployment

  flow_run = run_deployment(                                                   # ask the server to create a flow run
      name="pipeline/high_deployment",                                      # deployment name
      parameters={"git_repo": "https://github.com/team/repo.git",
                  "git_commit_hash": "a1b2c3d", "minio_key": "SYDNEY/Bennelong Point",
                  "submitter": "alice", "prefect_block": "yrocket"},
  )
  print(flow_run.id, flow_run.state)                                          # FlowRun object — id and final state
  ```

  - **파라미터** — `parameters={…}` dict 로, **네이티브 파이썬 타입** (int·bool·list 등) 을 그대로 넘깁니다.
  - **반환·제어** — `FlowRun` **객체** 를 돌려주고, 기본값은 run 이 **끝날 때까지 대기 (poll)** 합니다 (`timeout` 으로 제어, `timeout=0` 이면 즉시 반환). 그래서 상태·결과를 코드로 받아 다음 분기에 씁니다.
  - **주 용도** — flow 안에서 다른 run 을 **자동 trigger** (fan-out·orchestration), 조건부 실행, run 객체를 받아 상태 검사·후속 chaining (A 끝나면 B) 입니다.

### 8.3 Serve Mode

  work pool·dispatcher·이미지 빌드 없이 `pipeline.serve(name=…)` **한 프로세스가 deployment 등록과 실행을 겸하는** 단일 머신·소규모 대안입니다 (`serve()` 는 `@flow` 객체의 메서드라, flow 이름이 `pipeline` 이면 `pipeline.serve(...)` 입니다 — [Appendix C](#appendix-c-execution-architecture)).

  ```python
  # serve mode — one process registers the deployment AND runs it (no work pool / dispatcher).
  from my_flow import pipeline                 # the @flow object
  pipeline.serve(name="serve")    # long-lived; Ctrl-C to stop
  ```

  - **등록+실행** — `pipeline.serve(...)` 한 줄이 deployment 등록과 실행 프로세스를 겸합니다 (`prefect deploy`·dispatcher·이미지 빌드 불필요).
  - **trigger** — serve 프로세스는 상시 떠 있으므로 **별도 터미널에서** trigger 하며, 방법은 **§8.1·§8.2 와 똑같습니다** (`prefect deployment run "pipeline/serve"` · `run_deployment(...)`). served 프로세스가 그 run 을 자기 안에서 실행합니다.
  - **차이·적합** — run 마다 컨테이너 격리가 없고, 그 프로세스가 떠 있어야 run 이 돕니다. 다수 팀원·동시 실행·격리가 필요하면 work pool (이 스택) 입니다 ([Appendix C](#appendix-c-execution-architecture)).

## 9. Prefect UI

server 대시보드 (`http://<Host IP>:4200`) 에서 deployment·run·task 가 어떻게 보이는지입니다.

- **Deployments** — `<flow_name>/<deployment_name>` 로 나열됩니다 (예: `pipeline/high_deployment`·`pipeline/low_deployment`). flow 이름은 `@flow(name="pipeline")`, deployment 이름은 yaml 의 `name` 입니다.
- **Flow Runs** — trigger 된 run 이 `flow_run_name` 으로 나열됩니다. `submitter` 가 들어가 같은 deployment 아래에서 `alice@a1b2c3d` 처럼 **누구의 run 인지** 구분됩니다 ([§6.3](#63-pipelinepy) 의 `flow_run_name`). `pipeline.py` 는 payload 에 실행자 이름 (`submitter`) 만 넘기고 git 정보는 넘기지 않으므로, 팀 payload 의 flow run 은 실행자 이름 (예: `alice`) 으로 나열됩니다 (orchestrator run 은 `alice@a1b2c3d`).
- **Tasks** — 팀 payload 가 단계 (dp·fe·train·test) 를 **`@task`** 로 감싸고 `@flow` 로 묶으면, 컨테이너 env 의 `PREFECT_API_URL` 덕분에 그 subprocess 가 **자기 flow run 과 task** 를 보고해 단계가 보입니다 (orchestrator run 과 **별개 flow run**, subprocess 라 격리 유지 — [Appendix M](#appendix-m-prefect-task)).
- **Parameters · State · Logs** — run 마다 입력 파라미터 (`git_repo`·`git_commit_hash`·`minio_key`·`submitter`)·상태·로그가 자동 기록되어 (UI 의 Flow Run → Parameters), 같은 파라미터로 재실행 (재현) 할 수 있습니다.

job 하나가 trigger 되면 대시보드에 다음처럼 보입니다.

```text
Deployments
  pipeline/high_deployment     high_performance     # per-tier registration (§6.2)
  pipeline/low_deployment      low_performance

Flow Runs
  pipeline   alice@a1b2c3d   Completed   high_performance     # orchestrator (pipeline.py)
  my_flow    alice@a1b2c3d   Completed                        # team payload (@task), separate run
    ├─ data_prep      Completed
    ├─ feature_eng    Completed
    ├─ train_model    Completed
    └─ test_model     Completed
```

같은 job 이 **flow run 두 개** 로 보입니다 — orchestrator (`pipeline`) 와 팀 payload (`my_flow`). orchestrator 는 `flow_run_name` 이 `submitter@commit`, 팀 payload 는 `submitter` (pipeline.py 가 payload 엔 실행자 이름만 넘김) 이라 누구의 run 인지 묶어 보기 좋고, 팀 run 아래에 네 단계 task 가 달립니다. 팀 payload 가 plain 스크립트면 `my_flow` run·task 없이 orchestrator run 만 보입니다.

## Appendix A. Terminology

- **Host** — 모든 컨테이너 (server·dispatcher·pipeline_flow·postgres·minio·mlflow) 가 올라가는 한 대의 컴퓨터입니다.
- **`prefect_server`** — API·UI·스케줄러·work pool 대기열을 제공하는 중앙 진입점입니다. 메타데이터 (`prefect` DB) 만 관리하고 코드는 실행하지 않습니다.
- **`prefect_dispatcher`** — work pool 을 polling 해 job 마다 `pipeline_flow` 컨테이너를 띄우고 정리하는 dispatcher 입니다 (Prefect 공식 용어로는 worker). 코드는 실행하지 않습니다.
- **Pipeline Flow** — dispatcher 가 job 마다 띄우는 일시적 실행 컨테이너입니다. 받은 repo·커밋을 shallow `git fetch` 로 펼친 뒤 코드를 실행하고 끝나면 파괴됩니다.
- **ephemeral container** — `docker` work pool 이 job 마다 띄웠다 파괴하는 일시적 컨테이너입니다. 이 문서의 Pipeline Flow 가 여기 해당합니다.
- **work pool** — job 이 대기하는 큐이자 실행 방식 (type) 의 정의입니다. server 안의 메타데이터이며 컨테이너가 아닙니다.
- **work pool type** — Prefect 가 정한 실행 방식 이름입니다 (`process` · `docker` · `kubernetes` · `ecs` 등). 이 스택은 `docker` (job 마다 컨테이너) 를 씁니다.
- **serve mode** — `flow.serve()` 프로세스가 상시 떠서 flow run 요청을 받아 처리하는 모습이, 웹 서버가 요청을 처리하듯 flow 를 계속 **제공 (serve)** 하기 때문에 붙은 이름입니다.
- **deployment** — flow 를 어떻게 실행할지 묶어 **server DB (`prefect`) 에 저장한 레코드** 입니다. 파일·dict 가 아니라 server 안의 영구 레코드이고, API·UI·`prefect deployment inspect` 에서 **JSON 으로** 보입니다.
  - **누가** — 플랫폼·관리자가 등급마다 1회 (팀원 아님).
  - **어떻게** — `prefect deploy --prefect-file <yaml> --name <name> --no-prompt` (CLI) 가 yaml 정의를 server API 로 보내 DB 에 등록합니다 ([§6.2](#62-deployment)).
  - **사용** — 코드를 다시 안 봐도 이름 `<flow>/<deployment>` 로 run 을 trigger 합니다 (`prefect deployment run "pipeline/high_deployment" -p payload=my_flow.py` · UI · 스케줄). 그러면 dispatcher 가 그 정의대로 `pipeline_flow` 컨테이너를 띄웁니다.
  - 저장된 모습 (`prefect deployment inspect "pipeline/high_deployment"`):

    ```json
    { "name": "high_deployment", "flow_name": "pipeline", "entrypoint": "pipeline.py:pipeline",
      "work_pool_name": "high_performance", "job_variables": { "image": "pipeline-flow:latest" },
      "parameters": { "payload": "my_flow.py" } }
    ```
- **entrypoint** — deployment 가 실행할 flow 를 `<파일>:<@flow 함수>` 로 가리키는 문자열입니다 (예: `pipeline.py:pipeline`). server DB 에 저장되고, 컨테이너 런타임이 이 경로로 모듈을 import 해 그 `@flow` 함수를 run 파라미터와 함께 호출합니다 ([§6.2](#62-deployment)).
- **base job template** — pool 이 띄우는 flow 컨테이너의 공통 설정 (이미지·env·네트워크·메모리 상한 등) 입니다.
- **`PREFECT_API_URL`** — dispatcher·client 가 server API 를 찾는 주소 (`http://<host>:4200/api`) 입니다. 같은 호스트면 host 가 서비스명 `prefect_server` 입니다.

**Abbreviations**

- **AWS** = Amazon Web Services
- **S3** = (Amazon) Simple Storage Service — MinIO 가 호환하는 오브젝트 스토리지 API
- **API** = Application Programming Interface
- **UI** = User Interface (여기서는 Prefect 웹 대시보드)
- **DB** = Database
- **DSN** = Data Source Name — DB 접속에 필요한 정보 (드라이버·계정·호스트·포트·DB 이름) 를 한 줄로 엮은 접속 문자열입니다 (예: `postgresql://user:pass@host:5432/catalog`). 이 스택은 DSN 을 통째로 저장하지 않고 Credentials 블록 (이름은 임의의 소문자 id; 예 `yrocket`) 의 `postgresql_catalog`·`postgresql_optuna` 섹션 비밀 (`username`·`password`·`database`) 에 Variable `postgresql_host_port` (host:port) 를 더해 `catalog.py`·`pipeline.py` 가 이 문자열을 조립합니다.
- **CPU / GPU** = Central / Graphics Processing Unit

## Appendix B. Prefect CLI

`prefect` CLI 는 Prefect SDK 와 함께 설치되는 명령행 도구 (`pip install prefect`) 입니다. 본문 꼭지별로 묶었습니다.

- **§4 Server·Work Pool**
  - `prefect config set PREFECT_API_URL="http://<Host IP>:4200/api"` — client 가 바라볼 server 주소를 프로필에 1회 저장합니다.
  - `prefect config view` — 현재 활성 프로필의 설정값 (`PREFECT_API_URL` 등) 을 출력합니다. CLI 가 지금 어느 server 를 향하는지 확인합니다.
  - `prefect profile ls` — 프로필 목록을 출력합니다. 등록·조회가 어긋날 때 어떤 프로필 (어떤 `PREFECT_API_URL`) 이 활성이었는지 되짚습니다.
  - `prefect server start --host 0.0.0.0` — Prefect server 를 기동합니다.
  - `prefect work-pool create <name> --type docker --base-job-template <file> [--overwrite]` — `docker` work pool 을 server 에 등록합니다.
  - `prefect work-pool ls [--output json]` — 등록된 work pool 을 표 (또는 JSON) 로 출력합니다 (이름·type·동시성 한도; JSON 은 `run_dispatcher.ps1` 의 pool 검증이 파싱).
- **§5 Dispatcher**
  - `prefect work-pool get-default-base-job-template --type docker` — 도커 dispatcher 의 기본 base job template 을 출력합니다 (§5.1).
  - `prefect worker start --pool <name> [--limit N]` — dispatcher 를 기동해 그 pool 을 polling 하며 job 을 실행합니다 (§5.2).
  - `prefect work-pool set-concurrency-limit <pool> <N>` — pool 전체 동시 실행 상한을 설정합니다 (§5.3).
- **§6 Pipeline Flow**
  - `prefect deploy` (또는 `flow.deploy(...)`) — deployment 를 등록합니다 (§6.2).
  - `prefect deployment run "<flow>/<deployment>" -p <key>=<value>` — 등록된 deployment 를 파라미터와 함께 trigger 합니다 (§6.3).
- **§7 Credentials**
  - `prefect block ls` — server 에 등록된 블록 (`Credentials` 등) 을 표 (ID·Type·Name·Slug) 로 출력합니다. run-code 자격증명 (Credentials 블록, 예 `yrocket`) 이 등록됐는지 확인합니다 (§7). 블록은 **그 server 의 DB 에 저장** 되므로 server 마다 따로 등록해야 하며, 등록 시점의 `PREFECT_API_URL` 이 가리킨 server 에 들어갑니다.
  - `prefect variable ls` — server 에 등록된 Variable 을 출력합니다. 자격증명을 Secret 블록 대신 Variable 로 넣었는지 확인합니다 (§7).

## Appendix C. Execution Architecture

Prefect 실행 모드는 **serve mode** 와 **work pool mode** 이고, 차이는 **누가 코드를 실행하느냐** 입니다. work pool 은 type (`process`·`docker`·`kubernetes`) 에 따라 실행 주체가 달라지며, 이 스택은 **`docker`** 를 씁니다.

| Mode | Register | Code executor | Isolation | Best for |
|------|----------|---------------|-----------|----------|
| Serve Mode | `flow.serve()` | serve python | 단일 프로세스 | 단일 머신·단순 |
| Work Pool (`process`) | `flow.deploy()`<br>`prefect work-pool create --type process` | worker 컨테이너의 subprocess | dispatcher 와 같은 컨테이너 | 격리 불필요·경량 |
| Work Pool (`docker`) | `flow.deploy()`<br>`prefect work-pool create --type docker` | flow 컨테이너 | run 마다 컨테이너 격리 | 다수 팀원·동시 실행 (이 문서가 채택) |
| Work Pool (`kubernetes`) | `flow.deploy()`<br>`prefect work-pool create --type kubernetes` | flow pod | run 마다 pod 격리 | 클러스터·대규모 |

- **공통 — 등록** — **server 는 코드를 실행하지 않습니다** (이름표만 보관).
- **핵심 차이 — 실행 주체** — work pool type 이 실행 주체를 정합니다. `process` 는 worker 가 자기 컨테이너 안 subprocess 로, `docker` 는 job 마다 뜨는 flow 컨테이너가, `kubernetes` 는 job 마다 뜨는 pod 가 실행합니다. 그 실행 주체의 이미지에 라이브러리가 있어야 합니다.
- **serve mode** — 단일 머신·소규모 구성에는 work pool 없이 `flow.serve()` 만 띄우는 serve mode 가 더 단순합니다.

## Appendix D. backing_ports.ps1

backing service 포트 하나를 대상으로, action 에 따라 **도달성 확인 (`check`)** 또는 **인바운드 방화벽 개방 (`open`)** 을 하는 스크립트입니다 ([§3 Reachability to backing service](#reachability-to-backing-service)). `open` 은 그 포트를 **serving 하는 호스트**에서 (관리자 PowerShell), `check` 는 backing 호스트가 **아닌 소비 호스트**에서 실행합니다 — serving 호스트에서 자기 IP 로의 접속은 loopback 이라 방화벽과 무관하게 늘 열린 것처럼 보이기 때문입니다. `open` 은 멱등입니다. Linux 는 sibling `backing_ports.sh` (ufw) 로 grammar 동일합니다.

```powershell
# backing_ports.ps1 — check reachability of, or open the inbound firewall for, one backing service port.
# __version__ = "0.0.1"  # Semantic Versioning:  Version = Major.Minor.Patch
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
```

## Appendix E. run_server.ps1

제어 노드에서 Prefect server compose 스택을 띄우는 기동 스크립트입니다 ([§4 Server Setup](#server-setup)). 공유 `mlops` 네트워크가 없으면 만들고 `docker-compose.server.yml` 을 올립니다. work pool 등록은 별도입니다 (`register_pool.ps1` — [Appendix F](#appendix-f-register_poolps1)).

```powershell
# run_server.ps1 — bring up the Prefect server compose stack on the Control Node.
# __version__ = "0.0.20"  # Semantic Versioning:  Version = Major.Minor.Patch
param(
    [string]$Yaml    = 'docker-compose.server.yml', # the server compose file (its top-level name: sets the project)
    [string]$Network = 'mlops'                      # shared external network
)

$ErrorActionPreference = "Stop"

# Create the shared network only if it does not exist yet.
docker network inspect $Network *> $null
if ($LASTEXITCODE -ne 0) { docker network create $Network | Out-Null }

docker compose -f $Yaml up -d   # project name comes from the compose file's top-level name: (prefect-server)
```

## Appendix F. register_pool.ps1

server 에 work pool 을 등록 (또는 갱신) 하는 스크립트입니다 ([§4 Work Pool Registration](#work-pool-registration)).

`--overwrite` 가 **템플릿 동기** 를 맡습니다 — pool 이 이미 있으면 오류 없이 그 pool 의 **base job template 을 현재 파일** (`docker-pool-template-high.json`·`docker-pool-template-low.json`) **내용으로 갱신** 합니다 (idempotent). 그래서 템플릿을 고친 뒤 다시 실행하면 server 쪽 설정이 로컬 파일과 같아집니다 (`--overwrite` 가 없으면 이미 있는 pool 에 대해 등록이 실패).

```powershell
# register_pool.ps1 — register (or update) one Prefect work pool on the running server.
# __version__ = "0.0.20"  # Semantic Versioning:  Version = Major.Minor.Patch
# Idempotent: --overwrite keeps the base job template in sync. Run after the server is up (run_server.ps1).
#
#   .\register_pool.ps1 -PoolName high_performance  -TemplateFile docker-pool-template-high.json -ConcurrencyLimit 16
#   .\register_pool.ps1 -PoolName low_performance -TemplateFile docker-pool-template-low.json  -ConcurrencyLimit 8
#
param(
    [Parameter(Mandatory = $true)] [string]$PoolName,      # work pool name, e.g. high_performance | low_performance
    [Parameter(Mandatory = $true)] [string]$TemplateFile,  # base job template mounted into the server at /templates, e.g. docker-pool-template-high.json
    [int]$ConcurrencyLimit = 0,                            # pool-wide max concurrent runs (0 = no limit)
    [string]$Compose       = 'docker-compose.server.yml'   # the server compose (its top-level name: sets the project)
)

$ErrorActionPreference = "Stop"

# Build the create command. --overwrite keeps the base job template in sync on re-runs.
# (work-pool create has no --concurrency-limit in Prefect 3; the pool-wide limit is set separately below.)
$create = @('work-pool', 'create', $PoolName, '--type', 'docker',
            '--base-job-template', "/templates/$TemplateFile", '--overwrite')

# The server container has the prefect CLI and the mounted templates (/templates/<TemplateFile>).
# The API may need a moment after startup, so retry a few times.
$created = $false
for ($i = 1; $i -le 10; $i++) {
    docker compose -f $Compose exec -T prefect_server prefect @create
    if ($?) { $created = $true; break }
    Start-Sleep -Seconds 3
}

# Pool-wide concurrency limit is a separate command (create does not accept it).
if ($created -and $ConcurrencyLimit -gt 0) {
    docker compose -f $Compose exec -T prefect_server prefect work-pool set-concurrency-limit $PoolName "$ConcurrencyLimit"
}
```

## Appendix G. register_variables.ps1

server 에 backing service **주소 Variable** (MinIO·PostgreSQL·MLflow endpoint, 비밀 아님) 을 등록하는 스크립트입니다 ([§4 Service Address Variables](#service-address-variables)).

`--overwrite` 라 재실행하면 값이 동기화됩니다 (idempotent). 등록한 각 값을 stdout 에 그대로 찍습니다. `--postgresql` 은 `host:port` 한 덩어리로 받아 **단일 Variable `postgresql_host_port`** 로 저장하고, 소비 코드 (`catalog.py`·`pipeline.py`) 가 host·port 로 분리합니다.

```powershell
# register_variables.ps1 — register the shared backing-service ADDRESS variables on the Prefect server.
# __version__ = "0.0.4"  # Semantic Versioning:  Version = Major.Minor.Patch
# Single, non-secret source of backing addresses (LAN IP). Flow code and host tools (catalog.py) read
# them via prefect Variables from the server, so no docker-compose.env is needed outside containers.
# Run after the server is up (run_server.ps1). Idempotent (--overwrite).
#
#   .\register_variables.ps1 -Minio http://192.168.0.8:9000 -Postgresql 192.168.0.13:5432 `
#                            -Mlflow http://192.168.0.8:5000
#
param(
    [string]$Minio      = 'http://192.168.0.8:9000',     # MinIO S3 endpoint (data download / model upload)
    [string]$Postgresql = '192.168.0.13:5432',            # PostgreSQL host:port (catalog / optuna DBs)
    [string]$Mlflow     = 'http://192.168.0.8:5000',     # MLflow tracking server
    [string]$Compose    = 'docker-compose.server.yml'    # the server compose (its top-level name: sets the project)
)

$ErrorActionPreference = "Stop"

# set one variable on the server (overwrite so re-runs keep it in sync); echo the value we registered.
function Set-Var($name, $value) {
    docker compose -f $Compose exec -T prefect_server prefect variable set $name $value --overwrite | Out-Null
    Write-Host "Set variable '$name' to `"$value`""
}

Set-Var 'minio_endpoint'      $Minio
Set-Var 'postgresql_host_port' $Postgresql   # host:port; consumers (catalog.py / pipeline.py) split it
Set-Var 'mlflow_tracking_uri' $Mlflow
Write-Host "[register_variables] set: minio_endpoint, postgresql_host_port, mlflow_tracking_uri"
```

## Appendix H. run_dispatcher.ps1

각 dispatcher 머신에서 dispatcher compose 스택을 띄우는 기동 스크립트입니다 ([§5.2](#52-container)). server 기동과 work pool 등록은 별도입니다 (server 는 [Appendix E](#appendix-e-run_serverps1), pool 은 `register_pool.ps1` — [Appendix F](#appendix-f-register_poolps1)).

```powershell
# run_dispatcher.ps1 — start the Prefect dispatcher compose stack on a worker machine.
# __version__ = "0.0.20"  # Semantic Versioning:  Version = Major.Minor.Patch
#
# Brings up prefect_dispatcher, which polls the given WorkPool. WORK_POOL/WORKER_LIMIT are read from
# this shell at "docker compose up" (compose interpolation), so they are exported below.
# (PREFECT_API_URL etc. are read directly by the container from env_file=docker-compose.env.)
# Work pools live on the server and are registered there (register_pool.ps1), not here. Before starting,
# this script checks WorkPool against the pools registered on the server; if it is missing, it lists the
# registered pools and lets you pick one (guards against typos / not-yet-registered pools).
#
#   .\run_dispatcher.ps1 -WorkPool high_performance    # a high-tier machine
#   .\run_dispatcher.ps1 -WorkPool low_performance   # a low-tier machine
#
param(
    [string]$WorkPool = 'high_performance',  # the work pool this machine polls: high_performance | low_performance
    [int]$WorkerLimit = 8                     # max pipeline_flow containers this machine spawns concurrently
)

$ErrorActionPreference = "Stop"

$compose = "docker-compose.dispatcher.yml"

# On the same host, dispatcher/pipeline_flow containers reach the server by service name over the shared mlops network.
# (For a dispatcher on another machine, remove the networks block in the dispatcher compose and set PREFECT_API_URL to http://<host IP>:4200/api.)
docker network inspect mlops *> $null
if ($LASTEXITCODE -ne 0) { docker network create mlops | Out-Null }

# --- Validate WorkPool against the pools registered on the server ------------------------------
# Read the registered pools with the host prefect CLI (configured via its PREFECT_API_URL profile).
# EAP=Continue so the CLI's stderr (progress / version warnings) does not abort the script under Stop.
function Get-PoolsJsonText {
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $raw = prefect work-pool ls --output json 2>$null
    } finally {
        $ErrorActionPreference = $old
    }
    $text = ($raw -join "`n")
    $s = $text.IndexOf('['); $e = $text.LastIndexOf(']')
    if ($s -lt 0 -or $e -le $s) { return $null }       # no JSON => prefect CLI missing or server unreachable
    return $text.Substring($s, $e - $s + 1)
}

$jsonText = Get-PoolsJsonText
if ($null -eq $jsonText) {
    throw "Could not read work pools via the host 'prefect' CLI. Ensure prefect is installed and PREFECT_API_URL points at a running server (run_server.ps1), then retry."
}

# This dispatcher spawns docker containers, so only docker-type pools are valid
# (a name that exists only as a process pool — e.g. one auto-created by a typo — is rejected here).
$pools = @($jsonText | ConvertFrom-Json | Where-Object { $_.type -eq 'docker' })
if ($pools.Count -eq 0) {
    throw "No docker-type work pools are registered on the server. Run register_pool.ps1 (it registers --type docker) first."
}

$match = $pools | Where-Object { $_.name -eq $WorkPool } | Select-Object -First 1
if ($match) {
    $WorkPool = $match.name                              # normalize to the exact registered name
} else {
    Write-Warning "'$WorkPool' is not a registered docker work pool."
    Write-Host "Registered docker work pools:" -ForegroundColor Cyan
    for ($i = 0; $i -lt $pools.Count; $i++) {
        Write-Host ("{0,3}) {1}" -f ($i + 1), $pools[$i].name)
    }
    $sel = Read-Host "Pick a pool number (Enter to abort)"
    $idx = 0
    if (-not [int]::TryParse($sel, [ref]$idx) -or $idx -lt 1 -or $idx -gt $pools.Count) {
        throw "Aborted: no valid work pool selected."
    }
    $WorkPool = $pools[$idx - 1].name
    Write-Host "Using work pool '$WorkPool'." -ForegroundColor Green
}

# For the dispatcher compose ${...} interpolation — export to the current shell env (applies to this docker compose up).
$env:WORK_POOL    = $WorkPool
$env:WORKER_LIMIT = "$WorkerLimit"

# Bring the dispatcher stack down (keeping volumes) and back up in the background.
# project name comes from the compose file's top-level name: (prefect-dispatcher), so down only ever touches this stack.
docker compose -f $compose down
docker compose -f $compose up -d
```

## Appendix I. credentials.py

자격증명 블록을 JSON 으로 등록하는 스크립트입니다 ([§7 Credential Blocks](#credential-blocks)). 블록 이름은 **CLI 인자 > JSON `name` 필드 > 파일명** 순으로 정해지며, Prefect 규칙상 **소문자·숫자·하이픈만** 허용됩니다 (임의의 소문자 식별자, 팀원 이름과 무관). `Credentials` 클래스도 여기서 정의하며 `catalog.py` 가 import 해 씁니다 (`pipeline.py` 는 이미지 자기완결이라 같은 클래스를 따로 inline 정의 — [§6.3](#63-pipelinepy)).

```python
# credentials.py — shared Prefect credential block (Credentials) + JSON register CLI.
#
# Defines the one credential Block used across the stack and registers a Credentials block from a
# JSON file. Block name precedence: --block-name > JSON "name" field > file stem. Prefect requires the
# block name to be lowercase letters, numbers, and dashes only — any lowercase id (not tied to a person).
#
#     prefect block delete credentials/yrocket
#     python credentials.py --json-path yrocket.json --block-name yrocket    # save a block named "yrocket"
#
# Separation of concerns: the Prefect folder owns the credential block (this file); PrefectWorkflow's
# catalog.py imports it (`from credentials import Credentials`); pipeline.py keeps its own inline copy
# (baked into the flow image, so it must match this class name + fields). Needs prefect installed and
# the Prefect profile's PREFECT_API_URL pointing at the target server.
import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Union

from prefect.blocks.core import Block
from prefect.blocks.fields import SecretDict

__version__ = "0.0.19"  # Semantic Versioning:  Version = Major.Minor.Patch

# Prefect block document names allow lowercase letters, numbers, and dashes only (no upper/underscore/space/dot).
_BLOCK_NAME_RE = re.compile(r"^[a-z0-9-]+$")


class Credentials(Block):              # must match pipeline.py exactly (class name + fields).
    minio: SecretDict                  # access_key, secret_key        (endpoint is a prefect Variable)
    postgresql_catalog: SecretDict     # username, password, database  (host:port is the prefect Variable 'postgresql_host_port')
    postgresql_optuna: SecretDict      # username, password, database  (host:port is the prefect Variable 'postgresql_host_port')


def register(spec_path: Union[str, Path], name: Optional[str] = None) -> None:
    """JSON spec 으로 Credentials 블록을 server 에 save 한다 (이름 우선순위: 인자 > spec['name'] > 파일명)."""
    spec_path = Path(spec_path)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    name = name or spec.pop("name", None) or spec_path.stem
    spec.pop("name", None)             # drop "name" if present so it is not passed as a block field
    if not _BLOCK_NAME_RE.match(name):                     # also guards the JSON-name / file-stem path
        raise ValueError(f"invalid block name '{name}': use lowercase letters, numbers, and dashes only")
    Credentials(**spec).save(name, overwrite=True)
    print(f"[credentials] saved block '{name}'")


def _json_path(value: str) -> Path:
    """argparse type: 존재하는 .json 파일 경로만 통과시킨다."""
    path = Path(value)
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"file not found: {value}")
    if path.suffix.lower() != ".json":
        raise argparse.ArgumentTypeError(f"not a .json file: {value}")
    return path


def _block_name(value: str) -> str:
    """argparse type: Prefect block 이름 규칙(lowercase letters, numbers, dashes)에 맞는 문자열만 통과시킨다."""
    if not _BLOCK_NAME_RE.match(value):
        raise argparse.ArgumentTypeError(
            f"invalid block name '{value}': use lowercase letters, numbers, and dashes only"
        )
    return value


def parse_args(argv: Optional[List[str]] = None) -> Optional[argparse.Namespace]:
    """argparse 로 CLI 인자를 파싱한다. 옵션이 없으면 전체 도움말을 출력하고 None 을 돌려준다."""
    parser = argparse.ArgumentParser(description="Register a Credentials block from a JSON spec.")
    parser.add_argument(
        "--json-path", required=True, type=_json_path,
        help="path to an existing <name>.json credential spec",
    )
    parser.add_argument(
        "--block-name", default=None, type=_block_name,
        help="block name, lowercase letters/numbers/dashes (default: JSON 'name' field, else file stem)",
    )
    if not argv:                                           # no options -> show full help on stdout
        parser.print_help()
        return None
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args(sys.argv[1:])
    if args is not None:                                   # None: no options, help already printed
        try:
            register(args.json_path, args.block_name)
        except Exception as e:                             # show a clean message, not a traceback
            print(f"[credentials] error: {e}", file=sys.stderr)
            sys.exit(1)
```

## Appendix J. requirements.txt

Pipeline Flow 이미지에 설치하는 파이썬 의존성 목록입니다 ([§6.1](#61-image)). 팀 소스는 이미지에 굽지 않고 런타임에 git worktree 로 받으므로 여기에는 라이브러리만 고정합니다 (base: `python:3.11.15`). 카테고리로 나눠 두고 버전은 `numpy` 기준에 맞춥니다.

```text
# rev. 12
# Python dependencies for the shared team Pipeline Flow image (base: python:3.11.15, see Dockerfile).
# The team source is NOT baked; it is fetched into a git worktree at runtime, so only libraries are pinned here.

# WorkFlow
prefect>=3,<4                  # Prefect runtime (flow execution)
pydantic>=2,<3                 # Prefect blocks are pydantic models (SecretDict in pipeline.py); pinned to Prefect 3
boto3==1.34.131                # Object storage (MinIO, S3-compatible) access
psycopg2-binary==2.9.9         # Catalog DB (PostgreSQL) access
mlflow==2.14.1                 # Experiment tracking / model registry

# --- Core ML / DL: model training / inference frameworks ---
tensorflow==2.17.0             # Deep learning framework
tensorflow-datasets==4.9.9     # Standard dataset loader
keras==3.12.1                  # High-level neural network API
torch==2.9.1                   # Deep learning framework (PyTorch)
scikit-learn==1.4.2            # Classical machine learning algorithms
lightgbm==4.6.0                # Gradient boosting (LightGBM)
catboost==1.2.10               # Gradient boosting (CatBoost)
imbalanced-learn==0.14.1       # Imbalanced-data resampling
statsmodels==0.14.6            # Statistical models / tests
prophet==1.1.5                 # Time-series forecasting
bayesian-optimization==1.4.3   # Bayesian hyperparameter optimization
keract==4.5.1                  # Neural network activation / gradient visualization
optuna==4.8.0                  # Hyperparameter tuning

# --- Numeric / data: array & tabular ops and parallel processing ---
numpy==1.26.4                  # Numeric arrays (baseline version for all dependencies)
scipy==1.13.1                  # Scientific computing
pandas==2.0.3                  # Tabular data processing
numba==0.61.2                  # JIT compilation acceleration
numpy-ext==0.9.9               # numpy helper functions
dask==2025.12.0                # Parallel / distributed computation
h5py==3.15.1                   # HDF5 I/O

# --- Time series: pattern / distance / event detection ---
stumpy==1.14.1                 # Matrix Profile-based motif discovery
pyts==0.13.0                   # Time-series classification / transformation
dtaidistance==2.4.0            # DTW distance (C extension)
fastdtw==0.3.4                 # Approximate DTW
ucrdtw==0.201                  # UCR DTW (C extension)
peakdetect==1.2                # Peak detection

# --- Financial domain data: quotes / filings / calendars / technical indicators ---
dart-fss==0.4.10               # DART electronic disclosure collection
pandas-datareader==0.10.0      # External financial data loader
pandas-market-calendars==4.4.0 # Exchange trading calendars
ta==0.11.0                     # Technical analysis indicators (pure Python)
TA-Lib==0.4.29                 # Technical analysis indicators (requires C library)

# --- Visualization: graphs / plots ---
matplotlib==3.8.4              # Basic plotting
seaborn==0.11.2                # Statistical visualization
plotly==6.6.0                  # Interactive charts
mplcursors==0.6                # matplotlib cursors / tooltips
mpld3==0.5.11                  # matplotlib -> D3 web output
pydot==2.0.0                   # Graph (DOT) rendering
cycler==0.12.1                 # Plot style cycling

# --- File / IO / utils: storage / documents / crypto / general utils ---
pymongo==4.6.3                 # MongoDB driver
openpyxl==3.1.5                # Excel (xlsx) read / write
PyMuPDF==1.27.2.3              # PDF processing
Pillow==12.2.0                 # Image processing
pycryptodome==3.20.0           # Cryptographic algorithms
bcrypt==4.2.0                  # Password hashing
xmltodict==0.12.0              # XML <-> dict conversion
deepdiff==7.0.1                # Object diffing
semver==3.0.4                  # Semantic version handling
lockfile==0.12.2               # File locking
click==8.4.2                   # CLI building
rich==15.0.0                   # Terminal formatted output
tqdm==4.68.3                   # Progress bars
psutil==7.2.2                  # System / process info
packaging==24.2                # Version / package metadata handling
python-dateutil==2.9.0.post0   # Date parsing / arithmetic
pytz==2024.2                   # Timezone data
tzlocal==5.4.3                 # Local timezone detection
typing-extensions==4.15.0      # Type hint backport
protobuf==4.25.9               # Serialization (TensorFlow dependency)
pyarrow==15.0.2                # parquet I/O; mlflow 2.14.1 requires pyarrow<16
```

## Appendix K. Mounting a remote data folder

같은 LAN 의 remote Ubuntu 머신에 있는 data 폴더를 dispatcher 호스트의 docker 에 **NFS 로 mount** 해, `pipeline_flow` 컨테이너가 MinIO 다운로드 없이 그 폴더를 직접 읽게 하는 방법입니다. payload 는 `--data_folder` 로 경로만 받으므로 (`pipeline.py` [§6.3](#63-pipelinepy)) 다운로드든 mount 든 **무변경** 입니다.

**1) 데이터 호스트 (remote Ubuntu) — NFS export.** 폴더를 LAN 서브넷에 읽기전용으로 내보냅니다.

```bash
# on the data host (e.g. 192.168.0.50)
sudo apt-get install -y nfs-kernel-server
sudo mkdir -p /srv/datasets
# export read-only to the LAN subnet
echo "/srv/datasets 192.168.0.0/24(ro,sync,no_subtree_check)" | sudo tee -a /etc/exports
sudo exportfs -ra
sudo systemctl enable --now nfs-kernel-server
```

**2) dispatcher 호스트 — export 를 mount.** 두 방식 중 하나.

```bash
# option A: mount on the host, then bind-mount into the container (step 3)
sudo apt-get install -y nfs-common
sudo mkdir -p /mnt/datasets
sudo mount -t nfs 192.168.0.50:/srv/datasets /mnt/datasets        # ad-hoc
echo "192.168.0.50:/srv/datasets /mnt/datasets nfs ro,_netdev 0 0" | sudo tee -a /etc/fstab   # persistent

# option B: a docker NFS volume (no host mount needed)
docker volume create --driver local \
  --opt type=nfs --opt o=addr=192.168.0.50,ro \
  --opt device=:/srv/datasets datasets_nfs
```

**3) pool base job template 에 `volumes` 추가.** dispatcher 가 띄우는 모든 `pipeline_flow` 컨테이너에 마운트를 겁니다 (docker-pool-template-*.json 의 job 변수 → register_pool 재실행). option A 는 호스트 경로, option B 는 볼륨 이름.

```json
"volumes": ["/mnt/datasets:/datasets:ro"]
```

**4) pipeline.py — 다운로드 대신 마운트 경로 사용.** MinIO 다운로드 블록을 마운트 하위 경로로 바꿉니다.

```python
# instead of downloading from MinIO, point at the mounted folder
data = Path("/datasets") / minio_key
```

- **읽기전용 (`ro`) 권장** — 여러 run 이 공유하는 불변 데이터. 각 run 의 쓰기 산출물은 컨테이너 내부 임시 경로로.
- **다중 머신** — dispatcher 가 여러 대면 **모든 호스트에 같은 mount·같은 컨테이너 경로** (`/datasets`) 여야 payload 가 어디서 뜨든 동일하게 읽습니다.
- **lineage** — `minio_key` 를 경로 키로 재사용하면 "어느 데이터" 기록이 유지됩니다.
- **Windows/Docker Desktop dispatcher** 라면 NFS 대신 **SMB/CIFS** 가 편합니다 (대안: SSHFS·CIFS). 권한은 컨테이너 안에서 읽기 가능한 UID/GID 인지 확인합니다.

## Appendix L. Orchestrator Benchmarking

### Prefect vs Dagster vs Airflow

  오케스트레이터를 고를 때 자주 견주는 세 python 도구입니다. 셋 다 데이터/ML 파이프라인을 스케줄·실행·관측하지만 지향이 다릅니다 — **Prefect** 는 순수 python·동적 흐름, **Dagster** 는 데이터 자산 (asset) 과 타입·테스트, **Airflow** 는 성숙한 스케줄러와 최대 생태계입니다. 이 스택이 **Prefect** 를 고른 까닭은 flow 를 평범한 python 으로 짜면서 run 마다 격리된 컨테이너로 동적으로 띄우는 구성이 자연스럽기 때문입니다 (docker work pool).

  | Aspect | Prefect | Dagster | Airflow |
  |--------|---------|---------|---------|
  | Core abstraction | `@flow` · `@task` (명령형 python) | software-defined **asset** (데이터 자산 중심) | **DAG** (task 의존 그래프) |
  | Programming model | 순수 python·동적, 런타임에 흐름 결정 | asset·graph 선언형, 타입·테스트 강조 | DAG 선언, 스케줄러 중심 |
  | Dynamic workflows | native (런타임 분기·매핑 자유) | 지원 (제약 있음) | 약함 (정적 DAG 전제) |
  | Scheduling | flow run · automation · event | schedule · sensor · asset 기반 | 강력한 cron 스케줄러 (원조) |
  | Execution isolation | work pool: process · **docker** · k8s | run launcher: docker · k8s · celery | executor: Local · Celery · **Kubernetes** |
  | UI / lineage | flow run · task · 파라미터 자동 기록 | 데이터 자산 계보 (lineage) 1급 | DAG/task 로그 · 성숙한 UI |
  | Maturity / ecosystem | 신생 · 경량, 빠른 반복 | 신생, 데이터 플랫폼 지향 | 최고참 · 최대 생태계 |
  | Best fit | 동적 ML/데이터 파이프라인, python 우선 | 데이터 자산 · 품질/테스트 중시 | 정형 배치 ETL · 대규모 스케줄 |

### Execution pattern across systems

  "**가벼운 에이전트 (dispatcher) 가 작업을 집어, 작업마다 격리된 일시적 실행 단위를 띄워 실행하고 정리**" 하는 패턴은 오케스트레이션의 업계 표준입니다. 이 스택의 `docker` work pool 은 그 표준의 **단일 호스트 변형** 이고, 규모가 커지면 실행 단위를 컨테이너 → **pod** 로 올린 Kubernetes 변형으로 확장됩니다.

  | System | Dispatcher (agent) | Execution unit | Scale |
  |--------|--------------------|----------------|-------|
  | **Prefect** (docker pool) | worker | run 마다 **컨테이너** | 단일 호스트·소–중 |
  | **Prefect** (kubernetes pool) | worker | run 마다 **pod** | 클러스터·대 |
  | **Airflow** (KubernetesExecutor) | scheduler/executor | task 마다 **pod** | 클러스터·대 |
  | **Argo Workflows** | controller | step 마다 **pod** | 클러스터·대 |
  | **GitHub Actions / GitLab CI** | runner | job 마다 **컨테이너** | CI/CD |
  | **Kubernetes** (native Job) | controller | **pod** | 클러스터 |

### What a pod is

  - **pod** — Kubernetes 의 **최소 실행/배포 단위** 입니다. 컨테이너 하나 이상이 같은 네트워크·스토리지를 공유하며 한 덩어리로 스케줄됩니다. "작업 1개 → pod 1개" 가 격리 단위이며, 단일 호스트의 컨테이너 자리에 클러스터 규모에서 들어가는 것이 pod 입니다 (Kubernetes 의 실행 껍데기).

### job · task · step compared

  이 세 단어는 동의어가 아니라 **서로 다른 단위 (granularity)** 입니다. 도구마다 이름이 달라 혼동되므로 공통 계층으로 정리합니다.

  | Concept | Definition | Prefect | Airflow | Argo | GitHub Actions |
  |---------|------------|---------|---------|------|----------------|
  | **Workflow / Pipeline** | 전체 작업 그래프의 정의 | flow | DAG | Workflow | workflow |
  | **Run** | 그 정의를 한 번 실행한 인스턴스 | flow run | DAG run | Workflow (instance) | run |
  | **Task** | run 안의 한 작업 단위 (1 연산) | task | task | template | — |
  | **Step** | job/task 안의 순서 있는 하위 동작 | — | — | step | step |
  | **Job** | 제출되는 상위 작업 묶음 (실행 단위로 스케줄) | flow run ≈ job | — | — | job |

  - **job** — 시스템에 제출되어 한 덩어리로 스케줄되는 상위 작업입니다 (GitHub Actions 의 job, Kubernetes 의 Job). Prefect 에서는 한 flow run 이 사실상 여기 해당합니다.
  - **task** — run 안의 개별 작업 단위 (1 연산) 입니다 (`@task` 하나).
  - **step** — job/task 안에서 순서대로 실행되는 하위 동작입니다 (Argo·CI 의 step).

  > granularity 는 **Workflow → Run/Job → Task → Step** 순으로 좁아지고, 실행을 감싸는 껍데기는 **컨테이너 (단일 호스트) / pod (클러스터)** 입니다. 세 단어를 하나로 통일하기보다 이 계층 안에서 구분해 쓰는 것이 업계 표준에 맞습니다.

## Appendix M. Prefect @task

`@task` 를 쓰지 않아도 이력 관리와 재현 (reproducibility) 은 완전히 됩니다. Prefect 에서 실행 흐름을 묶는 핵심 단위는 `@task` 가 아니라 **`@flow`** 이기 때문입니다. `@flow` 데코레이터만 붙이면 그 안의 코드가 일반 함수든 클래스든 **실행 이력과 입력 파라미터가 Prefect Server 에 기록**됩니다.

### Reproducing without @task

  `@task` 없이 `@flow` 와 일반 함수만으로 과거 시점 (git 커밋 + MinIO 데이터 버전) 을 재현하는 구조입니다.

  ```python
  from prefect import flow
  import boto3

  # A plain Python function (not a Prefect @task).
  def download_data(minio_key):
      s3 = boto3.client("s3", endpoint_url="http://minio:9000")
      s3.download_file("ml-data", minio_key, "local.csv")     # the data version lives in the key path

  # A plain Python function (not a Prefect @task).
  def train_and_evaluate():
      accuracy = 0.95     # real training/validation logic (the git-checked-out code runs here)
      return accuracy

  # History and parameter tracking come from @flow, not @task.
  @flow(name="mlops-reproduce-pipeline")
  def reproduce_flow(git_commit_hash: str, minio_data_version: str):
      download_data(f"dataset/{minio_data_version}/dataset.csv")     # version pinned via the key path
      return train_and_evaluate()

  if __name__ == "__main__":
      # The arguments passed here are recorded in the Prefect server DB.
      reproduce_flow(git_commit_hash="a1b2c3d", minio_data_version="v3_best")
  ```

  이렇게 해도 이력·재현이 되는 이유는 둘입니다.

  - **파라미터 추적** — Prefect Server 가 `@flow` 진입 인자 (`git_commit_hash`·`minio_data_version`) 를 DB 에 기록합니다. UI 에서 그 기록을 보고 같은 파라미터로 재실행 (재현) 할 수 있습니다.
  - **상태 관리** — flow 의 성공 (Completed) / 실패 (Failed) 와 로그가 기록되므로 이력 관리에 문제가 없습니다.

### Why use @task then

  `@task` 없이도 이력은 남지만, 쓰는 이유는 **실패 복구**와 **성능** 입니다.

  | Capability | @flow only | @flow + @task (recommended) |
  |------------|-----------|-----------------------------|
  | Partial retry | 학습 중 에러 나면 데이터부터 다시 | 성공한 단계는 두고 실패한 단계만 재시도 |
  | Step monitoring | flow 하나의 진행만 보임 | 단계별 (다운로드·학습) 시각화·시간 측정 |
  | Caching | 매번 같은 데이터를 다시 다운로드 | 같은 입력이면 그 단계를 건너뜀 (cached) |

### Summary

  이력 관리와 과거 재현은 **`@flow` 에 파라미터 (git 커밋·MinIO 버전) 를 넘기는 것만으로 작동**합니다. 학습 소스가 클래스 덩어리라 `@task` 를 일일이 붙이기 번거롭다면, `@task` 를 생략하고 `@flow` 만 씌워도 MLOps 재현 목적에는 지장이 없습니다.
