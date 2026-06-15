# Prefect with remote worker

Prefect 스택을 **제어 노드와 워커 노드로 나눠** 도커로 실행하는 방법을 설명합니다. 제어 노드(머신 A)는 오케스트레이션 서버와 그 backend(메타데이터 DB·오브젝트 스토리지·실험 추적)를 모아 띄우고, 워커 노드(머신 B)는 실제 코드를 실행하는 워커만 띄워 네트워크로 제어 노드에 붙습니다.

Prefect 서버(`prefect_server`)는 잡(Job) 요청을 중앙에서 수집·스케줄링하는 **단일 진입점(Single Point of Entry)** 입니다. 다만 **`prefect_server` 는 코드를 실행하지 않습니다** — 코드는 항상 실행기(`python` 프로세스 또는 `prefect_worker`)가 떠 있는 컴퓨터에서 돕니다.

## 1. Architecture

이 구성은 두 층으로 나뉘며, 두 층은 서로 다른 컴퓨터에서 돌 수 있습니다.

| layer | machine | services | 연결 방식 |
|-------|---------|----------|----------|
| **Control Plane** | 머신 A | `postgres` · `minio` · `mlflow` · `prefect_server` | 같은 호스트에서 공유 네트워크 `mlops` 로 묶여 서비스명으로 통신합니다. |
| **Worker Node** | 머신 B | `prefect_worker` | 다른 컴퓨터이므로 `CONTROL_PLANE_HOST`(머신 A 의 IP/호스트명)로 접속합니다. |

- **제어 노드(머신 A)** 의 서비스들은 한 컴퓨터 안에서 도커 네트워크 `mlops` 를 공유하므로, 서로를 `postgres:5432` · `minio:9000` 처럼 **서비스명** 으로 찾습니다.
- **워커 노드(머신 B)** 는 제어 노드와 다른 컴퓨터라 도커 네트워크를 공유할 수 없으므로, 제어 노드가 노출한 포트(`:4200` · `:9000` · `:5432`)로 **IP/호스트명** 을 통해 접속합니다. 그 주소를 `CONTROL_PLANE_HOST` 로 지정합니다.
- 같은 컴퓨터에서 워커를 띄워 시험할 때는 `CONTROL_PLANE_HOST` 를 `host.docker.internal` 로 두면 됩니다.

> 워커 노드가 제어 노드에 네트워크로 접근 가능해야 합니다(같은 LAN 또는 도달 가능한 호스트). 두 노드가 같은 네트워크에 있으면 추가 방화벽 설정 없이 IP 로 바로 묶입니다.

각 서비스의 역할은 다음과 같습니다.

| service | endpoint | 설명 |
|---------|----------|------|
| `postgres` | `:5432` | 메타데이터 DB 입니다. 한 인스턴스에서 `prefect`/`mlflow`/`optuna`/`catalog` 4개 논리 DB 를 운영합니다. |
| `minio` | `:9000` (S3 API) · `:9001` (콘솔) | 오브젝트 스토리지입니다. 데이터·모델·아티팩트를 보관합니다. |
| `mlflow` | `:5000` | 실험 추적 서버 + 모델 레지스트리입니다. backend 는 `postgres`, artifact 는 `minio` 입니다. |
| `prefect_server` | `:4200` | Prefect 서버 + 대시보드(UI)입니다. backend 는 `postgres` 입니다. |
| `prefect_worker` | — | work pool 에서 잡을 가져와 코드를 실행합니다. `default` pool, 동시 최대 8개(`--limit 8`)입니다. |

> `postgres` · `minio` · `mlflow` 는 각자 자기 폴더의 compose 로 제어 노드에서 띄웁니다. 이 문서는 그중 **Prefect 서버와 워커** 의 설치·실행에 집중합니다.

## 2. Prefect Server Setup

제어 노드(머신 A)에서 실행합니다. 서버는 backend 인 `postgres` 가 같은 제어 노드에서 먼저 떠 있어야 정상 동작하므로, **PostgreSQL → (MinIO/MLflow) → Prefect 서버** 순으로 띄우길 권장합니다.

