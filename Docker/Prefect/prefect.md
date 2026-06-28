# Prefect Pipeline Orchestration on Docker

<sub>rev. 509</sub>

> 공식 사이트: [https://www.prefect.io/](https://www.prefect.io/)

Prefect stack 을 한 호스트에서 **세 구성요소 (Prefect Server · Prefect Dispatcher · Pipeline Flow)** 로 나눠 도커로 실행합니다. **AI/ML flow 의 실행은 하나의 python docker 이미지** (`pipeline-flow:latest`) **로만 하고, 그 flow 이미지는 dispatcher 이미지와 분리** 합니다. job 마다 그 이미지로 **일시적 컨테이너 (ephemeral)** 를 띄웠다 파괴하며, **여러 팀원이 동시에 다수 job 을 trigger** 하는 환경을 전제로 Prefect 의 **Docker work pool** 로 구현합니다.

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
- **deployment = 등급별 등록** — **deployment** (flow 를 어떤 pool·파라미터로 실행할지 server 에 등록한 실행 정의) 은 pool 하나에 바인딩되므로, 같은 flow 를 등급마다 등록해 (`pipeline/pipelineflow-high`·`pipeline/pipelineflow-low`) job 을 보낼 등급을 고릅니다 (등록 방법은 [§5.2](#52-deployment)).

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
              PREFECT_SERVER_DATABASE_CONNECTION_URL = postgres:5432/prefect
              PREFECT_UI_API_URL                     = http://localhost:4200/api
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
              pipelineflow-high.yml · pipelineflow-low.yml
     run    : docker build -f Dockerfile.pipeline_flow -t pipeline-flow:latest .   # in PipelineFlow/
              prefect deploy --prefect-file pipelineflow-<tier>.yml --name pipelineflow-<tier> --no-prompt
     config → deployment parameters (pipelineflow-{high,low}.yml)
              git_repo · git_commit_hash · minio_key · minio_bucket · member · payload
       │
       └─ Credential blocks (admin, once)         # one block per team member on server; needed before first run
          files  : credentials.py · <member>.json (e.g. Jason.json)
          run    : python credentials.py --json-path Jason.json   # register one block; file stem = member name
          config → run-code credentials (one block per member, nested)
                   <member> { minio · postgresql_catalog · postgresql_optuna }   # block name = member

  shared : docker-compose.env                      # at Docker/Prefect/ root; server & dispatcher read ../docker-compose.env
  ```

  > 전제 — 이 3 docker 앞에 **PostgreSQL → (MinIO/MLflow)** 가 먼저 떠 있어야 합니다. `docker-compose.env` 의 DB URL 과 Secret 의 MinIO 키가 그 스택을 가리키므로, 각 폴더 compose 로 먼저 띄웁니다 (이 문서 범위 밖).

### Setup Files

  설치 파일은 세 구성요소 + 자격증명 + 공유 env 로 나뉩니다. 각 묶음의 파일과 실행 명령을 함께 적습니다.

  1) **[PREFECT SERVER](#3-prefect-server-container)** — 제어 노드 1대 · 공식 이미지라 빌드 없음

     ```
     PrefectServer/
     ├─ docker-compose.server.yml      server container definition (port 4200 · mounts the base job templates)
     ├─ run_server.ps1                 start: create network + compose up
     ├─ register_pool.ps1              register work pools (once, after the server is up)
     ├─ prune_loop.sh                  worker_pruner sidecar loop (prunes OFFLINE worker records)
     ├─ docker-pool-template-high.json   high-tier base job template (mem_limit 16g · = flow container settings)
     └─ docker-pool-template-low.json    low-tier base job template (mem_limit 4g)
     ```

     Run (from `PrefectServer/`):

     ```powershell
     .\run_server.ps1 -Yaml docker-compose.server.yml -Network mlops
     .\register_pool.ps1 -PoolName high_performance  -TemplateFile docker-pool-template-high.json -ConcurrencyLimit 16 -Compose docker-compose.server.yml
     .\register_pool.ps1 -PoolName low_performance -TemplateFile docker-pool-template-low.json  -ConcurrencyLimit 8  -Compose docker-compose.server.yml
     ```

  2) **[PREFECT DISPATCHER](#4-prefect-dispatcher-container)** — 작업 머신마다 1대 · 직접 빌드

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

  3) **[PIPELINE FLOW](#5-pipeline-flow-container)** — job 마다 떴다 사라지는 컨테이너 · 직접 빌드

     ```
     PipelineFlow/
     ├─ Dockerfile.pipeline_flow       flow image recipe (FROM python:3.11.15)
     ├─ requirements.txt               team libraries (torch · mlflow · optuna …)
     ├─ pipeline.py                    orchestrator (copied into the image)
     └─ pipelineflow-{high,low}.yml    deployment definitions (admin registers once)
     ```

     Run (from `PipelineFlow/`):

     ```powershell
     docker build -f Dockerfile.pipeline_flow -t pipeline-flow:latest .   # build the image once
     prefect deploy --prefect-file pipelineflow-high.yml --name pipelineflow-high --no-prompt   # register a deployment (host shell, once; repeat for -low)
     ```

  4) **[Credentials](#6-credentials)** — 팀원별 자격증명 블록 (admin · 팀원마다 1회) · `Docker/Prefect/` 루트

     ```
     credentials.py                    Credentials block class + JSON register CLI ([Appendix G](#appendix-g-credentialspy))
     <member>.json                     per-member credential JSON (e.g. Jason.json)
     ```

     Run (from `Docker/Prefect/`, `PREFECT_API_URL` → server):

     ```powershell
     python credentials.py --json-path Jason.json     # save a Credentials block named "Jason" (the file stem)
     ```

  - **공유** — `Docker/Prefect/` 루트에 두고 server·dispatcher compose 가 `../docker-compose.env` 로 읽음

     ```
     docker-compose.env             credentials · PREFECT_API_URL   (Docker/Prefect/ root)
     ```

## 3. Prefect Server Container

### Server Setup

  server 는 backend 인 `postgres` 가 먼저 떠 있어야 하므로 **PostgreSQL → (MinIO/MLflow) → Prefect server** 순으로 띄웁니다.

  #### Yaml

  ```yaml
  # docker-compose.server.yml
  name: prefect-server   # compose project name baked in (replaces -p); run_server.ps1 / register_pool.ps1 rely on it
  services:
    prefect_server:
      image: prefecthq/prefect:3-latest
      command: prefect server start --host 0.0.0.0
      env_file:
        - ../docker-compose.env       # injects PREFECT_SERVER_DATABASE_CONNECTION_URL (shared, at Docker/Prefect root)
      environment:
        # the UI hands this API URL to the browser; docker-compose.env's PREFECT_API_URL is the internal
        # hostname (prefect_server) the browser can't resolve, so use the host's published port instead.
        - PREFECT_UI_API_URL=http://localhost:4200/api
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
  - `environment: PREFECT_UI_API_URL` 은 UI 가 **브라우저에게** 넘길 API 주소입니다. env_file 의 `PREFECT_API_URL` 은 도커 내부 호스트명 (`prefect_server`) 이라 브라우저가 못 푸니, 호스트 게시 포트 `http://localhost:4200/api` 로 따로 지정합니다 (다른 머신에서 열면 그 머신이 닿는 서버 주소로 바꿉니다).
  - `worker_pruner` 는 server 와 함께 뜨는 작은 사이드카 (alpine + curl + jq) 로, `PRUNE_INTERVAL_SECONDS` (기본 1시간) 마다 server 의 **OFFLINE (stale) 워커 레코드** 를 API 로 지웁니다 (`prune_loop.sh`). Prefect 는 죽은 워커를 OFFLINE 로 표시만 하고 지우지 않으므로, ONLINE 워커는 두고 나머지만 삭제해 목록을 깨끗이 유지합니다. `command` 의 `tr -d '\r'` 는 Windows 줄끝 (CR) 을 걸러 셸이 깨지지 않게 합니다.

  #### Execution Command

  `PrefectServer/` 에서 실행합니다.

  ```powershell
  .\run_server.ps1 -Yaml docker-compose.server.yml -Network mlops
  ```

  - `run_server.ps1` (코드는 [Appendix D](#appendix-d-run_serverps1)) — 네트워크 생성과 `docker compose up` 을 한 번에 처리합니다.
  - `-Yaml` — 띄울 compose 파일. 프로젝트명은 이 파일의 top-level `name:` (`prefect-server`) 이 정합니다.
  - `-Network` — 붙을 공유 네트워크.

  실행 후 대시보드는 **`http://<Host IP>:4200`** 에서 열립니다 (같은 컴퓨터는 `localhost`).

### Work Pool Registration

  work pool 은 **server 에 저장되는 메타데이터 (컨테이너 아님)** 라, server 가 뜨면 한 번 등록합니다. 등록된 pool 은 server DB 에 남아 이후 dispatcher 들이 polling 으로 접근하므로 ([§4](#4-prefect-dispatcher-container)), dispatcher 쪽엔 pool 생성 단계가 없습니다.

  **등록에는 dispatcher 정보가 필요 없습니다** — 등록값은 pool 이름·`--type`·base job template 뿐이고, pool 은 dispatcher 와 독립이라 dispatcher 가 0개여도 등록됩니다 (그동안 trigger 된 run 은 `Late` 로 대기). dispatcher 는 나중에 `prefect worker start` 로 그 pool 에 붙습니다 ([§4.2 Container](#42-container)).

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

  - `image` — flow 컨테이너로 쓸 Pipeline Flow 이미지 ([§5.1](#51-image)). 태그 (`pipeline-flow:latest`) 가 곧 **런타임 버전** (라이브러리 + orchestrator) 입니다.
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

  server 안 prefect CLI 로 pool 마다 등록합니다 (`PrefectServer/` 에서 실행; `<Pool Name>`·`<Template File>` 변수화; 코드는 [Appendix E](#appendix-e-register_poolps1)).

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

## 4. Prefect Dispatcher Container

dispatcher (`prefect_dispatcher`) 는 **네 가지 일**을 합니다.

- **job polling** — **server 에 있는 work pool** (큐) 을 polling 해 job 을 가져옵니다.
- **job dispatch** — 가져온 job 을 실행 환경으로 보내 실행합니다.
- **reporting** — 실행 중 상태·로그를 server 에 보고합니다.
- **cleanup** — 실행이 끝나면 정리합니다.

dispatcher 는 **`docker` work pool** 을 polling 해 job 마다 `pipeline_flow` 컨테이너를 띄웠다 정리합니다 — flow 코드는 **그 컨테이너가** 실행하고 dispatcher 자신은 실행하지 않습니다. 이 스택의 `high_performance`·`low_performance` 는 [§3](#work-pool-registration) 에서 `--type docker` 로 등록합니다.

준비물은 **dispatcher compose** 하나입니다 — base job template 등록은 server [§3](#3-prefect-server-container), Pipeline Flow 이미지는 [§5](#5-pipeline-flow-container) 입니다.

### 4.1 Image

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

### 4.2 Container

  dispatcher 는 호스트 도커 소켓을 마운트해 `pipeline_flow` 컨테이너를 띄웁니다.

  #### Yaml

  ```yaml
  # docker-compose.dispatcher.yml
  name: prefect-dispatcher   # compose project name baked in (replaces -p); run_dispatcher.ps1 relies on it
  services:
    prefect_dispatcher:
      image: prefect-dispatcher:latest   # built once from Dockerfile.dispatcher (prefect + prefect-docker)
      env_file:
        - ../docker-compose.env       # PREFECT_API_URL (shared, at Docker/Prefect root)
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
  - `command` — `prefect worker start` 만 합니다. prefect·prefect-docker 는 **이미지에 구워져** 있고 `PREFECT_API_URL` 은 env_file 이 주므로, 부팅 때 설치·export 가 없습니다 (`bash -c` 도 불필요). `--type docker` 로 docker worker 임을 고정하고, `--no-create-pool-if-not-found` 로 **없는 pool 을 자동 생성하지 않습니다** (오타 이름이 들어와도 process pool 이 몰래 생기지 않고 오류로 멈춤; pool 은 server [§3](#3-prefect-server-container) 가 이미 등록). `WORK_POOL`·`WORKER_LIMIT` 는 `docker compose up` 시 셸에서 읽는 변수입니다.
  - `--limit` 은 이 dispatcher 가 **동시에 띄우는 컨테이너 수의 상한** 입니다 (동시성 세 층은 [§3 Work Pool Registration](#work-pool-registration) 의 여러 pool 표 참고).

  #### Execution Command

  `PrefectDispatcher/` 에서 실행합니다.

  ```powershell
  .\run_dispatcher.ps1 -WorkPool <tier>
  ```

  - `run_dispatcher.ps1 -WorkPool <tier>` (코드는 [Appendix F](#appendix-f-run_dispatcherps1)) — yaml 을 띄웁니다 (머신마다 1회).
  - `-WorkPool <tier>` — 이 dispatcher 가 붙을 work pool 등급입니다 (예: `high_performance`).
  - **pool 검증** — 기동 전에 server 에 등록된 **docker 타입** work pool 목록과 대조해, 없는 이름이면 목록을 번호로 보여주고 그중에서 고르게 합니다 (오타·미등록 pool, 그리고 자동 생성된 process pool 까지 걸러 헛도는 것을 막습니다). 조회는 host 의 `prefect` CLI (`work-pool ls --output json`) 로 합니다.
  - `docker compose up` (스크립트 내부) — 컨테이너가 뜨면 그 `command` 인 `prefect worker start` 가 컨테이너 안에서 실행됩니다.

  **머신마다 실행** — 같은 compose 를 각 컴퓨터에서 자기 등급 `WORK_POOL` 로 띄웁니다. pool 이 server 에 이미 있으니 (§3) dispatcher 는 polling 만 하며, 등급별 첫 머신/추가 머신 구분이 없습니다.

  worker 가 뜨는 **그 순간** server 에 자기를 알리며 (heartbeat 시작) 해당 work pool 에 **자동 등록**됩니다 — **polling 시작 = 등록** 이라 별도 절차가 없습니다. heartbeat 가 끊기면 잠시 뒤 **OFFLINE** 으로 바뀝니다 (dispatcher 등록은 deployment 등록과 별개).

  > **보안 주의** — 도커 소켓 마운트는 dispatcher 에 호스트 도커 전체 제어권 (사실상 root) 을 줍니다. 신뢰된 내부망·스터디 용도로 한정하고, 더 강한 격리는 Kubernetes work pool 을 고려합니다 ([Appendix H](#appendix-h-orchestrator-benchmarking)).

### 4.3 Scaling

  **처리량·확장** — `--limit` 을 키우거나, **다른 머신에서 dispatcher 를 더 띄워 같은 pool 에 붙입니다** (그 머신은 `docker-compose.env` 의 `PREFECT_API_URL`=`http://<server IP>:4200/api`, `docker-compose.dispatcher.yml` 의 `networks:` 블록 제거). 여러 dispatcher 는 같은 prefect server 에 있는 pool 의 큐를 나눠 가집니다.

### 4.4 Verification

  dispatcher 가 ONLINE 인지 확인합니다 (pool 등록 확인은 [§3 Work Pool Registration](#work-pool-registration)).

  ```powershell
  prefect work-pool inspect high_performance
  ```

  `inspect` 의 `status` 가 `READY` 면 그 pool 을 polling 하는 dispatcher 가 1개 이상 떠 있다는 뜻입니다 — pool 단위 간접 확인입니다. **어느 dispatcher 가 ONLINE 인지**·마지막 heartbeat 는 UI 의 Work Pools → 해당 pool → **Workers 탭** 에서 봅니다 ([§8](#8-prefect-ui)).

## 5. Pipeline Flow Container

Pipeline Flow 는 dispatcher 가 job 마다 띄우는 per-flow 컨테이너입니다. dispatcher 하나가 동시 job 수만큼 **여러 개 (n 개)** 를 띄우며 (상한 `--limit`, 현재 8), 각 컨테이너는 독립입니다. 세 가지를 다룹니다 — 컨테이너가 쓰는 **이미지** ([§5.1](#51-image)), 그 이미지로 무엇을 실행할지 server 에 등록하는 **deployment** ([§5.2](#52-deployment)), 컨테이너 안에서 generic flow orchestrator 역할을 하는 `pipeline.py` ([§5.3](#53-pipelinepy)). dispatcher 자신은 flow 를 실행하지 않으므로 flow 는 **별도 이미지** 를 쓰며 ([§4.1](#41-image)), 팀 라이브러리는 이 flow 이미지에만 둡니다. 실행이 server UI 에 어떻게 보이는지는 [§8](#8-prefect-ui) 입니다.

### 5.1 Image

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

  **GPU** — 이 이미지로 GPU 를 쓰려면 `requirements.txt` 의 torch 를 CUDA 휠로 설치합니다 (CUDA 런타임이 휠에 번들되어 호스트 드라이버만 맞으면 동작). 더해 호스트에 NVIDIA 드라이버·nvidia-container-toolkit 을 두고, base job template 에서 GPU 를 요청합니다 ([§3 Work Pool Registration](#work-pool-registration)). 드라이버와 CUDA 버전이 안 맞으면 베이스 이미지를 `nvidia/cuda` 계열로 바꿉니다. GPU job 은 무거우므로 그 등급 dispatcher 의 `--limit` 을 1–2 로 낮춰 동시 실행을 제한합니다.

### 5.2 Deployment

  server 에 deployment 를 관리자가 1회 등록합니다. Deployment 는 yaml 로 entrypoint, work pool, pipeline flow image 를 정의합니다. 팀원이 작성하는 학습 스크립트 (`my_flow.py`) 와는 무관합니다.

  #### Yaml

  ```yaml
  # pipelineflow-high.yml - high-tier deployment definition
  deployments:
    - name: pipelineflow-high
      entrypoint: pipeline.py:pipeline       # <file>:<@flow function>
      work_pool:
        name: high_performance
        job_variables:
          image: pipeline-flow:latest
      parameters:
        payload: my_flow.py
  ```

  - `name: pipelineflow-high` — deployment 이름입니다 (등급별로 `pipelineflow-high`·`pipelineflow-low`).
  - `entrypoint: pipeline.py:pipeline` — 실행할 flow 를 `<파일>:<@flow 함수>` 로 가리킵니다 (어떻게 `pipeline.py` 가 되는지는 [§5.3](#53-pipelinepy)).
  - `work_pool.name: high_performance` — 이 deployment 가 제출될 work pool 입니다.
  - `job_variables.image: pipeline-flow:latest` — flow 를 띄울 이미지입니다 ([§5.1](#51-image)). 이 `job_variables` 블록은 `work_pool.name` 으로 등록된 work pool 의 **base job template 을 override** 합니다. `job_variables.image` 는 `job_configuration.image` 를 override 합니다 ([§3](#work-pool-registration)).
  - `parameters.payload: my_flow.py` — flow 파라미터 기본값입니다 (`git_repo`·`git_commit_hash`·`minio_key`·`member` 는 trigger 때 줍니다).

  `job_variables.image` 가 base job template 을 덮어쓰는 흐름 — template 은 `image` 변수 (기본값 `pipeline-flow:latest`) 를 선언하고 `job_configuration` 에서 `"image": "{{ image }}"` 로 받습니다. job 제출 때 Prefect 가 그 `{{ image }}` 자리를 채우는데, deployment 에 `job_variables.image` 가 있으면 **템플릿 `default` 대신 이 값** 이 들어가 컨테이너가 그 이미지로 뜹니다 (`cpu`·`mem_limit`·`env` 등 다른 변수도 같은 방식; 우선순위 `job_variables` > `default` 는 [§3](#work-pool-registration)).

  #### Execution Command

  `prefect deploy` 는 yaml 정의를 server 에 등록합니다.

  ```powershell
  cd PipelineFlow                                      # the folder with pipeline.py and pipelineflow-high.yml
  $env:PREFECT_API_URL = "http://localhost:4200/api"   # on another machine, http://<server IP>:4200/api
  prefect deploy --prefect-file pipelineflow-high.yml --name pipelineflow-high --no-prompt
  ```

  - `prefect CLI --prefect-file` — 정의 파일.
  - `prefect CLI --name` — 등록할 deployment.
  - `prefect CLI --no-prompt` — 대화형 질문을 끄고 yaml 정의대로 등록합니다 (이미지 빌드·스케줄 프롬프트 안 뜸).

  이 등록은 **제어 노드 호스트 셸 (컨테이너 밖) 에서 관리자가** 실행합니다 — `prefect` 가 깔린 곳에서 `PREFECT_API_URL` 을 server 로 두고 돌립니다. `prefect deploy` 는 DB 에 직접 쓰지 않고 server API 로 등록을 보냅니다 (server 가 Postgres `prefect` DB 에 저장). 등급마다 `pipelineflow-high`·`pipelineflow-low` yaml 로 두 벌 등록합니다.

  #### Verification

  deployment 이 server 에 등록됐는지 확인합니다.

  ```powershell
  prefect deployment ls
  prefect deployment inspect "pipeline/pipelineflow-low"
  ```

  `deployment ls` 결과물 예시 — `pipeline/pipelineflow-low` 가 `low_performance` pool 로 등록된 모습:

  ```text
                                       Deployments
  ┌───────────────────────────┬──────────────────────────────────────┬─────────────────┐
  │ Name                      │ ID                                   │ Work Pool       │
  ├───────────────────────────┼──────────────────────────────────────┼─────────────────┤
  │ pipeline/pipelineflow-low │ a1b2c3d4-5e6f-7081-92a3-b4c5d6e7f809 │ low_performance │
  └───────────────────────────┴──────────────────────────────────────┴─────────────────┘
  ```

### 5.3 pipeline.py

  orchestrator (`pipeline.py`) 는 **"커밋 받아 → 팀원 코드 실행"** 만 하는 얇은 python 골격 (`@flow` 함수) 으로, [§5.1](#51-image) 이미지에 구워집니다. 관리자가 관리하는 스크립트이며 팀원이 작성하지 않습니다 — 팀원은 자기 학습 스크립트 (`my_flow.py` 등) 만 작성해 `payload` 파라미터로 지정합니다.

  ```python
  # pipeline.py — orchestrator; Prefect runs this as the deployment entrypoint.
  import os
  import shutil
  import subprocess
  import tempfile
  import boto3
  from prefect import flow, get_run_logger
  from prefect.blocks.core import Block
  from prefect.blocks.fields import SecretDict

  __version__ = "0.0.15"  # Semantic Versioning:  Version = Major.Minor.Patch

  class Credentials(Block):                          # ONE block holds everything as nested dicts; values hidden
      minio: SecretDict                              # endpoint, access_key, secret_key
      postgresql_catalog: SecretDict                 # endpoint, username, password, database
      postgresql_optuna: SecretDict                  # endpoint, username, password, database

  @flow(name="pipeline", flow_run_name="{member}@{git_commit_hash}")                                          # run name shows whose run (e.g. alice@a1b2c3d)
  def pipeline(git_repo: str, git_commit_hash: str, minio_key: str, minio_bucket: str = "datasets",
                member: str = "", payload: str = "my_flow.py"):
      log    = get_run_logger()                                                                          # writes to this run's UI logs
      base   = tempfile.mkdtemp(prefix="run-")                                                           # per-run temp dir (removed in finally)
      repo   = os.path.join(base, "repo")                                                                # git database (.git + the fetched commit)
      script = os.path.join(base, "script")                                                              # worktree: team repo snapshot at the commit
      data   = os.path.join(base, "data")                                                                # MinIO download target
      try:
          subprocess.run(["git", "init", repo], check=True)                                              # git init creates repo/ (no mkdir needed)
          subprocess.run(["git", "-C", repo, "remote", "add", "origin", git_repo], check=True)
          subprocess.run(["git", "-C", repo, "fetch", "--depth", "1", "origin", git_commit_hash], check=True)  # just that commit (shallow; no history)
          subprocess.run(["git", "-C", repo, "worktree", "add", "--detach", script, git_commit_hash], check=True)  # expand the commit into script/ (clean worktree)

          os.makedirs(data, exist_ok=True)                                                              # git didn't create data/
          minio = Credentials.load(member).minio.get_secret_value()                                    # this run's member -> their block, minio section (§6)
          s3 = boto3.client("s3", endpoint_url=minio["endpoint"],
                            aws_access_key_id=minio["access_key"],
                            aws_secret_access_key=minio["secret_key"])
          local = os.path.join(data, os.path.basename(minio_key))                                        # e.g. data/Bennelong Point
          s3.download_file(minio_bucket, minio_key, local)                                               # bucket/key → data/ (latest; pick a version by its key path)

          subprocess.run(["python", payload,                                                             # run the team's payload in script/
                          "--git_repo", git_repo, "--git_commit_hash", git_commit_hash,                           # run identity, passed as CLI args
                          "--member", member, "--data", data], cwd=script, check=True)                     # stdout/stderr stream to this run's logs
      except subprocess.CalledProcessError as e:                                                         # payload exited non-zero (crashed)
          log.error(f"payload {payload} crashed (exit {e.returncode}) for {member}@{git_commit_hash}: {e}")   # tag the failure with whose run + message
          raise                                                                                          # re-raise → run marked Failed, logs kept in the UI
      finally:
          shutil.rmtree(base, ignore_errors=True)                                                        # one cleanup removes script/ + data/
  ```

  - **자유로운 코드** — `payload` 로 팀원이 자기 스크립트를 지정하므로 코드를 정해진 틀에 맞출 필요가 없습니다. 입력은 CLI 인자 (`--git_repo`·`--git_commit_hash`·`--member`·`--data`) 로 받으므로, 팀원 스크립트는 `argparse` 로 그 값만 읽으면 됩니다.
  - **데이터 이력** — `minio_bucket`·`minio_key` 가 **flow 파라미터** 라서 Prefect 가 run 마다 입력값을 `prefect` DB 에 자동 저장합니다 (어느 버킷·객체를 썼는지 lineage 로 남습니다).
  - **crash 확인** — payload 가 0 이 아닌 코드로 끝나면 `subprocess.run(check=True)` 가 `CalledProcessError` 를 던지고, `pipeline` 가 `member@commit` 을 단 에러를 run 로그에 남긴 뒤 다시 raise 해 run 이 **Failed** 로 표시됩니다. payload 의 stdout·stderr 는 실행 중 이 run 의 로그로 흘러 들어가므로, 팀원은 자기 이름이 붙은 run (`alice@a1b2c3d`) 의 **Logs** 에서 crash 원인을 봅니다. payload 가 `@task` 를 쓰면 자기 flow run ([§8](#8-prefect-ui)) 에서 **어느 단계** 가 깨졌는지까지 보입니다.
  - **이력 자동 저장** — `@flow` 진입 시 Prefect 가 run 의 상태·로그·파라미터를 자동 기록합니다. 지표·모델은 팀원 코드가 MLflow 로 로깅하면 함께 남습니다 ([Appendix I](#appendix-i-prefect-task)).

  [§5.2](#52-deployment) 의 deployment 가 entrypoint 를 **`pipeline.py:pipeline`** 로 가리킵니다. 이 문자열은 server 의 deployment 레코드 (`prefect` DB) 에 저장되고, dispatcher 가 띄운 컨테이너 안에서 Prefect 런타임이 이미지 작업 디렉터리 (`/work`, `Dockerfile.pipeline_flow` 가 `pipeline.py` 를 COPY 한 곳) 기준으로 `pipeline.py` 를 import 해 콜론 뒤 **`@flow` 함수 `pipeline`** 을 run 파라미터 (`git_repo`·`git_commit_hash`·`minio_key`·`minio_bucket`·`member`·`payload`) 와 함께 호출합니다. 그래서 deployment entrypoint 가 곧 이 `pipeline.py` 입니다.

  `pipeline` 함수에 전달한 run 파라미터 **값** 은 **trigger 할 때** 지정합니다 — trigger 주체는 보통 **팀원** (또는 스케줄·automation) 입니다. 팀원이 자기 머신·CI 에서 CLI `prefect deployment run "pipeline/pipelineflow-high" -p git_repo=… -p git_commit_hash=… -p minio_key=… -p member=…` 을 실행하거나 (CLI 는 [Appendix B](#appendix-b-prefect-cli)), server UI 의 Run 폼, 스케줄·automation, 또는 `run_deployment(name, parameters={…})` 로 ([§7.2](#72-python-sdk)) trigger 합니다.

  `pipeline.py` 가 **`pipeline_flow` 컨테이너 안에서** run 마다 만드는 폴더 구조입니다 (끝나면 통째로 삭제 — 컨테이너 자체가 일시적이라 함께 사라집니다).

  ```text
  /tmp/run-<rand>/                 # per-run temp dir (base; removed after the run)
  ├─ repo/                         # git init + fetch --depth 1 origin <git_commit_hash> (shallow git db)
  ├─ script/                       # git worktree add --detach script <git_commit_hash> (clean worktree at the commit)
  │  ├─ my_flow.py                 # payload — the team's entry (run: python my_flow.py --data ../data ...)
  │  └─ ...                        # the rest of the team repo at <git_commit_hash>
  └─ data/                         # MinIO download target (bucket/key → here)
     └─ <object>                   # e.g. Bennelong Point
  ```

  - **팀원별 repo** — `git_repo` 가 **flow 파라미터** 라 deployment 마다 다른 repo 를 기본값으로 등록할 수 있습니다. 팀원은 각자 repo·커밋을 쓰고, run 마다 사설 `script/` 에 펼쳐져 서로 간섭하지 않습니다. Prefect 가 `git_repo`·`git_commit_hash` 을 run 파라미터로 자동 기록해 재현·lineage 가 남습니다.
  - **데이터 준비** — `pipeline.py` 가 MinIO 에서 `minio_bucket`/`minio_key` 객체를 `data/` 로 미리 내려받고 `--data` 로 경로를 넘깁니다. 접속 자격증명 (그 팀원 블록의 `minio` 섹션) 은 [§6](#6-credentials) 의 Credential Blocks 로 받습니다. 팀원 코드는 자격증명·다운로드를 각자 짤 필요 없이 `--data` 폴더의 파일을 읽기만 하면 됩니다 (`pipeline.py` 가 `boto3` 로 받으므로 flow 이미지에 `boto3` 가 있어야 합니다 — [§5.1](#51-image)).

## 6. Credentials

설정 값은 **세 곳** 으로 나뉘고 서로 겹치지 않습니다 — ① server·dispatcher 인프라 값 (backend DB·Control Node 주소) 은 `docker-compose.env`, ② `pipeline_flow` 컨테이너의 **기동·연결 설정** (`PREFECT_API_URL`·`mem_limit` 등, 비밀 아님) 은 **base job template** (§3), ③ **run 코드용 자격증명** (MinIO·DB) 만 **Prefect Secret** 입니다. 따라서 base job template 에 적은 값 (`PREFECT_API_URL` 등) 은 **Secret 에 넣지 않습니다** (비밀이 아니고 `docker inspect` 로 보여도 무방). dispatcher 는 자격증명을 들지 않습니다.

### docker-compose.env

  **server·dispatcher 용 값** (backend DB URL·Control Node 주소) 은 `docker-compose.env` 한 파일에 모읍니다.

  ```dotenv
  # docker-compose.env_example  (every value is a placeholder — never expose real values)

  # -- prefect-server --
  PREFECT_SERVER_DATABASE_CONNECTION_URL=postgresql+asyncpg://CHANGE_ME:CHANGE_ME@postgres:5432/prefect

  # -- prefect-dispatcher --
  # The Prefect server API the dispatcher connects to. Use service name prefect_server on the same host,
  # or the host IP/hostname on another machine (then remove the networks block in the dispatcher compose).
  PREFECT_API_URL=http://prefect_server:4200/api
  ```

  - server 는 `postgres` 서비스명으로 backend 에 접속하므로 URL 호스트가 `postgres` 입니다.
  - dispatcher 는 코드를 실행하지 않아 MinIO·카탈로그 자격증명이 필요 없습니다 — 그 값들은 아래 Credential Blocks 에서 다룹니다.

### Credential Blocks

  코드가 **MinIO** 와 PostgreSQL 의 `catalog`·`optuna` DB 에 접속할 자격증명을 **한 블록** 에 모읍니다 — `minio`·`postgresql_catalog`·`postgresql_optuna` 세 묶음을 셋으로 쪼개지 않고 한 블록의 **nested dict** 로 담고, 비밀 값은 `SecretDict` 로 가립니다. server 에 한 번 저장하면 컨테이너·머신마다 따로 넣지 않아도 됩니다.

  블록 클래스는 `Credentials` **하나** (`minio`·`postgresql_catalog`·`postgresql_optuna` 세 `SecretDict` 필드) 이고, **블록 이름은 팀원 이름** 입니다 — 팀원마다 자기 이름의 블록을 하나 갖습니다 (예시 `Jason` 은 팀원 이름). **`pipeline.py`** 와 **`catalog.py`** (모든 팀원이 쓰는 공통 라이브러리) 가 같은 클래스를 정의해 쓰므로 한쪽 `save`, 다른 쪽 `load` 가 맞물립니다. 코드는 run 의 팀원 이름으로 `Credentials.load(<member>)` 해 그 팀원의 자격증명을 받습니다.

  ```text
  Jason                       # block name = a team member's name (e.g. Jason); load it -> everything
  ├─ minio              : endpoint, access_key, secret_key
  ├─ postgresql_catalog : endpoint, username, password, database
  └─ postgresql_optuna  : endpoint, username, password, database
  ```

  팀원별 자격증명을 **JSON 파일** 로 적고 `credentials.py` 로 등록합니다 — 블록 이름은 기본 파일명 (= 팀원) 이고 `--block-name` 으로 덮어쓸 수 있습니다. `credentials.py` 코드는 [Appendix G](#appendix-g-credentialspy).

  `Jason.json`:

  ```json
  {
    "minio": {"endpoint": "http://minio:9000", "access_key": "<MINIO_ACCESS_KEY>", "secret_key": "<MINIO_SECRET_KEY>"},
    "postgresql_catalog": {"endpoint": "postgres:5432", "username": "catalog_user", "password": "<CATALOG_DB_PASSWORD>", "database": "catalog"},
    "postgresql_optuna": {"endpoint": "postgres:5432", "username": "optuna_user", "password": "<OPTUNA_DB_PASSWORD>", "database": "optuna"}
  }
  ```

  ```powershell
  # Register (admin, per member) — PREFECT_API_URL must point at the server.
  python credentials.py --json-path Jason.json                       # block name = file stem "Jason"
  python credentials.py --json-path Jason.json --block-name alice     # explicit block name "alice"
  ```

  `pipeline.py` 는 그 run 의 팀원 블록에서 `minio` 섹션만, `catalog.py` 는 세 섹션을 모두 씁니다 (실제 load 예시는 [§5.3](#53-pipelinepy) 의 `pipeline.py`).

  > flow 컨테이너는 base job template 의 `PREFECT_API_URL` 로 server 에 연결돼야 블록을 받습니다 ([§3 Work Pool Registration](#work-pool-registration)). `mlflow`·`prefect` DB 는 사용자 코드가 직접 접속하지 않으므로, 사용자 role 에는 `catalog`·`optuna` 권한만 있으면 됩니다.

## 7. Job Triggering

등록된 deployment 를 실제로 돌리는 (trigger) 방법은 여러 가지지만, 결국 모두 **server 의 Prefect API 에 "flow run 생성" 요청을 보내는 것**입니다 — 코드가 아니라 **deployment 이름 + 파라미터 값** 만 보냅니다. **trigger 인터페이스 (CLI·SDK) 는 실행 모드와 무관하게 같고**, 실제 실행 주체는 **실행 모드** 가 정합니다 — 이 스택의 **work pool mode** (server 가 run 을 work pool 에 얹고 dispatcher 가 `pipeline_flow` 컨테이너를 띄워 그 안에서 `pipeline(**parameters)` 실행, [§5.3](#53-pipelinepy)) 와 단일 머신 대안인 **serve mode** ([§7.3](#73-serve-mode) · [Appendix C](#appendix-c-execution-architecture)) 입니다. 그래서 아래 §7.1·§7.2 는 두 모드 공통의 trigger 인터페이스이고, §7.3 이 serve mode 의 차이를 다룹니다.

> ⚠️ `pipeline(...)` 함수를 파이썬에서 직접 호출하는 것은 trigger 가 **아닙니다** — server·work pool 을 거치지 않고 그 자리에서 로컬 실행되어 컨테이너 격리·lineage 가 없습니다. 아래 [§7.2](#72-python-sdk) 는 반드시 `run_deployment` 를 말합니다.

| Aspect | Prefect CLI | Python SDK |
|--------|-------------|------------|
| 호출 | `prefect deployment run "<flow>/<deployment>"` | `run_deployment(name=…)` |
| 파라미터 | `-p key=value` (문자열) | `parameters={…}` (파이썬 타입) |
| 반환 | run id 출력 후 종료 | `FlowRun` 객체 |
| 완료 대기 | 기본 안 함 (`--watch` 로 따라감) | 기본 대기 (`timeout=0` 이면 즉시) |
| 주 용도 | 수동·셸·CI 스텝 | 코드 내 자동 trigger·chaining |

### 7.1 Prefect CLI

  사람이 셸에서, 또는 CI 의 한 스텝으로 직접 trigger 합니다. 필요한 것은 그 셸의 `prefect` CLI 와 `PREFECT_API_URL` 설정뿐입니다.

  ```powershell
  prefect deployment run "pipeline/pipelineflow-high" `
    -p git_repo=https://github.com/team/repo.git -p git_commit_hash=a1b2c3d -p minio_key="SYDNEY/Bennelong Point" -p member=alice
  ```

  - **파라미터** — `-p key=value` 로 하나씩 **문자열** 로 줍니다. server 가 `pipeline` 시그니처 스키마로 타입을 변환·검증합니다.
  - **반환·제어** — run 을 만들고 **id 만 출력한 뒤 바로 끝납니다** (완료를 기다리지 않음). 진행을 따라가려면 `--watch` 를 붙입니다.
  - **주 용도** — 사람이 수동으로 한 번, 셸 스크립트, CI/CD 의 한 스텝, 빠른 테스트입니다 (CLI 목록은 [Appendix B](#appendix-b-prefect-cli)).

### 7.2 Python SDK

  다른 파이썬 코드 (앱·서비스·또 다른 flow) 가 프로그램적으로 trigger 합니다.

  ```python
  from prefect.deployments import run_deployment

  flow_run = run_deployment(                                                   # ask the server to create a flow run
      name="pipeline/pipelineflow-high",
      parameters={"git_repo": "https://github.com/team/repo.git",
                  "git_commit_hash": "a1b2c3d", "minio_key": "SYDNEY/Bennelong Point", "member": "alice"},
  )
  print(flow_run.id, flow_run.state)                                          # FlowRun object — id and final state
  ```

  - **파라미터** — `parameters={…}` dict 로, **네이티브 파이썬 타입** (int·bool·list 등) 을 그대로 넘깁니다.
  - **반환·제어** — `FlowRun` **객체** 를 돌려주고, 기본값은 run 이 **끝날 때까지 대기 (poll)** 합니다 (`timeout` 으로 제어, `timeout=0` 이면 즉시 반환). 그래서 상태·결과를 코드로 받아 다음 분기에 씁니다.
  - **주 용도** — flow 안에서 다른 run 을 **자동 trigger** (fan-out·orchestration), 조건부 실행, run 객체를 받아 상태 검사·후속 chaining (A 끝나면 B) 입니다.

### 7.3 Serve Mode

  work pool·dispatcher·이미지 빌드 없이 `pipeline.serve(name=…)` **한 프로세스가 deployment 등록과 실행을 겸하는** 단일 머신·소규모 대안입니다 (`serve()` 는 `@flow` 객체의 메서드라, flow 이름이 `pipeline` 이면 `pipeline.serve(...)` 입니다 — [Appendix C](#appendix-c-execution-architecture)).

  ```python
  # serve mode — one process registers the deployment AND runs it (no work pool / dispatcher).
  from my_flow import pipeline                 # the @flow object
  pipeline.serve(name="pipelineflow-serve")    # long-lived; Ctrl-C to stop
  ```

  - **등록+실행** — `pipeline.serve(...)` 한 줄이 deployment 등록과 실행 프로세스를 겸합니다 (`prefect deploy`·dispatcher·이미지 빌드 불필요).
  - **trigger** — serve 프로세스는 상시 떠 있으므로 **별도 터미널에서** trigger 하며, 방법은 **§7.1·§7.2 와 똑같습니다** (`prefect deployment run "pipeline/pipelineflow-serve"` · `run_deployment(...)`). served 프로세스가 그 run 을 자기 안에서 실행합니다.
  - **차이·적합** — run 마다 컨테이너 격리가 없고, 그 프로세스가 떠 있어야 run 이 돕니다. 다수 팀원·동시 실행·격리가 필요하면 work pool (이 스택) 입니다 ([Appendix C](#appendix-c-execution-architecture)).

## 8. Prefect UI

server 대시보드 (`http://<Host IP>:4200`) 에서 deployment·run·task 가 어떻게 보이는지입니다.

- **Deployments** — `<flow_name>/<deployment_name>` 로 나열됩니다 (예: `pipeline/pipelineflow-high`·`pipeline/pipelineflow-low`). flow 이름은 `@flow(name="pipeline")`, deployment 이름은 yaml 의 `name` 입니다.
- **Flow Runs** — trigger 된 run 이 `flow_run_name` 으로 나열됩니다. `member` 가 들어가 같은 deployment 아래에서 `alice@a1b2c3d` 처럼 **누구의 run 인지** 구분됩니다 ([§5.3](#53-pipelinepy) 의 `flow_run_name`). `pipeline.py` 가 `member`·`git_commit_hash` 을 payload 에 CLI 인자로 넘기므로 팀 flow run 도 같은 이름을 씁니다.
- **Tasks** — 팀 payload 가 단계 (dp·fe·train·test) 를 **`@task`** 로 감싸고 `@flow` 로 묶으면, 컨테이너 env 의 `PREFECT_API_URL` 덕분에 그 subprocess 가 **자기 flow run 과 task** 를 보고해 단계가 보입니다 (orchestrator run 과 **별개 flow run**, subprocess 라 격리 유지 — [Appendix I](#appendix-i-prefect-task)).
- **Parameters · State · Logs** — run 마다 입력 파라미터 (`git_repo`·`git_commit_hash`·`minio_key`·`member`)·상태·로그가 자동 기록되어 (UI 의 Flow Run → Parameters), 같은 파라미터로 재실행 (재현) 할 수 있습니다.

job 하나가 trigger 되면 대시보드에 다음처럼 보입니다.

```text
Deployments
  pipeline/pipelineflow-high     high_performance     # per-tier registration (§5.2)
  pipeline/pipelineflow-low      low_performance

Flow Runs
  pipeline   alice@a1b2c3d   Completed   high_performance     # orchestrator (pipeline.py)
  my_flow    alice@a1b2c3d   Completed                        # team payload (@task), separate run
    ├─ data_prep      Completed
    ├─ feature_eng    Completed
    ├─ train_model    Completed
    └─ test_model     Completed
```

같은 job 이 **flow run 두 개** 로 보입니다 — orchestrator (`pipeline`) 와 팀 payload (`my_flow`). 둘 다 `flow_run_name` 이 `member@commit` 이라 묶어 보기 좋고, 팀 run 아래에 네 단계 task 가 달립니다. 팀 payload 가 plain 스크립트면 `my_flow` run·task 없이 orchestrator run 만 보입니다.

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
  - **어떻게** — `prefect deploy --prefect-file <yaml> --name <name> --no-prompt` (CLI) 가 yaml 정의를 server API 로 보내 DB 에 등록합니다 ([§5.2](#52-deployment)).
  - **사용** — 코드를 다시 안 봐도 이름 `<flow>/<deployment>` 로 run 을 trigger 합니다 (`prefect deployment run "pipeline/pipelineflow-high" -p payload=my_flow.py` · UI · 스케줄). 그러면 dispatcher 가 그 정의대로 `pipeline_flow` 컨테이너를 띄웁니다.
  - 저장된 모습 (`prefect deployment inspect "pipeline/pipelineflow-high"`):

    ```json
    { "name": "pipelineflow-high", "flow_name": "pipeline", "entrypoint": "pipeline.py:pipeline",
      "work_pool_name": "high_performance", "job_variables": { "image": "pipeline-flow:latest" },
      "parameters": { "payload": "my_flow.py" } }
    ```
- **entrypoint** — deployment 가 실행할 flow 를 `<파일>:<@flow 함수>` 로 가리키는 문자열입니다 (예: `pipeline.py:pipeline`). server DB 에 저장되고, 컨테이너 런타임이 이 경로로 모듈을 import 해 그 `@flow` 함수를 run 파라미터와 함께 호출합니다 ([§5.2](#52-deployment)).
- **base job template** — pool 이 띄우는 flow 컨테이너의 공통 설정 (이미지·env·네트워크·메모리 상한 등) 입니다.
- **`PREFECT_API_URL`** — dispatcher·client 가 server API 를 찾는 주소 (`http://<host>:4200/api`) 입니다. 같은 호스트면 host 가 서비스명 `prefect_server` 입니다.

**Abbreviations**

- **AWS** = Amazon Web Services
- **S3** = (Amazon) Simple Storage Service — MinIO 가 호환하는 오브젝트 스토리지 API
- **API** = Application Programming Interface
- **UI** = User Interface (여기서는 Prefect 웹 대시보드)
- **DB** = Database
- **DSN** = Data Source Name — DB 접속에 필요한 정보 (드라이버·계정·호스트·포트·DB 이름) 를 한 줄로 엮은 접속 문자열입니다 (예: `postgresql://user:pass@host:5432/catalog`). 이 스택은 DSN 을 통째로 저장하지 않고 팀원 블록 (이름이 팀원 이름; 예 `Jason`) 의 `postgresql_catalog`·`postgresql_optuna` 섹션 필드 (`endpoint`·`username`·`password`·`database`) 로 `catalog.py` 가 이 문자열을 조립합니다.
- **CPU / GPU** = Central / Graphics Processing Unit

## Appendix B. Prefect CLI

`prefect` CLI 는 Prefect SDK 와 함께 설치되는 명령행 도구 (`pip install prefect`) 입니다. 본문 꼭지별로 묶었습니다.

- **§3 Server·Work Pool**
  - `prefect config set PREFECT_API_URL="http://<Host IP>:4200/api"` — client 가 바라볼 server 주소를 프로필에 1회 저장합니다.
  - `prefect config view` — 현재 활성 프로필의 설정값 (`PREFECT_API_URL` 등) 을 출력합니다. CLI 가 지금 어느 server 를 향하는지 확인합니다.
  - `prefect profile ls` — 프로필 목록을 출력합니다. 등록·조회가 어긋날 때 어떤 프로필 (어떤 `PREFECT_API_URL`) 이 활성이었는지 되짚습니다.
  - `prefect server start --host 0.0.0.0` — Prefect server 를 기동합니다.
  - `prefect work-pool create <name> --type docker --base-job-template <file> [--overwrite]` — `docker` work pool 을 server 에 등록합니다.
  - `prefect work-pool ls [--output json]` — 등록된 work pool 을 표 (또는 JSON) 로 출력합니다 (이름·type·동시성 한도; JSON 은 `run_dispatcher.ps1` 의 pool 검증이 파싱).
- **§4 Dispatcher**
  - `prefect work-pool get-default-base-job-template --type docker` — 도커 dispatcher 의 기본 base job template 을 출력합니다 (§4.1).
  - `prefect worker start --pool <name> [--limit N]` — dispatcher 를 기동해 그 pool 을 polling 하며 job 을 실행합니다 (§4.2).
  - `prefect work-pool set-concurrency-limit <pool> <N>` — pool 전체 동시 실행 상한을 설정합니다 (§4.3).
- **§5 Pipeline Flow**
  - `prefect deploy` (또는 `flow.deploy(...)`) — deployment 를 등록합니다 (§5.2).
  - `prefect deployment run "<flow>/<deployment>" -p <key>=<value>` — 등록된 deployment 를 파라미터와 함께 trigger 합니다 (§5.3).
- **§6 Credentials**
  - `prefect block ls` — server 에 등록된 블록 (`Credentials` 등) 을 표 (ID·Type·Name·Slug) 로 출력합니다. run-code 자격증명 (팀원 블록, 예 `Jason`) 이 등록됐는지 확인합니다 (§6). 블록은 **그 server 의 DB 에 저장** 되므로 server 마다 따로 등록해야 하며, 등록 시점의 `PREFECT_API_URL` 이 가리킨 server 에 들어갑니다.
  - `prefect variable ls` — server 에 등록된 Variable 을 출력합니다. 자격증명을 Secret 블록 대신 Variable 로 넣었는지 확인합니다 (§6).

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

## Appendix D. run_server.ps1

제어 노드에서 Prefect server compose 스택을 띄우는 기동 스크립트입니다 ([§3 Server Setup](#server-setup)). 공유 `mlops` 네트워크가 없으면 만들고 `docker-compose.server.yml` 을 올립니다. work pool 등록은 별도입니다 (`register_pool.ps1` — [Appendix E](#appendix-e-register_poolps1)).

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

## Appendix E. register_pool.ps1

server 에 work pool 을 등록 (또는 갱신) 하는 스크립트입니다 ([§3 Work Pool Registration](#work-pool-registration)).

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

## Appendix F. run_dispatcher.ps1

각 dispatcher 머신에서 dispatcher compose 스택을 띄우는 기동 스크립트입니다 ([§4.2](#42-container)). server 기동과 work pool 등록은 별도입니다 (server 는 [Appendix D](#appendix-d-run_serverps1), pool 은 `register_pool.ps1` — [Appendix E](#appendix-e-register_poolps1)).

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

## Appendix G. credentials.py

팀원별 자격증명 블록을 JSON 으로 등록하는 스크립트입니다 ([§6 Credential Blocks](#credential-blocks)). 블록 이름은 **CLI 인자 > JSON `name` 필드 > 파일명** 순으로 정해집니다 (기본은 파일명 = 팀원). `Credentials` 클래스도 여기서 정의하며 `catalog.py` 가 import 해 씁니다 (`pipeline.py` 는 이미지 자기완결이라 같은 클래스를 따로 inline 정의 — [§5.3](#53-pipelinepy)).

```python
# credentials.py — shared Prefect credential block (Credentials) + JSON register CLI.
#
# Defines the one credential Block used across the stack and registers a team member's block from a
# JSON file. Block name precedence: --block-name > JSON "name" field > file stem.
#
#     python credentials.py --json-path Jason.json                       # block name = file stem "Jason"
#     python credentials.py --json-path Jason.json --block-name alice    # explicit block name "alice"
#
# Separation of concerns: the Prefect folder owns the credential block (this file); PrefectWorkflow's
# catalog.py imports it (`from credentials import Credentials`); pipeline.py keeps its own inline copy
# (baked into the flow image, so it must match this class name + fields). Needs prefect installed and
# the Prefect profile's PREFECT_API_URL pointing at the target server.
import argparse
import json
import os

from prefect.blocks.core import Block
from prefect.blocks.fields import SecretDict

__version__ = "0.0.12"  # Semantic Versioning:  Version = Major.Minor.Patch


class Credentials(Block):              # must match pipeline.py exactly (class name + fields)
    minio: SecretDict                  # endpoint, access_key, secret_key
    postgresql_catalog: SecretDict     # endpoint, username, password, database
    postgresql_optuna: SecretDict      # endpoint, username, password, database


def register(spec_path, name=None):
    """JSON spec 으로 그 팀원의 Credentials 블록을 server 에 save 한다 (이름 우선순위: 인자 > spec['name'] > 파일명)."""
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    name = name or spec.pop("name", None) or os.path.splitext(os.path.basename(spec_path))[0]
    spec.pop("name", None)             # drop "name" if present so it is not passed as a block field
    Credentials(**spec).save(name, overwrite=True)
    print(f"[credentials] saved block '{name}'")


def parse_args(argv=None):
    """CLI 인자를 파싱한다 (--block-name -> args.block_name, --json-path -> args.json_path)."""
    parser = argparse.ArgumentParser(description="Register a team member's Credentials block from a JSON spec.")
    parser.add_argument("--json-path", required=True, help="path to the <member>.json credential spec")
    parser.add_argument("--block-name", default=None, help="block name (default: JSON 'name' field, else file stem)")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    register(args.json_path, args.block_name)
```

## Appendix H. Orchestrator Benchmarking

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

## Appendix I. Prefect @task

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
