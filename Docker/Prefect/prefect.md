# Prefect Pipeline Orchestration on Docker

> 공식 사이트: [https://www.prefect.io/](https://www.prefect.io/)

Prefect stack 을 한 호스트에서 **세 구성요소 (Prefect Server · Prefect Dispatcher · Pipeline Flow)** 로 나눠 도커로 실행합니다. Pipeline Flow 의 실행 방식은 두 가지입니다 — **Short Term Container** (job 마다 컨테이너를 띄웠다 파괴, ephemeral docker-container-per-job) 와 **Long Term Container** (상시 컨테이너 재사용). 이 문서는 **여러 팀원이 동시에 다수 job 을 trigger** 하는 환경을 전제로, 격리·동시성에 유리한 **Short Term Container 를 주력**으로 하며 Prefect 의 **Docker work pool** 로 구현합니다.

Prefect server (`prefect_server`) 는 job 을 수집·스케줄링하는 **단일 진입점** 입니다. 단 **코드는 실행하지 않습니다** — 실행은 항상 Pipeline Flow 컨테이너 안에서 일어납니다.

단일 머신·소규모 구성에는 serve mode 가 더 단순합니다.

## 1. Architecture

기본 구성은 한 호스트에서 공유 네트워크 `mlops` 로 묶입니다. `prefect_server` 와 `prefect_dispatcher` 가 상시 떠 있고, job 마다 **`pipeline_flow` 컨테이너** 가 일시적으로 실행됩니다 (성능 등급으로 dispatcher 를 여러 머신에 둘 수 있습니다). work pool 은 server 에 등록된 메타데이터입니다 (컨테이너가 아닙니다).

| Component | Prefect term | Role | Lifetime |
|----------|--------------|------|----------|
| **1. Prefect Server** | server | job 수집·스케줄링·UI·**work pool 등록**.<br>실행 파라미터 (`git_commit`·`minio_version`) 전달.<br>코드는 실행하지 않습니다. | 상시 |
| **2. Prefect Dispatcher** | dispatcher / executor | Short Term (주력): pool 을 polling 해<br>job 마다 Pipeline Flow 컨테이너를 띄웁니다.<br>Long Term: 자기 컨테이너에서 flow 직접 실행. | 상시 |
| **3. Pipeline Flow** | execution unit | flow (코드) 가 실행되는 곳입니다.<br>Short Term 은 job 마다 뜨는 전용 컨테이너,<br>Long Term 은 Prefect Dispatcher 안 (별도 없음). | Short Term: 일시적<br>Long Term: 상시 |

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
     pool: lower_performance                     pool: high_performance
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
- **deployment = 등급별 등록** — deployment 하나는 pool 하나에 바인딩되므로, 같은 flow 를 등급마다 등록해 (`pipeline/high`·`pipeline/low`) job 을 보낼 등급을 고릅니다 ([§4.2](#42-dispatcher-registration)).

```
[ host server / shared Docker network (mlops) ]
-----------------+--------------------------------------------------------------
                 v
     +-----------------------+
     | 1. Prefect Server     |  pass parameters (git_commit, minio_version)
     +-----------------------+
                 |
                 v
     +-----------------------+
     | 2. Prefect Dispatcher |  spawn N pipeline_flow containers concurrently (one per job)
     +-----------------------+
                 |
   +-------------+-------------+   (spawned concurrently, one per team member/job)
   v             v             v
+----------+ +----------+ +----------+
| Pipeline | | Pipeline | | Pipeline |   <- 3. Pipeline Flow (ephemeral)
| ctr  A   | | ctr  B   | | ctr  C   |
|  clone   | |  clone   | |  clone   |
|  a1b2c3d | |  e5f6... | |  9z8y... |
+----------+ +----------+ +----------+
   |             |             |
   v             v             v
 auto-remove   auto-remove   auto-remove   (destroyed after the run)
```

- **동시성** — dispatcher 는 job 마다 같은 이미지로 **독립 컨테이너를 동시에** 띄웁니다. 서로 상태를 공유하지 않고 (`git clone` 도 각자), 끝나면 파괴되어 동시성 관리가 단순합니다.
- **단일 호스트** — 기본은 한 호스트에서 모든 컨테이너가 `mlops` 를 공유합니다. 다른 머신에 dispatcher 를 더 붙이는 방법은 [§4.2](#42-dispatcher-registration) 을 참고합니다.

각 서비스의 역할입니다.

| Service | Endpoint | Description |
|---------|----------|------|
| `postgres` | `:5432` | 메타데이터 DB. 한 인스턴스에서 `prefect`/`mlflow`/`optuna`/`catalog` 4개 논리 DB 를 운영합니다. |
| `minio` | `:9000` (S3 API) · `:9001` (console) | Object storage. datasets / models / artifacts 의 3개 buckets 를 운영합니다. |
| `mlflow` | `:5000` | 실험 추적 + 모델 레지스트리. backend 는 `postgres`, artifact 는 `minio` 입니다. |
| `prefect_server` | `:4200` | Prefect server + 웹 대시보드 (UI). backend 는 `postgres` 입니다. |
| `prefect_dispatcher` | — | Short Term work pool 을 polling 해 job 마다 `pipeline_flow` 컨테이너를 띄우는 dispatcher. Long Term (`process`) 에서는 별도 컨테이너 없이 dispatcher 안에서 직접 실행합니다. |

> `postgres`·`minio`·`mlflow` 는 각자 폴더의 compose 로 띄웁니다. 이 문서는 **Prefect server·dispatcher 와 `pipeline_flow` 이미지** 에 집중합니다.

## 2. Execution Architecture

Prefect 실행 모드는 두 가지이고, 차이는 **누가 코드를 실행하느냐** 입니다.

### 1) Serve Mode (Push-Based / Static)

- **동작** — `flow.serve()` 스크립트를 실행하면 그 프로세스가 deployment 를 등록하고 상시 떠서, trigger 시 **자기 자신이** 실행합니다.
- **실행 위치·환경** — `.serve()` 를 띄운 머신 (보통 팀원 client) 의 python 으로 실행되어 팀원이 환경을 자유롭게 씁니다 (work pool mode 는 server 측 공용 이미지로 통일).
- **장점** — 별도 dispatcher·pool 이 없어 단순합니다. 단일 머신에 적합합니다.

### 2) Work Pool Mode (Pull-Based / Dynamic)

- **동작** — `flow.deploy()` 로 등록만 하고 python 은 종료됩니다. dispatcher 가 pool 에서 job 을 가져와 실행하고 정리합니다.
- **pool 타입** — 실행 환경을 만드는 방식이 갈립니다.
  - **Long Term Container** — dispatcher 자기 컨테이너에서 subprocess 로 실행하며, run 들이 컨테이너를 공유합니다 ([Appendix C](#appendix-c-long-term-container-work-pool)).
  - **Short Term Container** — job 마다 새 컨테이너 (Pipeline Flow) 를 띄워 실행하고 파괴합니다. run 마다 격리되어 다수 팀원·동시 실행에 적합합니다.

### Comparison

| Aspect | Serve Mode | Work Pool — Long Term Container | Work Pool — Short Term Container |
|--------|------------|---------------------|--------------------|
| Register | `flow.serve()` | `flow.deploy()` | `flow.deploy()` |
| Code executor | serve 를 띄운 python | dispatcher 프로세스 | job 마다 뜨는 컨테이너 |
| Isolation | 단일 프로세스 | run 들이 공유 | run 마다 컨테이너 격리 |
| Dependencies | 그 python 환경 | dispatcher 환경 | Pipeline Flow 이미지 |
| Best for | 단일 머신·단순 | 단일/소규모 | 다수 팀원·동시 실행 |

- **공통 — 등록** — 세 방식 모두 deployment 등록은 같고, **server 는 코드를 실행하지 않습니다** (이름표만 보관).
- **핵심 차이 — 실행 주체** — Short Term Container (`docker`) 는 job 마다 뜨는 컨테이너의 python 이 실행하므로, 그 이미지에 라이브러리가 있어야 합니다.

## 3. Prefect Server Container

server 는 backend 인 `postgres` 가 먼저 떠 있어야 하므로 **PostgreSQL → (MinIO/MLflow) → Prefect server** 순으로 띄웁니다.

```powershell
# (first time) Copy the example file and fill in the server section. docker-compose.env is not committed.
Copy-Item docker-compose.env_example docker-compose.env

# Create the shared network mlops (ignore the error if it exists) and start the server in the background.
docker network create mlops
docker compose -p <Project Name> -f docker-compose.server.yml up -d
```

실행 후 대시보드는 **`http://<Host IP>:4200`** 에서 열립니다 (같은 컴퓨터는 `localhost`).

```dotenv
# Server backend (PostgreSQL prefect DB) URL — PREFECT_SERVER_DATABASE_CONNECTION_URL is a Prefect standard variable.
PREFECT_SERVER_DATABASE_CONNECTION_URL=postgresql+asyncpg://CHANGE_ME:CHANGE_ME@postgres:5432/prefect
```

```yaml
# docker-compose.server.yml
services:
  prefect_server:
    image: prefecthq/prefect:3-latest
    command: prefect server start --host 0.0.0.0
    env_file:
      - docker-compose.env          # injects PREFECT_SERVER_DATABASE_CONNECTION_URL
    ports:
      - "4200:4200"                 # dashboard/API. Clients connect on this port.
    volumes:
      - ./high.json:/opt/high.json:ro   # base job template for the high_performance pool
      - ./low.json:/opt/low.json:ro     # base job template for the lower_performance pool
    networks:
      - mlops
    restart: unless-stopped

networks:
  mlops:
    external: true
```

- `command: prefect server start --host 0.0.0.0` 은 컨테이너 밖에서도 접속하도록 모든 인터페이스에 바인딩합니다.
- `networks: mlops` 로 `postgres` 와 서비스명으로 통신합니다. `postgres` 는 별도 compose 라 `depends_on` 대신 `restart: unless-stopped` 로 준비될 때까지 재시도합니다.

### Work Pool Registration

work pool 은 **server 에 저장되는 메타데이터 (컨테이너 아님)** 라, server 가 뜨면 한 번 등록합니다 (`--overwrite` 로 템플릿 동기). 등록된 pool 은 server DB 에 남아 이후 dispatcher 들이 polling 으로 접근하므로 ([§4](#4-prefect-dispatcher-container)), dispatcher 쪽엔 pool 생성 단계가 없습니다.

**Base job template** — pool 이 띄우는 모든 `pipeline_flow` 컨테이너의 공통 설정입니다. flow 컨테이너는 dispatcher 의 마운트·네트워크를 상속하지 않으므로 **`PREFECT_API_URL` 과 네트워크를 여기서 명시** 합니다. 등급별로 `high.json`·`low.json` 두 벌을 두며 (`docker-pool-template.json` 은 단일 pool 용 기본형), 위 server compose 가 이를 server 컨테이너에 마운트해 둡니다.

```json
{
  "variables": {
    "type": "object",
    "properties": {
      "image":   { "type": "string", "default": "pipeline-flow:latest" },
      "env":     { "type": "object", "additionalProperties": { "type": "string" },
                   "default": { "PREFECT_API_URL": "http://prefect_server:4200/api" } },
      "networks":{ "type": "array",  "items": { "type": "string" }, "default": ["mlops"] },
      "volumes": { "type": "array",  "items": { "type": "string" },
                   "default": ["pipeline-data-cache:/cache"] },
      "auto_remove": { "type": "boolean", "default": true },
      "mem_limit":   { "type": "string", "default": "8g" }
    }
  },
  "job_configuration": {
    "image":       "{{ image }}",
    "env":         "{{ env }}",
    "networks":    "{{ networks }}",
    "volumes":     "{{ volumes }}",
    "auto_remove": "{{ auto_remove }}",
    "mem_limit":   "{{ mem_limit }}"
  }
}
```

- `image` — flow 컨테이너로 쓸 Pipeline Flow 이미지 ([§5.1](#51-image)). 태그 (`pipeline-flow:latest`) 가 곧 **런타임 버전** (라이브러리 + orchestrator) 입니다.
- **이미지 저장 위치** — 빌드 이미지는 그 호스트의 **로컬 Docker 이미지 스토어** 에 저장됩니다 (`docker images`). 같은 호스트 dispatcher 는 그대로 쓰고, 여러 머신이면 레지스트리에 push/pull 하거나 각 머신에서 빌드합니다.
- `env` — flow 컨테이너가 server·Secret 을 찾는 `PREFECT_API_URL` 을 줍니다. repo 주소는 deployment 별 flow 파라미터 `git_repo` 라 (팀원마다 다른 repo) 여기 두지 않습니다.
- `networks` — flow 컨테이너가 붙을 네트워크 (`mlops` 면 `minio`·`prefect_server` 를 서비스명으로 찾음).
- `volumes` — **이름 있는 공유 볼륨** `/cache` (`pipeline-data-cache`) 에 데이터 버전 캐시가 보존됩니다. 컨테이너 밖이라 일시적 컨테이너가 죽어도 살아남고, 버전 경로 (`v3_best` 등) 는 불변이라 공유해도 안전합니다. 팀 코드는 볼륨이 아니라 run 마다 `git clone` 으로 받습니다.
- **볼륨 마운트는 Dockerfile 이 아닙니다** — 이미지는 "무엇이 들어 있는가" 만 정하고, `/cache` 같은 공유 볼륨은 **컨테이너를 띄우는 시점** 에 ST 는 이 base job template, LT 는 compose (Appendix C) 가 마운트합니다. 같은 named volume 을 붙이므로 캐시가 공유됩니다.
- `auto_remove: true` — run 종료 시 컨테이너 자동 삭제.
- `mem_limit` — flow 컨테이너 메모리 상한. 등급별 pool 의 핵심 차이값입니다 (high 크게·low 작게).

> base job template 필드는 Prefect 버전마다 다를 수 있으니, `prefect work-pool get-default-base-job-template --type docker` 로 최신 템플릿을 받아 `image`·`env`·`networks`·`volumes` 의 `default` 만 채우길 권장합니다.

> **여러 pool** — pool 마다 이 템플릿을 하나씩 등록합니다 (`high.json`·`low.json`). 등급 차이는 dispatcher 의 `--limit` (머신당 동시 컨테이너 수) 과 템플릿의 `mem_limit` 로 주고, 이미지·repo·데이터 경로는 같습니다.
>
> | Field | `high.json` | `low.json` |
> |---|---|---|
> | `mem_limit` | `16g` | `4g` |
> | dispatcher `--limit` | `8` | `2` |

**등록 (`set_pool.ps1`)** — server 안 prefect CLI 로 pool 마다 등록합니다. `<Pool Name>`·`<Template File>`·`<Project Name>` 을 변수로 뺐습니다.

```powershell
# set_pool.ps1 — register/update one work pool on the running server (idempotent via --overwrite).
param(
    [Parameter(Mandatory)] [string]$PoolName,       # e.g. high_performance | lower_performance
    [Parameter(Mandatory)] [string]$TemplateFile,   # mounted into the server at /opt, e.g. high.json
    [string]$ProjectName = "mlops",                 # docker compose project name (-p)
    [string]$Compose     = "docker-compose.server.yml"
)
docker compose -p $ProjectName -f $Compose exec -T prefect_server `
  prefect work-pool create $PoolName --type docker --base-job-template "/opt/$TemplateFile" --overwrite
```

```powershell
# Register each tier (run once, after the server is up).
.\set_pool.ps1 -PoolName high_performance  -TemplateFile high.json
.\set_pool.ps1 -PoolName lower_performance -TemplateFile low.json
```

## 4. Prefect Dispatcher Container

dispatcher (`prefect_dispatcher`) 는 **네 가지 일**을 합니다.

- **job polling** — work pool 을 polling 해 job 을 가져옵니다.
- **job dispatch** — 가져온 job 을 실행 환경으로 보내 실행합니다.
- **reporting** — 실행 중 상태·로그를 server 에 보고합니다.
- **cleanup** — 실행이 끝나면 정리합니다.

dispatcher 는 **dispatch 를 위해 두 방식**을 지원합니다.

- **Short Term Container** (`docker` work pool) — job 마다 `pipeline_flow` 컨테이너를 띄웠다 정리합니다.
- **Long Term Container** (`process` work pool) — dispatcher 자기 상시 컨테이너 안에서 flow 를 직접 실행합니다 (별도 컨테이너 없음).

이 절은 주력인 **Short Term Container** 설정을 다룹니다. Long Term Container 설정은 [Appendix C](#appendix-c-long-term-container-work-pool), work pool type 정의는 [Appendix A](#appendix-a-terminology) 를 참고합니다.

여기서 dispatcher (`prefect_dispatcher`) 는 **Short Term Container (docker pool) 전용** 입니다. work pool 을 polling 하다가 job 마다 Pipeline Flow 이미지로 컨테이너를 띄워 실행하고 정리합니다. 준비물은 **dispatcher compose** 하나입니다 (base job template 등록은 server [§3](#3-prefect-server-container), Pipeline Flow 이미지는 [§5](#5-pipeline-flow-container)).

### 4.1 Dispatcher Docker

dispatcher 는 호스트 도커 소켓을 마운트해 형제 컨테이너를 띄웁니다. docker dispatcher 는 `prefect-docker` 가 필요하므로 기동 시 설치합니다 (이미지로 구우려면 별도 Dockerfile).

```powershell
# (first time) Copy the example file and fill in the dispatcher section (CONTROL_NODE_HOST).
Copy-Item docker-compose.env_example docker-compose.env

# Dispatcher vars, read from the shell at "compose up" (single-$ in the compose command).
# Run once PER MACHINE with WORK_POOL set to that machine's tier. The pool is already registered
# on the server (§3), so the dispatcher only polls it — no pool creation here.
$env:WORK_POOL    = "high_performance"   # the tier this machine serves: high_performance | lower_performance
$env:WORKER_LIMIT = "8"                  # max concurrent pipeline_flow containers on this machine

# Create mlops if missing, then start the dispatcher in the background.
docker network create mlops
docker compose -p <Project Name> -f docker-compose.dispatcher.yml up -d
```

```yaml
# docker-compose.dispatcher.yml
services:
  prefect_dispatcher:
    image: prefecthq/prefect:3-latest
    env_file:
      - docker-compose.env          # CONTROL_NODE_HOST (prefect_server on the same host)
    command: >
      bash -c "pip install --no-cache-dir prefect-docker &&
               export PREFECT_API_URL=http://$${CONTROL_NODE_HOST:-prefect_server}:4200/api &&
               prefect worker start --pool ${WORK_POOL:-high_performance} --limit ${WORKER_LIMIT:-8}"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock   # host docker socket, to spawn sibling containers
    networks:
      - mlops
    restart: unless-stopped

networks:
  mlops:
    external: true
```

- `volumes: /var/run/docker.sock` — dispatcher 가 호스트 도커로 Pipeline Flow 컨테이너를 띄우는 통로입니다 (Windows/Docker Desktop 도 같은 경로).
- `command` — `prefect-docker` 설치 → `PREFECT_API_URL` 설정 → `prefect worker start` 순입니다. pool 생성 단계가 없습니다 (server [§3](#3-prefect-server-container) 가 이미 등록). `WORK_POOL`·`WORKER_LIMIT` 는 `docker compose up` 시 셸에서 읽는 변수입니다.
- **머신마다 실행** — 같은 compose 를 각 컴퓨터에서 자기 등급 `WORK_POOL` 로 띄웁니다. pool 이 server 에 이미 있으니 (§3) dispatcher 는 polling 만 하며, 등급별 첫 머신/추가 머신 구분이 없습니다.
- `--limit` 은 이 dispatcher 가 **동시에 띄우는 컨테이너 수의 상한** 입니다 ([Concurrency & Scaling](#concurrency--scaling)).

> **보안 주의** — 도커 소켓 마운트는 dispatcher 에 호스트 도커 전체 제어권 (사실상 root) 을 줍니다. 신뢰된 내부망·스터디 용도로 한정하고, 더 강한 격리는 Kubernetes work pool 을 고려합니다 ([Appendix D](#appendix-d-orchestrator-benchmarking)).

### Concurrency & Scaling

Short Term Container 는 run 마다 별도 컨테이너라 동시 실행이 자연히 격리됩니다. 동시 실행량은 셋으로 조절합니다.

- **dispatcher `--limit`** — 한 dispatcher 의 동시 컨테이너 상한 (현재 8). 초과분은 slot 이 빌 때까지 대기합니다.
- **pool concurrency limit** — pool 전체 상한 (`prefect work-pool set-concurrency-limit <pool> <N>`). 등급별 pool 은 등급마다 상한을 둡니다.
- **컨테이너 자원 상한** — base job template 의 `mem_limit` 등. GPU 학습처럼 1 job 이 무거우면 `--limit` 을 1~2 로 낮춥니다.

### 4.2 Dispatcher Registration

dispatcher 는 `prefect worker start` 순간 server 에 자기를 알리고 (heartbeat 시작) 해당 work pool 에 **자동 등록**됩니다 — **polling 시작 = 등록** 이라 별도 절차가 없습니다. heartbeat 가 끊기면 잠시 뒤 **OFFLINE** 으로 바뀝니다. (dispatcher 등록은 deployment 등록과 별개입니다.)

| Aspect | Before (no dispatcher) | After (dispatcher polling) |
|--------|--------------------|----------------------------|
| pool | 큐일 뿐 — trigger 된 run 이 `Late`/대기로 멈춤 | dispatcher 가 큐에서 run 을 가져와 실행 |
| 실행 머신 | 없음 | dispatcher 가 도는 호스트 |
| 가시성 | — | UI 의 Work Pools → Workers (이름·ONLINE·last heartbeat) |
| 동시 실행 용량 | — | 그 dispatcher 의 `--limit` 만큼 |

**처리량·확장** — `--limit` 을 키우거나, **다른 머신에서 dispatcher 를 더 띄워 같은 pool 에 붙입니다.** 그 머신에서 `PREFECT_API_URL` 을 server 로 두고 dispatcher 를 띄우면 polling 과 동시에 합류합니다 (다른 머신은 `networks` 블록 제거 + `CONTROL_NODE_HOST`=server IP). pool 등록은 server (§3) 가 이미 했으니 dispatcher 쪽엔 별도 절차가 없습니다. 여러 dispatcher 는 같은 pool 의 큐를 나눠 가집니다. 성능 등급이 다른 머신은 **등급별 pool** (`high_performance`·`lower_performance`) 로 나누고, 각 머신이 자기 등급 pool 의 dispatcher 를 띄웁니다 (한 등급에 머신이 여럿이면 dispatcher 도 여럿).

예시 — dispatcher 를 띄우면 `worker start` 순간 자동 등록되고, server 에서 확인합니다.

```powershell
# Start a dispatcher on a high-tier machine (auto-registers with the server on `worker start`).
.\set_docker.ps1 -Role dispatcher -WorkPool high_performance

# Verify: the dispatcher is ONLINE and its pool is served.
prefect work-pool ls
prefect work-pool inspect high_performance
```

## 5. Pipeline Flow Container

Pipeline Flow 는 dispatcher 가 job 마다 띄우는 per-flow 컨테이너입니다. dispatcher 하나가 동시 job 수만큼 **여러 개 (n 개)** 를 띄우며 (상한 `--limit`, 현재 8), 각 컨테이너는 독립입니다. 여기서는 그 컨테이너의 **이미지 (빌드)** 와 그 안에서 도는 **orchestrator flow (실행 골격)** 를 다룹니다.

이 한 이미지를 **Short Term·Long Term 양쪽에 그대로** 씁니다 — ST 는 job 마다 컨테이너로, LT 는 dispatcher 로 상시 띄웁니다 ([Appendix C](#appendix-c-long-term-container-work-pool)). 그래서 라이브러리를 dispatcher 와 이미지에 중복 설치할 필요가 없습니다.

### 5.1 Image

job 마다 뜨는 컨테이너의 python 환경입니다. **라이브러리와 orchestrator (`pipeline.py`) 만** 굽습니다. 팀 코드는 런타임에 `git clone` 으로 받아 (`git_commit` 으로 커밋 고정) 컨테이너 자기 디렉터리에 펼칩니다. 이미지가 한 번 빌드로 고정되어 모두 같은 런타임을 씁니다.

```dockerfile
# Dockerfile — shared team Pipeline Flow image (libraries + orchestrator)
FROM prefecthq/prefect:3-python3.11
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt
COPY requirements.txt .               # boto3, psycopg2-binary, mlflow, optuna, pandas, torch, ...
RUN pip install --no-cache-dir -r requirements.txt

COPY pipeline.py .                    # orchestrator (deployment entrypoint); team repo is cloned at runtime into a per-run dir
```

```powershell
# Build once at setup (libraries + orchestrator only). The team repo is cloned at runtime per run.
docker build -t pipeline-flow:latest .
```

- **entrypoint 등록** — `from_source(entrypoint="pipeline.py:pipeline")` 로 **deployment entrypoint** (`<파일>:<flow 함수>`) 를 명시해 등록하면, 그 문자열이 **server 의 deployment 레코드 (`prefect` DB)** 에 저장됩니다 (`prefect deployment inspect` / UI 에서 확인). 경로는 컨테이너 작업 디렉터리 (`/opt`) 기준이라 거기 COPY 된 `pipeline.py` 를 가리킵니다. **이 등록은 플랫폼·관리자가 1회** 하는 일이고 (팀원·등급 구분은 deployment 이름·pool), 팀원 payload (`train.py`) 에는 넣지 않습니다.

```python
# Register once (admin); the entrypoint is given explicitly as "<file>:<flow function>".
from prefect import flow
flow.from_source(source=".", entrypoint="pipeline.py:pipeline").deploy(   # "." = platform repo holding pipeline.py
    name="high", work_pool_name="high_performance",
    image="pipeline-flow:latest", build=False, push=False)
```

- **누가 실행하나** — trigger 되면 dispatcher 가 `pipeline_flow` 컨테이너를 띄우고, 그 안의 **Prefect 런타임이 위 entrypoint (`pipeline.py:pipeline`) 를** run 파라미터 (`git_repo`·`git_commit`·`minio_version`·`payload`) 와 함께 호출합니다. 사람이 직접 실행하지 않습니다.

### 5.2 Flow (Orchestrator)

orchestrator (flow) 는 **"커밋 받아 → 팀원 코드 실행"** 만 하는 얇은 골격이라 이미지에 굽습니다. 팀원의 실제 코드는 `git_repo`·`git_commit` 으로 매 job 받아 와 **무슨 코드든 그대로 실행**됩니다 (`payload` 로 스크립트 지정).

이 orchestrator (`pipeline.py`) 는 **플랫폼·관리자가 관리하는 공유·고정 골격** 이라 이미지에 포함되며 (deployment entrypoint), 팀원이 작성하지 않습니다. 팀원은 **payload 스크립트** (`train.py` 등) 만 작성해 `payload` 파라미터로 고릅니다. (`payload` 는 팀 스크립트일 뿐, deployment entrypoint 인 `pipeline.py` 와 다릅니다 — `pipeline.py` 를 넣으면 orchestrator 가 자기 자신을 다시 부릅니다.)

```python
# pipeline.py — orchestrator; Prefect runs this as the deployment entrypoint.
import os
import shutil
import subprocess
import tempfile
from prefect import flow

@flow(name="pipeline")
def pipeline(git_repo: str, git_commit: str, minio_version: str, payload: str = "train.py"):
    work = tempfile.mkdtemp(prefix="run-")                                      # private clone dir (per run)
    try:
        subprocess.run(["git", "clone", git_repo, work], check=True)           # fresh clone (small per-member repo)
        subprocess.run(["git", "-C", work, "checkout", git_commit], check=True)  # pin to the requested commit
        env = {**os.environ, "MINIO_VERSION": minio_version}                   # team code reads the cached version under /cache
        subprocess.run(["python", payload], cwd=work, env=env, check=True)     # run the team's payload script in the private clone
    finally:
        shutil.rmtree(work, ignore_errors=True)                               # LT: clean up; ST is auto-removed with the container
```

- **팀원별 repo** — `git_repo` 가 **flow 파라미터** 라 deployment 마다 다른 repo 를 기본값으로 등록할 수 있습니다. 팀원은 각자 repo·커밋을 쓰고, run 마다 사설 디렉터리에 `git clone` 되어 서로 간섭하지 않습니다. Prefect 가 `git_repo`·`git_commit` 을 run 파라미터로 자동 기록해 재현·lineage 가 남습니다.
- **자유로운 코드** — `payload` 로 팀원이 자기 스크립트를 지정하므로 코드를 정해진 틀에 맞출 필요가 없습니다. 데이터 읽기·저장은 팀원 코드가 직접 하고, 데이터 버전은 `MINIO_VERSION` 환경변수로 받습니다.
- **데이터 이력** — `minio_version` 이 **flow 파라미터** 라서 Prefect 가 run 마다 입력값을 `prefect` DB 에 자동 저장합니다 (UI 의 Flow Run → Parameters). 데이터셋 버전·lineage 는 팀원 코드 (또는 공유 헬퍼) 가 카탈로그에 등록합니다.
- **이력 자동 저장** — `@flow` 진입 시 Prefect 가 run 의 상태·로그·파라미터를 자동 기록합니다 (대시보드 Flow Runs). 지표·모델은 팀원 코드가 MLflow 로 로깅하면 함께 남습니다 ([Appendix E](#appendix-e-prefect-task)).

### 5.3 GPU

flow 컨테이너에서 GPU 를 쓰려면 호스트에 NVIDIA 드라이버·nvidia-container-toolkit 이 있고 base job template 에서 GPU 를 요청해야 합니다 ([§3 Work Pool Registration](#work-pool-registration)). torch 의 CUDA 휠은 런타임을 번들하므로 호스트 드라이버가 최신이면 동작하며, 버전이 안 맞으면 베이스 이미지를 `nvidia/cuda` 계열로 교체합니다.

## 6. Credentials

설정 값은 두 갈래입니다 — **인프라 값** (server·dispatcher 의 backend DB·Control Node 주소) 은 `docker-compose.env`, **run 코드용 자격증명** (MinIO·DB) 은 **Prefect Secret** 으로 다룹니다. dispatcher 는 자격증명을 들지 않습니다.

### docker-compose.env

**server·dispatcher 용 값** (backend DB URL·Control Node 주소) 은 `docker-compose.env` 한 파일에 모읍니다. 실제 값 파일은 `.gitignore` 로 제외하고, 비운 `docker-compose.env_example` 만 커밋합니다.

```dotenv
# docker-compose.env_example  (every value is a placeholder — never expose real values)

# -- prefect-server --
PREFECT_SERVER_DATABASE_CONNECTION_URL=postgresql+asyncpg://CHANGE_ME:CHANGE_ME@postgres:5432/prefect

# -- prefect-dispatcher --
# Address the dispatcher uses to reach the Prefect server. Use the service name prefect_server on the
# same host, or the host IP/hostname on another machine (then remove the networks block in the dispatcher compose).
CONTROL_NODE_HOST=prefect_server
```

- server 는 `postgres` 서비스명으로 backend 에 접속하므로 URL 호스트가 `postgres` 입니다.
- dispatcher 는 코드를 실행하지 않아 MinIO·카탈로그 자격증명이 필요 없습니다 — 그 값들은 아래 Prefect Secret 으로 전달됩니다.

### Prefect Secret

코드가 **MinIO** 와 PostgreSQL 의 `catalog`·`optuna` DB 에 직접 접속하려면 자격증명 (`MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY`/`MINIO_ENDPOINT`/`POSTGRESQL_CATALOG_DSN`/`POSTGRESQL_OPTUNA_DSN`) 이 필요합니다. **Prefect Secret** 으로 다룹니다 — server 에 한 번 저장하면 `pipeline_flow` 코드가 실행 중 이름으로 받아 쓰므로 **컨테이너·머신마다 따로 넣지 않아도 됩니다.**

```python
# Save (admin, once) — register on the server.
from prefect.blocks.system import Secret

Secret(value="<MINIO_ACCESS_KEY>").save("minio-access-key", overwrite=True)
# Save minio-secret-key / catalog-dsn / optuna-dsn the same way.
```

```python
# Use — load by name inside a flow.
from prefect.blocks.system import Secret

ak = Secret.load("minio-access-key").get()   # fetched from the server and used directly
```

> flow 컨테이너는 base job template 의 `PREFECT_API_URL` 로 server 에 연결돼야 Secret 을 받습니다 ([§3 Work Pool Registration](#work-pool-registration)). `mlflow`·`prefect` DB 는 사용자 코드가 직접 접속하지 않으므로, 사용자 role 에는 `catalog`·`optuna` 권한만 있으면 됩니다.

## Appendix A. Terminology

- **Host (호스트)** — 모든 컨테이너 (server·dispatcher·pipeline_flow·postgres·minio·mlflow) 가 올라가는 한 대의 컴퓨터입니다.
- **`prefect_server`** — API·UI·스케줄러·work pool 대기열을 제공하는 중앙 진입점입니다. 메타데이터 (`prefect` DB) 만 관리하고 코드는 실행하지 않습니다.
- **`prefect_dispatcher`** — work pool 을 polling 해 job 마다 `pipeline_flow` 컨테이너를 띄우고 정리하는 dispatcher 입니다 (Prefect 공식 용어로는 worker). 코드는 실행하지 않습니다.
- **Pipeline Flow** — dispatcher 가 job 마다 띄우는 일시적 실행 컨테이너입니다. 받은 repo·커밋을 git clone 으로 펼친 뒤 코드를 실행하고 끝나면 파괴됩니다.
- **Short Term (ST) Container (ephemeral container)** — `docker` work pool 이 job 마다 띄웠다 파괴하는 일시적 컨테이너입니다. 이 문서의 Pipeline Flow 가 여기 해당합니다.
- **Long Term (LT) Container** — `process` work pool 에서 여러 job 을 subprocess 로 실행하는 공유 상시 컨테이너 (dispatcher 컨테이너 자체) 입니다.
- **work pool** — job 이 대기하는 큐이자 실행 방식 (type) 의 정의입니다. server 안의 메타데이터이며 컨테이너가 아닙니다.
- **work pool type** — Prefect 가 정한 실행 방식 이름입니다. `process` (Long Term Container) · `docker` (job 마다 Short Term Container) · `kubernetes` (job 마다 pod) · `ecs` 등이 있습니다.
- **serve mode** — `flow.serve()` 프로세스가 상시 떠서 flow run 요청을 받아 처리하는 모습이, 웹 서버가 요청을 처리하듯 flow 를 계속 **제공 (serve)** 하기 때문에 붙은 이름입니다.
- **deployment** — flow 를 언제·어떻게·어떤 파라미터로 실행할지 묶어 server 에 등록한 실행 정의입니다.
- **base job template** — pool 이 띄우는 flow 컨테이너의 공통 설정 (이미지·env·네트워크·볼륨) 입니다.
- **`CONTROL_NODE_HOST`** — dispatcher 가 server 를 찾는 주소입니다. 같은 호스트면 서비스명 `prefect_server` 입니다.

**Abbreviations**

- **AWS** = Amazon Web Services
- **S3** = (Amazon) Simple Storage Service — MinIO 가 호환하는 오브젝트 스토리지 API
- **API** = Application Programming Interface
- **UI** = User Interface (여기서는 Prefect 웹 대시보드)
- **DB** = Database
- **DSN** = Data Source Name (DB 접속 문자열)
- **CPU / GPU** = Central / Graphics Processing Unit

## Appendix B. Prefect CLI

`prefect` CLI 는 Prefect SDK 와 함께 설치되는 명령행 도구 (`pip install prefect`) 입니다.

- `prefect config set PREFECT_API_URL="http://<Host IP>:4200/api"` — client 가 바라볼 server 주소를 프로필에 1회 저장합니다.
- `prefect server start --host 0.0.0.0` — Prefect server 를 기동합니다 (§3).
- `prefect work-pool create <name> --type docker --base-job-template <file> [--overwrite]` — Short Term Container work pool 을 server 에 등록합니다 (§3).
- `prefect work-pool get-default-base-job-template --type docker` — 도커 dispatcher 의 기본 base job template 을 출력합니다 (§4.1).
- `prefect work-pool set-concurrency-limit <pool> <N>` — pool 전체 동시 실행 상한을 설정합니다.
- `prefect worker start --pool <name> [--limit N]` — dispatcher 를 기동해 그 pool 을 polling 하며 job 을 실행합니다 (§4.2).
- `prefect deploy` (또는 `flow.deploy(...)`) — deployment 를 등록합니다.
- `prefect deployment run "<flow>/<deployment>" -p <key>=<value>` — 등록된 deployment 를 파라미터와 함께 trigger 합니다.

## Appendix C. Long Term Container Work Pool

단일 머신·소규모에서는 매 flow 컨테이너를 띄우는 대신 dispatcher **자기 프로세스** 로 실행하는 Long Term Container 가 더 단순합니다. **Short Term 과 같은 `pipeline-flow` 이미지를 dispatcher 로 띄우고** ([§5.1](#51-image)), 데이터는 ST 와 같은 `/cache` 볼륨을 마운트해 씁니다 (라이브러리·orchestrator 는 이미지에 이미 있음). 팀 repo 는 ST 와 똑같이 run 마다 `git clone` 으로 받습니다. run 들이 프로세스 공간을 공유하므로 격리는 약합니다.

```yaml
# docker-compose.dispatcher.yml (process variant — single/small scale)
services:
  prefect_dispatcher:
    image: pipeline-flow:latest     # the same image as the Short Term run container (§5.1)
    env_file:
      - docker-compose.env          # CONTROL_NODE_HOST (prefect_server on the same host)
    command: >
      bash -c "export PREFECT_API_URL=http://$${CONTROL_NODE_HOST:-prefect_server}:4200/api &&
               prefect work-pool create ${WORK_POOL:-default} --type process --overwrite &&
               prefect worker start --pool ${WORK_POOL:-default} --limit ${WORKER_LIMIT:-8}"
    working_dir: /opt                # where the orchestrator pipeline.py lives
    volumes:
      - pipeline-data-cache:/cache   # data version cache
    networks:
      - mlops
    restart: unless-stopped

volumes:
  pipeline-data-cache:

networks:
  mlops:
    external: true
```

- **ST·LT 동일 이미지** — ST 는 `pipeline-flow` 이미지를 job 마다 띄우고, LT 는 같은 이미지를 dispatcher 로 상시 띄웁니다. 라이브러리·orchestrator 가 이미지에 있고 팀 repo 는 run 마다 `git clone` 으로 받으므로, dispatcher 에 따로 설치·전달할 게 없습니다. LT 는 한 컨테이너에서 여러 run 이 동시에 돌지만, 각 run 이 자기 사설 디렉터리에 clone 하므로 서로 간섭하지 않습니다.

## Appendix D. Orchestrator Benchmarking

"**가벼운 에이전트 (dispatcher) 가 작업을 집어, 작업마다 격리된 일시적 실행 단위를 띄워 실행하고 정리**" 하는 패턴은 오케스트레이션의 업계 표준입니다. 이 스택의 Short Term Container work pool 은 그 표준의 **단일 호스트 변형** 이고, 규모가 커지면 실행 단위를 컨테이너 → **pod** 로 올린 Kubernetes 변형으로 확장됩니다.

| System | Dispatcher (agent) | Execution unit | Scale |
|--------|--------------------|----------------|-------|
| **Prefect** (Short Term Container) | worker | run 마다 **컨테이너** | 단일 호스트·소~중 |
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

## Appendix E. Prefect @task

`@task` 를 쓰지 않아도 이력 관리와 재현 (reproducibility) 은 완전히 됩니다. Prefect 에서 실행 흐름을 묶는 핵심 단위는 `@task` 가 아니라 **`@flow`** 이기 때문입니다. `@flow` 데코레이터만 붙이면 그 안의 코드가 일반 함수든 클래스든 **실행 이력과 입력 파라미터가 Prefect Server 에 기록**됩니다.

### Reproducing without @task

`@task` 없이 `@flow` 와 일반 함수만으로 과거 시점 (git 커밋 + MinIO 데이터 버전) 을 재현하는 구조입니다.

```python
from prefect import flow
import boto3

# A plain Python function (not a Prefect @task).
def download_data_from_minio(version_id):
    s3 = boto3.client("s3", endpoint_url="http://minio:9000")
    s3.download_file("ml-data", "dataset.csv", "local.csv", ExtraArgs={"VersionId": version_id})

# A plain Python function (not a Prefect @task).
def train_and_evaluate():
    accuracy = 0.95     # real training/validation logic (the git-checked-out code runs here)
    return accuracy

# History and parameter tracking come from @flow, not @task.
@flow(name="mlops-reproduce-pipeline")
def reproduce_flow(git_commit_hash: str, minio_data_version: str):
    download_data_from_minio(minio_data_version)
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
