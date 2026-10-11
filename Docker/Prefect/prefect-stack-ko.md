# MLOps Prefect Stack
Rev. 632 | Created: 2026-06-13 | Updated: 2026-10-11 01:25 CDT

<img src="assets/prefect-wordmark.png" alt="Prefect" height="100">

> 공식 사이트: [https://www.prefect.io/](https://www.prefect.io/)

- [1. Purpose](#1-purpose)
- [2. Summary](#2-summary)
- [3. Architecture](#3-architecture)
- [4. Installation](#4-installation)
  - [4.1 Installation Sequence](#41-installation-sequence)
  - [4.2 Setup Files](#42-setup-files)
- [5. Network](#5-network)
  - [5.1 Reachability to Backing Service](#51-reachability-to-backing-service)
  - [5.2 Docker Network](#52-docker-network)
  - [5.3 Server Connection](#53-server-connection)
- [6. Docker Registry](#6-docker-registry)
- [7. Credentials](#7-credentials)
  - [7.1 docker-compose.env_example](#71-docker-composeenv_example)
  - [7.2 Credential Blocks](#72-credential-blocks)
- [8. Job Triggering](#8-job-triggering)
- [9. Prefect UI](#9-prefect-ui)
- [Appendix A. Terminology](#appendix-a-terminology)
- [Appendix B. backing_ports.sh](#appendix-b-backing_portssh)
- [Appendix C. credentials.py](#appendix-c-credentialspy)

## 1. Purpose

- **Problem Statement**: Prefect stack 을 server · worker · flow 세 구성요소로 나눠 docker 로 운영하므로, 구성요소마다 설정과 script 가 다른 folder 에 있어 전체 순서와 공통 설정을 한곳에서 보기 어렵습니다.
- **Goal**: 실무자가 이 문서로 stack 의 전체 구성, 설치 순서, 공통 설정 (network · registry · credentials · job trigger) 을 파악하고, 구성요소 문서로 바로 이동할 수 있게 합니다.
- **Non-Goal**: 구성요소별 설정과 script 의 세부는 각 구성요소 문서에, Prefect 의 일반 개념 (실행 구조 · trigger · CLI · `@task`) 은 [prefect-concepts-ko.md](prefect-concepts-ko.md) 에 두고 여기서 다루지 않습니다. Backing service (PostgreSQL · MinIO · MLflow) 의 설치는 다루지 않습니다.

## 2. Summary

이 stack 은 server · worker · flow 세 구성요소로 나뉘고, 구성요소마다 자기 folder 의 문서가 그 파일과 절차를 담습니다. 이 문서는 전체 구성 ([§3](#3-architecture)), 설치 순서 ([§4](#4-installation)), 공통 설정인 network ([§5](#5-network)) · registry ([§6](#6-docker-registry)) · credentials ([§7](#7-credentials)) 와 job trigger ([§8](#8-job-triggering)) 를 다룹니다.

Table 1. Documents of the stack

| Document                                                        | Folder           | Covers                                                        |
| :-------------------------------------------------------------: | :--------------: | :-----------------------------------------------------------: |
| [prefect-server-ko.md](PrefectServer/prefect-server-ko.md)       | `PrefectServer/` | server 기동, work pool 등록, 서비스 주소 Variable              |
| [prefect-worker-ko.md](PrefectWorker/prefect-worker-ko.md)       | `PrefectWorker/` | worker image push, `run_worker.sh`, scaling                    |
| [prefect-flow-ko.md](PrefectFlow/prefect-flow-ko.md)             | `PrefectFlow/`   | flow image push, deployment 등록, `pipeline.py`                |
| [prefect-concepts-ko.md](prefect-concepts-ko.md)                 | `./`             | Prefect 실행 구조, trigger, CLI, `@task`                       |
| [prefect-registry-ko.md](prefect-registry-ko.md)                 | `./`             | docker registry 와 pull policy                                 |
| [prefect-work-queue-ko.md](prefect-work-queue-ko.md)             | `./`             | work queue, priority, 전용 worker                              |
| [prefect-secret-ko.md](prefect-secret-ko.md)                     | `./`             | Prefect Secret block                                           |
| [prefect-stack-troubleshooting-ko.md](prefect-stack-troubleshooting-ko.md) | `./`             | 증상별 원인과 해결                                             |

## 3. Architecture

Prefect stack 을 한 호스트에서 **세 구성요소 (Prefect Server · Prefect Worker · Pipeline Flow)** 로 나눠 도커로 실행합니다. Prefect stack 의 backing service 는 PostgreSQL · MinIO · MLflow 가 있습니다. **AI/ML flow 의 실행은 하나의 python docker 이미지** (`pipeline-flow:latest`) **로만 하고, 그 flow image 는 worker 이미지와 분리** 합니다. job 마다 그 이미지로 **일시적 컨테이너 (ephemeral)** 를 띄웠다 파괴하며, **여러 팀원이 동시에 다수 job 을 trigger** 하는 환경을 전제로 Prefect 의 **Docker work pool** 로 구현합니다.

Prefect work pool 의 type 은 `process` · `docker` · `kubernetes` 가 있는데 ([prefect-concepts-ko.md §3](prefect-concepts-ko.md#3-execution-architecture)), 이 스택은 **`docker`** 를 씁니다 — flow 를 worker 와 **분리된 별도 컨테이너** 에서 실행하기 위함입니다. 이 stack 이 Prefect 를 고른 까닭은 flow 를 평범한 python 으로 짜면서 run 마다 격리된 컨테이너로 동적으로 띄우는 구성이 자연스럽기 때문입니다.

Prefect server (`prefect_server`) 는 job 을 수집·스케줄링하는 **단일 진입점** 입니다. 단 **코드는 실행하지 않습니다** — 실행은 항상 Pipeline Flow 컨테이너 안에서 일어납니다.

기본 구성은 한 호스트에서 공유 네트워크 `mlops` 로 묶입니다. `prefect_server` 와 `prefect_worker` 가 상시 떠 있고, job 마다 **`pipeline_flow` 컨테이너** 가 일시적으로 실행됩니다. Work pool 은 server 에 등록된 메타데이터입니다 (컨테이너가 아닙니다).

Table 2. Components of the stack

| Component | Prefect term | Role | Lifetime |
| :---: | :---: | :---: | :---: |
| **Prefect Server** | server | job 수집·스케줄링·UI·**work pool 등록**.<br>실행 파라미터를 entrypoint 에 전달.<br>코드는 실행하지 않습니다. | 상시 |
| **Prefect Worker** | worker | pool 을 polling 해 job 마다<br>`pipeline_flow` 컨테이너를 띄웁니다.<br>코드는 실행하지 않습니다. | 상시 |
| **Pipeline Flow** | execution unit | flow (코드) 가 실행되는 곳입니다.<br>job 마다 뜨는 전용 일시적 컨테이너입니다. | 일시적 |

**구성 수 (cardinality)** — server 를 정점으로 부채꼴로 퍼집니다.

- **server = 1** — 중앙 진입점입니다.
- **pool / server = n_pool** (n_pool ≥ 1) — 라우팅 구분마다 1개입니다.
- **worker / pool = n_worker** (n_worker ≥ 1) — worker 하나는 pool 하나를 polling 합니다.
- **flow / worker = n_flow** — 동시 실행 시 1 ≤ n_flow ≤ limit (= 8), 유휴 시 0입니다.

**성능 등급별 pool 예시 (2 pools · worker 마다 flow 2개):**

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
      |  worker L1   |               +--------------+          +--------------+
      |  (machine 1) |               |  worker H1   |          |  worker H2   |
      +------+-------+               +------+-------+          +------+-------+
         |       |                      |       |                 |       |
         v       v                      v       v                 v       v
      +----+  +----+                 +----+  +----+            +----+  +----+
      |flow|  |flow|                 |flow|  |flow|            |flow|  |flow|
      +----+  +----+                 +----+  +----+            +----+  +----+
```

<a id="fig-1"></a>
Fig 1. Two pools by performance tier, two flows per worker

- **pool = 라우팅 라벨** — server 가 run 을 `work_pool_name` 으로 해당 등급 pool 에 보냅니다 (pool 은 큐일 뿐 컨테이너가 아닙니다).
- **worker = 머신마다 1개** — 각 컴퓨터가 자기 등급 pool 의 worker 를 띄웁니다. 한 등급에 머신이 여럿이면 그 pool 에 worker 가 여럿 붙어 큐를 나눕니다 (위 그림: high 는 2대 → worker 2개).
- **worker 마다 flow 여럿** — 각 worker 가 `--limit` 까지 pipeline_flow 컨테이너를 동시에 띄웁니다 (그림은 2개씩).
- **deployment = 등급별 등록** — **deployment** (flow 를 어떤 pool·파라미터로 실행할지 server 에 등록한 실행 정의) 은 pool 하나에 바인딩되므로, 같은 flow 를 등급마다 등록해 (`pipeline/high_deployment`·`pipeline/low_deployment`) job 을 보낼 등급을 고릅니다 (등록 방법은 [prefect-flow-ko.md §4](PrefectFlow/prefect-flow-ko.md#4-deployment)).

각 서비스의 역할입니다.

Table 3. Backing services and their endpoints

| Service | Endpoint | Role |
| :---: | :---: | :---: |
| `postgres` | `:5432` | Metadata DB · `prefect`/`mlflow`/`optuna`/`catalog` 4 논리 DB |
| `minio` | `:9000` (S3 API) · `:9001` (console) | Object storage · `datasets`/`models`/`mlflow` 3 buckets |
| `mlflow` | `:5000` | 실험 추적 + 모델 레지스트리 · backend `postgres` · artifact `minio` |
| `prefect_server` | `:4200` | Prefect server + 대시보드 (UI) · backend `postgres` |
| `prefect_worker` | — | job polling · dispatch · reporting · cleanup |
| `registry` | `:12357` | Worker image · flow image 저장소 (HTTP) · [§6](#6-docker-registry) |

> `postgres`·`minio`·`mlflow`·`registry` 는 각자 폴더의 compose 로 띄웁니다. 이 문서는 **Prefect server·worker 와 `pipeline_flow` 이미지** 에 집중합니다.

## 4. Installation

설치는 **2 routings** (docker · pool) + **3 dockers** (server → worker → pipeline_flow) 입니다. [Installation Sequence](#41-installation-sequence) 가 설치 순서와 단계별 configuration 을, [Setup Files](#42-setup-files) 가 구성요소별 파일과 실행 명령을 정리합니다.

### 4.1 Installation Sequence

  2 routings (docker · pool) + 3 dockers 의 설치 순서와, 각 단계가 요구하는 configuration 입니다 (파일 전체와 실행 명령은 아래 [Setup Files](#42-setup-files)).

  ```text
  NETWORK ── docker network create mlops          # routing 1 — docker routing: container ↔ container
             shared external network; all 3 dockers attach by service name

  ══ DOCKER 1 ── PREFECT SERVER ════════════════════════════════════════════
     dir    : PrefectServer/
     files  : docker-compose.server.yml · run_server.sh · register_pool.sh
              docker-pool-template-high.json · docker-pool-template-low.json
              Dockerfile.pruner · prune_loop.sh
     run    : run_server.sh                       # in PrefectServer/: create network + compose up -d
     config → ../docker-compose.env
              PREFECT_SERVER_DATABASE_CONNECTION_URL = <POSTGRESQL_IP>:5432/prefect
              PREFECT_API_URL                        = http://<server IP>:4200/api   # UI inherits this
       │
       └─ Work Pool Registration ── register_pool.sh    # routing 2 — pool routing: run → pool (once, after server up)
          config → base job template (docker-pool-template-{high,low}.json)
                   image    = pipeline-flow:latest
                   env      = { PREFECT_API_URL: http://prefect_server:4200/api }
                   networks = [mlops]   auto_remove = true   mem_limit = 16g | 4g
                   concurrency-limit (pool) = 16 | 8
       ▼
  ══ DOCKER 2 ── PREFECT WORKER ════════════════════════════════════════
     dir    : PrefectWorker/
     files  : Dockerfile.worker · docker-compose.worker.yml · run_worker.sh · push_worker_image.sh
     run    : push_worker_image.sh                  # multi-arch build + push, on the build host, once
              run_worker.sh --work-pool <tier>  # compose pull + up -d, on every worker machine
     config → ../docker-compose.env + shell
              IMAGE_REGISTRY  = <host>:<port>              # registry of the worker image
              PREFECT_API_URL = http://prefect_server:4200/api
              WORK_POOL = high_performance | low_performance
              WORKER_LIMIT = 8 | 4                 # worker --limit
       ▼
  ══ DOCKER 3 ── PIPELINE FLOW ═════════════════════════════════════════════
     dir    : PrefectFlow/
     files  : Dockerfile.pipeline_flow · requirements.txt · pipeline.py · push_flow_image.sh
              high_deployment.yml · low_deployment.yml
     run    : push_flow_image.sh                    # multi-arch build + push, on the build host
              prefect deploy --prefect-file <tier>_deployment.yml --name <tier>_deployment --no-prompt
     config → ../docker-compose.env
              IMAGE_REGISTRY  = <host>:<port>              # registry of the flow image
              deployment parameters ({high,low}-deployment.yml)
              git_repo · git_commit_hash · minio_key · minio_bucket · submitter · payload
       │
       └─ Credential blocks (admin, once)         # Credentials blocks on server; needed before first run
          files  : credentials.py · <name>.json (e.g. yrocket.json)
          run    : python credentials.py --json-path yrocket.json --block-name yrocket   # block name = any lowercase id
          config → run-code credentials (one or more blocks, nested)
                   <name> { minio · postgresql_catalog · postgresql_optuna }   # block name = any lowercase id (not tied to a person)

  shared : docker-compose.env                      # at Docker/Prefect/ root; server & worker read ../docker-compose.env
  ```

  <a id="fig-2"></a>
  Fig 2. Installation sequence and the configuration of each step

  > 전제 — 이 3 docker 앞에 **PostgreSQL → (MinIO/MLflow)** 가 먼저 떠 있어야 합니다. `docker-compose.env` 의 DB URL 과 Secret 의 MinIO 키가 그 스택을 가리키므로, 각 폴더 compose 로 먼저 띄웁니다 (이 문서 범위 밖).

### 4.2 Setup Files

  설치 파일은 세 구성요소 + 자격증명 + 공유 env 로 나뉩니다. 각 묶음의 파일과 실행 명령을 함께 적습니다.

  1) **[PREFECT SERVER](PrefectServer/prefect-server-ko.md)** — 제어 노드 1대 · 공식 이미지라 빌드 없음

     ```
     PrefectServer/
     ├─ docker-compose.server.yml      server container definition (port 4200)
     ├─ run_server.sh                  start: create network + compose up
     ├─ register_variables.sh          register backing-address variables (once, after the server is up)
     ├─ register_pool.sh               register work pools (once, after the server is up)
     ├─ Dockerfile.pruner              worker_pruner sidecar image (bakes prune_loop.sh + curl + jq)
     ├─ prune_loop.sh                  worker_pruner sidecar loop (prunes OFFLINE worker records)
     ├─ docker-pool-template-high.json   high-tier base job template (mem_limit 16g · = flow container settings)
     └─ docker-pool-template-low.json    low-tier base job template (mem_limit 4g)
     ```

     <a id="fig-3"></a>
     Fig 3. Files of PrefectServer

     Run (from `PrefectServer/`):

     ```bash
     ./run_server.sh --yaml docker-compose.server.yml --network mlops
     ./register_variables.sh --minio http://<MINIO_IP>:9000 --postgresql <POSTGRESQL_IP>:5432 --mlflow http://<MLFLOW_IP>:5000
     ./register_pool.sh --pool-name high_performance --template-file docker-pool-template-high.json --concurrency-limit 16
     ./register_pool.sh --pool-name low_performance --template-file docker-pool-template-low.json  --concurrency-limit 8
     ```

  2) **[PREFECT WORKER](PrefectWorker/prefect-worker-ko.md#2-role)** — 작업 머신마다 1대 · image 는 registry 에서 받음

     ```
     PrefectWorker/
     ├─ Dockerfile.worker          image recipe (python + prefect + prefect-docker)
     ├─ docker-compose.worker.yml  container definition (mounts docker.sock)
     ├─ run_worker.sh              start: compose pull + up
     └─ push_worker_image.sh       multi-arch build + push of the worker image
     ```

     <a id="fig-4"></a>
     Fig 4. Files of PrefectWorker

     Run (from `PrefectWorker/`):

     ```bash
     # on the build host, once per Dockerfile change
     ./push_worker_image.sh
     # on every worker machine; pulls the image from IMAGE_REGISTRY
     ./run_worker.sh --work-pool high_performance --worker-limit 8
     ./run_worker.sh --work-pool low_performance --worker-limit 4
     ```

  3) **[PIPELINE FLOW](PrefectFlow/prefect-flow-ko.md#2-role)** — job 마다 떴다 사라지는 컨테이너 · image 는 registry 에서 받음

     ```
     PrefectFlow/
     ├─ Dockerfile.pipeline_flow       flow image recipe (FROM python:3.11.15)
     ├─ .dockerignore                  build context = requirements.txt + pipeline.py only
     ├─ requirements.txt               team libraries (torch · mlflow · optuna …)
     ├─ pipeline.py                    orchestrator (copied into the image)
     ├─ push_flow_image.sh             multi-arch build + push of the flow image
     └─ {high,low}-deployment.yml    deployment definitions (admin registers once)
     ```

     <a id="fig-5"></a>
     Fig 5. Files of PrefectFlow

     Run (from `PrefectFlow/`):

     ```bash
     ./push_flow_image.sh   # on the build host, after a change to the Dockerfile, requirements.txt or pipeline.py
     prefect deploy --prefect-file high_deployment.yml --name high_deployment --no-prompt   # register a deployment (host shell, once; repeat for low_deployment)
     ```

  4) **[Credentials](#7-credentials)** — 자격증명 블록 (admin · 블록마다 1회) · `Docker/Prefect/` 루트

     ```
     credentials.py                    Credentials block class + JSON register CLI (Appendix C)
     <name>.json                       credential JSON (e.g. yrocket.json)
     ```

     <a id="fig-6"></a>
     Fig 6. Credential files at the Docker/Prefect root

     Run (from `Docker/Prefect/`, `PREFECT_API_URL` → server):

     ```bash
     python credentials.py --json-path yrocket.json --block-name yrocket     # save a block named "yrocket" (lowercase)
     ```

  - **공유** — `Docker/Prefect/` 루트에 두고 server·worker compose 가 `../docker-compose.env` 로 읽음

     ```
     docker-compose.env             credentials · PREFECT_API_URL   (Docker/Prefect/ root)
     ```

     <a id="fig-7"></a>
     Fig 7. Shared env file at the Docker/Prefect root

## 5. Network

이 스택은 여러 머신에 걸쳐 있어, 통신이 되려면 두 가지가 갖춰져야 합니다 — ① 원격 backing service 포트가 방화벽 너머로 **도달 가능**해야 하고, ② 컨테이너를 띄우는 **각 호스트**에 로컬 docker network `mlops` 가 있어야 합니다. stack 을 올리기 전에 이 순서로 확인합니다.

### 5.1 Reachability to Backing Service

  **LAN IP 모델** 에서는 원격 backing service (PostgreSQL·MinIO·MLflow) 를 호스트의 LAN IP와 port로 부릅니다. 이때 **호스트 방화벽**을 점검해야 합니다. 특히 Docker 가 `0.0.0.0:<port>` 로 게시해도 backing 호스트 (특히 **Windows + Docker Desktop**) 는 LAN 인바운드를 기본 차단하는 경우가 많습니다. 막혀 있으면 예컨대 prefect_server 는 DB 에 못 붙어 migration `TimeoutError` 로 crash-loop 합니다.

  방화벽 열기와 도달성 검증은 **서로 다른 호스트**의 일입니다 — 여는 것은 그 backing 호스트의 로컬 방화벽이라 거기서, 검증은 자기 자신이 아닌 **소비 호스트**에서 해야 실제 네트워크 도달성을 봅니다 (backing 호스트에서 자기 LAN IP 로의 접속은 loopback 이라 방화벽과 무관하게 늘 열린 것처럼 보입니다). 순서대로:

  `backing_ports.sh` 에 action (`open` · `check`) 과 `-host`·`-port` 를 줘서 포트 하나씩 처리합니다. 코드는 [Appendix B](#appendix-b-backing_portssh).

  **① backing 호스트에서 인바운드 열기** (`open`, 멱등) — 주소에서 뽑은 LAN subnet 으로 제한합니다.

  ```bash
  # on the backing host (needs sudo for the ufw rule)
  sudo ./backing_ports.sh open -host <POSTGRESQL_IP> -port 5432  # PostgreSQL
  sudo ./backing_ports.sh open -host <MINIO_IP> -port 9000  # MinIO
  sudo ./backing_ports.sh open -host <MLFLOW_IP> -port 5000  # MLflow
  ```

  **② 소비 호스트 (server·worker) 에서 도달성 검증** (`check`) — backing 호스트가 **아닌** 다른 호스트에서 실행해야 loopback 이 아닌 실제 도달성을 봅니다.

  ```bash
  # on a consuming host (NOT the backing host), to see real reachability
  ./backing_ports.sh check -host <POSTGRESQL_IP> -port 5432  # PostgreSQL
  ./backing_ports.sh check -host <MINIO_IP> -port 9000  # MinIO
  ./backing_ports.sh check -host <MLFLOW_IP> -port 5000  # MLflow
  ```

  모든 포트가 `OPEN` 이면 다음으로 넘어갑니다 (backing service 자체의 설치·포트 게시는 각 서비스 문서를 따릅니다).

### 5.2 Docker Network

  Prefect stack 의 컨테이너들은 docker network `mlops` 로 통신합니다. 접근 방식은 컨테이너가 **같은 머신**인지 **다른 머신**인지에 따라 갈립니다 (**LAN IP 모델**):

  - **같은 머신** → docker **서비스 이름** (`prefect_server`·`minio`·`postgres`·`mlflow`). 같은 호스트의 `mlops` 에 붙은 컨테이너끼리 이름으로 바로 찾습니다.
  - **다른 머신** → 그 서비스가 있는 **호스트의 LAN IP + 게시 포트** (예: `http://<SERVER_IP>:4200/api`, `<MinIO 호스트 IP>:9000`).

  왜 다른 머신은 이름이 안 되나 — 기본 `bridge` network 는 **호스트 로컬**이라, 각 머신에 같은 이름 `mlops` 를 만들어도 **이름만 같을 뿐 별개의 network** 입니다. docker 서비스 이름은 그 호스트의 network 안에서만 해석되므로 **머신을 넘지 못합니다.** 그래서 크로스머신 접근은 LAN IP 로 합니다.

  > docker 이름을 **머신을 넘어** 쓰려면 Docker Swarm 의 **overlay network** 가 필요하지만, 전 노드가 **LAN-native Linux** 여야 동작합니다 (Windows/macOS 의 Docker Desktop 노드는 불가 — [docker-network-ko.md §2 Swarm Overlay Network](../docker-network-ko.md#2-swarm-overlay-network)). 이 스택은 OS 혼합·단순성을 위해 기본적으로 **LAN IP 모델** 을 씁니다.

#### Create the Network

  컨테이너를 띄울 **각 호스트**에서 로컬 bridge `mlops` 를 한 번 만듭니다 (이미 있으면 무해).

  ```bash
  docker network create mlops        # local bridge; run once per host
  docker network ls | grep mlops     # DRIVER = bridge, SCOPE = local
  ```

  이후 절의 모든 compose 는 이 `mlops` 를 external network 로 참조합니다. 같은 호스트의 컨테이너는 **서비스 이름**으로, 다른 호스트의 서비스는 **LAN IP** 로 접근합니다 (`PREFECT_API_URL`·credential endpoint 등에서 지정).

### 5.3 Server Connection

  어느 Prefect server 에 연결할지 (`PREFECT_API_URL`) 를 최초 1회 설정하면 이후 모든 client 명령이 이 server 를 향합니다. 설정 방법은 두 가지이며, 환경변수가 프로필보다 우선합니다 (환경변수 > 프로필 > 기본값). 같은 컴퓨터면 `<Host IP>` 는 `localhost`.

  1) **환경변수** — OS 환경변수로 지정. 영구 등록은 shell 프로필 (`~/.bashrc` 등) 에 `export` 를 추가하고, 현재 셸에만 임시로 줄 땐 `export` 를 바로 실행합니다.

  ```bash
  echo 'export PREFECT_API_URL="http://<Host IP>:4200/api"' >> ~/.bashrc   # persist — applies to newly opened shells
  export PREFECT_API_URL="http://<Host IP>:4200/api"                       # temporary — current shell only
  ```

  2) **prefect CLI** — Prefect 프로필 (`~/.prefect/profiles.toml`) 에 저장.

  ```bash
  prefect config set PREFECT_API_URL="http://<Host IP>:4200/api"
  ```

  이 주소는 job 을 trigger 할 때 (`prefect deployment run ...`), deployment 를 등록할 때, Prefect Secret 블록을 등록/조회할 때 등 server 와 통신하는 client 작업 전반에 쓰입니다. 단 이 값은 접속 주소일 뿐이라, 그 URL 에 Prefect server 가 실제로 떠 있어야 합니다.

## 6. Docker Registry

Worker image 와 flow image 는 같은 docker registry 에서 받습니다. 두 image 를 올리는 방법은 [prefect-worker-ko.md §3](PrefectWorker/prefect-worker-ko.md#3-image) 와 [prefect-flow-ko.md §3](PrefectFlow/prefect-flow-ko.md#3-image) 에 있고, registry 와 pull policy 의 원리는 [prefect-registry-ko.md](prefect-registry-ko.md) 를 따릅니다.

- Registry 는 `registry:2` container 로 host port `12357` 에 있습니다. 5000 은 같은 machine 의 MLflow 가 쓰므로 12357 을 골랐습니다.
- Worker image 는 `<IMAGE_REGISTRY>/prefect-worker:latest`, flow image 는 `<IMAGE_REGISTRY>/pipeline-flow:latest` 입니다. `IMAGE_REGISTRY` 는 `docker-compose.env` 에 `<host>:<port>` 로 적습니다.
- Worker machine 의 docker daemon 은 `insecure-registries` 에 `<REGISTRY_IP>:12357` 을 가져야 HTTP registry 에서 pull 할 수 있습니다.
- 같은 registry 를 다른 stack 도 씁니다. 그 stack 의 build script 는 `localhost:12357/yrocket-finance:latest` 를 push 하고, serve container 는 `POOL_IMAGE=<REGISTRY_IP>:12357/yrocket-finance:latest` 로 pool deployment 를 `image_pull_policy="Always"` 로 등록합니다.
- Registry 에는 아직 `prefect-worker` 와 `pipeline-flow` repository 가 없고, 도는 worker 는 그 전에 local 에서 build 한 `prefect-worker:latest` 로 떠 있습니다.

## 7. Credentials

설정 값은 **네 곳** 으로 나뉘고 서로 겹치지 않습니다 — ① server·worker **부트스트랩** (backend DB URL·server 주소) 은 `docker-compose.env_example`, ② `pipeline_flow` 컨테이너의 **기동 설정** (`PREFECT_API_URL`·`mem_limit` 등, 비밀 아님) 은 **base job template** ([prefect-server-ko.md](PrefectServer/prefect-server-ko.md)), ③ **backing service 주소** (MinIO·PostgreSQL·MLflow endpoint, 비밀 아님) 은 서버의 **Prefect Variable** (`register_variables`, [prefect-server-ko.md §4](PrefectServer/prefect-server-ko.md#4-service-address-variables)), ④ **run 코드용 비밀** (MinIO 키·DB 비번) 만 **Credential 블록** (Prefect Secret) 입니다. **주소(③)와 비밀(④)을 분리** — 주소는 한 곳(Variable)에서 관리하고 비밀만 블록에 둡니다. worker 는 자격증명을 들지 않습니다.

### 7.1 docker-compose.env_example

  **server·worker 부트스트랩 값** (server 주소·backend DB URL) 만 `docker-compose.env_example` 에 모읍니다 (컨테이너가 `env_file` 로 읽음). backing 주소는 여기 없고 서버 Variable 에 있습니다 ([prefect-server-ko.md §4 Service Address Variables](PrefectServer/prefect-server-ko.md#4-service-address-variables)).

  ```dotenv
  # docker-compose.env_example  (Prefect stack — server/worker bootstrap config)
  # __version__ = "0.0.17"
  # Container-only config: read via env_file by prefect_server and prefect_worker. NOT used by host
  # tools. Backing-service addresses (MinIO / PostgreSQL / MLflow) live on the server as prefect Variables
  # (register_variables.sh) — a single, non-secret source read by the flow and by host tools alike.
  # The real docker-compose.env is git-ignored; only this _example is committed. Secrets stay CHANGE_ME.

  # -- Prefect server address (bootstrap) -------------------------------------
  # Server API address — used by the worker, by flow containers (via the base job template), and by
  # in-container CLI (register_pool). Set to the prefect_server host LAN IP.
  PREFECT_API_URL=http://<SERVER_IP>:4200/api
  # API address the server hands to browsers for the dashboard (browsers live outside docker).
  PREFECT_UI_API_URL=http://<SERVER_IP>:4200/api

  # -- Prefect metadata DB (bootstrap) ----------------------------------------
  # Where the server stores flow runs / deployments / logs. Host = the PostgreSQL host LAN IP.
  PREFECT_SERVER_DATABASE_CONNECTION_URL=postgresql+asyncpg://CHANGE_ME:CHANGE_ME@<POSTGRESQL_IP>:5432/prefect

  # -- Docker registry (image source) -----------------------------------------
  # <host>:<port> of the registry holding the multi-arch prefect-worker / pipeline-flow images. Read by
  # run_worker.sh (worker image) and register_pool.sh (flow image default of the base job template).
  IMAGE_REGISTRY=<REGISTRY_IP>:<REGISTRY_PORT>
  ```

  - **메타 DB 호스트** 는 PostgreSQL 이 있는 머신의 **LAN IP** (`<POSTGRESQL_IP>`) — IP 로 두면 server 와 같은 머신이든 다른 머신이든 동작합니다 (같은 머신·같은 `mlops` 망이면 서비스 이름 `postgres` 도 가능).
  - `PREFECT_UI_API_URL` — 브라우저는 docker network 밖이라 `prefect_server` 대신 **LAN IP**.
  - `IMAGE_REGISTRY` — worker image 와 flow image 를 담은 registry 의 `<host>:<port>` 입니다 ([§6](#6-docker-registry)). `run_worker.sh` 는 worker image 를 이 주소에서 받고, `register_pool.sh` 는 pool 의 flow image 기본값 앞에 이 주소를 붙입니다.
  - **backing 주소 (MinIO·PostgreSQL·MLflow) 는 여기 없습니다** — 서버 Variable 로 관리합니다 ([prefect-server-ko.md §4 Service Address Variables](PrefectServer/prefect-server-ko.md#4-service-address-variables)). worker 는 자격증명·주소를 들지 않습니다.

### 7.2 Credential Blocks

  코드가 **MinIO** 와 PostgreSQL 의 `catalog`·`optuna` DB 에 접속할 **비밀** 을 **한 블록** 에 모읍니다 — `minio`·`postgresql_catalog`·`postgresql_optuna` 세 묶음의 **비밀만** (주소·endpoint 는 위 Variable). 비밀 값은 `SecretDict` 로 가립니다. server 에 한 번 저장하면 컨테이너·머신마다 따로 넣지 않아도 됩니다.

  블록 클래스는 `Credentials` **하나** (`minio`·`postgresql_catalog`·`postgresql_optuna` 세 `SecretDict` 필드) 이고, **블록 이름은 임의의 소문자 식별자** 입니다 — 자격증명 세트마다 블록을 하나 만듭니다 (예시 `yrocket`; 팀원 이름과 무관, 이름은 자유). **`pipeline.py`** 와 **`catalog.py`** (공통 라이브러리) 가 같은 클래스를 정의해 쓰므로 한쪽 `save`, 다른 쪽 `load` 가 맞물립니다. 코드는 run 이 지정한 블록 이름으로 `Credentials.load(<name>)` 해 그 **비밀** 을 받습니다 (주소는 Variable).

  ```text
  yrocket                     # block name = any lowercase id (e.g. yrocket); load it -> SECRETS only
  ├─ minio              : access_key, secret_key
  ├─ postgresql_catalog : username, password, database
  └─ postgresql_optuna  : username, password, database
  ```

  <a id="fig-8"></a>
  Fig 8. Layout of one Credentials block

  자격증명을 **JSON 파일** 로 적고 `credentials.py` 로 등록합니다 — 블록 이름은 Prefect 규칙상 **소문자·숫자·하이픈만** 가능하므로 `--block-name` 으로 소문자 이름을 지정합니다 (예: 파일 `yrocket.json` → 블록 이름 `yrocket`). `credentials.py` 코드는 [Appendix C](#appendix-c-credentialspy).

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

  ```bash
  # Register a Credentials block (admin) — PREFECT_API_URL must point at the server.
  # Block name must be lowercase (Prefect rule); pass --block-name (any lowercase id).
  prefect block delete credentials/yrocket                              # drop the old block first (clears stale fields)
  python credentials.py --json-path yrocket.json --block-name yrocket   # save a block named "yrocket"
  ```

  등록이 성공하면 `[credentials] saved block 'yrocket'` 이 찍힙니다. 블록은 server DB 에 저장되므로, 등록에 쓴 **같은 프로필** (`PREFECT_API_URL` → server) 로 확인합니다. slug 는 `<block-type-slug>/<block-document-name>` 이라 클래스 `Credentials` → `credentials/yrocket` 입니다.

  ```bash
  prefect config view                       # PREFECT_API_URL 이 server 를 가리키는지 확인
  prefect block ls                            # Name=yrocket, Type=Credentials (Slug 열에 credentials/yrocket)
  prefect block inspect credentials/yrocket   # 세 섹션 확인 (SecretDict 라 비밀 값은 *** 로 가려짐)
  python -c "from credentials import Credentials as cr; print(cr.load('yrocket').minio.get_secret_value())"
  ```

  UI 로는 `http://<Host IP>:4200` → **Blocks** 에서도 같은 블록이 보입니다.

  `pipeline.py` 는 블록의 `minio` **비밀** + Variable **주소** 로 다운로드하고, `catalog.py` 는 `minio`·`postgresql_catalog`·`postgresql_optuna` **비밀** + Variable **주소** 를 씁니다 (실제 load 예시는 [prefect-flow-ko.md §5](PrefectFlow/prefect-flow-ko.md#5-pipelinepy) 의 `pipeline.py`).

  > flow 컨테이너는 base job template 의 `PREFECT_API_URL` 로 server 에 연결돼야 블록을 받습니다 ([prefect-server-ko.md §3 Work Pool Registration](PrefectServer/prefect-server-ko.md#3-work-pool-registration)). `mlflow`·`prefect` DB 는 사용자 코드가 직접 접속하지 않으므로, 사용자 role 에는 `catalog`·`optuna` 권한만 있으면 됩니다.

## 8. Job Triggering

이 stack 의 deployment 는 `pipeline/high_deployment` 와 `pipeline/low_deployment` 이고, server 가 run 을 work pool 에 얹으면 worker 가 `pipeline_flow` 컨테이너를 띄워 그 안에서 `pipeline(**parameters)` 를 실행합니다 ([prefect-flow-ko.md §5](PrefectFlow/prefect-flow-ko.md#5-pipelinepy)). CLI · SDK · serve mode 로 trigger 하는 방법은 [prefect-concepts-ko.md §4](prefect-concepts-ko.md#4-job-triggering) 를 따릅니다.

```bash
prefect deployment run "pipeline/high_deployment" \
  -p git_repo=https://github.com/team/repo.git -p git_commit_hash=a1b2c3d \
  -p minio_key="SYDNEY/Bennelong Point" -p submitter=alice -p prefect_block=yrocket
```

- server 가 `pipeline` 시그니처 스키마로 `-p` 값의 타입을 변환·검증합니다.
- `pipeline(...)` 함수를 Python 에서 직접 부르면 work pool 을 거치지 않고 부른 process 안에서 바로 실행되므로, 컨테이너 격리가 없고 deployment 와도 이어지지 않습니다.

## 9. Prefect UI

server 대시보드 (`http://<Host IP>:4200`) 에서 deployment·run·task 가 어떻게 보이는지입니다.

- **Deployments** — `<flow_name>/<deployment_name>` 로 나열됩니다 (예: `pipeline/high_deployment`·`pipeline/low_deployment`). flow 이름은 `@flow(name="pipeline")`, deployment 이름은 yaml 의 `name` 입니다.
- **Flow Runs** — trigger 된 run 이 `flow_run_name` 으로 나열됩니다. `submitter` 가 들어가 같은 deployment 아래에서 `alice@a1b2c3d` 처럼 **누구의 run 인지** 구분됩니다 ([prefect-flow-ko.md §5](PrefectFlow/prefect-flow-ko.md#5-pipelinepy) 의 `flow_run_name`). `pipeline.py` 는 payload 에 실행자 이름 (`submitter`) 만 넘기고 git 정보는 넘기지 않으므로, 팀 payload 의 flow run 은 실행자 이름 (예: `alice`) 으로 나열됩니다 (orchestrator run 은 `alice@a1b2c3d`).
- **Tasks** — 팀 payload 가 단계 (dp·fe·train·test) 를 **`@task`** 로 감싸고 `@flow` 로 묶으면, 컨테이너 env 의 `PREFECT_API_URL` 덕분에 그 subprocess 가 **자기 flow run 과 task** 를 보고해 단계가 보입니다 (orchestrator run 과 **별개 flow run**, subprocess 라 격리 유지 — [prefect-concepts-ko.md §6](prefect-concepts-ko.md#6-prefect-task)).
- **Parameters · State · Logs** — run 마다 입력 파라미터 (`git_repo`·`git_commit_hash`·`minio_key`·`submitter`)·상태·로그가 자동 기록되어 (UI 의 Flow Run → Parameters), 같은 파라미터로 재실행 (재현) 할 수 있습니다.

job 하나가 trigger 되면 대시보드에 다음처럼 보입니다.

```text
Deployments
  pipeline/high_deployment     high_performance     # per-tier registration (prefect-flow-ko.md §4)
  pipeline/low_deployment      low_performance

Flow Runs
  pipeline   alice@a1b2c3d   Completed   high_performance     # orchestrator (pipeline.py)
  my_flow    alice@a1b2c3d   Completed                        # team payload (@task), separate run
    ├─ data_prep      Completed
    ├─ feature_eng    Completed
    ├─ train_model    Completed
    └─ test_model     Completed
```

<a id="fig-9"></a>
Fig 9. Dashboard after one job is triggered

같은 job 이 **flow run 두 개** 로 보입니다 — orchestrator (`pipeline`) 와 팀 payload (`my_flow`). orchestrator 는 `flow_run_name` 이 `submitter@commit`, 팀 payload 는 `submitter` (pipeline.py 가 payload 엔 실행자 이름만 넘김) 이라 누구의 run 인지 묶어 보기 좋고, 팀 run 아래에 네 단계 task 가 달립니다. 팀 payload 가 plain 스크립트면 `my_flow` run·task 없이 orchestrator run 만 보입니다.

---

## Appendix A. Terminology

- **Host** — 모든 컨테이너 (server·worker·pipeline_flow·postgres·minio·mlflow) 가 올라가는 한 대의 컴퓨터입니다.
- **`prefect_server`** — API·UI·스케줄러·work pool 대기열을 제공하는 중앙 진입점입니다. 메타데이터 (`prefect` DB) 만 관리하고 코드는 실행하지 않습니다.
- **`prefect_worker`** — work pool 을 polling 해 job 마다 `pipeline_flow` 컨테이너를 띄우고 정리하는 worker 입니다 (Prefect 공식 용어로는 worker). 코드는 실행하지 않습니다.
- **Pipeline Flow** — worker 가 job 마다 띄우는 일시적 실행 컨테이너입니다. 받은 repo·커밋을 shallow `git fetch` 로 펼친 뒤 코드를 실행하고 끝나면 파괴됩니다.
- **flow image** — Pipeline Flow 컨테이너를 띄우는 image 입니다. deployment 의 `image` (없으면 base job template 의 `image` 기본값) 가 가리키며, 이 스택에서는 `pipeline-flow:latest` 입니다 ([prefect-flow-ko.md §3](PrefectFlow/prefect-flow-ko.md#3-image)).
- **ephemeral container** — `docker` work pool 이 job 마다 띄웠다 파괴하는 일시적 컨테이너입니다. 이 문서의 Pipeline Flow 가 여기 해당합니다.
- **work pool** — job 이 대기하는 큐이자 실행 방식 (type) 의 정의입니다. server 안의 메타데이터이며 컨테이너가 아닙니다.
- **work pool type** — Prefect 가 정한 실행 방식 이름입니다 (`process` · `docker` · `kubernetes` · `ecs` 등). 이 스택은 `docker` (job 마다 컨테이너) 를 씁니다.
- **serve mode** — `flow.serve()` 프로세스가 상시 떠서 flow run 요청을 받아 처리하는 모습이, 웹 서버가 요청을 처리하듯 flow 를 계속 **제공 (serve)** 하기 때문에 붙은 이름입니다.
- **deployment** — flow 를 어떻게 실행할지 묶어 **server DB (`prefect`) 에 저장한 레코드** 입니다. 파일·dict 가 아니라 server 안의 영구 레코드이고, API·UI·`prefect deployment inspect` 에서 **JSON 으로** 보입니다.
  - **누가** — 플랫폼·관리자가 등급마다 1회 (팀원 아님).
  - **어떻게** — `prefect deploy --prefect-file <yaml> --name <name> --no-prompt` (CLI) 가 yaml 정의를 server API 로 보내 DB 에 등록합니다 ([prefect-flow-ko.md §4](PrefectFlow/prefect-flow-ko.md#4-deployment)).
  - **사용** — 코드를 다시 안 봐도 이름 `<flow>/<deployment>` 로 run 을 trigger 합니다 (`prefect deployment run "pipeline/high_deployment" -p payload=my_flow.py` · UI · 스케줄). 그러면 worker 가 그 정의대로 `pipeline_flow` 컨테이너를 띄웁니다.
  - 저장된 모습 (`prefect deployment inspect "pipeline/high_deployment"`):

    ```json
    { "name": "high_deployment", "flow_name": "pipeline", "entrypoint": "pipeline.py:pipeline",
      "work_pool_name": "high_performance", "job_variables": { "image": "pipeline-flow:latest" },
      "parameters": { "payload": "my_flow.py" } }
    ```
- **entrypoint** — deployment 가 실행할 flow 를 `<파일>:<@flow 함수>` 로 가리키는 문자열입니다 (예: `pipeline.py:pipeline`). server DB 에 저장되고, 컨테이너 런타임이 이 경로로 모듈을 import 해 그 `@flow` 함수를 run 파라미터와 함께 호출합니다 ([prefect-flow-ko.md §4](PrefectFlow/prefect-flow-ko.md#4-deployment)).
- **base job template** — pool 이 띄우는 flow 컨테이너의 공통 설정 (이미지·env·네트워크·메모리 상한 등) 입니다.
- **`PREFECT_API_URL`** — worker·client 가 server API 를 찾는 주소 (`http://<host>:4200/api`) 입니다. 같은 호스트면 host 가 서비스명 `prefect_server` 입니다.

**Abbreviations**

- **AWS** = Amazon Web Services
- **S3** = (Amazon) Simple Storage Service — MinIO 가 호환하는 오브젝트 스토리지 API
- **API** = Application Programming Interface
- **UI** = User Interface (여기서는 Prefect 웹 대시보드)
- **DB** = Database
- **DSN** = Data Source Name — DB 접속에 필요한 정보 (드라이버·계정·호스트·포트·DB 이름) 를 한 줄로 엮은 접속 문자열입니다 (예: `postgresql://user:pass@host:5432/catalog`). 이 스택은 DSN 을 통째로 저장하지 않고 Credentials 블록 (이름은 임의의 소문자 id; 예 `yrocket`) 의 `postgresql_catalog`·`postgresql_optuna` 섹션 비밀 (`username`·`password`·`database`) 에 Variable `postgresql_host_port` (host:port) 를 더해 `catalog.py`·`pipeline.py` 가 이 문자열을 조립합니다.
- **CPU / GPU** = Central / Graphics Processing Unit

## Appendix B. backing_ports.sh

backing service 포트 하나를 대상으로, action 에 따라 **도달성 확인 (`check`)** 또는 **인바운드 방화벽 개방 (`open`)** 을 하는 스크립트입니다 ([§5.1 Reachability to backing service](#51-reachability-to-backing-service)). `open` 은 그 포트를 **serving 하는 호스트**에서 `sudo` 로 (ufw 규칙 추가), `check` 는 backing 호스트가 **아닌 소비 호스트**에서 실행합니다 — serving 호스트에서 자기 IP 로의 접속은 loopback 이라 방화벽과 무관하게 늘 열린 것처럼 보이기 때문입니다. `open` 은 멱등입니다.

```bash
#!/usr/bin/env bash
# backing_ports.sh — check reachability of, or open the inbound firewall (ufw) for, one backing service port.
# __version__ = "0.0.4"  # Semantic Versioning:  Version = Major.Minor.Patch
#   check : TCP-test the port. Run from a CONSUMING host (server / worker) to see real reachability;
#           from the serving host it is a meaningless loopback (always OPEN).
#   open  : open the inbound firewall (ufw) for the port. Run on the host that SERVES it (needs sudo). Idempotent.
#
#   ./backing_ports.sh check -host <POSTGRESQL_IP> -port 5432
#   sudo ./backing_ports.sh open -host <POSTGRESQL_IP> -port 5432
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
    subnet="${HOST%.*}.0/24"                # derive the LAN /24 from the address (a.b.c.13 -> a.b.c.0/24)
    echo "ensuring inbound $PORT/tcp from $subnet"
    sudo ufw allow from "$subnet" to any port "$PORT" proto tcp   # idempotent: ufw skips a duplicate rule
fi
```

## Appendix C. credentials.py

자격증명 블록을 JSON 으로 등록하는 스크립트입니다 ([§7.2 Credential Blocks](#72-credential-blocks)). 블록 이름은 **CLI 인자 > JSON `name` 필드 > 파일명** 순으로 정해지며, Prefect 규칙상 **소문자·숫자·하이픈만** 허용됩니다 (임의의 소문자 식별자, 팀원 이름과 무관). `Credentials` 클래스도 여기서 정의하며 `catalog.py` 가 import 해 씁니다 (`pipeline.py` 는 이미지 자기완결이라 같은 클래스를 따로 inline 정의 — [prefect-flow-ko.md §5](PrefectFlow/prefect-flow-ko.md#5-pipelinepy)).

```python
# credentials.py — shared Prefect credential block (Credentials) + JSON register CLI.
#
# Defines the one credential Block (SECRETS only; service addresses live in prefect Variables)
# and registers a Credentials block from a JSON file. Block name precedence: --block-name > JSON "name"
# field > file stem. Prefect requires the
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

__version__ = "0.0.22"  # Semantic Versioning:  Version = Major.Minor.Patch

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
