# Prefect with Docker Work Pool

Prefect stack 을 **Control Node 와 Worker Node 로 나눠** 도커로 실행하는 방법을 설명합니다. 여기서 **Node** 는 서비스 컨테이너를 띄우는 한 대의 컴퓨터 (물리 머신 또는 VM) 를 가리킵니다. Control Node 는 오케스트레이션 server 와 그 backend (메타데이터 DB·오브젝트 스토리지·실험 추적) 를 모아 띄우고, Worker Node 는 job 을 받아 실행 환경을 만드는 디스패처만 띄워 네트워크로 Control Node 에 붙습니다.

이 구성은 **여러 팀원이 여러 코드베이스를 개발하고 동시에 다수 job 을 trigger** 하는 상황을 전제로, 실행을 도커 컨테이너 단위로 격리하는 **Docker work pool** 구조를 주력으로 합니다. job 마다 깨끗한 컨테이너가 떠서 코드를 실행하므로 run 들이 서로 간섭하지 않습니다. 단일 머신·소규모 구성에는 [Appendix F](#appendix-f-process-work-pool) 의 process work pool 또는 serve mode 가 더 단순합니다.

Prefect server (`prefect_server`) 는 job 요청을 중앙에서 수집·스케줄링하는 **단일 진입점 (Single Point of Entry)** 입니다. 다만 **`prefect_server` 는 코드를 실행하지 않습니다** — 코드는 항상 실행기 (run 컨테이너 또는 `python` 프로세스) 가 떠 있는 컴퓨터에서 실행됩니다.

## 1. Architecture

이 구성은 두 층으로 나뉘며, 두 층은 같은 컴퓨터에서 돌 수도 있고 서로 다른 컴퓨터에서 돌 수도 있습니다.

| Layer | Services | Connection |
|-------|----------|----------|
| **Control Node** | `postgres` · `minio` · `mlflow` · `prefect_server` | 같은 호스트에서 공유 네트워크 `mlops` 로 묶여 서비스명으로 통신합니다. |
| **Worker Node** | `prefect_pool` (디스패처) + job 마다 뜨는 `prefect_worker` 컨테이너 | 같은 머신이면 `mlops` 네트워크로, 다른 머신이면 `CONTROL_NODE_HOST` (Control Node 의 IP/호스트명) 로 접속합니다. |

Worker Node 의 두 역할은 다음과 같이 나뉩니다. 이 문서는 사용자 구분에 맞춰 디스패처를 `prefect_pool`, 실행 이미지를 `prefect_worker` 로 부릅니다 (Prefect 공식 용어로는 디스패처도 "worker" 라 부릅니다).

| 이름 | Prefect 용어 | 역할 | 구성 |
|------|--------------|------|------|
| **`prefect_pool`** | docker-type worker (디스패처) | docker work pool 을 폴링해 job 마다 컨테이너를 띄우고 끝나면 정리합니다. 코드는 실행하지 않습니다. | `prefect` + `prefect-docker` + 호스트 도커 소켓 |
| **`prefect_worker`** | per-run 실행 이미지 | 디스패처가 job 마다 띄우는 AI/ML python 컨테이너입니다. 기동 시 코드를 받아 실제로 실행합니다. | python + 라이브러리 (torch·boto3 등) |

- **Control Node** 의 서비스들은 한 컴퓨터 안에서 도커 네트워크 `mlops` 를 공유하므로, 서로를 `postgres:5432` · `minio:9000` 처럼 **서비스명** 으로 찾습니다.
- **같은 머신** 에서 Worker Node 를 띄우면 디스패처와 run 컨테이너도 `mlops` 에 붙어 `prefect_server:4200` · `minio:9000` 을 서비스명으로 찾습니다 (`CONTROL_NODE_HOST` 기본값 `prefect_server`).
- **다른 머신** 에서 Worker Node 를 띄우면 도커 네트워크를 공유할 수 없으므로, Control Node 가 노출한 포트로 **IP/호스트명** 을 통해 접속합니다. 그 주소를 `CONTROL_NODE_HOST` 로 지정하고 `mlops` 네트워크 설정은 제거합니다.

각 서비스의 역할은 다음과 같습니다.

| Service | Endpoint | Description |
|---------|----------|------|
| `postgres` | `:5432` | 메타데이터 DB 입니다. 한 인스턴스에서 `prefect`/`mlflow`/`optuna`/`catalog` 4개 논리 DB 를 운영합니다. |
| `minio` | `:9000` (S3 API) · `:9001` (console) | 오브젝트 스토리지입니다. 데이터·모델·아티팩트를 보관합니다. |
| `mlflow` | `:5000` | 실험 추적 server + 모델 레지스트리입니다. backend 는 `postgres`, artifact 는 `minio` 입니다. |
| `prefect_server` | `:4200` | Prefect server + 대시보드 (UI) 입니다. backend 는 `postgres` 입니다. |
| `prefect_pool` | — | docker work pool 을 폴링해 job 마다 `prefect_worker` 컨테이너를 띄웁니다. |

> `postgres` · `minio` · `mlflow` 는 각자 자기 폴더의 compose 로 Control Node 에서 띄웁니다. 이 문서는 그중 **Prefect server 와 디스패처** 의 설치·실행에 집중합니다.

## 2. Prefect Server Setup

Control Node 에서 실행합니다. server 는 backend 인 `postgres` 가 같은 Control Node 에서 먼저 떠 있어야 정상 동작하므로, **PostgreSQL → (MinIO/MLflow) → Prefect server** 순으로 띄우길 권장합니다.

```powershell
# (최초 1회) 예시 파일을 복사해 server 섹션의 값을 채운다. docker-compose.env 는 git 에 커밋하지 않는다.
Copy-Item docker-compose.env_example docker-compose.env

# 공유 네트워크 mlops 를 만들고 (이미 있으면 에러는 무시) server 를 백그라운드로 띄운다.
docker network create mlops
docker compose -p <Project Name> -f docker-compose.server.yml up -d
```

실행 후 Prefect 대시보드는 **`http://<Control Node IP>:4200`** 에서 열립니다 (같은 컴퓨터에서는 `localhost`).

채워 넣을 `docker-compose.env` 의 server 섹션과 compose 정의입니다 (값은 `CHANGE_ME` placeholder).

```dotenv
# server backend (PostgreSQL prefect DB) 접속 URL — PREFECT_SERVER_DATABASE_CONNECTION_URL 은 Prefect 표준 변수다.
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

## 3. Worker Setup

Worker Node 에서 디스패처 (`prefect_pool`) 를 띄웁니다. 디스패처는 docker work pool 을 폴링하다가 job 마다 **실행 이미지 (`prefect_worker`) 로 컨테이너를 새로 띄워** 코드를 실행시키고, 끝나면 정리합니다. 준비물은 세 가지입니다 — ① 실행 이미지, ② run 컨테이너 공통 설정 (base job template), ③ 디스패처 compose.

### 3.1 Run Image (`prefect_worker`)

job 마다 뜨는 컨테이너의 python 환경입니다. **코드는 굽지 않고** (run 시점에 git 으로 전달), python·prefect·라이브러리만 고정합니다. `git` 은 run 시점 코드 전달 (clone) 에 필요하므로 설치합니다.

```dockerfile
# Dockerfile — 팀 표준 AI/ML 실행 이미지
FROM prefecthq/prefect:3-python3.11
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/prefect
COPY requirements.txt .               # boto3·psycopg2-binary·mlflow·optuna·pandas·torch 등
RUN pip install --no-cache-dir -r requirements.txt
# 코드는 COPY 하지 않는다(run 시점에 git 으로 전달).
```

```powershell
# 실행 이미지를 빌드한다. 여러 머신을 쓰면 레지스트리에 push/pull 하거나 머신마다 빌드한다.
docker build -t prefect-worker:py311 .
```

> 라이브러리를 바꾸면 이 이미지를 다시 빌드하고 태그를 올립니다 (`prefect-worker:py312` 등). 이미지 태그가 곧 **런타임 버전** 입니다 ([§7](#7-code-delivery--versioning)).

### 3.2 Base Job Template

디스패처가 띄우는 모든 run 컨테이너에 공통 적용할 설정입니다. 실행 이미지·환경변수·네트워크를 여기 둡니다. run 컨테이너는 디스패처의 마운트·네트워크를 상속하지 않으므로, **`PREFECT_API_URL` 과 네트워크를 반드시 여기서 주입** 해야 합니다.

```json
{
  "variables": {
    "type": "object",
    "properties": {
      "image":   { "type": "string", "default": "prefect-worker:py311" },
      "env":     { "type": "object", "additionalProperties": { "type": "string" },
                   "default": { "PREFECT_API_URL": "http://prefect_server:4200/api" } },
      "networks":{ "type": "array",  "items": { "type": "string" }, "default": ["mlops"] },
      "auto_remove": { "type": "boolean", "default": true }
    }
  },
  "job_configuration": {
    "image":       "{{ image }}",
    "env":         "{{ env }}",
    "networks":    "{{ networks }}",
    "auto_remove": "{{ auto_remove }}"
  }
}
```

- `image` — run 컨테이너로 쓸 실행 이미지입니다 (§3.1 에서 빌드한 것).
- `env.PREFECT_API_URL` — run 컨테이너가 server·Secret 블록을 찾는 주소입니다. 같은 머신 + `mlops` 면 서비스명 `prefect_server`, 다른 머신이면 `http://<Control Node IP>:4200/api` 로 바꿉니다.
- `networks` — run 컨테이너가 붙을 네트워크입니다. 같은 머신이면 `mlops` 로 두어 `minio`·`prefect_server` 를 서비스명으로 찾습니다. 다른 머신이면 비우고 `env` 의 주소를 IP 로 둡니다.
- `auto_remove: true` — run 이 끝나면 컨테이너를 자동 삭제합니다.

> 위는 핵심만 추린 예시입니다. 도커 worker 의 base job template 은 Prefect 버전에 따라 필드가 다를 수 있으므로, 정확한 최신 기본 템플릿은 `prefect work-pool get-default-base-job-template --type docker` 로 받아 위 `image`·`env`·`networks` 의 `default` 만 채워 쓰는 것을 권장합니다.

### 3.3 Dispatcher

디스패처는 호스트 도커 소켓을 마운트해 형제 (sibling) 컨테이너를 띄웁니다. docker worker 는 `prefect-docker` 패키지가 필요하므로 기동 시 설치합니다 (이미지로 구우려면 별도 Dockerfile 로 만듭니다).

```powershell
# (최초 1회) 예시 파일을 복사해 worker 섹션 (CONTROL_NODE_HOST) 을 채운다.
Copy-Item docker-compose.env_example docker-compose.env

# 같은 머신이면 mlops 가 필요하다(없으면 1회 생성). 디스패처를 백그라운드로 띄운다.
docker network create mlops
docker compose -p <Project Name> -f docker-compose.worker.yml up -d
```

```yaml
# docker-compose.worker.yml
services:
  prefect_pool:
    image: prefecthq/prefect:3-latest
    env_file:
      - docker-compose.env          # CONTROL_NODE_HOST (같은 머신+mlops 면 prefect_server)
    command: >
      bash -c "pip install --no-cache-dir prefect-docker &&
               export PREFECT_API_URL=http://$${CONTROL_NODE_HOST:-prefect_server}:4200/api &&
               if [ ${CREATE_POOL:-true} = true ]; then
                 prefect work-pool create ${WORK_POOL:-docker-pool} --type docker --base-job-template /opt/template.json --overwrite;
               fi &&
               prefect worker start --pool ${WORK_POOL:-docker-pool} --limit ${WORKER_LIMIT:-8}"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock   # 형제 컨테이너 기동용 호스트 도커 소켓
      - ./docker-pool-template.json:/opt/template.json:ro
    networks:
      - mlops                        # 같은 머신이면 prefect_server·minio 를 서비스명으로 찾는다.
    restart: unless-stopped

networks:
  mlops:
    external: true
```

- `volumes: /var/run/docker.sock` — 디스패처가 호스트 도커 데몬에 명령해 run 컨테이너를 띄우는 통로입니다. Windows/Docker Desktop 도 리눅스 컨테이너에 같은 경로로 노출됩니다.
- `command` — `prefect-docker` 설치 → `PREFECT_API_URL` 설정 → docker pool 생성 (base job template 적용) → `prefect worker start` 순입니다. `CREATE_POOL`·`WORK_POOL`·`WORKER_LIMIT` 는 `docker compose up` 시점에 셸에서 읽는 compose 변수입니다 (미설정 시 `true`·`docker-pool`·`8`).
- `$${CONTROL_NODE_HOST:-prefect_server}` — `env_file` 의 `CONTROL_NODE_HOST` 가 비어 있으면 같은 머신 기준 서비스명 `prefect_server` 로 떨어집니다. `$$` 는 compose 가 `$` 로 바꿔 컨테이너 셸이 확장합니다.
- `--limit` 은 이 디스패처가 **동시에 띄우는 run 컨테이너 수의 상한** 입니다 ([Concurrency & Scaling](#concurrency--scaling)).

> **보안 주의** — 도커 소켓 마운트는 디스패처에 호스트 도커 전체 제어권 (사실상 root 권한) 을 줍니다. 신뢰된 내부망·스터디 용도로 한정하고, 외부에 노출하지 않습니다. 더 강한 격리가 필요하면 Kubernetes work pool 을 고려합니다 (이 문서 범위 밖).

### Concurrency & Scaling

docker pool 은 run 마다 **별도 컨테이너** 라 동시 실행이 자연히 격리·병렬화됩니다. 동시 실행량은 세 가지로 조절합니다.

- **디스패처 `--limit`** — 한 디스패처가 동시에 띄우는 run 컨테이너 수의 상한입니다 (현재 8). 상한을 넘는 job 은 slot 이 빌 때까지 대기합니다.
- **pool concurrency limit** — pool 전체의 동시 실행 상한입니다 (`prefect work-pool set-concurrency-limit <pool> <N>`). 여러 디스패처를 붙여도 pool 단위로 묶어 제한합니다.
- **컨테이너 자원 상한** — base job template 의 `mem_limit` 등으로 run 컨테이너당 자원을 제한합니다. GPU 학습처럼 1 job 이 자원을 많이 쓰면 `--limit` 을 1~2 로 낮춥니다.

처리량을 늘리려면 `--limit` 을 키우거나, 여러 머신에서 디스패처를 더 띄워 같은 pool 에 붙입니다 ([Appendix D](#appendix-d-additional-dispatcher-attachment)). 다만 Worker Node 의 CPU/GPU/메모리 한도 안에서 정합니다 (자원 경합 시 오히려 느려집니다).

### GPU

run 컨테이너에서 GPU 를 쓰려면 호스트에 NVIDIA 드라이버와 nvidia-container-toolkit 이 설치돼 있어야 하고, base job template 에서 GPU 를 요청해야 합니다 (`--gpus all` 에 해당하는 device request). torch 의 CUDA 휠은 런타임을 번들하므로 호스트 드라이버가 충분히 최신이면 동작하며, 버전이 맞지 않으면 베이스 이미지를 `nvidia/cuda` 계열로 교체합니다.

## 4. Execution Architecture

Prefect 실행에는 **두 가지 모드** 가 있고, 차이는 **누가 (어떤 python 이) 코드를 실행하느냐** 입니다.

### 1) Serve Mode (Push-Based / Static)

- **구조**: 개발자가 코드가 실행될 프로세스를 미리 구동해 놓는 구조입니다.
- **동작**: `flow.serve()` 가 든 python script 를 실행하면, 그 python 프로세스가 server 에 **deployment** (flow 를 언제·어떻게 실행할지 묶어 server 에 등록해 두는 실행 정의) 를 등록하고 상시 떠서 신호를 수신하다가, trigger 되면 **자기 자신이** 코드를 즉시 실행합니다.
- **장점**: architecture 가 단순하여 별도 디스패처·pool 이 필요 없습니다. 단일 머신·단순 구성에 적합합니다.

### 2) Work Pool Mode (Pull-Based / Dynamic)

- **구조**: server 와 실제 실행 인프라 사이에 Work Pool (큐) 과 Worker (디스패처) 를 두는 분산 구조입니다.
- **동작**: `flow.deploy()` (또는 `prefect deploy`) 로 등록만 하고 python 은 종료됩니다. 디스패처가 주기적으로 pool 에서 job 을 가져와 실행 환경을 만들어 실행하고, 끝나면 정리합니다.
- **pool 타입** — 실행 환경을 어떻게 만드느냐로 갈립니다.
  - **process pool** — 디스패처 **자신의 프로세스** 로 실행합니다. 디스패처 환경에 라이브러리가 있어야 하며, run 들이 같은 컨테이너를 공유합니다 (단일/소규모: [Appendix F](#appendix-f-process-work-pool)).
  - **docker pool (주력)** — job 마다 **새 컨테이너** 를 띄워 그 안에서 실행합니다. run 마다 격리되고, 이미지를 job 단위로 지정할 수 있어 여러 팀원·여러 코드베이스·동시 실행에 적합합니다.

### Comparison

| Aspect | Serve Mode | Work Pool — process | Work Pool — docker |
|--------|------------|---------------------|--------------------|
| Register | `flow.serve()` | `flow.deploy()` | `flow.deploy()` |
| Code executor | serve 를 띄운 python | 디스패처 프로세스 | job 마다 뜨는 컨테이너 |
| Isolation | 단일 프로세스 | run 들이 공유 | run 마다 컨테이너 격리 |
| Dependencies | 그 python 환경 | 디스패처 환경 | run 이미지 (job 별 지정) |
| Best for | 단일 머신·단순 | 단일/소규모 | 다수 팀원·동시 실행 |

- **공통 — 등록** — 세 방식 모두 deployment 정의를 server 에 올리는 **등록** 은 같고, **server 자체는 코드를 실행하지 않습니다** (이름표만 보관).
- **핵심 차이 — 실행 주체** — 코드를 실제로 실행하는 python 이 누구냐가 갈립니다. docker pool 은 job 마다 뜨는 컨테이너의 python 이 실행하므로, 그 이미지에 라이브러리가 있어야 합니다.

## 5. Execution Topology

### Server Connection

Python client (디스패처 또는 job 을 trigger 하는 노드) 가 **어느 Prefect server 에 연결할지** 주소를 지정합니다. **최초 1회** 설정하면 이후 모든 client 명령이 이 server 를 향합니다.

```powershell
prefect config set PREFECT_API_URL="http://<Control Node IP>:4200/api"
# 같은 컴퓨터면 <Control Node IP>=localhost, 다른 컴퓨터의 server 면 그 IP/호스트명을 쓴다.
```

이 설정은 job 을 **trigger** 할 때 (`prefect deployment run ...`), **deployment 를 등록** 할 때, **Prefect Secret 블록을 등록/조회** 할 때 등 server 와 통신하는 client 작업 전반에 필요합니다.

### Code-to-Worker Flow

trigger 는 코드를 보내지 않습니다. **deployment 에는 코드의 "참조" (git 위치 + entrypoint) 만** 등록되고, 코드는 run 컨테이너가 직접 가져옵니다.

```
[client] trigger ─▶ [server] 큐에 run 등록 ─▶ [prefect_pool] job 을 가져옴
                                                   │
                                                   ├─ ① run 이미지로 컨테이너를 띄운다
                                                   ├─ ② 컨테이너가 deployment 의 git ref 를 clone(코드 전달)
                                                   └─ ③ 컨테이너의 python 으로 entrypoint flow 실행 → 종료 시 정리
```

코드 전달·버전 고정의 상세는 [§7](#7-code-delivery--versioning) 을 참고합니다.

## 6. Python Execution

flow 를 등록·실행하는 방식입니다. flow 코드는 같고 **등록·라우팅 방식만** 다릅니다. 아래 예시의 이름은 placeholder 이며 실제 값으로 바꿔 씁니다.

- **flow 이름**: `ai-full-pipeline` (`@flow(name="ai-full-pipeline")`) — 함수는 `full_pipeline`.
- **entrypoint**: `flow.py:full_pipeline` — `<파일경로>:<flow 함수명>`.
- **git 소스**: `<git-repo-url>` (예: `https://github.com/<org>/<repo>.git`), 브랜치/커밋 `<ref>`.
- **work pool**: `docker-pool`.

### Work Pool Mode (Docker)

deployment 를 git 소스로 등록하면, run 컨테이너가 기동 시 그 소스를 clone 해 코드를 받습니다. 팀원·코드베이스마다 자기 repo (또는 브랜치) 로 deployment 를 따로 등록합니다.

```powershell
# CLI — git 소스로 등록 후 실행
prefect deploy flow.py:full_pipeline -n member1 --pool docker-pool
prefect deployment run "ai-full-pipeline/member1"
```

```python
# Python — git 소스로 등록 후 실행
from prefect import flow
from prefect.deployments import run_deployment

flow.from_source(
    source="<git-repo-url>",              # run 컨테이너가 clone 할 코드 위치
    entrypoint="flow.py:full_pipeline",   # <파일경로>:<flow 함수명>
).deploy(
    name="member1",
    work_pool_name="docker-pool",
    image="prefect-worker:py311",         # run 컨테이너로 쓸 실행 이미지
    build=False, push=False,              # 코드는 굽지 않고 git 으로 전달하므로 이미지 빌드/푸시를 끈다
)

run_deployment("ai-full-pipeline/member1")
```

- `from_source(source=<git-repo-url>)` — run 시점에 그 repo 를 clone 하는 pull step 을 deployment 에 넣습니다. 특정 커밋/태그로 고정하면 재현 가능합니다 ([§7](#7-code-delivery--versioning)).
- `image=` — base job template 의 기본 이미지를 deployment 별로 덮어쓸 때 지정합니다 (대부분 template 기본값으로 충분).
- `build=False, push=False` — 코드를 이미지에 굽지 않으므로 (git 전달) 이미지 빌드·푸시 단계를 건너뜁니다.

> **Dedicated pool (특정 머신 고정)** — 특정 머신 (예: GPU 머신) 에서만 실행하려면 그 머신 전용 pool 을 만들고 그 pool 로 deployment 를 보냅니다 (`work_pool_name="docker-gpu"`). 전용 pool 에 디스패처를 붙이는 방법은 [Appendix D](#appendix-d-additional-dispatcher-attachment) 를 참고합니다.

### Serve Mode

`flow.serve()` 를 띄운 python 프로세스가 deployment 를 등록하고 **자기 자신이** 코드를 실행합니다 (pool·디스패처 불필요). 단일 머신·단순 구성에 적합합니다.

```python
from prefect import flow

@flow(name="ai-full-pipeline")
def full_pipeline():
    ...

if __name__ == "__main__":
    full_pipeline.serve(name="local")   # 이 프로세스가 상시 떠서 직접 실행
```

```powershell
prefect deployment run "ai-full-pipeline/local"     # 등록된 deployment 를 trigger
```

### Credentials

코드가 **MinIO** (데이터·모델 저장소) 와 **PostgreSQL** 의 `catalog`·`optuna` DB 에 직접 접속하려면 자격증명 (`MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` / `MINIO_ENDPOINT` / `POSTGRESQL_CATALOG_DSN` / `POSTGRESQL_OPTUNA_DSN`) 이 필요합니다. 이 스택은 **Prefect Secret** 으로 다룹니다 — 값을 server 에 한 번 저장해 두면 run 컨테이너의 코드가 실행 중 이름으로 받아 그대로 쓰므로, **컨테이너·머신마다 따로 넣을 필요가 없습니다.** 디스패처는 자격증명을 들고 있지 않아도 됩니다.

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

> run 컨테이너는 base job template 의 `PREFECT_API_URL` 로 server 에 연결되어 있어야 Secret 을 받을 수 있습니다 (§3.2). `mlflow`·`prefect` DB 는 사용자 코드가 직접 접속하지 않습니다 — 코드는 MLflow REST API (`:5000`)·Prefect API (`:4200`) 로만 통신하므로, 사용자 role 에는 `catalog`·`optuna` DB 권한만 있으면 됩니다.

## 7. Code Delivery & Versioning

Prefect 자체는 코드를 버전관리하지 않습니다 (오케스트레이터일 뿐). 코드 버전은 **git 소스로 전달하며 무엇으로 고정하느냐** 로 정해집니다.

| 고정 대상 | 의미 | 재현성 |
|-----------|------|--------|
| git **브랜치** | run 마다 그 브랜치 최신 커밋을 clone | "그 시점 최신" (재현 보장 안 됨) |
| git **커밋/태그** | run 마다 고정된 커밋을 clone | **완전 재현** |
| **run 이미지 태그** | 런타임 (라이브러리) 버전 고정 | 라이브러리까지 재현 |

- **코드 버전** — deployment 의 git 소스를 **커밋/태그로 고정** 하면, 트리거 시점과 무관하게 항상 같은 코드가 실행됩니다. 활발히 개발 중이면 브랜치로 두고, 재현이 필요한 run 은 커밋으로 고정합니다.
- **런타임 버전** — 실행 이미지 태그 (`prefect-worker:py311`) 가 라이브러리 버전을 고정합니다. 라이브러리를 바꾸면 새 태그로 빌드합니다.
- **모델 ↔ 코드 연결** — MLflow 는 git repo 안에서 run 을 돌리면 git 커밋 SHA 를 자동 태그로 남기므로, "이 모델이 어떤 코드로 학습됐나" 는 MLflow 의 git 커밋 태그로 추적됩니다 (데이터 lineage 는 catalog 가 담당).

> **Private repo** — `from_source` 의 git clone 이 private repo 면 토큰이 필요합니다. 토큰을 Prefect Secret/credentials 블록에 저장해 pull step 에서 참조하거나 인증된 clone URL 을 씁니다. public repo 면 plain URL 로 충분합니다.

## Appendix A. Terminology

- **Control Node** — 오케스트레이션 server 와 그 backend (메타데이터 DB·오브젝트 스토리지·실험 추적) 를 모아 띄우는 컴퓨터입니다.
- **Worker Node** — job 을 받아 실행 환경을 만드는 디스패처를 띄우는 컴퓨터입니다. Control Node 와 다른 컴퓨터일 수 있습니다.
- **`prefect_server`** — API·UI·스케줄러·work pool 대기열을 제공하는 중앙 진입점 (도커 컨테이너) 입니다. 메타데이터 (`prefect` DB) 만 관리하고 코드는 실행하지 않습니다.
- **`prefect_pool` (디스패처)** — docker work pool 을 폴링해 job 마다 컨테이너를 띄우고 정리하는 worker (도커 컨테이너) 입니다. 코드는 실행하지 않습니다.
- **`prefect_worker` (실행 이미지)** — 디스패처가 job 마다 띄우는 AI/ML python 컨테이너입니다. git 으로 받은 코드를 실제로 실행합니다.
- **work pool** — job 이 대기하는 큐이자 실행 방식 (process/docker) 의 정의입니다.
- **deployment** — flow 를 언제·어떻게·어떤 코드 (git 소스) 로 실행할지 묶어 server 에 등록해 두는 실행 정의입니다.
- **base job template** — pool 이 띄우는 run 컨테이너의 공통 설정 (이미지·env·네트워크) 입니다.
- **`CONTROL_NODE_HOST`** — Worker Node 가 Control Node 를 찾는 주소 (IP/호스트명) 입니다. 같은 머신 + `mlops` 면 서비스명 `prefect_server` 입니다.

**약자 (Abbreviations)**

- **AWS** = Amazon Web Services
- **S3** = (Amazon) Simple Storage Service — MinIO 가 호환하는 오브젝트 스토리지 API
- **API** = Application Programming Interface
- **UI** = User Interface
- **DB** = Database
- **DSN** = Data Source Name (DB 접속 문자열)
- **CPU / GPU** = Central / Graphics Processing Unit

## Appendix B. Prefect CLI

`prefect` CLI 는 Prefect SDK 와 함께 설치되는 명령행 도구 (`pip install prefect`) 입니다. 이 문서에서 쓰는 주요 명령만 정리합니다.

- `prefect config set PREFECT_API_URL="http://<Control Node IP>:4200/api"` — client 가 바라볼 server 주소를 프로필에 1회 저장합니다 (§5).
- `prefect server start --host 0.0.0.0` — Prefect server 를 기동합니다 (§2).
- `prefect work-pool create <name> --type docker --base-job-template <file> [--overwrite]` — docker work pool 을 만듭니다 (§3.3).
- `prefect work-pool get-default-base-job-template --type docker` — 도커 worker 의 기본 base job template 을 출력합니다 (§3.2).
- `prefect work-pool set-concurrency-limit <pool> <N>` — pool 전체 동시 실행 상한을 설정합니다.
- `prefect work-pool ls` — work pool 목록을 봅니다.
- `prefect worker start --pool <name> [--limit N]` — 디스패처를 기동해 그 pool 을 폴링하며 job 을 실행합니다 (§3.3).
- `prefect deploy` (또는 `flow.from_source(...).deploy(...)`) — git 소스 deployment 를 등록합니다 (§6).
- `prefect deployment run "<flow-name>/<deployment-name>"` — 등록된 deployment 를 trigger 합니다 (§6).

## Appendix C. docker-compose.env example

자격증명·endpoint 는 yml 에 평문으로 두지 않고 `docker-compose.env` 한 파일에 모읍니다. 실제 값이 담긴 `docker-compose.env` 는 `.gitignore` 로 제외하고, 비밀값을 비운 `docker-compose.env_example` 만 커밋합니다. Control Node 에는 server 섹션을, Worker Node 에는 worker 섹션을 채웁니다.

```dotenv
# docker-compose.env_example  (모든 값은 placeholder — 실제 값 노출 금지)

# ── prefect-server (Control Node) ──
PREFECT_SERVER_DATABASE_CONNECTION_URL=postgresql+asyncpg://CHANGE_ME:CHANGE_ME@postgres:5432/prefect

# ── prefect-worker (디스패처, Worker Node) ──
# 디스패처가 Prefect server 를 찾는 주소. 같은 머신+mlops 면 서비스명 prefect_server,
# 다른 머신이면 머신 A 의 IP/호스트명(이때 worker compose 의 networks 블록은 제거).
CONTROL_NODE_HOST=prefect_server
```

- Control Node 의 server 는 `postgres` 서비스명으로 backend 에 접속하므로 URL 의 호스트가 `postgres` 입니다.
- 디스패처는 코드를 실행하지 않으므로 MinIO·카탈로그 자격증명이 필요 없습니다 — 그 값들은 run 컨테이너의 코드가 Prefect Secret 블록으로 받아 씁니다 (§6 Credentials).

## Appendix D. Additional Dispatcher Attachment

> **선택 사항입니다.** Worker Node 하나로 충분하면 건너뛰어도 됩니다. 처리량을 분산하거나 특정 머신 (예: GPU) 에서만 실행하려면 다른 머신에서 디스패처를 더 띄워 같은 server 의 work pool 에 붙입니다.

디스패처는 server 와 분리돼 있어 Control Node 를 변경하지 않고 그 머신에서 docker work pool 을 폴링하기만 하면 합류합니다. 전제로 그 컴퓨터에서 Control Node (`http://<Control Node IP>:4200`) 에 네트워크로 접근 가능해야 하고, 실행 이미지가 있어야 합니다.

### ① Shared — 같은 pool 공유

같은 `docker-pool` 을 여러 디스패처가 공유해 job 을 분산합니다 (먼저 비는 디스패처가 가져감). 다른 머신에서 같은 `docker-compose.worker.yml` 을 `CREATE_POOL=false` 로 재사용합니다 (다른 머신이면 `CONTROL_NODE_HOST` 를 IP 로, `networks` 블록은 제거).

```powershell
$env:CREATE_POOL="false"; docker compose -p <Project Name> -f docker-compose.worker.yml up -d
```

### ② Dedicated — 전용 pool (특정 머신 고정)

특정 머신에서만 실행하려면 그 머신 전용 pool 을 만들고 그 머신의 디스패처만 그 pool 을 폴링하게 합니다. deployment 를 그 pool 로 보내면 항상 그 머신에서 실행됩니다.

```powershell
$env:WORK_POOL="docker-gpu"; docker compose -p <Project Name> -f docker-compose.worker.yml up -d
```

## Appendix E. Monitoring

work pool·디스패처·flow run 상태를 확인하는 방법입니다.

- **work pool** — `prefect work-pool ls` (목록), `prefect work-pool inspect <pool>` (상세·base job template).
- **디스패처** — UI `http://<Control Node IP>:4200` 의 Work Pools → 해당 pool → Workers (online 여부·last polled). 디스패처는 heartbeat 로 추적되어 끄면 잠시 뒤 offline 으로 바뀝니다.
- **run 컨테이너** — Worker Node 에서 `docker ps` 로 job 마다 뜬 컨테이너를 직접 봅니다 (`auto_remove` 라 끝나면 사라집니다).
- **flow run** — UI 의 Flow Runs 에서 상태·로그를, CLI 는 `prefect flow-run ls` 로 최근 run 목록을 봅니다.

## Appendix F. Process Work Pool

단일 머신·소규모 구성에서는 컨테이너를 매 run 띄우는 대신 디스패처 **자신의 프로세스** 로 실행하는 process pool 이 더 단순합니다. 이때는 디스패처 환경에 라이브러리를 직접 설치해야 하고, 코드는 bind-mount 또는 git 으로 그 머신에 둡니다. run 들이 같은 프로세스 공간을 공유하므로 격리는 약합니다.

```yaml
# docker-compose.worker.yml (process 변형 — 단일/소규모)
services:
  prefect_worker:
    image: prefecthq/prefect:3-python3.11
    env_file:
      - docker-compose.env
    command: >
      bash -c "pip install -r /app/requirements.txt &&
               export PREFECT_API_URL=http://$${CONTROL_NODE_HOST:-prefect_server}:4200/api &&
               prefect work-pool create ${WORK_POOL:-default} --type process --overwrite &&
               prefect worker start --pool ${WORK_POOL:-default} --limit ${WORKER_LIMIT:-8}"
    volumes:
      - ../../Prefect:/app          # flow 코드가 있는 폴더를 마운트한다.
    working_dir: /app
    networks:
      - mlops
    restart: unless-stopped

networks:
  mlops:
    external: true
```

- process pool 은 코드를 마운트된 디스크에서 읽으므로, run 컨테이너로 코드를 전달하는 git pull 단계가 없습니다. 대신 그 머신에 코드가 있어야 합니다.
- 라이브러리를 매번 설치하지 않으려면 §3.1 처럼 이미지를 빌드해 `build:` 로 씁니다.
