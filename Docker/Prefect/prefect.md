# Prefect with remote worker

Prefect stack 을 **Control Node 와 Worker Node 로 나눠** 도커로 실행하는 방법을 설명합니다. 여기서 **Node** 는 서비스 컨테이너를 띄우는 한 대의 컴퓨터 (물리 머신 또는 VM) 를 가리킵니다. Control Node 는 오케스트레이션 server 와 그 backend (메타데이터 DB·오브젝트 스토리지·실험 추적) 를 모아 띄우고, Worker Node 는 실제 코드를 실행하는 worker 만 띄워 네트워크로 Control Node 에 붙습니다. worker 는 꼭 별도 머신이 아니어도 되며, Control Node 와 같은 컴퓨터에서 worker 를 띄워 같은 Control Node 에 붙일 수도 있습니다 (시험·소규모 구성).

Prefect server (`prefect_server`) 는 job 요청을 중앙에서 수집·스케줄링하는 **단일 진입점 (Single Point of Entry)** 입니다. 다만 **`prefect_server` 는 코드를 실행하지 않습니다** — 코드는 항상 실행기 (`python` 프로세스 또는 `prefect_worker`) 가 떠 있는 컴퓨터에서 돕니다.

## 1. Architecture

이 구성은 두 층으로 나뉘며, 두 층은 서로 다른 컴퓨터에서 돌 수 있습니다.

| Layer | Services | Connection |
|-------|----------|----------|
| **Control Node** | `postgres` · `minio` · `mlflow` · `prefect_server` | 같은 호스트에서 공유 네트워크 `mlops` 로 묶여 서비스명으로 통신합니다. |
| **Worker Node** | `prefect_worker` | 다른 컴퓨터이므로 `CONTROL_NODE_HOST` (Control Node 의 IP/호스트명) 로 접속합니다. |

- **Control Node** 의 서비스들은 한 컴퓨터 안에서 도커 네트워크 `mlops` 를 공유하므로, 서로를 `postgres:5432` · `minio:9000` 처럼 **서비스명** 으로 찾습니다.
- **Worker Node** 는 Control Node 와 다른 컴퓨터라 도커 네트워크를 공유할 수 없으므로, Control Node 가 노출한 포트 (`:4200` · `:9000` · `:5432`) 로 **IP/호스트명** 을 통해 접속합니다. 그 주소를 `CONTROL_NODE_HOST` 로 지정합니다.
- 같은 컴퓨터에서 worker 를 띄워 시험할 때는 `CONTROL_NODE_HOST` 를 `host.docker.internal` 로 두면 됩니다.

각 서비스의 역할은 다음과 같습니다.

| Service | Endpoint | Description |
|---------|----------|------|
| `postgres` | `:5432` | 메타데이터 DB 입니다. 한 인스턴스에서 `prefect`/`mlflow`/`optuna`/`catalog` 4개 논리 DB 를 운영합니다. |
| `minio` | `:9000` (S3 API) · `:9001` (console) | 오브젝트 스토리지입니다. 데이터·모델·아티팩트를 보관합니다. |
| `mlflow` | `:5000` | 실험 추적 server + 모델 레지스트리입니다. backend 는 `postgres`, artifact 는 `minio` 입니다. |
| `prefect_server` | `:4200` | Prefect server + 대시보드 (UI) 입니다. backend 는 `postgres` 입니다. |
| `prefect_worker` | — | work pool 에서 job 을 가져와 코드를 실행합니다. `default` pool, 동시 최대 8개 (`--limit 8`) 입니다. |

> `postgres` · `minio` · `mlflow` 는 각자 자기 폴더의 compose 로 Control Node 에서 띄웁니다. 이 문서는 그중 **Prefect server 와 worker** 의 설치·실행에 집중합니다.

## 2. Prefect Server Setup

Control Node 에서 실행합니다. server 는 backend 인 `postgres` 가 같은 Control Node 에서 먼저 떠 있어야 정상 동작하므로, **PostgreSQL → (MinIO/MLflow) → Prefect server** 순으로 띄우길 권장합니다.

```powershell
# (최초 1회) 예시 파일을 복사해 server 섹션의 값을 채운다. docker-compose.env 는 git 에 커밋하지 않는다.
Copy-Item docker-compose.env_example docker-compose.env

# 공유 네트워크 mlops 를 만들고(이미 있으면 에러는 무시) server 를 백그라운드로 띄운다.
docker network create mlops
docker compose -f docker-compose.server.yml up -d
```

