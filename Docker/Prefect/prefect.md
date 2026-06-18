# Prefect with Docker Work Pool

> 공식 사이트: [https://www.prefect.io/](https://www.prefect.io/)

Prefect stack 을 한 호스트 서버 위에서 **세 구성요소 (Prefect Server · Prefect Worker · Pipeline Flow)** 로 나눠 도커로 실행하는 방법을 설명합니다. 이 구성은 **여러 팀원이 여러 코드베이스를 개발하고 동시에 다수 job 을 trigger** 하는 상황을 전제로, **ephemeral docker-container-per-job model** — job 하나마다 일시적 컨테이너 하나를 띄워 실행하고 끝나면 파괴하는 모델 — 을 주력으로 합니다. 이를 Prefect 의 **Docker work pool** 로 실현합니다. job 마다 깨끗한 컨테이너가 떠서 코드를 실행하고 끝나면 스스로 사라지므로, run 들이 서로 간섭하지 않고 동시성 관리가 단순해집니다.

Prefect server (`prefect_server`) 는 job 요청을 중앙에서 수집·스케줄링하는 **단일 진입점 (Single Point of Entry)** 입니다. 다만 **`prefect_server` 는 코드를 실행하지 않습니다** — 코드는 항상 실행 컨테이너 (Pipeline Flow) 안에서 실행됩니다.

단일 머신·소규모 구성에는 [Appendix F](#appendix-f-process-work-pool) 의 process work pool 또는 serve mode 가 더 단순합니다.

## 1. Architecture

모든 구성요소는 한 호스트 서버 위에서 공유 도커 네트워크 `mlops` 로 묶입니다. Control Node (제어 노드) 에는 `prefect_server` 와 `prefect_worker` (디스패처) 가 함께 올라가고, job 마다 **Pipeline Flow 컨테이너** 가 같은 호스트에 일시적으로 떴다 사라집니다.

| 구성요소 | Prefect 용어 | 역할 | 수명 |
|----------|--------------|------|------|
| **1. Prefect Server** | server | job 수집·스케줄링·UI. 실행 파라미터 (`git_commit`·`minio_version`) 를 전달합니다. 코드는 실행하지 않습니다. | 상시 |
| **2. Prefect Worker** | docker-type worker (디스패처) | docker work pool 을 폴링해 job 마다 Pipeline Flow 컨테이너를 띄우고, 끝나면 정리합니다. 코드는 실행하지 않습니다. | 상시 |
| **3. Pipeline Flow** | per-run 실행 컨테이너 | 디스패처가 job 마다 띄우는 컨테이너입니다. 받은 커밋으로 git checkout 한 뒤 실제 코드를 실행하고 끝나면 스스로 파괴됩니다. | 일시적 (job 1개당 1개) |

```
[ 호스트 서버 / 공유 Docker 네트워크 (mlops) ]
-----------------+--------------------------------------------------------------
                 v
     +-------------------+
     | 1. Prefect Server |  파라미터 전달 (git_commit, minio_version)
     +-------------------+
                 |
                 v
     +-------------------+
     | 2. Prefect Worker |  job 마다 Pipeline Flow 컨테이너를 동시에 N 개 생성
     +-------------------+
                 |
   ┌─────────────┼─────────────┐   (동시 생성 — 팀원/job 수만큼)
   v             v             v
+----------+ +----------+ +----------+
| Pipeline | | Pipeline | | Pipeline |   ← 3. Pipeline Flow (일시적)
| 컨테이너 A| | 컨테이너 B| | 컨테이너 C|
| checkout | | checkout | | checkout |
|  a1b2c3d | |  e5f6... | |  9z8y... |
+----------+ +----------+ +----------+
   |             |             |
   v             v             v
 작업 후        작업 후        작업 후
 자동 삭제      자동 삭제      자동 삭제
```

각 Pipeline Flow 컨테이너는 **동일한 이미지 (팀 공통 소스 빌드본)** 에서 떠서, 받은 파라미터대로 내부에서 다음 단계를 수행합니다.

```
[ Prefect Server ] ── 파라미터 (git_commit: a1b2c3d, minio_version: v3_best) ──▶ [ Pipeline Flow 컨테이너 ]
                                                                                        │
   [스텝 A] Git Checkout ── git fetch origin && git checkout a1b2c3d                     │  지정 커밋으로 소스 전환
   [스텝 B] MinIO Data Check ── 로컬 캐시에 minio_version 이 없으면 그 버전만 내려받음     │  데이터 준비
   [스텝 C] 코드 실행 ── python 스크립트를 하위 프로세스로 기동                            │  실제 연산
   [스텝 D] 결과 저장 ── 산출물을 MinIO 에 올리고 메타데이터를 Server/카탈로그에 기록      │  결과 영속화
                                                                                        ▼
                                                                            작업 완료 후 컨테이너 자동 삭제
```

- **동시성** — 디스패처는 job 을 받을 때마다 같은 이미지로 **독립된 컨테이너를 필요한 만큼 동시에** 생성합니다. 컨테이너끼리 상태를 공유하지 않아 (`git checkout` 도 각자) 완전히 독립적으로 연산하고, 끝나면 스스로 파괴되므로 동시성 관리가 단순합니다.
- **단일 호스트** — 위 구성은 한 호스트에서 모든 컨테이너가 `mlops` 네트워크를 공유하는 것을 기본으로 합니다. 다른 머신에 디스패처를 더 붙이는 방법은 [Appendix D](#appendix-d-additional-dispatcher-attachment) 를 참고합니다.

각 서비스의 역할은 다음과 같습니다.

| Service | Endpoint | Description |
|---------|----------|------|
| `postgres` | `:5432` | 메타데이터 DB 입니다. 한 인스턴스에서 `prefect`/`mlflow`/`optuna`/`catalog` 4개 논리 DB 를 운영합니다. |
| `minio` | `:9000` (S3 API) · `:9001` (console) | 오브젝트 스토리지입니다. 데이터·모델·아티팩트를 보관합니다. |
| `mlflow` | `:5000` | 실험 추적 server + 모델 레지스트리입니다. backend 는 `postgres`, artifact 는 `minio` 입니다. |
| `prefect_server` | `:4200` | Prefect server + 대시보드 (UI) 입니다. backend 는 `postgres` 입니다. |
| `prefect_worker` | — | docker work pool 을 폴링해 job 마다 Pipeline Flow 컨테이너를 띄우는 디스패처입니다. |

> `postgres` · `minio` · `mlflow` 는 각자 자기 폴더의 compose 로 띄웁니다. 이 문서는 그중 **Prefect server 와 worker (디스패처)**, 그리고 **Pipeline Flow 이미지** 의 설치·실행에 집중합니다.

## 2. Prefect Server Setup

server 는 backend 인 `postgres` 가 같은 호스트에서 먼저 떠 있어야 정상 동작하므로, **PostgreSQL → (MinIO/MLflow) → Prefect server** 순으로 띄우길 권장합니다.

```powershell
# (최초 1회) 예시 파일을 복사해 server 섹션의 값을 채운다. docker-compose.env 는 git 에 커밋하지 않는다.
Copy-Item docker-compose.env_example docker-compose.env

# 공유 네트워크 mlops 를 만들고 (이미 있으면 에러는 무시) server 를 백그라운드로 띄운다.
docker network create mlops
docker compose -p <Project Name> -f docker-compose.server.yml up -d
```

실행 후 Prefect 대시보드는 **`http://<Host IP>:4200`** 에서 열립니다 (같은 컴퓨터에서는 `localhost`).

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
      - "4200:4200"                 # 대시보드/API. 클라이언트가 이 포트로 접속한다.
    networks:
      - mlops
    restart: unless-stopped

networks:
  mlops:
    external: true
```

- `command: prefect server start --host 0.0.0.0` 은 컨테이너 밖에서도 접속할 수 있도록 모든 인터페이스에 바인딩합니다.
- `networks: mlops` 로 같은 호스트의 `postgres` 와 서비스명으로 통신합니다. `postgres` 는 별도 compose 라 `depends_on` 을 걸 수 없으므로, `restart: unless-stopped` 로 준비될 때까지 자동 재시도합니다.

## 3. Worker Setup

디스패처 (`prefect_worker`) 는 docker work pool 을 폴링하다가 job 마다 **Pipeline Flow 이미지로 컨테이너를 새로 띄워** 코드를 실행시키고, 끝나면 정리합니다. 준비물은 세 가지입니다 — ① Pipeline Flow 이미지, ② run 컨테이너 공통 설정 (base job template), ③ 디스패처 compose.

### 3.1 Pipeline Flow Image (팀 공통 소스 빌드본)

job 마다 뜨는 컨테이너의 python 환경입니다. **팀 공통 소스를 구워 두고** (`.git` 포함), 런타임에 `git fetch && git checkout <commit>` 으로 원하는 커밋으로 전환합니다. 라이브러리·소스가 한 이미지에 고정되어 모든 팀원이 같은 런타임을 씁니다.

```dockerfile
# Dockerfile — 팀 공통 Pipeline Flow 이미지
FROM prefecthq/prefect:3-python3.11
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt
COPY requirements.txt .               # boto3·psycopg2-binary·mlflow·optuna·pandas·torch 등
RUN pip install --no-cache-dir -r requirements.txt

# 팀 공통 소스를 구워 둔다(.git 포함 → 런타임 git checkout 이 빠르다).
ARG GIT_REPO                          # 빌드 시 --build-arg GIT_REPO=<git-repo-url> 로 전달
RUN git clone "$GIT_REPO" pipeline
WORKDIR /opt/pipeline
```

```powershell
# 이미지를 빌드한다(런타임 버전 = 이미지 태그). 라이브러리를 바꾸면 새 태그로 다시 빌드한다.
docker build -t pipeline-flow:latest --build-arg GIT_REPO=<git-repo-url> .
```

- 소스를 구워 두면 컨테이너에 `.git` 이 이미 있어 `git checkout <commit>` 이 빠릅니다. `git fetch` 는 빌드 이후의 새 커밋만 받아 옵니다.
- 이미지 태그 (`pipeline-flow:latest`) 가 곧 **런타임 버전** (라이브러리 + 베이스 소스) 입니다 ([§7](#7-code-delivery--versioning)).

### 3.2 Base Job Template

디스패처가 띄우는 모든 Pipeline Flow 컨테이너에 공통 적용할 설정입니다. run 컨테이너는 디스패처의 마운트·네트워크를 상속하지 않으므로, **`PREFECT_API_URL` 과 네트워크를 반드시 여기서 주입** 해야 합니다.

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
                   "default": ["pipeline-data-cache:/opt/pipeline/data"] },
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

- `image` — run 컨테이너로 쓸 Pipeline Flow 이미지입니다 (§3.1).
- `env.PREFECT_API_URL` — run 컨테이너가 server·Secret 블록을 찾는 주소입니다 (같은 호스트 + `mlops` 면 서비스명 `prefect_server`).
- `networks` — run 컨테이너가 붙을 네트워크입니다 (`mlops` 로 두어 `minio`·`prefect_server` 를 서비스명으로 찾습니다).
- `volumes` — **데이터 캐시용 공유 볼륨** 입니다. 컨테이너는 일시적이라 내부 `data/` 가 매번 사라지므로, 이름 있는 볼륨을 `data/` 에 마운트해 캐시를 run 사이에 보존합니다. 버전 경로 (`v3_best` 등) 는 불변이라 여러 컨테이너가 공유해도 안전합니다 (스텝 B). `data/` 는 repo 에서 gitignore 되어 있어야 스텝 A 의 `git reset --hard` 가 캐시를 건드리지 않습니다.
- `auto_remove: true` — run 이 끝나면 컨테이너를 자동 삭제합니다.

> 도커 worker 의 base job template 은 Prefect 버전에 따라 필드가 다를 수 있으므로, 정확한 최신 기본 템플릿은 `prefect work-pool get-default-base-job-template --type docker` 로 받아 위 `image`·`env`·`networks`·`volumes` 의 `default` 만 채워 쓰는 것을 권장합니다.

### 3.3 Dispatcher (`prefect_worker`)

디스패처는 호스트 도커 소켓을 마운트해 형제 (sibling) 컨테이너를 띄웁니다. docker worker 는 `prefect-docker` 패키지가 필요하므로 기동 시 설치합니다 (이미지로 구우려면 별도 Dockerfile 로 만듭니다).

```powershell
# (최초 1회) 예시 파일을 복사해 worker 섹션 (CONTROL_NODE_HOST) 을 채운다.
Copy-Item docker-compose.env_example docker-compose.env

# mlops 가 없으면 1회 생성한 뒤 디스패처를 백그라운드로 띄운다.
docker network create mlops
docker compose -p <Project Name> -f docker-compose.worker.yml up -d
```

```yaml
# docker-compose.worker.yml
services:
  prefect_worker:
    image: prefecthq/prefect:3-latest
    env_file:
      - docker-compose.env          # CONTROL_NODE_HOST (같은 호스트면 prefect_server)
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
      - mlops
    restart: unless-stopped

networks:
  mlops:
    external: true
```

- `volumes: /var/run/docker.sock` — 디스패처가 호스트 도커 데몬에 명령해 Pipeline Flow 컨테이너를 띄우는 통로입니다. Windows/Docker Desktop 도 리눅스 컨테이너에 같은 경로로 노출됩니다.
- `command` — `prefect-docker` 설치 → `PREFECT_API_URL` 설정 → docker pool 생성 (base job template 적용) → `prefect worker start` 순입니다. `CREATE_POOL`·`WORK_POOL`·`WORKER_LIMIT` 는 `docker compose up` 시점에 셸에서 읽는 compose 변수입니다 (미설정 시 `true`·`docker-pool`·`8`).
- `--limit` 은 이 디스패처가 **동시에 띄우는 Pipeline Flow 컨테이너 수의 상한** 입니다 ([Concurrency & Scaling](#concurrency--scaling)).

> **보안 주의** — 도커 소켓 마운트는 디스패처에 호스트 도커 전체 제어권 (사실상 root 권한) 을 줍니다. 신뢰된 내부망·스터디 용도로 한정합니다. 더 강한 격리가 필요하면 Kubernetes work pool 을 고려합니다 ([Appendix G](#appendix-g-orchestrator-benchmarking)).

### Concurrency & Scaling

docker pool 은 run 마다 **별도 컨테이너** 라 동시 실행이 자연히 격리·병렬화됩니다. 동시 실행량은 세 가지로 조절합니다.

- **디스패처 `--limit`** — 한 디스패처가 동시에 띄우는 컨테이너 수의 상한입니다 (현재 8). 상한을 넘는 job 은 slot 이 빌 때까지 대기합니다.
- **pool concurrency limit** — pool 전체의 동시 실행 상한입니다 (`prefect work-pool set-concurrency-limit <pool> <N>`).
- **컨테이너 자원 상한** — base job template 의 `mem_limit` 등으로 컨테이너당 자원을 제한합니다. GPU 학습처럼 1 job 이 자원을 많이 쓰면 `--limit` 을 1~2 로 낮춥니다.

처리량을 늘리려면 `--limit` 을 키우거나, 여러 머신에서 디스패처를 더 띄워 같은 pool 에 붙입니다 ([Appendix D](#appendix-d-additional-dispatcher-attachment)).

### GPU

run 컨테이너에서 GPU 를 쓰려면 호스트에 NVIDIA 드라이버와 nvidia-container-toolkit 이 설치돼 있어야 하고, base job template 에서 GPU 를 요청해야 합니다. torch 의 CUDA 휠은 런타임을 번들하므로 호스트 드라이버가 충분히 최신이면 동작하며, 버전이 맞지 않으면 베이스 이미지를 `nvidia/cuda` 계열로 교체합니다.

## 4. Execution Architecture

Prefect 실행에는 **두 가지 모드** 가 있고, 차이는 **누가 (어떤 python 이) 코드를 실행하느냐** 입니다.

### 1) Serve Mode (Push-Based / Static)

- **동작**: `flow.serve()` 가 든 python script 를 실행하면, 그 python 프로세스가 server 에 deployment 를 등록하고 상시 떠서 신호를 수신하다가, trigger 되면 **자기 자신이** 코드를 즉시 실행합니다.
- **장점**: architecture 가 단순하여 별도 디스패처·pool 이 필요 없습니다. 단일 머신·단순 구성에 적합합니다.

### 2) Work Pool Mode (Pull-Based / Dynamic)

- **동작**: `flow.deploy()` (또는 `prefect deploy`) 로 등록만 하고 python 은 종료됩니다. 디스패처가 주기적으로 pool 에서 job 을 가져와 실행 환경을 만들어 실행하고, 끝나면 정리합니다.
- **pool 타입** — 실행 환경을 어떻게 만드느냐로 갈립니다.
  - **process pool** — 디스패처 **자신의 프로세스** 로 실행합니다. run 들이 같은 컨테이너를 공유합니다 (단일/소규모: [Appendix F](#appendix-f-process-work-pool)).
  - **docker pool (주력)** — job 마다 **새 컨테이너 (Pipeline Flow)** 를 띄워 그 안에서 실행합니다. run 마다 격리되고, 이미지를 통해 런타임을 통일할 수 있어 여러 팀원·동시 실행에 적합합니다.

### Comparison

| Aspect | Serve Mode | Work Pool — process | Work Pool — docker |
|--------|------------|---------------------|--------------------|
| Register | `flow.serve()` | `flow.deploy()` | `flow.deploy()` |
| Code executor | serve 를 띄운 python | 디스패처 프로세스 | job 마다 뜨는 컨테이너 |
| Isolation | 단일 프로세스 | run 들이 공유 | run 마다 컨테이너 격리 |
| Dependencies | 그 python 환경 | 디스패처 환경 | Pipeline Flow 이미지 |
| Best for | 단일 머신·단순 | 단일/소규모 | 다수 팀원·동시 실행 |

- **공통 — 등록** — 세 방식 모두 deployment 정의를 server 에 올리는 **등록** 은 같고, **server 자체는 코드를 실행하지 않습니다** (이름표만 보관).
- **핵심 차이 — 실행 주체** — docker pool 은 job 마다 뜨는 컨테이너의 python 이 실행하므로, 그 이미지에 라이브러리가 있어야 합니다.

## 5. Execution Topology

### Server Connection

Python client (디스패처 또는 job 을 trigger 하는 노드) 가 **어느 Prefect server 에 연결할지** 주소를 지정합니다. **최초 1회** 설정하면 이후 모든 client 명령이 이 server 를 향합니다.

```powershell
prefect config set PREFECT_API_URL="http://<Host IP>:4200/api"
# 같은 컴퓨터면 <Host IP>=localhost.
```

이 설정은 job 을 **trigger** 할 때 (`prefect deployment run ...`), **deployment 를 등록** 할 때, **Prefect Secret 블록을 등록/조회** 할 때 등 server 와 통신하는 client 작업 전반에 필요합니다.

### Code-to-Container Flow

trigger 는 코드를 보내지 않습니다. server 는 **deployment 의 참조 + 실행 파라미터** (`git_commit`·`minio_version`) 만 전달하고, 컨테이너가 그 커밋으로 직접 전환해 실행합니다.

```
[client] trigger(git_commit, minio_version) ─▶ [server] 큐에 run 등록 ─▶ [prefect_worker] job 을 가져옴
                                                                              │
                                                                              ├─ ① Pipeline Flow 이미지로 컨테이너를 띄운다
                                                                              ├─ ② git fetch && git checkout <git_commit>  (스텝 A)
                                                                              ├─ ③ minio_version 데이터 준비 → 코드 실행      (스텝 B·C)
                                                                              └─ ④ 결과 저장 → 컨테이너 자동 삭제             (스텝 D)
```

## 6. Python Execution

### Pipeline Flow

Pipeline Flow 는 **파라미터로 받은 커밋으로 소스를 전환한 뒤 실제 코드를 실행** 하는 얇은 오케스트레이터입니다. 오케스트레이터 자체는 이미지에 구운 버전으로 고정되고, 바뀌는 payload 코드 (예: `train.py`) 는 `git checkout` 후 **하위 프로세스로** 실행합니다.

```python
import subprocess
from prefect import flow, task

REPO = "/opt/pipeline"     # 이미지에 구워 둔 팀 공통 소스(.git 포함)

@task
def checkout(git_commit: str):                                   # 스텝 A
    subprocess.run(["git", "fetch", "origin"], cwd=REPO, check=True)
    subprocess.run(["git", "reset", "--hard"], cwd=REPO, check=True)      # 이전 작업 잔여물 제거
    subprocess.run(["git", "checkout", git_commit], cwd=REPO, check=True) # 지정 커밋으로 전환

@task
def ensure_data(minio_version: str):                             # 스텝 B
    # 로컬 캐시(data/)에 minio_version 이 없으면 MinIO 에서 그 버전만 내려받는다(버전 경로는 불변).
    ...

@task
def run_code():                                                  # 스텝 C
    subprocess.run(["python", "train.py"], cwd=REPO, check=True) # 전환된 커밋의 코드를 하위 프로세스로 실행

@task
def save_results():                                              # 스텝 D
    # 산출물을 MinIO 에 올리고 메타데이터를 카탈로그/서버에 기록한다.
    ...

@flow(name="pipeline")
def pipeline(git_commit: str, minio_version: str):
    checkout(git_commit)
    ensure_data(minio_version)
    run_code()
    save_results()
```

### Deployment & Trigger

오케스트레이터가 이미지에 구워져 있으므로 별도 git 소스 지정 없이 **이미지의 entrypoint** 로 등록합니다. 팀원·코드베이스 구분은 deployment 를 따로 두지 않고 **`git_commit` 파라미터** 로 처리합니다.

```python
from pipeline import pipeline

# 등록 — Pipeline Flow 이미지로, docker-pool 에 (entrypoint pipeline.py:pipeline 는 이미지 안에 있어야 한다)
pipeline.deploy(
    name="team",
    work_pool_name="docker-pool",
    image="pipeline-flow:latest",
    build=False, push=False,        # 코드는 이미지에 이미 있으므로 빌드/푸시를 끈다
)
```

```powershell
# trigger — 커밋과 데이터 버전을 파라미터로 넘긴다
prefect deployment run "pipeline/team" -p git_commit=a1b2c3d -p minio_version=v3_best
```
```python
from prefect.deployments import run_deployment
run_deployment("pipeline/team", parameters={"git_commit": "a1b2c3d", "minio_version": "v3_best"})
```

> 팀원마다 자기 커밋만 넘기면 같은 deployment·같은 이미지로 각자 다른 코드 버전을 동시에 돌릴 수 있습니다 (컨테이너가 각자 checkout).

### Credentials

코드가 **MinIO** 와 **PostgreSQL** 의 `catalog`·`optuna` DB 에 직접 접속하려면 자격증명 (`MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` / `MINIO_ENDPOINT` / `POSTGRESQL_CATALOG_DSN` / `POSTGRESQL_OPTUNA_DSN`) 이 필요합니다. 이 스택은 **Prefect Secret** 으로 다룹니다 — 값을 server 에 한 번 저장해 두면 Pipeline Flow 컨테이너의 코드가 실행 중 이름으로 받아 그대로 쓰므로, **컨테이너·머신마다 따로 넣을 필요가 없습니다.** 디스패처는 자격증명을 들고 있지 않아도 됩니다.

```python
# 저장 (admin, 1회) — server 에 등록
from prefect.blocks.system import Secret

Secret(value="<MINIO_ACCESS_KEY>").save("minio-access-key", overwrite=True)
# minio-secret-key / catalog-dsn / optuna-dsn 등도 동일하게 저장한다.
```

```python
# 사용 — flow 안에서 이름으로 로드
from prefect.blocks.system import Secret

ak = Secret.load("minio-access-key").get()   # server 에서 받아 그대로 사용
```

> run 컨테이너는 base job template 의 `PREFECT_API_URL` 로 server 에 연결돼 있어야 Secret 을 받을 수 있습니다 (§3.2). `mlflow`·`prefect` DB 는 사용자 코드가 직접 접속하지 않으므로, 사용자 role 에는 `catalog`·`optuna` DB 권한만 있으면 됩니다.

## 7. Code Delivery & Versioning

Prefect 자체는 코드를 버전관리하지 않습니다 (오케스트레이터일 뿐). 이 구성에서는 **세 축** 으로 버전이 고정됩니다.

| 축 | 무엇으로 고정 | 의미 |
|----|---------------|------|
| **코드 버전** | `git_commit` 파라미터 (`git checkout <commit>`) | 어떤 소스 커밋으로 실행할지 — 커밋 고정 시 완전 재현 |
| **런타임 버전** | Pipeline Flow 이미지 태그 | 라이브러리 + 베이스 소스 버전 |
| **데이터 버전** | `minio_version` 파라미터 | 어떤 데이터 버전을 쓸지 (불변 경로) |

- **코드 버전** — trigger 시 `git_commit` 을 커밋 SHA 로 넘기면, 컨테이너가 그 커밋으로 `checkout` 해 실행하므로 항상 같은 코드가 돕니다. 브랜치명을 넘기면 "그 시점 최신" 이 됩니다.
- **런타임 버전** — 이미지 태그 (`pipeline-flow:latest`) 가 라이브러리를 고정합니다. 라이브러리를 바꾸면 새 태그로 빌드합니다.
- **모델 ↔ 코드 연결** — MLflow 는 git repo 안에서 run 을 돌리면 git 커밋 SHA 를 자동 태그로 남기므로, "이 모델이 어떤 코드로 학습됐나" 는 MLflow 의 git 커밋 태그로 추적됩니다 (데이터 lineage 는 카탈로그가 담당).

> **Private repo** — 이미지 빌드의 `git clone` 과 런타임 `git fetch` 가 private repo 면 토큰이 필요합니다. 빌드 시 토큰을 build secret 으로 주입하거나, 런타임 토큰을 Prefect Secret 으로 받아 인증된 remote 로 fetch 합니다. public repo 면 그대로 됩니다.

## Appendix A. Terminology

- **Host (호스트)** — 모든 컨테이너 (server·worker·Pipeline Flow·postgres·minio·mlflow) 가 올라가는 한 대의 컴퓨터입니다.
- **`prefect_server`** — API·UI·스케줄러·work pool 대기열을 제공하는 중앙 진입점 (도커 컨테이너) 입니다. 메타데이터 (`prefect` DB) 만 관리하고 코드는 실행하지 않습니다.
- **`prefect_worker` (디스패처)** — docker work pool 을 폴링해 job 마다 Pipeline Flow 컨테이너를 띄우고 정리하는 worker (도커 컨테이너) 입니다. 코드는 실행하지 않습니다.
- **Pipeline Flow** — 디스패처가 job 마다 띄우는 일시적 실행 컨테이너입니다. 받은 커밋으로 checkout 한 뒤 코드를 실행하고 끝나면 스스로 파괴됩니다.
- **work pool** — job 이 대기하는 큐이자 실행 방식 (process/docker) 의 정의입니다. server 안의 메타데이터이며 컨테이너가 아닙니다.
- **deployment** — flow 를 언제·어떻게·어떤 파라미터로 실행할지 묶어 server 에 등록해 두는 실행 정의입니다.
- **base job template** — pool 이 띄우는 run 컨테이너의 공통 설정 (이미지·env·네트워크·볼륨) 입니다.
- **`CONTROL_NODE_HOST`** — 디스패처가 Control Node 의 server 를 찾는 주소입니다. 같은 호스트면 서비스명 `prefect_server` 입니다.

**약자 (Abbreviations)**

- **AWS** = Amazon Web Services
- **S3** = (Amazon) Simple Storage Service — MinIO 가 호환하는 오브젝트 스토리지 API
- **API** = Application Programming Interface
- **UI** = User Interface
- **DB** = Database
- **DSN** = Data Source Name (DB 접속 문자열)
- **CPU / GPU** = Central / Graphics Processing Unit

## Appendix B. Prefect CLI

`prefect` CLI 는 Prefect SDK 와 함께 설치되는 명령행 도구 (`pip install prefect`) 입니다.

- `prefect config set PREFECT_API_URL="http://<Host IP>:4200/api"` — client 가 바라볼 server 주소를 프로필에 1회 저장합니다 (§5).
- `prefect server start --host 0.0.0.0` — Prefect server 를 기동합니다 (§2).
- `prefect work-pool create <name> --type docker --base-job-template <file> [--overwrite]` — docker work pool 을 만듭니다 (§3.3).
- `prefect work-pool get-default-base-job-template --type docker` — 도커 worker 의 기본 base job template 을 출력합니다 (§3.2).
- `prefect work-pool set-concurrency-limit <pool> <N>` — pool 전체 동시 실행 상한을 설정합니다.
- `prefect worker start --pool <name> [--limit N]` — 디스패처를 기동해 그 pool 을 폴링하며 job 을 실행합니다 (§3.3).
- `prefect deploy` (또는 `flow.deploy(...)`) — deployment 를 등록합니다 (§6).
- `prefect deployment run "<flow>/<deployment>" -p <key>=<value>` — 등록된 deployment 를 파라미터와 함께 trigger 합니다 (§6).

## Appendix C. docker-compose.env example

자격증명·endpoint 는 yml 에 평문으로 두지 않고 `docker-compose.env` 한 파일에 모읍니다. 실제 값이 담긴 `docker-compose.env` 는 `.gitignore` 로 제외하고, 비밀값을 비운 `docker-compose.env_example` 만 커밋합니다.

```dotenv
# docker-compose.env_example  (모든 값은 placeholder — 실제 값 노출 금지)

# ── prefect-server ──
PREFECT_SERVER_DATABASE_CONNECTION_URL=postgresql+asyncpg://CHANGE_ME:CHANGE_ME@postgres:5432/prefect

# ── prefect-worker (디스패처) ──
# 디스패처가 Prefect server 를 찾는 주소. 같은 호스트면 서비스명 prefect_server,
# 다른 머신이면 호스트의 IP/호스트명(이때 worker compose 의 networks 블록은 제거).
CONTROL_NODE_HOST=prefect_server
```

- server 는 `postgres` 서비스명으로 backend 에 접속하므로 URL 의 호스트가 `postgres` 입니다.
- 디스패처는 코드를 실행하지 않으므로 MinIO·카탈로그 자격증명이 필요 없습니다 — 그 값들은 Pipeline Flow 컨테이너의 코드가 Prefect Secret 블록으로 받아 씁니다 (§6 Credentials).

## Appendix D. Additional Dispatcher Attachment

> **선택 사항입니다.** 호스트 하나로 충분하면 건너뛰어도 됩니다. 처리량을 분산하거나 특정 머신 (예: GPU) 에서만 실행하려면 다른 머신에서 디스패처를 더 띄워 같은 server 의 work pool 에 붙입니다.

디스패처는 server 와 분리돼 있어 그 머신에서 docker work pool 을 폴링하기만 하면 합류합니다. 전제로 그 컴퓨터에서 server (`http://<Host IP>:4200`) 에 네트워크로 접근 가능해야 하고, Pipeline Flow 이미지가 있어야 합니다.

```powershell
# 추가 디스패처 — pool 생성은 건너뛰고 폴링만(다른 머신이면 CONTROL_NODE_HOST 를 IP 로, networks 블록 제거)
$env:CREATE_POOL="false"; docker compose -p <Project Name> -f docker-compose.worker.yml up -d
```

특정 머신 전용으로 라우팅하려면 그 머신 전용 pool 을 만들고 deployment 를 그 pool 로 보냅니다 (`$env:WORK_POOL="docker-gpu"`).

## Appendix E. Monitoring

- **work pool** — `prefect work-pool ls` (목록), `prefect work-pool inspect <pool>` (상세·base job template).
- **디스패처** — UI `http://<Host IP>:4200` 의 Work Pools → 해당 pool → Workers (online 여부·last polled). heartbeat 로 추적되어 끄면 잠시 뒤 offline 으로 바뀝니다.
- **Pipeline Flow 컨테이너** — 호스트에서 `docker ps` 로 job 마다 뜬 컨테이너를 직접 봅니다 (`auto_remove` 라 끝나면 사라집니다).
- **flow run** — UI 의 Flow Runs 에서 상태·로그를, CLI 는 `prefect flow-run ls` 로 최근 run 목록을 봅니다.

## Appendix F. Process Work Pool

단일 머신·소규모 구성에서는 컨테이너를 매 run 띄우는 대신 디스패처 **자신의 프로세스** 로 실행하는 process pool 이 더 단순합니다. 이때는 디스패처 환경에 라이브러리를 직접 설치해야 하고, 코드는 bind-mount 로 그 머신에 둡니다. run 들이 같은 프로세스 공간을 공유하므로 격리는 약합니다.

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

- process pool 은 코드를 마운트된 디스크에서 읽으므로 컨테이너로 코드를 전달하는 단계가 없습니다. 대신 그 머신에 코드가 있어야 합니다.

## Appendix G. Orchestrator Benchmarking

"**가벼운 에이전트 (디스패처) 가 작업을 집어, 작업마다 격리된 일시적 실행 단위를 띄워 실행하고 정리**" 하는 패턴은 오케스트레이션 전반의 업계 표준입니다. 이 스택의 docker work pool 은 그 표준의 **단일 호스트 변형** 이고, 규모가 커지면 실행 단위를 컨테이너 → **pod** 로 올린 Kubernetes 변형으로 자연스럽게 확장됩니다.

| System | Dispatcher (agent) | Execution unit | Scale |
|--------|--------------------|----------------|-------|
| **Prefect** (docker pool) | worker | run 마다 **컨테이너** | 단일 호스트·소~중 |
| **Prefect** (kubernetes pool) | worker | run 마다 **pod** | 클러스터·대 |
| **Airflow** (KubernetesExecutor) | scheduler/executor | task 마다 **pod** | 클러스터·대 |
| **Argo Workflows** | controller | step 마다 **pod** | 클러스터·대 |
| **GitHub Actions / GitLab CI** | runner | job 마다 **컨테이너** | CI/CD |
| **Kubernetes** (native Job) | controller | **pod** | 클러스터 |

### pod 의 정의

- **pod** — Kubernetes 의 **최소 실행/배포 단위** 입니다. 컨테이너 하나 이상이 **같은 네트워크 (IP)·스토리지를 공유** 하며 한 덩어리로 스케줄됩니다. 오케스트레이션에서 "작업 1개 → pod 1개" 가 격리 단위가 됩니다. 즉 docker pool 의 "컨테이너" 자리에 클러스터 규모에서 들어가는 것이 pod 입니다 (Prefect/Airflow 의 개념이 아니라, 그 아래 Kubernetes 의 실행 껍데기입니다).

### job · task · step 의 비교

이 세 단어는 **동의어가 아니라 서로 다른 단위 (granularity)** 입니다. 도구마다 이름이 조금씩 달라 혼동되므로, 공통 계층으로 정리하면 다음과 같습니다.

| 공통 개념 | 정의 | Prefect | Airflow | Argo | GitHub Actions |
|-----------|------|---------|---------|------|----------------|
| **Workflow / Pipeline** | 전체 작업 그래프의 정의 | flow | DAG | Workflow | workflow |
| **Run (1회 실행)** | 그 정의를 한 번 실행한 인스턴스 | flow run | DAG run | Workflow (instance) | run |
| **Task** | run 안의 한 작업 단위 (1 연산) | task | task | template | — |
| **Step** | job/task 안의 **순서 있는 하위 동작** | — | — | step | step |
| **Job** | 제출되는 상위 작업 묶음 (실행 단위로 스케줄) | flow run ≈ job | — | — | job |

- **job** — 시스템에 제출되어 한 덩어리로 스케줄되는 **상위 작업** 입니다 (GitHub Actions 의 job, Kubernetes 의 Job). Prefect 에서는 한 flow run 이 사실상 이 job 에 해당합니다.
- **task** — run 안의 **개별 작업 단위 (1 연산)** 입니다 (Prefect·Airflow 의 task). `@task` 하나가 여기에 해당합니다.
- **step** — job/task 안에서 **순서대로 실행되는 하위 동작** 입니다 (Argo·CI 의 step). 이 문서의 스텝 A~D 가 이 의미입니다.

> 정리하면 granularity 는 **Workflow → Run/Job → Task → Step** 순으로 좁아지고, 그 실행을 감싸는 껍데기가 **컨테이너 (단일 호스트) / pod (클러스터)** 입니다. 세 단어를 하나로 "통일" 하기보다, 이 계층 안에서 각자의 자리를 구분해 쓰는 것이 업계 표준에 맞습니다.