```powershell
# (최초 1회) 예시 파일을 복사해 server 섹션의 값을 채운다. docker-compose.env 는 git 에 커밋하지 않는다.
Copy-Item docker-compose.env_example docker-compose.env

# 공유 네트워크 mlops 를 보장하고 서버를 백그라운드로 띄운다(기본 역할이 server).
.\set_docker.ps1
```

실행 후 Prefect 대시보드는 **http://localhost:4200** 에서 열립니다(다른 컴퓨터에서는 `http://<머신 A 주소>:4200`).

```yaml
# docker-compose.server.yml
services:
  prefect_server:
    image: prefecthq/prefect:3-latest
    command: prefect server start --host 0.0.0.0
    env_file:
      - docker-compose.env          # PREFECT_SERVER_DATABASE_CONNECTION_URL 을 주입한다.
    ports:
      - "4200:4200"                 # 대시보드/API. 워커 노드와 클라이언트가 이 포트로 접속한다.
    networks:
      - mlops
    restart: unless-stopped

networks:
  mlops:
    external: true
```

- `command: prefect server start --host 0.0.0.0` 은 컨테이너 밖(다른 컴퓨터 포함)에서도 접속할 수 있도록 모든 인터페이스에 바인딩합니다.
- `env_file` 의 `PREFECT_SERVER_DATABASE_CONNECTION_URL` 은 `postgres` 서비스명으로 `prefect` DB 에 접속하는 URL 입니다(제어 노드의 `mlops` 네트워크 안이라 호스트가 `postgres` 입니다).
- `networks: mlops` 로 같은 제어 노드의 `postgres` 와 서비스명으로 통신합니다. `postgres` 는 별도 compose 라 `depends_on` 을 걸 수 없으므로, `restart: unless-stopped` 로 준비될 때까지 자동 재시도합니다.

## 3. Prefect Worker Setup

워커 노드(머신 B)에서 실행합니다. 워커는 제어 노드와 다른 컴퓨터이므로 `CONTROL_PLANE_HOST` 로 제어 노드 주소를 지정해 붙습니다.

```powershell
# (최초 1회) 예시 파일을 복사해 worker 섹션(CONTROL_PLANE_HOST·자격증명)을 채운다.
Copy-Item docker-compose.env_example docker-compose.env

# 워커 역할로 띄운다.
.\set_docker.ps1 -Role worker
```

```yaml
# docker-compose.worker.yml
services:
  prefect_worker:
    image: prefecthq/prefect:3-latest
    env_file:
      - docker-compose.env          # CONTROL_PLANE_HOST, POSTGRES_*, MINIO_ACCESS_KEY/SECRET, AWS_*
    command: >
      bash -c "export PREFECT_API_URL=http://$$CONTROL_PLANE_HOST:4200/api &&
               export MINIO_ENDPOINT=http://$$CONTROL_PLANE_HOST:9000 &&
               export POSTGRESQL_CATALOG_DSN=postgresql://$$POSTGRES_USER:$$POSTGRES_PASSWORD@$$CONTROL_PLANE_HOST:5432/catalog &&
               prefect work-pool create default --type process --overwrite &&
               prefect worker start --pool default --limit 8"
    volumes:
      - ../../Prefect:/app          # flow 코드(catalog.py, example/)가 있는 폴더를 /app 으로 마운트한다.
    working_dir: /app
    restart: unless-stopped
```

- 워커는 `CONTROL_PLANE_HOST` 한 값으로 API(`:4200`)·MinIO(`:9000`)·카탈로그 DB(`:5432`)를 모두 가리킵니다. 엔드포인트에 비밀번호·호스트가 섞이므로 `command` 안에서 `env_file` 값으로 조립해 `export` 합니다.
- `volumes: ../../Prefect:/app` 은 flow 코드가 있는 `MLOps/Prefect` 폴더를 마운트합니다. **워커 노드에도 이 저장소가 같은 구조로 있어야** 합니다.
- `restart: unless-stopped` 는 제어 노드(API)가 늦게 떠 연결에 실패해 종료돼도 자동으로 다시 붙게 합니다.

### Concurrency & Scaling