실행 후 Prefect 대시보드는 **`http://<Control Node IP>:4200`** 에서 열립니다 (같은 컴퓨터에서는 `localhost`).

채워 넣을 `docker-compose.env` 의 server 섹션 예시입니다 (값은 `CHANGE_ME` placeholder).

```dotenv
# server backend(PostgreSQL prefect DB) 접속 URL — PREFECT_SERVER_DATABASE_CONNECTION_URL 은 Prefect 표준 변수다.
PREFECT_SERVER_DATABASE_CONNECTION_URL=postgresql+asyncpg://CHANGE_ME:CHANGE_ME@postgres:5432/prefect
```

```yaml
# docker-compose.server.yml
services:
  prefect_server:
    image: prefecthq/prefect:3-latest
    command: prefect server start --host 0.0.0.0
    env_file:
      - docker-compose.env          # PREFECT_SERVER_DATABASE_CONNECTION_URL 을 주입한다.
    ports:
      - "4200:4200"                 # 대시보드/API. Worker Node 와 클라이언트가 이 포트로 접속한다.
    networks:
      - mlops
    restart: unless-stopped

networks:
  mlops:
    external: true
```

- `command: prefect server start --host 0.0.0.0` 은 컨테이너 밖 (다른 컴퓨터 포함) 에서도 접속할 수 있도록 모든 인터페이스에 바인딩합니다.
- `env_file` 의 `PREFECT_SERVER_DATABASE_CONNECTION_URL` 은 `postgres` 서비스명으로 `prefect` DB 에 접속하는 URL 입니다 (Control Node 의 `mlops` 네트워크 안이라 호스트가 `postgres` 입니다).
- `networks: mlops` 로 같은 Control Node 의 `postgres` 와 서비스명으로 통신합니다. `postgres` 는 별도 compose 라 `depends_on` 을 걸 수 없으므로, `restart: unless-stopped` 로 준비될 때까지 자동 재시도합니다.

## 3. Prefect Worker Setup

Worker Node 에서 실행합니다. worker 는 Control Node 와 다른 컴퓨터이므로 `CONTROL_NODE_HOST` 로 Control Node 주소를 지정해 붙습니다.

```powershell
# (최초 1회) 예시 파일을 복사해 worker 섹션(CONTROL_NODE_HOST·자격증명)을 채운다.
Copy-Item docker-compose.env_example docker-compose.env

# worker 를 백그라운드로 띄운다(Worker Node 는 공유 네트워크가 필요 없다).
docker compose -f docker-compose.worker.yml up -d
```

```yaml
# docker-compose.worker.yml
services:
  prefect_worker:
    image: prefecthq/prefect:3-latest
    env_file:
      - docker-compose.env          # CONTROL_NODE_HOST, POSTGRES_*, MINIO_ACCESS_KEY/SECRET, AWS_*
    command: >
      bash -c ": $${CONTROL_NODE_HOST:?set in docker-compose.env} $${POSTGRES_USER:?set in docker-compose.env} $${POSTGRES_PASSWORD:?set in docker-compose.env} &&
               export PREFECT_API_URL=http://$$CONTROL_NODE_HOST:4200/api &&
               export MINIO_ENDPOINT=http://$$CONTROL_NODE_HOST:9000 &&
               export POSTGRESQL_CATALOG_DSN=postgresql://$$POSTGRES_USER:$$POSTGRES_PASSWORD@$$CONTROL_NODE_HOST:5432/catalog &&
               export POSTGRESQL_OPTUNA_DSN=postgresql://$$POSTGRES_USER:$$POSTGRES_PASSWORD@$$CONTROL_NODE_HOST:5432/optuna &&
               if [ ${CREATE_POOL:-true} = true ]; then prefect work-pool create ${WORK_POOL:-default} --type process --overwrite; fi &&
               prefect worker start --pool ${WORK_POOL:-default} --limit ${WORKER_LIMIT:-8}"
    volumes:
      - ../../Prefect:/app          # flow 코드가 있는 폴더를 /app 으로 마운트한다.
    working_dir: /app
    restart: unless-stopped
```

