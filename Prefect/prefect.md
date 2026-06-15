# Prefect

Prefect 스택(서버·워커·메타데이터 DB·오브젝트 스토리지·실험 추적)을 **도커로 실행/구성**하는 방법입니다.

Prefect 서버(`prefect_server`)는 작업(Job) 요청을 중앙에서 수집하고 스케줄링하는 **단일 진입점(Single Point of Entry)** 입니다. 단, **`prefect_server` 는 코드를 실행하지 않습니다** — 코드는 항상 실행기(`python` 프로세스 또는 `prefect_worker`)가 떠 있는 컴퓨터(server host)에서 돕니다.

## 1. Configuration

`docker-compose.yml`이 정의하는 서비스 구성입니다 ([Chap 2](#2-docker-setup) 참고).

| service | endpoint | features |
|---------|----------|----------|
| `postgres` | `:5432` | 메타데이터 DB — 4 logical DBs: `prefect`/`mlflow`/`optuna`/`catalog`, init SQL 인라인 |
| `minio` | `:9000` (S3 API) · `:9001` (콘솔) | 오브젝트 스토리지 — 3 buckets: `datasets`/`models`/`mlflow`, `minio-data` 볼륨 |
| `createbuckets` | — | 1회용 — 버킷 생성 + 버저닝 ON(`datasets`/`models`) 후 종료 |
| `mlflow` | `:5000` | 추적 서버 + 모델 레지스트리 — backend=`postgres`, artifact=`minio` |
| `prefect_server` | `:4200` | Prefect 서버 + 대시보드(UI) |
| `prefect_worker` | — | 잡 실행 — `default` pool, **동시 최대 8개 job**(`--limit 8`), `restart: unless-stopped` |

## 2. Docker Setup

`docker-compose.yml`이 있는 폴더에서 실행합니다. **자격증명은 `docker-compose.env`에서 읽으므로**, 처음 한 번은 예시 파일을 복사해 값을 채워둡니다([Appendix C](#appendix-c-docker-composeenv-example) 참고).

```powershell
# (최초 1회) 예시 파일을 복사해 비밀번호/키를 채운다. docker-compose.env 는 git 에 커밋하지 않는다.
Copy-Item docker-compose.env_example docker-compose.env

# 전체 스택을 백그라운드(detached)로 한 번에 실행
docker compose up -d
```

실행 후 접속:

- Prefect 대시보드: **http://localhost:4200**
- MLflow UI: **http://localhost:5000**
- MinIO 콘솔: **http://localhost:9001**

아래가 전체 `docker-compose.yml` 입니다.

```yaml
services:
  # 1) 메타데이터 DB — prefect/mlflow/optuna/catalog 4개 논리 DB를 한 인스턴스에서 운영.
  #    init SQL 은 아래 configs.init_sql 로 yml 안에 인라인되어, 최초 기동 시 4개 DB 를 만든다.
  postgres:
    image: postgres:16
    env_file:
      - docker-compose.env   # POSTGRES_USER / POSTGRES_PASSWORD 주입(기본 DB=postgres, 4개 DB 는 init_sql 이 생성)
    ports:
      # 호스트의 catalog.py / data_uploader.ps1 이 localhost:5432 로 접속할 수 있도록 노출.
      - "5432:5432"
    volumes:
      - pg-data:/var/lib/postgresql/data
    configs:
      # 아래 configs 의 init_sql 이 /docker-entrypoint-initdb.d/init.sql 로 마운트되어 최초 기동 시 자동 실행된다.
      - source: init_sql
        target: /docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER"]
      interval: 5s
      retries: 10

  # 2) 오브젝트 스토리지 — 실제 대용량 데이터/모델/아티팩트 (S3 호환). 콘솔: http://localhost:9001
  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    env_file:
      - docker-compose.env   # MINIO_ROOT_USER / MINIO_ROOT_PASSWORD 주입
    ports:
      - "9000:9000"   # S3 API
      - "9001:9001"   # 웹 콘솔
    volumes:
      - minio-data:/data
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 5s
      retries: 10

  # 2-1) MinIO 버킷 생성 + 버저닝 ON. 한 번 실행되고 종료(one-shot)된다.
  createbuckets:
    image: minio/mc
    env_file:
      - docker-compose.env
    depends_on:
      minio:
        condition: service_healthy
    entrypoint: >
      /bin/sh -c "
      mc alias set local http://minio:9000 $$MINIO_ROOT_USER $$MINIO_ROOT_PASSWORD &&
      mc mb --ignore-existing local/datasets local/models local/mlflow &&
      mc version enable local/datasets &&
      mc version enable local/models
      "
    restart: "no"

  # 3) MLflow 추적 서버 + 모델 레지스트리. backend=postgres(mlflow DB), artifact=MinIO. UI: http://localhost:5000
  mlflow:
    image: ghcr.io/mlflow/mlflow:latest
    command: >
      bash -c "pip install --quiet psycopg2-binary boto3 &&
               mlflow server --host 0.0.0.0 --port 5000
               --backend-store-uri postgresql://$$POSTGRES_USER:$$POSTGRES_PASSWORD@postgres:5432/mlflow
               --artifacts-destination s3://mlflow"
    env_file:
      - docker-compose.env   # MLFLOW_S3_ENDPOINT_URL / AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY 주입
    ports:
      - "5000:5000"
    depends_on:
      postgres:
        condition: service_healthy
      minio:
        condition: service_healthy

  # 4) Prefect 서버 + 대시보드(UI). backend=postgres(prefect DB). 브라우저: http://localhost:4200
  prefect_server:
    image: prefecthq/prefect:3-latest
    command: prefect server start --host 0.0.0.0
    env_file:
      - docker-compose.env   # PREFECT_SERVER_DATABASE_CONNECTION_URL 주입
    ports:
      - "4200:4200"
    depends_on:
      postgres:
        condition: service_healthy

  # 5) 워커: 실제로 잡을 실행. 동시 실행 수를 여기서 제한.
  #    (A) 중앙 실행: user는 잡 제출만, 이 워커가 대신 실행 → client computer 엔 자격증명 불필요.
  #        그래서 워커에도 자격증명을 주입하되, 컨테이너라 엔드포인트는 서비스명(minio/postgres)을 쓴다.
  prefect_worker:
    image: prefecthq/prefect:3-latest
    env_file:
      - docker-compose.env          # 자격증명: MINIO_ACCESS_KEY/SECRET, AWS_*, POSTGRES_*
    environment:
      PREFECT_API_URL: http://prefect_server:4200/api
      MINIO_ENDPOINT: http://minio:9000    # env_file 의 localhost 를 컨테이너 주소로 덮어씀
    # POSTGRESQL_CATALOG_DSN 은 비밀번호가 들어가므로 env_file 계정으로 컨테이너 주소 DSN 을 만들어 export.
    command: >
      bash -c "export POSTGRESQL_CATALOG_DSN=postgresql://$$POSTGRES_USER:$$POSTGRES_PASSWORD@postgres:5432/catalog &&
               prefect work-pool create default --type process --overwrite &&
               prefect worker start --pool default --limit 8"
    volumes:
      - ./:/app                     # flow 코드(catalog.py, example/ 등)가 있는 폴더를 /app 으로 마운트 (./ 는 compose 폴더 — 코드가 다른 폴더면 그 경로로)
    working_dir: /app
    depends_on:
      - prefect_server
    # prefect_server 가 늦게 떠 prefect_worker 가 API(:4200) 연결에 실패해 종료돼도 자동 재시작해 다시 붙는다.
    restart: unless-stopped

configs:
  init_sql:
    content: |
      CREATE DATABASE prefect;
      CREATE DATABASE mlflow;
      CREATE DATABASE optuna;
      CREATE DATABASE catalog;

volumes:
  pg-data:
  minio-data:
```

서비스 설명:

- **`postgres`** — 메타데이터 DB. 한 인스턴스에 `prefect`/`mlflow`/`optuna`/`catalog` 4개 논리 DB. `5432`를 호스트로 노출(호스트의 `catalog.py`/`data_uploader.ps1`이 접속). init SQL은 아래 `configs`로 인라인.
- **`minio`** — 오브젝트 스토리지(S3 호환). API `9000`, 콘솔 `9001`. 데이터는 `minio-data` 볼륨에 영속 저장.
- **`createbuckets`** — `minio/mc`로 `datasets`/`models`/`mlflow` 버킷 생성 + `datasets`/`models` 버저닝 ON. 1회 실행 후 종료.
- **`mlflow`** — 추적 서버 + 모델 레지스트리. backend=`postgres`(mlflow DB), artifact=`minio`(`s3://mlflow`).
- **`prefect_server`** — Prefect 서버 + 대시보드(UI). backend=`postgres`(prefect DB). `4200`.
- **`prefect_worker`** — 실제 잡 실행. `default` work pool, `--limit 8`. `restart: unless-stopped`로 `prefect_server`가 준비될 때까지 자동 재시도. **자격증명을 `env_file`로 주입**하고(컨테이너 주소로 접속), user 코드를 `./:/app`로 마운트 — user가 잡만 제출하면 이 워커가 대신 실행하는 **중앙 실행 모델**용([§4](#4-workflow-execution) 참고).

**4개 논리 DB 생성 (init SQL 인라인)**: 별도 `init-db.sql` 파일 없이 init SQL을 `docker-compose.yml` 안에 인라인(`configs.init_sql.content`)합니다. 이 config가 postgres의 `/docker-entrypoint-initdb.d/`에 마운트되어 컨테이너 **최초 기동 시 한 번** 실행되며 4개 DB를 만듭니다.

> 데이터 카탈로그 **테이블(`datasets`)** 은 여기(인프라)서 만들지 않고, **코드에서 자동으로 만듭니다(이미 있으면 그대로 두고, 없을 때만 생성).**

> ⚠️ **주의**: `docker-compose.env` 에는 비밀번호·키가 담기므로, **`.gitignore` 에 등록하여 `docker-compose.env` 를 git 추적에서 제외**시켜야 합니다. 커밋·공유는 비밀값을 비운 `docker-compose.env_example` 로만 합니다([Appendix C](#appendix-c-docker-composeenv-example) 참고).

### Work Pool Mode — Python Version & Dependencies

기본 `prefect_worker`(위 yml)에는 **python + prefect만** 들어있어, work pool mode로 user 코드를 실행하면 `import torch` 같은 **모듈이 없어 실패**합니다([§3](#3-execution-architecture) 참고). work pool mode를 쓰려면 워커에 **python 버전을 고정**하고 **`requirements.txt`를 설치**해야 합니다. (serve mode만 쓰면 내 컴퓨터 python이 이미 라이브러리를 갖고 있으므로 불필요합니다.)

**1) `requirements.txt`** (프로젝트 루트에 두고, 코드가 import 하는 라이브러리를 적음):

```text
prefect>=3
boto3
psycopg2-binary
mlflow
optuna
pandas
# numpy, torch, scikit-learn ... 실제로 import 하는 라이브러리를 모두 추가
```

**2) `prefect_worker`** (python 버전 고정 + 기동 시 설치):

```yaml
  prefect_worker:
    image: prefecthq/prefect:3-python3.11    # ← python 버전 고정 (코드와 동일 버전으로)
    env_file:
      - docker-compose.env
    environment:
      PREFECT_API_URL: http://prefect_server:4200/api
      MINIO_ENDPOINT: http://minio:9000
    command: >
      bash -c "pip install -r /app/requirements.txt &&
               export POSTGRESQL_CATALOG_DSN=postgresql://$$POSTGRES_USER:$$POSTGRES_PASSWORD@postgres:5432/catalog &&
               prefect work-pool create default --type process --overwrite &&
               prefect worker start --pool default --limit 8"
    volumes:
      - ./:/app                  # flow 코드 + requirements.txt 가 있는 폴더를 /app 으로 마운트 (./ 는 compose 폴더 — 코드가 다른 폴더면 그 경로로 바꿀 것)
    working_dir: /app
    depends_on:
      - prefect_server
    restart: unless-stopped
```

- `image: prefecthq/prefect:3-python3.11` — 워커 python을 3.11로 고정(코드가 3.12면 `3-python3.12`). 확인: `docker compose run --rm prefect_worker python --version`.
- `pip install -r /app/requirements.txt` — 컨테이너가 뜰 때마다 user 라이브러리를 설치(`./:/app` 마운트로 파일 접근).
- 매번 설치가 느리면 `Dockerfile`(`FROM prefecthq/prefect:3-python3.11` + `RUN pip install -r requirements.txt`)로 한 번 빌드해 `build:` 로 쓰면 더 빠릅니다.

### Worker Setup

Prefect는 **"서버(=잡 대기열) 1개 + 워커 N개"** 구조라 운영 모델을 선택할 수 있습니다.

> **워커 1개가 동시에 돌리는 job 수 = `--limit` 값(현재 8).** 워커는 work pool 에서 잡을 가져와 실행하는데, `prefect worker start --pool default --limit 8` 의 `--limit` 이 그 워커의 **동시 실행 상한**입니다. 9번째 잡은 앞 잡 하나가 끝나 슬롯이 빌 때까지 대기열에서 기다립니다. 처리량을 늘리는 방법은 두 가지입니다 — ① `--limit` 을 키우거나(`--limit N`), ② 워커 수를 늘립니다(`docker compose up -d --scale worker=3`). 이때 **전체 동시 실행 수 ≈ 워커 수 × `--limit`** 입니다. 단, 무작정 키우지 말고 서버의 **CPU/GPU/메모리 한도** 안에서 정하세요(자원 경합 시 오히려 느려짐). GPU 학습처럼 1잡이 자원을 많이 쓰면 `--limit` 을 1~2로 낮추는 게 안전합니다.

- **현재 compose 기본값**: 워커 1개, `--limit 8`(동시 8개 job 까지 실행). user들은 보통 **잡(run)만 중앙 서버에 제출**하고, 이 공용 워커가 대신 실행하므로 user가 각자 워커를 띄울 필요가 없습니다.
- **워커를 늘리고 싶을 때(처리량을 높이려면)**: `docker compose up -d --scale worker=3` 처럼 워커를 여러 개로 확장합니다.
- **컴퓨터를 추가해서 worker를 늘리는 경우**는 [Appendix D](#appendix-d-worker-attachment-to-a-work-pool-from-a-user-computer)를 참고합니다.

## 3. Execution Architecture

Prefect 실행은 **두 가지 모드**뿐이고, 차이는 **"누가(어떤 python이) 코드를 실행하느냐"** 입니다. 두 모드는 아키텍처가 다릅니다.

### 1) Push-Based / Static Architecture (Serve Mode)

- **구조적 특징**: 개발자가 코드가 실행될 인프라(호스트 서버)를 미리 준비하고 프로세스를 직접 구동해 놓는 구조입니다.
- **동작**: `flow.serve()` 가 든 python 스크립트를 실행하면, 그 python 프로세스가 ① 서버에 deployment를 등록하고 ② 상시 떠서 Prefect 서버의 신호를 수신(Listening)하다가 ③ 트리거되면 **자기 자신이** 코드를 즉시 실행합니다(실행하는 python = 스크립트를 띄운 그 python).
- **장점**: 아키텍처가 단순하여 별도의 인프라 관리용 에이전트(Worker)를 띄울 필요가 없습니다.

### 2) Pull-Based / Dynamic Architecture (Work Pool Mode)

- **구조적 특징**: Prefect 서버와 실제 인프라 사이에 중간 매개체인 Work Pool(큐)과 Worker(에이전트)를 두는 분산 구조입니다.
- **동작**: `flow.deploy()`(또는 `prefect deploy`)로 **등록만 하고 python은 종료**됩니다. Worker가 주기적으로 Work Pool에서 작업 요청을 가로채온(Pull) 뒤, Docker 컨테이너나 Kubernetes Pod 같은 격리 환경을 동적으로 생성(Spawn)해 **Worker의 python**으로 작업을 실행하고, 끝나면 인프라를 파괴합니다(실행하는 python = Worker의 python → 그래서 Worker 환경에 라이브러리 설치 필요).
- **장점**: 확장성(Scalability)이 뛰어나며, 다양한 이기종 인프라(AWS, GCP, Docker 등)를 중앙에서 유연하게 제어할 수 있습니다.

### Comparison

| Aspect | Serve Mode (`flow.serve()`) | Work Pool Mode (`flow.deploy()`) |
|--------|------------------------------|-----------------------------------|
| Architecture | Push-based / static | Pull-based / dynamic |
| Register | `flow.serve()` | `flow.deploy()` / `prefect deploy` |
| Code executor | the python process running `flow.serve()` | a Worker (separate agent) |
| Python that runs code | the python where the script was launched | the Worker's python (its runtime/image) |
| Separate worker needed | No | Yes (`prefect worker start`) |
| Dependencies (e.g. numpy, torch) | already in that python environment | must be installed in the Worker runtime |
| Best for | single machine, simple | scalability, heterogeneous infra |

두 모드 모두 **등록**(deployment 정의를 Prefect 서버에 올림)은 공통이고, **Prefect 서버는 코드를 실행하지 않습니다**(이름표만 보관). 위 표의 핵심 차이는 **"코드를 실제로 실행하는 python이 누구냐"** — Serve mode는 스크립트를 띄운 python이, Work pool mode는 Worker의 python이 실행합니다. 나머지 행(등록 방법·워커 필요 여부·라이브러리 설치 위치)은 모두 이 차이에서 따라옵니다.

## 4. Workflow Execution

### Server Connection

Prefect 클라이언트가 **어느 Prefect 서버에 연결할지** 지정합니다. **최초 1회** 설정하면 이후 모든 client 명령이 이 서버를 향합니다.

```powershell
prefect config set PREFECT_API_URL="http://<서버>:4200/api"
# 같은 컴퓨터면 <서버>=localhost, 다른 컴퓨터의 서버면 그 IP/호스트명
```

**언제 필요한가**
- 잡을 **트리거**할 때 (`prefect deployment run ...`)
- **Prefect Secret 블록을 등록/조회**할 때
- 그 외 Prefect 서버와 통신하는 client 작업 전반

> 이는 MinIO/PostgreSQL **자격증명이 아니라 Prefect 서버 주소** 설정입니다.

### Code Execution Methods

| Case | Trigger | Trigger Loc | Execution Mode | Execution Loc | Credentials |
|------|------|------|------|------|------|
| **A** | admin | server host | serve | server host | 불필요 |
| **B** | user | client computer | work pool | server host | 불필요 |
| **C** | user | server host | serve | server host | 필요 |
| **D** | user | client computer | serve | client computer | 필요 |
| **E** | user | client computer | work pool | client computer | 필요 |

**Credentials** — 코드를 실행하는 주체(serve mode면 그 python 프로세스, work pool mode면 `prefect_worker`)가 MinIO·PostgreSQL 에 접속할 **자격증명(키·비밀번호)** 을 **user가 직접 공급해야 하는지**를 나타냅니다.
- **필요**: 코드가 실행되는 그 컴퓨터(예: user의 로컬 머신)에서 자격증명을 쓸 수 있게 해줘야 함 — ① 그 컴퓨터에 **환경변수**로 등록하거나 ② **Prefect Secret**(Prefect 서버에 저장해 두고 코드가 이름으로 불러옴). 셋업 방법은 아래 [Credentials](#credentials) 참고.
- **불필요**: **user별 별도 자격증명이 필요 없음** — 잡을 서버/워커가 대신 실행하므로, user는 [Server Connection](#server-connection)만 하면 됨.

### Trigger

- **serve mode**: `flow.serve(name="...")`
- **work pool mode**: `flow.deploy(name="...")` 또는 `prefect deployment run "<flow-name>/<deployment-name>"`

`"<flow-name>/<deployment-name>"` 에서:
- `<flow-name>` = 코드의 `@flow(name="...")` 에 준 flow 이름.
- `<deployment-name>` = `.serve(name="...")` / `.deploy(name="...")` 에 준 deployment 이름.

### Credentials

credentials는 **`MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` / `MINIO_ENDPOINT` / `POSTGRESQL_CATALOG_DSN`** 등으로 구성됩니다. 코드가 **MinIO**(데이터·모델 저장소)와 **PostgreSQL**(카탈로그 DB)에 접속해 **데이터를 읽고/쓰기 위해** 필요합니다. 아래 둘 중 하나로 셋업합니다.

**방법 1 — 환경변수**
실행하는 컴퓨터에 자격증명을 환경변수(`MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` / `MINIO_ENDPOINT` / `POSTGRESQL_CATALOG_DSN`)로 설정해 두면 코드가 `os.environ` 에서 읽습니다.

**방법 2 — Prefect Secret**
자격증명을 Prefect 서버에 Secret 으로 저장해 두고 코드가 이름으로 불러옵니다.

**저장** (admin, 1회):

```python
from prefect.blocks.system import Secret

Secret(value="<MINIO_ACCESS_KEY>").save("minio-access-key", overwrite=True)
# minio-secret-key / catalog-dsn 등도 동일하게 저장
```

**사용** — flow 안에서 이름으로 로드:

```python
from prefect import flow, task
from prefect.blocks.system import Secret

@flow
def my_pipeline():
    ak = Secret.load("minio-access-key").get()   # 서버에서 로드 → 실제 값
    ...
```

## Appendix A. Terminology

- **`prefect_server`** — Prefect 서버 서비스(docker container process). API·UI·스케줄러·work pool 대기열을 제공하는 중앙 진입점이며, 메타데이터(`prefect` DB)만 관리하고 코드는 실행하지 않습니다.
- **`prefect_worker`** — work pool 에서 잡을 가져와 실제 코드를 실행하는 워커 서비스(docker container process).
- **server host** — 위 컨테이너들이 떠 있는 **컴퓨터**(도커 호스트). `prefect_server`(서비스)와 구분되는 물리적 실행 위치입니다.

**약자(Abbreviations)**

- **AWS** = Amazon Web Services (아마존 클라우드)
- **GCP** = Google Cloud Platform (구글 클라우드)
- **S3** = (Amazon) Simple Storage Service — MinIO가 호환하는 오브젝트 스토리지 API
- **API** = Application Programming Interface
- **UI** = User Interface
- **DB** = Database
- **DSN** = Data Source Name (DB 접속 문자열)
- **CPU / GPU** = Central / Graphics Processing Unit

## Appendix B. Docker Handy Command

```powershell
docker compose up -d            # 백그라운드 실행 (창 닫아도 유지)
docker compose up -d --build    # 이미지를 새로 빌드하면서 실행

docker compose ps               # 컨테이너 상태 확인
docker compose logs -f server   # Prefect server 로그 실시간 보기
docker compose logs -f worker   # worker가 신호를 잘 받는지 확인
docker compose logs -f mlflow   # MLflow 로그
docker compose logs -f minio    # MinIO 로그

docker compose stop             # 컨테이너 정지 (제거하지 않음)
docker compose start            # 정지된 컨테이너 다시 시작
docker compose restart worker   # 특정 서비스만 재시작

docker compose down             # 정지 + 컨테이너/네트워크 제거 (볼륨은 유지)
docker compose down -v          # 볼륨까지 삭제 (DB/MinIO 데이터 초기화)
```

## Appendix C. docker-compose.env example

`docker-compose.env`는 **서버 admin 전용**입니다. 자격증명·엔드포인트는 yml 에 평문으로 두지 않고 **`docker-compose.env` 한 파일에 모읍니다.** 컨테이너는 각 서비스가 `env_file`로 읽고, **호스트 파이썬(`catalog.py` 등)은 이 값들을 환경변수로 올린 뒤 `os.environ`에서 읽습니다.** 실제 값이 담긴 `docker-compose.env`는 **`.gitignore`로 제외**하고, 비밀값을 비운 아래 **`docker-compose.env_example`만 커밋**합니다. 새 환경에서는 이 예시를 복사해 모든 `CHANGE_ME`를 채우면 됩니다.

```powershell
# 복사 후 모든 CHANGE_ME 를 실제 사용자명/비밀번호/키로 채운다
Copy-Item docker-compose.env_example docker-compose.env
```

```dotenv
# docker-compose.env_example  (모든 자격증명은 CHANGE_ME placeholder — 실제 값 노출 금지)

# ── PostgreSQL (메타데이터 DB) ──
POSTGRES_USER=CHANGE_ME
POSTGRES_PASSWORD=CHANGE_ME

# ── MinIO 루트 계정 (minio 서버가 기대하는 변수명) ──
MINIO_ROOT_USER=CHANGE_ME
MINIO_ROOT_PASSWORD=CHANGE_ME

# ── MinIO 클라이언트 자격증명 (값은 위 루트 계정과 동일하게 맞춘다) ──
MINIO_ACCESS_KEY=CHANGE_ME
MINIO_SECRET_KEY=CHANGE_ME
AWS_ACCESS_KEY_ID=CHANGE_ME
AWS_SECRET_ACCESS_KEY=CHANGE_ME

# ── 컨테이너 내부 엔드포인트 (docker 네트워크의 서비스명으로 접속) ──
MLFLOW_S3_ENDPOINT_URL=http://minio:9000
PREFECT_SERVER_DATABASE_CONNECTION_URL=postgresql+asyncpg://CHANGE_ME:CHANGE_ME@postgres:5432/prefect

# ── 호스트(로컬 컴퓨터)용 엔드포인트 (catalog.py 가 localhost 로 접속) ──
MINIO_ENDPOINT=http://localhost:9000
POSTGRESQL_CATALOG_DSN=postgresql://CHANGE_ME:CHANGE_ME@localhost:5432/catalog
```

- **변수명이 용도별로 나뉜 이유**: 컨테이너는 서비스명(`minio:9000`, `postgres:5432`)으로, 호스트 파이썬은 노출 포트(`localhost:...`)로 접속합니다. 그래서 컨테이너용(`MLFLOW_S3_ENDPOINT_URL`, `PREFECT_SERVER_DATABASE_CONNECTION_URL`)과 호스트용(`MINIO_ENDPOINT`, `POSTGRESQL_CATALOG_DSN`)을 **서로 다른 변수명**으로 한 파일에 함께 둡니다.
- **명령어 안 자격증명은 `$$VAR`**(예: `$$MINIO_ROOT_USER`)로 적습니다 — `$$`는 compose가 `$`로 바꿔 **컨테이너 셸**이 env_file 값으로 확장합니다(`$` 단독은 compose가 먼저 가로채므로 안 됨).
- 모든 `CHANGE_ME`를 **강한 사용자명/비밀번호/키로 교체**하고, 실제 `docker-compose.env`는 git이 아니라 안전한 채널로 공유하세요.

## Appendix D. Worker Attachment to a Work Pool from a User Computer

> **선택 사항입니다.** 중앙 공용 워커(compose의 `prefect_worker` 서비스) 하나로 충분하면 이 절은 건너뛰어도 됩니다. **user가 자기 컴퓨터의 로컬 자원(특히 GPU)에서 학습을 돌려야 하거나, 처리량을 분산하고 싶을 때만** 필요합니다.

Prefect의 **서버**(잡 대기열·대시보드)와 **워커**(실제 실행 주체)는 분리되어 있습니다. 따라서 user는 도커 서버를 건드리지 않고, **자기 컴퓨터에서 워커만 띄워 같은 서버의 work pool에 붙일 수 있습니다.** 그러면 그 user에게 배정된 잡은 user의 로컬 자원(GPU 등)에서 실행됩니다.

**전제**: client computer에서 도커 서버(`http://<서버주소>:4200`)에 네트워크로 접근 가능해야 합니다.

```powershell
# 1) 로컬 컴퓨터에 Prefect 설치
pip install prefect

# 2) 서버 주소 설정 — §4 Server Connection 참고 (prefect config set PREFECT_API_URL=...)

# 3) (work pool이 아직 없다면 한 번만) process 타입 풀 생성
#    compose는 'default' 풀을 이미 만들어두므로 보통 생략 가능
prefect work-pool create default --type process

# 4) 같은 'default' 풀에 워커를 붙여 대기 (이 창은 실행 상태로 유지됨)
prefect worker start --pool default
```

이렇게 하면 도커의 공용 워커와 **로컬 워커가 같은 `default` 풀**을 함께 바라보게 되고, 잡이 가용한 워커로 분산 실행됩니다.

> 풀을 user별로 나누고 싶다면(예: user2 잡은 user2 컴퓨터에서만 실행), 별도 풀을 만들고 그 풀로 워커를 띄우면 됩니다.
> ```powershell
> prefect work-pool create member2-pool --type process
> prefect worker start --pool member2-pool
> ```
> 그리고 해당 잡의 deployment를 그 풀로 지정하면, 그 풀에 붙은 워커(=user2 컴퓨터)에서만 실행됩니다.