워커 1개가 동시에 돌리는 job 수는 `--limit` 값(현재 8)입니다. 워커는 work pool 에서 잡을 가져와 실행하는데, `prefect worker start --pool default --limit 8` 의 `--limit` 이 그 워커의 **동시 실행 상한** 입니다. 9번째 잡은 앞 잡 하나가 끝나 슬롯이 빌 때까지 대기열에서 기다립니다. 처리량을 늘리는 방법은 두 가지입니다 — `--limit` 을 키우거나(`--limit N`), 워커 수를 늘립니다(`docker compose -f docker-compose.worker.yml up -d --scale prefect_worker=3`). 이때 **전체 동시 실행 수 ≈ 워커 수 × `--limit`** 입니다. 다만 무작정 키우지 말고 워커 노드의 **CPU/GPU/메모리 한도** 안에서 정해야 하며(자원 경합 시 오히려 느려집니다), GPU 학습처럼 1잡이 자원을 많이 쓰면 `--limit` 을 1~2 로 낮추는 편이 안전합니다.

### Python Version & Dependencies

기본 워커 이미지(`prefecthq/prefect:3-latest`)에는 **python 과 prefect 만** 들어 있어, work pool mode 로 사용자 코드를 실행하면 `import torch` 같은 **라이브러리가 없어 실패** 할 수 있습니다([§4](#4-execution-architecture) 참고). work pool mode 를 쓰려면 워커에 **python 버전을 고정** 하고 **필요한 라이브러리를 설치** 해야 합니다. (serve mode 만 쓰면 코드를 실행하는 컴퓨터의 python 이 이미 라이브러리를 갖고 있으므로 이 작업이 필요 없습니다.)

가장 간단한 방법은 워커가 뜰 때 `requirements.txt` 를 설치하도록 `command` 맨 앞에 설치 단계를 두는 것입니다.

```yaml
    command: >
      bash -c "pip install -r /app/requirements.txt &&
               export PREFECT_API_URL=http://$$CONTROL_PLANE_HOST:4200/api &&
               export MINIO_ENDPOINT=http://$$CONTROL_PLANE_HOST:9000 &&
               export POSTGRESQL_CATALOG_DSN=postgresql://$$POSTGRES_USER:$$POSTGRES_PASSWORD@$$CONTROL_PLANE_HOST:5432/catalog &&
               prefect work-pool create default --type process --overwrite &&
               prefect worker start --pool default --limit 8"
```

매번 설치가 느리면 `Dockerfile`(`FROM prefecthq/prefect:3-python3.11` + `RUN pip install -r requirements.txt`)로 한 번 빌드한 뒤 `image:` 대신 `build:` 로 쓰면 더 빠릅니다.

## 4. Execution Architecture

Prefect 실행에는 **두 가지 모드** 가 있고, 차이는 **누가(어떤 python 이) 코드를 실행하느냐** 입니다. 두 모드는 아키텍처가 다릅니다.

### 1) Push-Based / Static Architecture (Serve Mode)

- **구조적 특징**: 개발자가 코드가 실행될 인프라를 미리 준비하고 프로세스를 직접 구동해 놓는 구조입니다.
- **동작**: `flow.serve()` 가 든 python 스크립트를 실행하면, 그 python 프로세스가 서버에 deployment 를 등록하고 상시 떠서 Prefect 서버의 신호를 수신하다가, 트리거되면 **자기 자신이** 코드를 즉시 실행합니다(실행하는 python = 스크립트를 띄운 그 python).
- **장점**: 아키텍처가 단순하여 별도의 워커를 띄울 필요가 없습니다.

### 2) Pull-Based / Dynamic Architecture (Work Pool Mode)

- **구조적 특징**: Prefect 서버와 실제 인프라 사이에 중간 매개체인 Work Pool(큐)과 Worker(에이전트)를 두는 분산 구조입니다.
- **동작**: `flow.deploy()`(또는 `prefect deploy`)로 등록만 하고 python 은 종료됩니다. Worker 가 주기적으로 Work Pool 에서 작업 요청을 가져온 뒤 실행 환경을 만들어 **Worker 의 python** 으로 작업을 실행하고, 끝나면 정리합니다(실행하는 python = Worker 의 python → 그래서 Worker 환경에 라이브러리 설치가 필요합니다).
- **장점**: 확장성이 뛰어나며, 다양한 이기종 인프라를 중앙에서 유연하게 제어할 수 있습니다.

### Comparison

| Aspect | Serve Mode (`flow.serve()`) | Work Pool Mode (`flow.deploy()`) |
|--------|------------------------------|-----------------------------------|
| Architecture | Push-based / static | Pull-based / dynamic |
| Register | `flow.serve()` | `flow.deploy()` / `prefect deploy` |
| Code executor | `flow.serve()` 를 실행한 python 프로세스 | Worker(별도 에이전트) |
| Python that runs code | 스크립트를 띄운 그 python | Worker 의 python(런타임/이미지) |
| Separate worker needed | No | Yes (`prefect worker start`) |
| Dependencies (numpy, torch 등) | 이미 그 python 환경에 있음 | Worker 런타임에 설치해야 함 |
| Best for | 단일 머신, 단순 구성 | 확장성, 이기종 인프라 |

두 모드 모두 **등록**(deployment 정의를 Prefect 서버에 올림)은 공통이고, **Prefect 서버는 코드를 실행하지 않습니다**(이름표만 보관합니다). 위 표의 핵심 차이는 **코드를 실제로 실행하는 python 이 누구냐** 이며 — Serve mode 는 스크립트를 띄운 python 이, Work pool mode 는 Worker 의 python 이 실행합니다. 나머지 행은 모두 이 차이에서 따라옵니다.

## 5. Workflow Execution

### Server Connection

Prefect 클라이언트가 **어느 Prefect 서버에 연결할지** 지정합니다. **최초 1회** 설정하면 이후 모든 client 명령이 이 서버를 향합니다.

```powershell
prefect config set PREFECT_API_URL="http://<머신 A 주소>:4200/api"
# 같은 컴퓨터면 <머신 A 주소>=localhost, 다른 컴퓨터의 서버면 그 IP/호스트명을 쓴다.
```

이 설정은 잡을 **트리거** 할 때(`prefect deployment run ...`), **Prefect Secret 블록을 등록/조회** 할 때, 그 밖에 Prefect 서버와 통신하는 client 작업 전반에 필요합니다.

> 이는 MinIO/PostgreSQL **자격증명이 아니라 Prefect 서버 주소** 설정입니다.

### Code Execution Methods

| Case | Trigger | Trigger Loc | Execution Mode | Execution Loc | Credentials |
|------|---------|-------------|----------------|---------------|-------------|
| **A** | admin | 제어 노드 | serve | 제어 노드 | 불필요 |
| **B** | user | client 컴퓨터 | work pool | 워커 노드 | 불필요 |
| **C** | user | 제어 노드 | serve | 제어 노드 | 필요 |
| **D** | user | client 컴퓨터 | serve | client 컴퓨터 | 필요 |
| **E** | user | client 컴퓨터 | work pool | client 컴퓨터 | 필요 |

**Credentials** 열은 코드를 실행하는 주체(serve mode 면 그 python 프로세스, work pool mode 면 `prefect_worker`)가 MinIO·PostgreSQL 에 접속할 **자격증명을 user 가 직접 공급해야 하는지** 를 나타냅니다.

- **필요**: 코드가 실행되는 그 컴퓨터에서 자격증명을 쓸 수 있게 해줘야 합니다. 그 컴퓨터에 **환경변수** 로 등록하거나, **Prefect Secret**(Prefect 서버에 저장해 두고 코드가 이름으로 불러옴)으로 공급합니다. 셋업 방법은 아래 [Credentials](#credentials) 를 참고합니다.
- **불필요**: user 별 별도 자격증명이 필요 없습니다. 잡을 제어 노드/워커가 대신 실행하므로, user 는 [Server Connection](#server-connection) 만 하면 됩니다.

### Trigger

- **serve mode**: `flow.serve(name="...")`
- **work pool mode**: `flow.deploy(name="...")` 또는 `prefect deployment run "<flow-name>/<deployment-name>"`

`"<flow-name>/<deployment-name>"` 에서 `<flow-name>` 은 코드의 `@flow(name="...")` 에 준 flow 이름이고, `<deployment-name>` 은 `.serve(name="...")` / `.deploy(name="...")` 에 준 deployment 이름입니다.

### Credentials

자격증명은 `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` / `MINIO_ENDPOINT` / `POSTGRESQL_CATALOG_DSN` 등으로 구성됩니다. 코드가 **MinIO**(데이터·모델 저장소)와 **PostgreSQL**(카탈로그 DB)에 접속해 데이터를 읽고 쓰기 위해 필요합니다. 아래 둘 중 하나로 셋업합니다.

**방법 1 — 환경변수**: 코드를 실행하는 컴퓨터에 자격증명을 환경변수로 설정해 두면 코드가 `os.environ` 에서 읽습니다.

**방법 2 — Prefect Secret**: 자격증명을 Prefect 서버에 Secret 으로 저장해 두고 코드가 이름으로 불러옵니다.

```python
# 저장(admin, 1회)
from prefect.blocks.system import Secret

Secret(value="<MINIO_ACCESS_KEY>").save("minio-access-key", overwrite=True)
# minio-secret-key / catalog-dsn 등도 동일하게 저장한다.
```

```python
# 사용 — flow 안에서 이름으로 로드
from prefect import flow
from prefect.blocks.system import Secret

@flow
def my_pipeline():
    ak = Secret.load("minio-access-key").get()   # 서버에서 로드 → 실제 값
    ...
```

## Appendix A. Terminology

- **Control Plane(제어 노드)** — 오케스트레이션 서버와 그 backend(메타데이터 DB·오브젝트 스토리지·실험 추적)를 모아 띄우는 컴퓨터(머신 A)입니다.
- **Worker Node(워커 노드)** — 실제 코드를 실행하는 워커만 띄우는 컴퓨터(머신 B)입니다. 제어 노드와 다른 컴퓨터일 수 있습니다.
- **`prefect_server`** — API·UI·스케줄러·work pool 대기열을 제공하는 중앙 진입점(도커 컨테이너)입니다. 메타데이터(`prefect` DB)만 관리하고 코드는 실행하지 않습니다.
- **`prefect_worker`** — work pool 에서 잡을 가져와 실제 코드를 실행하는 워커(도커 컨테이너)입니다.
- **`CONTROL_PLANE_HOST`** — 워커 노드가 제어 노드를 찾는 주소(IP/호스트명)입니다. 같은 컴퓨터에서 시험할 때는 `host.docker.internal` 을 씁니다.

**약자(Abbreviations)**

- **AWS** = Amazon Web Services
- **GCP** = Google Cloud Platform
- **S3** = (Amazon) Simple Storage Service — MinIO 가 호환하는 오브젝트 스토리지 API
- **API** = Application Programming Interface
- **UI** = User Interface
- **DB** = Database
- **DSN** = Data Source Name(DB 접속 문자열)
- **CPU / GPU** = Central / Graphics Processing Unit

## Appendix B. Handy Commands

```powershell
# 제어 노드(server) — docker-compose.server.yml 대상
docker compose -f docker-compose.server.yml up -d        # 백그라운드 실행
docker compose -f docker-compose.server.yml logs -f prefect_server   # 서버 로그
docker compose -f docker-compose.server.yml down         # 정지 + 제거(볼륨 유지)

# 워커 노드(worker) — docker-compose.worker.yml 대상
docker compose -f docker-compose.worker.yml up -d                    # 워커 실행
docker compose -f docker-compose.worker.yml logs -f prefect_worker   # 워커가 신호를 잘 받는지 확인
docker compose -f docker-compose.worker.yml up -d --scale prefect_worker=3   # 워커 수 늘리기
docker compose -f docker-compose.worker.yml down         # 워커 정지 + 제거
```

## Appendix C. docker-compose.env example

자격증명·엔드포인트는 yml 에 평문으로 두지 않고 `docker-compose.env` 한 파일에 모읍니다. 컨테이너는 각 서비스가 `env_file` 로 읽습니다. 실제 값이 담긴 `docker-compose.env` 는 `.gitignore` 로 제외하고, 비밀값을 비운 아래 `docker-compose.env_example` 만 커밋합니다. 제어 노드에는 server 섹션을, 워커 노드에는 worker 섹션을 채웁니다.

```dotenv
# docker-compose.env_example  (모든 값은 CHANGE_ME placeholder — 실제 값 노출 금지)

# ── prefect-server (제어 노드, 머신 A) ──
PREFECT_SERVER_DATABASE_CONNECTION_URL=postgresql+asyncpg://CHANGE_ME:CHANGE_ME@postgres:5432/prefect

# ── prefect-worker (워커 노드, 머신 B) ──
CONTROL_PLANE_HOST=CHANGE_ME       # 머신 A 의 IP/호스트명. 같은 컴퓨터면 host.docker.internal
POSTGRES_USER=CHANGE_ME
POSTGRES_PASSWORD=CHANGE_ME
MINIO_ACCESS_KEY=CHANGE_ME
MINIO_SECRET_KEY=CHANGE_ME
AWS_ACCESS_KEY_ID=CHANGE_ME
AWS_SECRET_ACCESS_KEY=CHANGE_ME
```

- 제어 노드의 서버는 `postgres` 서비스명으로 backend 에 접속하므로 URL 의 호스트가 `postgres` 입니다.
- 워커 노드는 `CONTROL_PLANE_HOST` 로 제어 노드를 가리키며, `command` 안에서 이 값으로 API/MinIO/카탈로그 DSN 을 조립합니다.
- 명령 안에서 자격증명을 참조할 때는 `$$VAR`(예: `$$POSTGRES_USER`)로 적습니다. `$$` 는 compose 가 `$` 로 바꿔 컨테이너 셸이 `env_file` 값으로 확장합니다.
- 모든 `CHANGE_ME` 는 강한 값으로 교체하고, 실제 `docker-compose.env` 는 git 이 아니라 안전한 채널로 공유합니다.

## Appendix D. Additional Worker Attachment

> **선택 사항입니다.** 워커 노드 하나로 충분하면 이 절은 건너뛰어도 됩니다. user 가 자기 컴퓨터의 로컬 자원(특히 GPU)에서 학습을 돌려야 하거나, 처리량을 분산하고 싶을 때만 필요합니다.

Prefect 의 **서버**(잡 대기열·대시보드)와 **워커**(실제 실행 주체)는 분리되어 있습니다. 따라서 user 는 제어 노드를 건드리지 않고, **자기 컴퓨터에서 워커만 띄워 같은 서버의 work pool 에 붙일 수 있습니다.** 그러면 그 user 에게 배정된 잡은 user 의 로컬 자원(GPU 등)에서 실행됩니다.

전제로, 그 컴퓨터에서 제어 노드(`http://<머신 A 주소>:4200`)에 네트워크로 접근 가능해야 합니다.

```powershell
# 1) 로컬 컴퓨터에 Prefect 를 설치한다.
pip install prefect

# 2) 서버 주소를 설정한다(§5 Server Connection 참고).
prefect config set PREFECT_API_URL="http://<머신 A 주소>:4200/api"

# 3) (work pool 이 아직 없다면 한 번만) process 타입 풀을 만든다.
prefect work-pool create default --type process

# 4) 같은 'default' 풀에 워커를 붙여 대기시킨다(이 창은 실행 상태로 유지된다).
prefect worker start --pool default
```

이렇게 하면 도커 워커 노드와 **로컬 워커가 같은 `default` 풀** 을 함께 바라보게 되고, 잡이 가용한 워커로 분산 실행됩니다.

> 풀을 user 별로 나누고 싶다면(예: user2 잡은 user2 컴퓨터에서만 실행), 별도 풀을 만들고 그 풀로 워커를 띄운 뒤 해당 deployment 를 그 풀로 지정합니다.
> ```powershell
> prefect work-pool create member2-pool --type process
> prefect worker start --pool member2-pool
> ```