- worker 는 `CONTROL_NODE_HOST` 한 값으로 API (`:4200`)·MinIO (`:9000`)·catalog·optuna DB (`:5432`) 를 모두 가리킵니다. endpoint 에 비밀번호·호스트가 섞이므로 `command` 안에서 `env_file` 값으로 조립해 `export` 합니다.
- **같은 파일로 첫 worker·추가 worker 모두 처리** — `command` 의 `CREATE_POOL`·`WORK_POOL`·`WORKER_LIMIT` 는 `docker compose up` 시점에 **셸에서 읽는 compose 변수**입니다 (미설정 시 `true`·`default`·`8`). 기본 `up -d` 는 **첫 worker** (pool 생성 후 시작) 이고, **추가 worker** 는 `up` 앞에 `CREATE_POOL=false` 를 붙여 pool 생성을 건너뜁니다. 특정 머신 전용은 `WORK_POOL=pool-1` 로 지정합니다 (명령 예시는 Appendix D 참고).
- `volumes: ../../Prefect:/app` 은 flow 코드가 있는 `MLOps/Prefect` 폴더를 마운트합니다. **Worker Node 에도 이 저장소가 같은 구조로 있어야** 합니다.
- `restart: unless-stopped` 는 Control Node (API) 가 늦게 떠 연결에 실패해 종료돼도 자동으로 다시 붙게 합니다.
- `command` 맨 앞의 `: $${VAR:?...}` 는 **필수 env (`CONTROL_NODE_HOST`·`POSTGRES_USER`·`POSTGRES_PASSWORD`) 가 비어 있으면 즉시 명확한 에러로 종료**시키는 가드입니다 — 빈 값으로 `http://:4200/api` 같은 깨진 주소를 만들어 모호하게 crash-loop 하는 것을 막습니다 (`$${VAR:?메시지}` 는 값이 unset·빈 값이면 메시지를 출력하고 종료).

### Concurrency & Scaling

worker 1개가 동시에 돌리는 job 수는 `--limit` 값 (현재 8) 입니다. worker 는 work pool 에서 job 을 가져와 실행하는데, `prefect worker start --pool default --limit 8` 의 `--limit` 이 그 worker 의 **동시 실행 상한** 입니다. 9번째 job 은 앞 job 하나가 끝나 slot 이 빌 때까지 대기열에서 기다립니다. 처리량을 늘리는 방법은 두 가지입니다 — `--limit` 을 키우거나 (`--limit N`), worker 수를 늘립니다 (`docker compose -f docker-compose.worker.yml up -d --scale prefect_worker=3`). 이때 **전체 동시 실행 수 ≈ worker 수 × `--limit`** 입니다. 다만 무작정 키우지 말고 Worker Node 의 **CPU/GPU/메모리 한도** 안에서 정해야 하며 (자원 경합 시 오히려 느려집니다), GPU 학습처럼 1job 이 자원을 많이 쓰면 `--limit` 을 1~2 로 낮추는 편이 안전합니다.

### Python Version & Dependencies

