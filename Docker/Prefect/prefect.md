# Prefect with Docker Work Pools

> 공식 사이트: [https://www.prefect.io/](https://www.prefect.io/)

Prefect stack 을 한 호스트에서 **세 구성요소 (Prefect Server · Prefect Worker · Pipeline Flow)** 로 나눠 도커로 실행합니다. 실행 방식은 두 가지입니다 — **Short Term Container** (job 마다 컨테이너를 띄웠다 파괴, ephemeral docker-container-per-job) 와 **Long Term Container** (상시 컨테이너 재사용). 이 문서는 **여러 팀원이 동시에 다수 job 을 trigger** 하는 환경을 전제로, 격리·동시성에 유리한 **Short Term Container 를 주력**으로 하며 Prefect 의 **Docker work pool** 로 구현합니다.

Prefect server (`prefect_server`) 는 job 을 수집·스케줄링하는 **단일 진입점** 입니다. 단 **코드는 실행하지 않습니다** — 실행은 항상 Pipeline Flow 컨테이너 안에서 일어납니다.

단일 머신·소규모 구성에는 serve mode 가 더 단순합니다.

## 1. Architecture

모든 구성요소는 한 호스트에서 공유 네트워크 `mlops` 로 묶입니다. `prefect_server` 와 `prefect_worker` (dispatcher) 가 상시 떠 있고, job 마다 **Pipeline Flow 컨테이너** 가 실행 (일시, 상시) 됩니다.

| Component | Prefect term | Role | Lifetime |
|----------|--------------|------|----------|
| **1. Prefect Server** | server | job 수집·스케줄링·UI. 실행 파라미터<br>(`git_commit`·`minio_version`) 전달.<br>코드는 실행하지 않습니다. | 상시 |
| **2. Prefect Worker** | dispatcher / executor | Short Term (주력): pool 을 polling 해<br>job 마다 Pipeline Flow 컨테이너를 띄웁니다.<br>Long Term: 자기 컨테이너에서 flow 직접 실행. | 상시 |
| **3. Pipeline Flow** | execution unit | flow (코드) 가 실행되는 곳입니다.<br>Short Term 은 job 마다 뜨는 전용 컨테이너,<br>Long Term 은 Prefect Worker 안 (별도 없음). | Short Term: 일시적 / Long Term: 상시 |

**Short-Term Pipeline Flow 예시:**

```
[ host server / shared Docker network (mlops) ]
-----------------+--------------------------------------------------------------
                 v
     +-------------------+
     | 1. Prefect Server |  pass parameters (git_commit, minio_version)
     +-------------------+
                 |
                 v
     +-------------------+
     | 2. Prefect Worker |  spawn N Pipeline Flow containers concurrently (one per job)
     +-------------------+
                 |
   +-------------+-------------+   (spawned concurrently, one per team member/job)
   v             v             v
+----------+ +----------+ +----------+
| Pipeline | | Pipeline | | Pipeline |   <- 3. Pipeline Flow (ephemeral)
| ctr  A   | | ctr  B   | | ctr  C   |
| worktree | | worktree | | worktree |
|  a1b2c3d | |  e5f6... | |  9z8y... |
+----------+ +----------+ +----------+
   |             |             |
   v             v             v
 auto-remove   auto-remove   auto-remove   (destroyed after the run)
```

- **동시성** — dispatcher 는 job 마다 같은 이미지로 **독립 컨테이너를 동시에** 띄웁니다. 서로 상태를 공유하지 않고 (`git worktree` 도 각자), 끝나면 파괴되어 동시성 관리가 단순합니다.
- **단일 호스트** — 기본은 한 호스트에서 모든 컨테이너가 `mlops` 를 공유합니다. 다른 머신에 dispatcher 를 더 붙이는 방법은 [§4.3](#43-dispatcher-attachment) 을 참고합니다.

각 서비스의 역할입니다.

| Service | Endpoint | Description |
|---------|----------|------|
| `postgres` | `:5432` | 메타데이터 DB. 한 인스턴스에서 `prefect`/`mlflow`/`optuna`/`catalog` 4개 논리 DB 를 운영합니다. |
| `minio` | `:9000` (S3 API) · `:9001` (console) | Object storage. datasets / models / artifacts 의 3개 buckets 를 운영합니다. |
| `mlflow` | `:5000` | 실험 추적 + 모델 레지스트리. backend 는 `postgres`, artifact 는 `minio` 입니다. |
| `prefect_server` | `:4200` | Prefect server + 웹 대시보드 (UI). backend 는 `postgres` 입니다. |
| `prefect_worker` | — | Short Term work pool 을 polling 해 job 마다 Pipeline Flow 컨테이너를 띄우는 dispatcher. Long Term (`process`) 에서는 별도 컨테이너 없이 worker 안에서 직접 실행합니다. |

> `postgres`·`minio`·`mlflow` 는 각자 폴더의 compose 로 띄웁니다. 이 문서는 **Prefect server·worker (dispatcher) 와 Pipeline Flow 이미지** 에 집중합니다.

## 2. Execution Architecture

Prefect 실행 모드는 두 가지이고, 차이는 **누가 코드를 실행하느냐** 입니다.

### 1) Serve Mode (Push-Based / Static)

- **동작** — `flow.serve()` 스크립트를 실행하면 그 프로세스가 deployment 를 등록하고 상시 떠서, trigger 시 **자기 자신이** 실행합니다.
- **실행 위치·환경** — `.serve()` 를 띄운 머신 (보통 팀원 client) 의 python 으로 실행되어 팀원이 환경을 자유롭게 씁니다 (work pool mode 는 server 측 공용 이미지로 통일).
- **장점** — 별도 dispatcher·pool 이 없어 단순합니다. 단일 머신에 적합합니다.

### 2) Work Pool Mode (Pull-Based / Dynamic)

- **동작** — `flow.deploy()` 로 등록만 하고 python 은 종료됩니다. dispatcher 가 pool 에서 job 을 가져와 실행하고 정리합니다.
- **pool 타입** — 실행 환경을 만드는 방식이 갈립니다.
  - **Long Term Container** (`process`) — dispatcher 자기 컨테이너에서 subprocess 로 실행하며, run 들이 컨테이너를 공유합니다 ([Appendix C](#appendix-c-long-term-container-work-pool)).
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
    networks:
      - mlops
    restart: unless-stopped

networks:
  mlops:
    external: true
```

- `command: prefect server start --host 0.0.0.0` 은 컨테이너 밖에서도 접속하도록 모든 인터페이스에 바인딩합니다.
- `networks: mlops` 로 `postgres` 와 서비스명으로 통신합니다. `postgres` 는 별도 compose 라 `depends_on` 대신 `restart: unless-stopped` 로 준비될 때까지 재시도합니다.

## 4. Prefect Worker Container

worker (`prefect_worker`) 는 **네 가지 일**을 합니다.

- **job polling** — work pool 을 polling 해 job 을 가져옵니다.
- **job dispatch** — 가져온 job 을 실행 환경으로 보내 실행합니다.
- **reporting** — 실행 중 상태·로그를 server 에 보고합니다.
- **cleanup** — 실행이 끝나면 정리합니다.

worker 는 **dispatch 를 위해 두 방식**을 지원합니다.

- **Short Term Container** (`docker` work pool) — job 마다 Pipeline Flow 컨테이너를 띄웠다 정리합니다.
- **Long Term Container** (`process` work pool) — worker 자기 상시 컨테이너 안에서 flow 를 직접 실행합니다 (별도 컨테이너 없음).

이 절은 주력인 **Short Term Container** 설정을 다룹니다. Long Term Container 설정은 [Appendix C](#appendix-c-long-term-container-work-pool), work pool type 정의는 [Appendix A](#appendix-a-terminology) 를 참고합니다.

여기서 dispatcher (`prefect_worker`) 는 **Short Term Container (docker pool) 전용** 입니다. work pool 을 polling 하다가 job 마다 Pipeline Flow 이미지로 컨테이너를 띄워 실행하고 정리합니다. 준비물은 둘입니다 — ① base job template, ② dispatcher compose (Pipeline Flow 이미지는 [§5](#5-pipeline-flow-container) 에서 빌드).

### 4.1 Base Job Template

dispatcher 가 띄우는 모든 Pipeline Flow 컨테이너의 공통 설정입니다. run 컨테이너는 dispatcher 의 마운트·네트워크를 상속하지 않으므로 **`PREFECT_API_URL` 과 네트워크를 여기서 명시** 해야 합니다.

이 설정을 `docker-pool-template.json` 에 담아 **pool 생성 시 한 번** 등록합니다 (`prefect work-pool create --type docker --base-job-template docker-pool-template.json`). 등록하면 server 에 저장되어 모든 run 에 자동 적용되므로, 팀원 deploy 코드에는 다시 적지 않아도 됩니다.

`docker-pool-template.json`:

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
      "auto_remove": { "type": "boolean", "default": true }
    }
  },
  "job_configuration": {
    "image":       "{{ image }}",
    "env":         "{{ env }}",
    "networks":    "{{ networks }}",
    "volumes":     "{{ volumes }}",
    "auto_remove": "{{ auto_remove }}"
  }
}
```

- `image` — run 컨테이너로 쓸 Pipeline Flow 이미지 (§5.1).
- `env.PREFECT_API_URL` — run 컨테이너가 server·Secret 을 찾는 주소 (같은 호스트 + `mlops` 면 `prefect_server`).
- `networks` — run 컨테이너가 붙을 네트워크 (`mlops` 면 `minio`·`prefect_server` 를 서비스명으로 찾음).
- `volumes` — **데이터 캐시용 공유 볼륨**. 컨테이너는 일시적이라 내부 파일이 매번 사라지므로, repo 밖 `/cache` 에 이름 있는 볼륨을 마운트해 캐시를 run 사이에 보존합니다. 버전 경로 (`v3_best` 등) 는 불변이라 여러 컨테이너가 공유해도 안전하고, repo 밖이라 git 작업과도 무관합니다.
- `auto_remove: true` — run 종료 시 컨테이너 자동 삭제.

> base job template 필드는 Prefect 버전마다 다를 수 있으니, `prefect work-pool get-default-base-job-template --type docker` 로 최신 템플릿을 받아 `image`·`env`·`networks`·`volumes` 의 `default` 만 채우길 권장합니다.

### 4.2 Dispatcher (`prefect_worker`)

dispatcher 는 호스트 도커 소켓을 마운트해 형제 컨테이너를 띄웁니다. docker worker 는 `prefect-docker` 가 필요하므로 기동 시 설치합니다 (이미지로 구우려면 별도 Dockerfile).

```powershell
# (first time) Copy the example file and fill in the worker section (CONTROL_NODE_HOST).
Copy-Item docker-compose.env_example docker-compose.env

# Create mlops if missing, then start the dispatcher in the background.
docker network create mlops
docker compose -p <Project Name> -f docker-compose.worker.yml up -d
```

```yaml
# docker-compose.worker.yml
services:
  prefect_worker:
    image: prefecthq/prefect:3-latest
    env_file:
      - docker-compose.env          # CONTROL_NODE_HOST (prefect_server on the same host)
    command: >
      bash -c "pip install --no-cache-dir prefect-docker &&
               export PREFECT_API_URL=http://$${CONTROL_NODE_HOST:-prefect_server}:4200/api &&
               if [ ${CREATE_POOL:-true} = true ]; then
                 prefect work-pool create ${WORK_POOL:-docker-pool} --type docker --base-job-template /opt/template.json --overwrite;
               fi &&
               prefect worker start --pool ${WORK_POOL:-docker-pool} --limit ${WORKER_LIMIT:-8}"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock   # host docker socket, to spawn sibling containers
      - ./docker-pool-template.json:/opt/template.json:ro
    networks:
      - mlops
    restart: unless-stopped

networks:
  mlops:
    external: true
```

- `volumes: /var/run/docker.sock` — dispatcher 가 호스트 도커로 Pipeline Flow 컨테이너를 띄우는 통로입니다 (Windows/Docker Desktop 도 같은 경로).
- `command` — `prefect-docker` 설치 → `PREFECT_API_URL` 설정 → pool 생성 → `prefect worker start` 순입니다. `CREATE_POOL`·`WORK_POOL`·`WORKER_LIMIT` 는 `docker compose up` 시 셸에서 읽는 변수입니다 (기본 `true`·`docker-pool`·`8`).
- `--limit` 은 이 dispatcher 가 **동시에 띄우는 컨테이너 수의 상한** 입니다 ([Concurrency & Scaling](#concurrency--scaling)).

> **보안 주의** — 도커 소켓 마운트는 dispatcher 에 호스트 도커 전체 제어권 (사실상 root) 을 줍니다. 신뢰된 내부망·스터디 용도로 한정하고, 더 강한 격리는 Kubernetes work pool 을 고려합니다 ([Appendix D](#appendix-d-orchestrator-benchmarking)).

### Concurrency & Scaling

Short Term Container 는 run 마다 별도 컨테이너라 동시 실행이 자연히 격리됩니다. 동시 실행량은 셋으로 조절합니다.

- **dispatcher `--limit`** — 한 dispatcher 의 동시 컨테이너 상한 (현재 8). 초과분은 slot 이 빌 때까지 대기합니다.
- **pool concurrency limit** — pool 전체 상한 (`prefect work-pool set-concurrency-limit <pool> <N>`).
- **컨테이너 자원 상한** — base job template 의 `mem_limit` 등. GPU 학습처럼 1 job 이 무거우면 `--limit` 을 1~2 로 낮춥니다.

### 4.3 Dispatcher Attachment

dispatcher 는 `prefect worker start` 순간 server 에 자기를 알리고 (heartbeat 시작) 해당 work pool 에 **자동 등록**됩니다 — **polling 시작 = 등록** 이라 별도 절차가 없습니다. heartbeat 가 끊기면 잠시 뒤 **OFFLINE** 으로 바뀝니다. (worker 등록은 deployment 등록과 별개입니다.)

| Aspect | Before (no worker) | After (dispatcher polling) |
|--------|--------------------|----------------------------|
| pool | 큐일 뿐 — trigger 된 run 이 `Late`/대기로 멈춤 | worker 가 큐에서 run 을 가져와 실행 |
| 실행 머신 | 없음 | dispatcher 가 도는 호스트 |
| 가시성 | — | UI 의 Work Pools → Workers (이름·ONLINE·last heartbeat) |
| 동시 실행 용량 | — | 그 worker 의 `--limit` 만큼 |

**처리량·확장** — `--limit` 을 키우거나, **다른 머신에서 dispatcher 를 더 띄워 같은 pool 에 붙입니다.** 그 머신에서 `PREFECT_API_URL` 을 server 로 두고 worker 를 띄우면 polling 과 동시에 합류합니다 (추가 dispatcher 는 `CREATE_POOL=false`, 다른 머신은 `networks` 블록 제거 + `CONTROL_NODE_HOST`=server IP). 여러 worker 는 같은 pool 의 큐를 나눠 가집니다. 특정 머신 (예: GPU) 전용은 **전용 pool** (`WORK_POOL=docker-gpu`) 로 라우팅합니다.

### GPU

run 컨테이너에서 GPU 를 쓰려면 호스트에 NVIDIA 드라이버·nvidia-container-toolkit 이 있고 base job template 에서 GPU 를 요청해야 합니다. torch 의 CUDA 휠은 런타임을 번들하므로 호스트 드라이버가 최신이면 동작하며, 버전이 안 맞으면 베이스 이미지를 `nvidia/cuda` 계열로 교체합니다.

## 5. Pipeline Flow Container

Pipeline Flow 는 dispatcher 가 job 마다 띄우는 per-run 컨테이너입니다. dispatcher 하나가 동시 job 수만큼 **여러 개 (n 개)** 를 띄우며 (상한 `--limit`, 현재 8), 각 컨테이너는 독립입니다. 여기서는 그 컨테이너의 **이미지 (빌드)** 와 그 안에서 도는 **orchestrator flow (실행 골격)** 를 다룹니다.

이 한 이미지를 **Short Term·Long Term 양쪽에 그대로** 씁니다 — ST 는 job 마다 컨테이너로, LT 는 worker 로 상시 띄웁니다 ([Appendix C](#appendix-c-long-term-container-work-pool)). 그래서 라이브러리를 worker 와 이미지에 중복 설치할 필요가 없습니다.

### 5.1 Image (팀 공통 소스 빌드본)

job 마다 뜨는 컨테이너의 python 환경입니다. **git repo 를 이미지에 clone 해 두고** (`.git` 포함), 런타임에 `git fetch` 로 새 커밋을 받아 `git worktree` 로 원하는 커밋을 펼칩니다. 라이브러리·소스가 한 이미지에 고정되어 모두 같은 런타임을 씁니다.

```dockerfile
# Dockerfile — shared team Pipeline Flow image
FROM prefecthq/prefect:3-python3.11
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt
COPY requirements.txt .               # boto3, psycopg2-binary, mlflow, optuna, pandas, torch, ...
RUN pip install --no-cache-dir -r requirements.txt

# Bake the shared team source (with .git so runtime git worktree is fast).
ARG GIT_REPO                          # build-time arg: docker build --build-arg GIT_REPO=<git-repo-url> .
RUN git clone "$GIT_REPO" pipeline
WORKDIR /opt/pipeline
```

```powershell
# Build the image (tag = runtime version). Rebuild with a new tag when libraries change.
docker build -t pipeline-flow:latest --build-arg GIT_REPO=<git-repo-url> .
```

- **`ARG GIT_REPO` 이유** — repo 주소를 Dockerfile 에 하드코딩하지 않고 빌드 시 주입합니다. 그래서 같은 Dockerfile 을 repo 마다 재사용하고, 커밋되는 파일에 주소·토큰을 넣지 않아 안전합니다.
- git repo 를 이미지에 clone 해 두면 `.git` 이 이미 있어 `git worktree` 가 빠릅니다. `git fetch` 는 빌드 이후 push 된 새 커밋을 받되 working tree·HEAD 는 바꾸지 않습니다.
- 이미지 태그 (`pipeline-flow:latest`) 가 곧 **런타임 버전** (라이브러리 + 베이스 소스) 입니다.
- **저장 위치** — 빌드 이미지는 그 호스트의 **로컬 Docker 이미지 스토어** 에 저장됩니다 (`docker images`). 같은 호스트 dispatcher 는 그대로 쓰고, 여러 머신이면 레지스트리에 push/pull 하거나 각 머신에서 빌드합니다.

### 5.2 Flow (Orchestrator)

orchestrator (flow) 는 **"커밋 받아 → 팀원 코드 실행"** 만 하는 얇은 골격이라 이미지에 굽습니다. 팀원의 실제 코드는 굽지 않고 `git_commit` 으로 매 job 받아 와 **무슨 코드든 그대로 실행**됩니다 (`entrypoint` 로 스크립트 지정).

```python
# pipeline.py — orchestrator; Prefect runs this as the deployment entrypoint.
import os
import subprocess
from prefect import flow

REPO = "/opt/pipeline"     # baked clone in the image (shared .git object store)

@flow(name="pipeline")
def pipeline(git_commit: str, minio_version: str, entrypoint: str = "train.py"):
    subprocess.run(["git", "fetch", "origin"], cwd=REPO, check=True)        # download objects only (local state unchanged)
    work = f"/tmp/run-{git_commit}"                                         # isolated working tree (use a unique path per run)
    subprocess.run(["git", "worktree", "add", "--detach", work, git_commit], cwd=REPO, check=True)
    env = {**os.environ, "MINIO_VERSION": minio_version}                    # team code reads the cached version under /cache
    subprocess.run(["python", entrypoint], cwd=work, env=env, check=True)   # run the team's code in the isolated tree
    subprocess.run(["git", "worktree", "remove", "--force", work], cwd=REPO, check=True)  # LT: prevent worktree buildup; ST is auto-removed with the container
```

- **자유로운 코드** — `entrypoint` 로 팀원이 자기 스크립트를 지정하므로 코드를 정해진 틀에 맞출 필요가 없습니다. 데이터 읽기·저장은 팀원 코드가 직접 하고, 데이터 버전은 `MINIO_VERSION` 환경변수로 받습니다.
- **데이터 이력** — `minio_version` 이 **flow 파라미터** 라서 Prefect 가 run 마다 입력값을 `prefect` DB 에 자동 저장합니다 (UI 의 Flow Run → Parameters). 데이터셋 버전·lineage 는 팀원 코드 (또는 공유 헬퍼) 가 카탈로그에 등록합니다.
- **이력 자동 저장** — `@flow` 진입 시 Prefect 가 run 의 상태·로그·파라미터를 자동 기록합니다 (대시보드 Flow Runs). 지표·모델은 팀원 코드가 MLflow 로 로깅하면 함께 남습니다 ([Appendix E](#appendix-e-prefect-task)).

## 6. Credentials

코드가 **MinIO** 와 PostgreSQL 의 `catalog`·`optuna` DB 에 직접 접속하려면 자격증명 (`MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY`/`MINIO_ENDPOINT`/`POSTGRESQL_CATALOG_DSN`/`POSTGRESQL_OPTUNA_DSN`) 이 필요합니다. 이 스택은 **Prefect Secret** 으로 다룹니다 — server 에 한 번 저장하면 Pipeline Flow 코드가 실행 중 이름으로 받아 쓰므로 **컨테이너·머신마다 따로 넣지 않아도 됩니다.** dispatcher 는 자격증명을 들지 않습니다.

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

> run 컨테이너는 base job template 의 `PREFECT_API_URL` 로 server 에 연결돼야 Secret 을 받습니다 (§4.1). `mlflow`·`prefect` DB 는 사용자 코드가 직접 접속하지 않으므로, 사용자 role 에는 `catalog`·`optuna` 권한만 있으면 됩니다.

### docker-compose.env

Prefect Secret 이 **run 코드용** 이라면, **server·dispatcher 용 값** (backend DB URL·Control Node 주소) 은 `docker-compose.env` 한 파일에 모읍니다. 실제 값 파일은 `.gitignore` 로 제외하고, 비운 `docker-compose.env_example` 만 커밋합니다.

```dotenv
# docker-compose.env_example  (every value is a placeholder — never expose real values)

# -- prefect-server --
PREFECT_SERVER_DATABASE_CONNECTION_URL=postgresql+asyncpg://CHANGE_ME:CHANGE_ME@postgres:5432/prefect

# -- prefect-worker (dispatcher) --
# Address the dispatcher uses to reach the Prefect server. Use the service name prefect_server on the
# same host, or the host IP/hostname on another machine (then remove the networks block in worker compose).
CONTROL_NODE_HOST=prefect_server
```

- server 는 `postgres` 서비스명으로 backend 에 접속하므로 URL 호스트가 `postgres` 입니다.
- dispatcher 는 코드를 실행하지 않아 MinIO·카탈로그 자격증명이 필요 없습니다 — 그 값들은 위 Prefect Secret 으로 전달됩니다.

## Appendix A. Terminology

- **Host (호스트)** — 모든 컨테이너 (server·worker·Pipeline Flow·postgres·minio·mlflow) 가 올라가는 한 대의 컴퓨터입니다.
- **`prefect_server`** — API·UI·스케줄러·work pool 대기열을 제공하는 중앙 진입점입니다. 메타데이터 (`prefect` DB) 만 관리하고 코드는 실행하지 않습니다.
- **`prefect_worker` (dispatcher)** — work pool 을 polling 해 job 마다 Pipeline Flow 컨테이너를 띄우고 정리하는 worker 입니다. 코드는 실행하지 않습니다.
- **Pipeline Flow** — dispatcher 가 job 마다 띄우는 일시적 실행 컨테이너입니다. 받은 커밋을 git worktree 로 펼친 뒤 코드를 실행하고 끝나면 파괴됩니다.
- **Short Term (ST) Container (ephemeral container)** — `docker` work pool 이 job 마다 띄웠다 파괴하는 일시적 컨테이너입니다. 이 문서의 Pipeline Flow 가 여기 해당합니다.
- **Long Term (LT) Container** — `process` work pool 에서 여러 job 을 subprocess 로 실행하는 공유 상시 컨테이너 (worker 컨테이너 자체) 입니다.
- **work pool** — job 이 대기하는 큐이자 실행 방식 (type) 의 정의입니다. server 안의 메타데이터이며 컨테이너가 아닙니다.
- **work pool type** — Prefect 가 정한 실행 방식 이름입니다. `process` (Long Term Container) · `docker` (job 마다 Short Term Container) · `kubernetes` (job 마다 pod) · `ecs` 등이 있습니다.
- **serve mode** — `flow.serve()` 프로세스가 상시 떠서 flow run 요청을 받아 처리하는 모습이, 웹 서버가 요청을 처리하듯 flow 를 계속 **제공 (serve)** 하기 때문에 붙은 이름입니다.
- **deployment** — flow 를 언제·어떻게·어떤 파라미터로 실행할지 묶어 server 에 등록한 실행 정의입니다.
- **base job template** — pool 이 띄우는 run 컨테이너의 공통 설정 (이미지·env·네트워크·볼륨) 입니다.
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
- `prefect work-pool create <name> --type docker --base-job-template <file> [--overwrite]` — Short Term Container work pool 을 만듭니다 (§4.2).
- `prefect work-pool get-default-base-job-template --type docker` — 도커 worker 의 기본 base job template 을 출력합니다 (§4.1).
- `prefect work-pool set-concurrency-limit <pool> <N>` — pool 전체 동시 실행 상한을 설정합니다.
- `prefect worker start --pool <name> [--limit N]` — dispatcher 를 기동해 그 pool 을 polling 하며 job 을 실행합니다 (§4.2).
- `prefect deploy` (또는 `flow.deploy(...)`) — deployment 를 등록합니다.
- `prefect deployment run "<flow>/<deployment>" -p <key>=<value>` — 등록된 deployment 를 파라미터와 함께 trigger 합니다.

## Appendix C. Long Term Container Work Pool

단일 머신·소규모에서는 매 run 컨테이너를 띄우는 대신 worker **자기 프로세스** 로 실행하는 Long Term Container 가 더 단순합니다. **Short Term 과 같은 `pipeline-flow` 이미지를 worker 로 띄우면** ([§5.1](#51-image-팀-공통-소스-빌드본)) 라이브러리·소스가 이미 있어 추가 설치·마운트가 없습니다. run 들이 프로세스 공간을 공유하므로 격리는 약합니다.

```yaml
# docker-compose.worker.yml (process variant — single/small scale)
services:
  prefect_worker:
    image: pipeline-flow:latest     # the same image as the Short Term run container (§5.1)
    env_file:
      - docker-compose.env
    command: >
      bash -c "export PREFECT_API_URL=http://$${CONTROL_NODE_HOST:-prefect_server}:4200/api &&
               prefect work-pool create ${WORK_POOL:-default} --type process --overwrite &&
               prefect worker start --pool ${WORK_POOL:-default} --limit ${WORKER_LIMIT:-8}"
    working_dir: /opt/pipeline       # baked team source (with .git)
    networks:
      - mlops
    restart: unless-stopped

networks:
  mlops:
    external: true
```

- **ST·LT 동일 이미지** — ST 는 `pipeline-flow` 이미지를 job 마다 띄우고, LT 는 같은 이미지를 worker 로 상시 띄웁니다. 라이브러리·소스가 이미지에 있어 코드는 git worktree 로 펼칠 뿐 별도 전달·설치가 없습니다 (worker 에 라이브러리를 따로 설치하지 않으므로 중복이 없습니다). 특히 LT 는 한 컨테이너에서 여러 run 이 동시에 도므로, `git checkout` 대신 run 마다 격리된 worktree 를 써야 충돌이 없습니다.

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