기본 worker 이미지 (`prefecthq/prefect:3-latest`) 에는 **python 과 prefect 만** 들어 있어, work pool mode 로 사용자 코드를 실행하면 `import torch` 같은 **라이브러리가 없어 실패** 할 수 있습니다 ([§4](#4-execution-architecture) 참고). work pool mode 를 쓰려면 worker 에 **python 버전을 고정** 하고 **필요한 라이브러리를 설치** 해야 합니다. (serve mode 만 쓰면 코드를 실행하는 컴퓨터의 python 이 이미 라이브러리를 갖고 있으므로 이 작업이 필요 없습니다.)

가장 간단한 방법은 worker 가 뜰 때 `requirements.txt` 를 설치하도록 `command` 맨 앞에 설치 단계를 두는 것입니다.

```yaml
    command: >
      bash -c ": $${CONTROL_NODE_HOST:?set in docker-compose.env} $${POSTGRES_USER:?set in docker-compose.env} $${POSTGRES_PASSWORD:?set in docker-compose.env} &&
               pip install -r /app/requirements.txt &&
               export PREFECT_API_URL=http://$$CONTROL_NODE_HOST:4200/api &&
               export MINIO_ENDPOINT=http://$$CONTROL_NODE_HOST:9000 &&
               export POSTGRESQL_CATALOG_DSN=postgresql://$$POSTGRES_USER:$$POSTGRES_PASSWORD@$$CONTROL_NODE_HOST:5432/catalog &&
               export POSTGRESQL_OPTUNA_DSN=postgresql://$$POSTGRES_USER:$$POSTGRES_PASSWORD@$$CONTROL_NODE_HOST:5432/optuna &&
               if [ ${CREATE_POOL:-true} = true ]; then prefect work-pool create ${WORK_POOL:-default} --type process --overwrite; fi &&
               prefect worker start --pool ${WORK_POOL:-default} --limit ${WORKER_LIMIT:-8}"
```

매번 설치가 느리면 `Dockerfile` (`FROM prefecthq/prefect:3-python3.11` + `RUN pip install -r requirements.txt`) 로 한 번 빌드한 뒤 `image:` 대신 `build:` 로 쓰면 더 빠릅니다.

## 4. Execution Architecture

Prefect 실행에는 **두 가지 모드** 가 있고, 차이는 **누가 (어떤 python 이) 코드를 실행하느냐** 입니다. 두 모드는 architecture 가 다릅니다.

### 1) Push-Based / Static Architecture (Serve Mode)

- **구조**: 개발자가 코드가 실행될 인프라를 미리 준비하고 프로세스를 직접 구동해 놓는 구조입니다.
- **동작**: `flow.serve()` 가 든 python script 를 실행하면, 그 python 프로세스가 server 에 **deployment** (flow 를 언제·어떻게 실행할지 — 스케줄·파라미터·대상 work pool — 를 묶어 server 에 등록해 두는 실행 정의) 를 등록하고 상시 떠서 Prefect server 의 신호를 수신하다가, trigger 되면 **자기 자신이** 코드를 즉시 실행합니다 (실행하는 python = script 를 띄운 그 python).
- **장점**: architecture 가 단순하여 별도의 worker 를 띄울 필요가 없습니다.

### 2) Pull-Based / Dynamic Architecture (Work Pool Mode)

- **구조**: Prefect server 와 **실제 인프라** (코드가 실제로 도는 컴퓨터·컨테이너 — 예: GPU 머신, worker 가 떠 있는 노드) 사이에 중간 매개체인 Work Pool (큐) 과 Worker (에이전트) 를 두는 분산 구조입니다.
- **동작**: `flow.deploy()` (또는 `prefect deploy`) 로 등록만 하고 python 은 종료됩니다. Worker 가 주기적으로 Work Pool 에서 작업 요청을 가져온 뒤 실행 환경을 만들어 **Worker 의 python** 으로 작업을 실행하고, 끝나면 정리합니다 (실행하는 python = Worker 의 python → 그래서 Worker 환경에 라이브러리 설치가 필요합니다).
- **장점**: 확장성이 뛰어나며, 다양한 이기종 머신을 중앙에서 유연하게 제어할 수 있습니다.

### Comparison

| Aspect | Serve Mode | Work Pool Mode |
|--------|------------|----------------|
| Architecture | Push-based / static | Pull-based / dynamic |
| Register | `flow.serve()` | `flow.deploy()` / `prefect deploy` |
| Code executor | `flow.serve()` 를 실행한 python 프로세스 | Worker (별도 에이전트) |
| Python that runs code | script 를 띄운 그 python | Worker 의 python (런타임/이미지) |
| Separate worker needed | No | Yes (`prefect worker start`) |
| Dependencies (numpy, torch 등) | 이미 그 python 환경에 있음 | Worker 런타임에 설치해야 함 |
| Best for | 단일 머신·단순 구성 | 확장성·이기종 머신 |

- **push vs pull** — Serve mode 는 실행할 프로세스 (인프라) 를 미리 띄워 그 deployment 전용으로 **고정 (static)** 해 두고, 큐에서 일감을 끌어오는 단계 없이 그 프로세스가 곧장 실행하는 **push** 모델입니다. Work pool mode 는 worker 가 work pool 큐를 주기적으로 들여다보며 일감을 스스로 가져오고 (**pull**) 실행 환경을 매 run 마다 **동적 (dynamic)** 으로 구성합니다.
- **공통 — 등록** — 두 모드 모두 deployment 정의를 Prefect server 에 올리는 **등록**은 같고, **Prefect server 자체는 코드를 실행하지 않습니다** (이름표만 보관).
- **핵심 차이 — 실행 주체** — 코드를 실제로 실행하는 python 이 누구냐가 갈립니다. Serve mode 는 script 를 띄운 python 이, Work pool mode 는 Worker 의 python 이 실행하며, 표의 나머지 행은 모두 이 차이에서 따라옵니다.
- **'단일 머신' 의 의미** — Serve mode 는 work pool·worker 를 아예 쓰지 않고 `.serve()` 를 띄운 그 python 이 직접 실행하므로 한 머신에서 끝납니다. 별도 Worker Node 를 두지 않고 **Worker 역할을 같은 컴퓨터가 겸한다**는 뜻입니다.

## 5. Execution Topology

### Server Connection

Python client (prefect worker or job triggering node) 가 **어느 Prefect server 에 연결할지** 주소를 지정합니다. **최초 1회** 설정하면 이후 모든 client 명령이 이 server 를 향합니다.

```powershell
prefect config set PREFECT_API_URL="http://<Control Node IP>:4200/api"
# 같은 컴퓨터면 <Control Node IP>=localhost, 다른 컴퓨터의 server 면 그 IP/호스트명을 쓴다.
```

이 설정은 job 을 **trigger** 할 때 (`prefect deployment run ...`), **Prefect Secret 블록을 등록/조회** 할 때, 그 밖에 Prefect server 와 통신하는 client 작업 전반에 필요합니다.

### Execution Scenarios

| Case | Trigger | Trigger Location | Execution<br>Mode | Worker<br>Location | Execution<br>Location | Reference |
|------|---------|------------------|----------------|-----------------|--------------------|-----------|
| **A** | admin | Server<br>(Control Node) | serve | — | Server | [§6 Serve](#serve-mode) |
| **B** | user | Server<br>(Control Node) | serve | — | Server | [§6 Serve](#serve-mode) |
| **C** | user | Client | serve | — | Client | [§6 Serve](#serve-mode) |
| **D** | user | Client | work pool | Shared<br>Worker<br>Node | Worker<br>machine | [§6 Shared](#work-pool-mode-shared-worker) |
| **E** | user | Client | work pool | Dedicated<br>Worker<br>Node | Client | [§6 Dedicated](#work-pool-mode-dedicated-worker) |

Execution Location 은 Execution Mode 로 결정됩니다.

- **serve** — Execution Location 은 **Trigger Location 과 같습니다** (`.serve()` 를 띄운 그 프로세스가 직접 실행하므로).
- **work pool** — Execution Location 은 **worker 가 있는 머신**입니다 (그 worker 가 job 을 가져와 실행하므로).

## 6. Python Execution

prefect 과 python 으로 flow 를 실행하는 세 가지 방식입니다 (§5 Execution Scenarios 표 참고). flow 코드는 같고 **등록·라우팅 방식만** 다릅니다.

아래 예시에서 쓰는 이름은 다음과 같습니다 (실제 값으로 바꿔 쓰세요).

- **flow 이름**: `full-pipeline` (`@flow(name="full-pipeline")`) — 함수는 `full_pipeline`.
- **entrypoint**: `flow.py:full_pipeline` — `<파일경로>:<flow 함수명>` (즉 `flow.py` 파일 안의 `full_pipeline` 함수), 소스 경로 `source="/app"`.
- **deployment 이름**: `local` (serve) · `shared-dep` (shared) · `dedicated-dep` (dedicated).
- **work pool**: `default` (shared) · `pool-1` (dedicated).

### Serve Mode

`flow.serve()` 를 띄운 python 프로세스가 deployment 를 등록하고 **자기 자신이** 코드를 실행합니다 (work pool·worker 불필요). 단일 머신·단순 구성에 적합합니다 (Case A·B·C).

```python
from prefect import flow

@flow(name="full-pipeline")
def full_pipeline():
    ...

if __name__ == "__main__":
    full_pipeline.serve(name="local")   # 이 프로세스가 상시 떠서 직접 실행
```

trigger (이미 떠 있는 deployment 실행) 는 CLI·Python 둘 다 됩니다 (serve 등록 자체는 Python `.serve()` 전용입니다).

```powershell
prefect deployment run "full-pipeline/local"     # CLI
```
```python
from prefect.deployments import run_deployment
run_deployment("full-pipeline/local")            # Python
```

### Work Pool Mode (Shared Worker)

`default` work pool 을 여러 worker 가 공유해 job 을 분산합니다. **먼저 비는 worker 가 가져가므로 머신은 못 고릅니다** (Case D). worker 를 `default` pool 에 붙이는 방법은 [Appendix D](#appendix-d-additional-worker-attachment) 를 참고합니다.

deployment 를 `default` pool 로 등록·실행합니다 (CLI·Python).

```powershell
# CLI — 등록 + 실행
prefect deploy flow.py:full_pipeline -n shared-dep --pool default
prefect deployment run "full-pipeline/shared-dep"
```
```python
# Python — 등록 + 실행
from prefect import flow
from prefect.deployments import run_deployment

@flow(name="full-pipeline")
def full_pipeline():
    ...

full_pipeline.from_source(source="/app", entrypoint="flow.py:full_pipeline").deploy(
    name="shared-dep", work_pool_name="default")
run_deployment("full-pipeline/shared-dep")
```

### Work Pool Mode (Dedicated Worker)

특정 머신에서만 돌리려면 (예: 내 GPU) 그 머신 **전용 pool** 로 라우팅합니다 (Case E). `default` 에 붙이면 분산되어 고정이 안 됩니다. 전용 pool 생성·worker 붙이기는 [Appendix D](#appendix-d-additional-worker-attachment) 를 참고합니다.

어느 pool 로 갈지는 **deployment 의 `work_pool_name`** (CLI 는 `--pool`) 이 정합니다 (process pool 이라 이미지 빌드 불필요). CLI·Python 둘 다 됩니다.

```powershell
# CLI — 등록 + 실행
prefect deploy flow.py:full_pipeline -n dedicated-dep --pool pool-1
prefect deployment run "full-pipeline/dedicated-dep"
```

```python
from prefect import flow
from prefect.deployments import run_deployment

@flow(name="full-pipeline")
def full_pipeline():
    ...

full_pipeline.from_source(
    source="/app",                        # flow 코드 위치 (repo 경로 또는 git URL)
    entrypoint="flow.py:full_pipeline",   # <파일경로>:<flow 함수명>
).deploy(
    name="dedicated-dep",
    work_pool_name="pool-1",        # ← 이 pool 로만 간다 (default 면 Shared)
    # work_queue_name="gpu",              # (선택) pool 안 특정 queue 로 더 좁힘
)

run_deployment(name="full-pipeline/dedicated-dep")   # 그 deployment 로 run 생성
```

> **코드 불변, pool 만 변경** — `work_pool_name` 을 python 코드에 직접 적는 대신 `prefect.yaml` 또는 `prefect deploy --pool <pool>` 로 분리하면, flow 코드를 고치지 않고 pool 만 바꿔 Shared ↔ Dedicated 를 전환할 수 있습니다.

### Credentials

코드가 **MinIO** (데이터·모델 저장소) 와 **PostgreSQL** 의 `catalog`·`optuna` DB 에 직접 접속하려면 자격증명 (`MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` / `MINIO_ENDPOINT` / `POSTGRESQL_CATALOG_DSN` / `POSTGRESQL_OPTUNA_DSN`) 이 필요합니다. 이 스택은 **Prefect Secret** 으로 다룹니다 — 값을 server 에 한 번 저장해 두면 코드가 실행 중 이름으로 받아 그대로 쓰므로, **머신마다 따로 넣을 필요가 없습니다.**

```python
# 저장 (admin, 1회) — server 에 등록
from prefect.blocks.system import Secret

Secret(value="<MINIO_ACCESS_KEY>").save("minio-access-key", overwrite=True)
# minio-secret-key / catalog-dsn / optuna-dsn 등도 동일하게 저장한다.
```

```python
# 사용 — flow 안에서 이름으로 로드
from prefect import flow
from prefect.blocks.system import Secret

@flow
def my_pipeline():
    ak = Secret.load("minio-access-key").get()   # server 에서 받아 그대로 사용
    ...
```

> `mlflow`·`prefect` DB 는 사용자 코드가 직접 접속하지 않습니다 — 코드는 MLflow REST API (`:5000`)·Prefect API (`:4200`) 로만 통신하고, 그 DB 는 MLflow server·Prefect server 가 각자 자기 `docker-compose.env` 의 계정으로 접속합니다. 따라서 사용자 role 에는 `catalog`·`optuna` DB 권한만 있으면 됩니다 (postgresql.md 의 Granular Database Access Control 참고).

## Appendix A. Terminology

- **Control Node** — 오케스트레이션 server 와 그 backend (메타데이터 DB·오브젝트 스토리지·실험 추적) 를 모아 띄우는 컴퓨터입니다.
- **Worker Node** — 실제 코드를 실행하는 worker 만 띄우는 컴퓨터입니다. Control Node 와 다른 컴퓨터일 수 있습니다.
- **`prefect_server`** — API·UI·스케줄러·work pool 대기열을 제공하는 중앙 진입점 (도커 컨테이너) 입니다. 메타데이터 (`prefect` DB) 만 관리하고 코드는 실행하지 않습니다.
- **`prefect_worker`** — work pool 에서 job 을 가져와 실제 코드를 실행하는 worker (도커 컨테이너) 입니다.
- **deployment** — flow 를 언제·어떻게 실행할지 (스케줄·파라미터·대상 work pool) 를 묶어 Prefect server 에 등록해 두는 실행 정의입니다. trigger 하면 이 정의대로 flow run 이 만들어집니다.
- **`CONTROL_NODE_HOST`** — Worker Node 가 Control Node 를 찾는 주소 (IP/호스트명) 입니다. 같은 컴퓨터에서 시험할 때는 `host.docker.internal` 을 씁니다.

**약자 (Abbreviations)**

- **AWS** = Amazon Web Services
- **GCP** = Google Cloud Platform
- **S3** = (Amazon) Simple Storage Service — MinIO 가 호환하는 오브젝트 스토리지 API
- **API** = Application Programming Interface
- **UI** = User Interface
- **DB** = Database
- **DSN** = Data Source Name (DB 접속 문자열)
- **CPU / GPU** = Central / Graphics Processing Unit

## Appendix B. Prefect CLI

`prefect` CLI 는 Prefect SDK 와 함께 설치되는 명령행 도구 (`pip install prefect`) 로, server·worker·work pool·deployment 를 다룹니다. 이 문서에서 쓰는 주요 명령만 정리합니다.

- `prefect config set PREFECT_API_URL="http://<Control Node IP>:4200/api"` — client 가 바라볼 server 주소를 프로필에 1회 저장합니다 (§5).
- `prefect config view` — 현재 프로필 설정을 확인합니다.
- `prefect server start --host 0.0.0.0` — Prefect server (API·UI·스케줄러·work pool 대기열) 를 기동합니다 (§2).
- `prefect work-pool create <name> --type process [--overwrite]` — work pool 을 만듭니다 (`--overwrite` 는 멱등이라 재실행해도 안전).
- `prefect work-pool ls` — work pool 목록을 봅니다.
- `prefect worker start --pool <name> [--limit N] [--work-queue <q>]` — worker 를 기동해 그 pool (또는 특정 queue) 을 폴링하며 job 을 실행합니다 (§3).
- `prefect deploy` (또는 `flow.deploy(name="...")`) — work pool mode 용 deployment 를 server 에 등록합니다 (§6).
- `prefect deployment run "<flow-name>/<deployment-name>"` — 등록된 deployment 를 trigger 합니다. 인자는 **`<flow-name>/<deployment-name>`** 형식으로, 예를 들어 `full-pipeline/local` 은 flow `full-pipeline` 의 `local` deployment 를 가리킵니다 (§6).

> `prefect config set` 으로 저장한 `PREFECT_API_URL` 은 그 머신의 프로필 (`~/.prefect`) 에 남아 이후 모든 CLI·SDK 호출에 적용됩니다. docker 컨테이너 안에서는 프로필 대신 `PREFECT_API_URL` 환경변수로 주입합니다 (§3 `command` 참고).

## Appendix C. docker-compose.env example

자격증명·endpoint 는 yml 에 평문으로 두지 않고 `docker-compose.env` 한 파일에 모읍니다. 컨테이너는 각 서비스가 `env_file` 로 읽습니다. 실제 값이 담긴 `docker-compose.env` 는 `.gitignore` 로 제외하고, 비밀값을 비운 아래 `docker-compose.env_example` 만 커밋합니다. Control Node 에는 server 섹션을, Worker Node 에는 worker 섹션을 채웁니다.

```dotenv
# docker-compose.env_example  (모든 값은 CHANGE_ME placeholder — 실제 값 노출 금지)

# ── prefect-server (Control Node) ──
PREFECT_SERVER_DATABASE_CONNECTION_URL=postgresql+asyncpg://CHANGE_ME:CHANGE_ME@postgres:5432/prefect

# ── prefect-worker (Worker Node) ──
CONTROL_NODE_HOST=CHANGE_ME       # Control Node 의 IP/호스트명. 같은 컴퓨터면 host.docker.internal
POSTGRES_USER=CHANGE_ME
POSTGRES_PASSWORD=CHANGE_ME
MINIO_ACCESS_KEY=CHANGE_ME
MINIO_SECRET_KEY=CHANGE_ME
AWS_ACCESS_KEY_ID=CHANGE_ME
AWS_SECRET_ACCESS_KEY=CHANGE_ME
```

- Control Node 의 server 는 `postgres` 서비스명으로 backend 에 접속하므로 URL 의 호스트가 `postgres` 입니다.
- Worker Node 는 `CONTROL_NODE_HOST` 로 Control Node 를 가리키며, `command` 안에서 이 값으로 API/MinIO/catalog DSN 을 조립합니다.
- 명령 안에서 자격증명을 참조할 때는 `$$VAR` (예: `$$POSTGRES_USER`) 로 적습니다. `$$` 는 compose 가 `$` 로 바꿔 컨테이너 셸이 `env_file` 값으로 확장합니다.
- 모든 `CHANGE_ME` 는 강한 값으로 교체하고, 실제 `docker-compose.env` 는 git 이 아니라 안전한 채널로 공유합니다.

## Appendix D. Additional Worker Attachment

> **선택 사항입니다.** Worker Node 하나로 충분하면 건너뛰어도 됩니다. user 가 자기 컴퓨터의 로컬 자원 (특히 GPU) 에서 학습을 돌리거나 처리량을 분산하고 싶을 때, 다른 머신에서 worker 를 더 띄워 같은 server 의 work pool 에 붙입니다.

worker 는 server 와 분리돼 있어 Control Node 를 변경하지 않고 그 머신에서 `prefect worker start` 만 하면 같은 server 의 work pool 에 합류합니다 (도커 Worker Node 와 동일한 메커니즘, 설치만 로컬 `pip`). 전제로 그 컴퓨터에서 Control Node (`http://<Control Node IP>:4200`) 에 네트워크로 접근 가능해야 합니다. 붙이는 방식은 **어느 pool 에 붙이느냐**에 따라 두 가지입니다 (deployment 등록·실행은 §6 Python Execution 참고).

### ① Shared — `default` pool 공유

`default` pool 을 여러 worker 가 공유해 job 을 분산합니다 (먼저 비는 worker 가 가져감, §6 Case D). 다른 머신에서:

```powershell
pip install prefect
prefect config set PREFECT_API_URL="http://<Control Node IP>:4200/api"   # §5 Server Connection
prefect work-pool create default --type process                          # 없으면 1회
prefect worker start --pool default                                      # default pool 폴링
```

- 여러 대를 붙여도 모두 `default` pool 을 공유합니다 (OS·하드웨어 무관).
- docker 로 붙이는 경우 — 같은 `docker-compose.worker.yml` 을 그 머신에서 `CREATE_POOL=false` 로 재사용합니다 (§3).

```powershell
$env:CREATE_POOL="false"; docker compose -f docker-compose.worker.yml up -d
```

### ② Dedicated — 전용 pool (특정 머신 고정)

특정 머신에서만 돌리려면 그 머신 전용 pool 을 만들고 그 머신의 worker 만 그 pool 을 폴링하게 합니다 (§6 Case E). deployment 를 그 pool 로 보내면 항상 그 머신에서 실행됩니다.

```powershell
# 전용 pool + 그 머신 worker
prefect work-pool create pool-1 --type process
prefect worker start --pool pool-1
```

- 더 좁히려면 한 pool 안에서 **work queue** 를 나눠 `prefect worker start --pool <pool> --work-queue <name>` 로 특정 queue 만 폴링하게 합니다.
- docker 로 붙일 때는 같은 `docker-compose.worker.yml` 에 `CREATE_POOL=false WORK_POOL=pool-1` 로 띄웁니다 (전용 pool 은 첫 worker 만 `CREATE_POOL=true`).

```powershell
$env:CREATE_POOL="false"; $env:WORK_POOL="pool-1"; docker compose -f docker-compose.worker.yml up -d
```

