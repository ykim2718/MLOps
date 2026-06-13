# Prefect

Prefect 스택(서버·워커·메타데이터 DB·오브젝트 스토리지·실험 추적)을 **도커로 실행/구성**하는 방법입니다.

## 1. Configuration

`docker-compose.yml`이 정의하는 서비스 구성입니다.

| service | endpoint | features |
|---------|----------|----------|
| `postgres` | `:5432` | 메타데이터 DB — 4 logical DBs: `prefect`/`mlflow`/`optuna`/`catalog`, init SQL 인라인 |
| `minio` | `:9000` (S3 API) · `:9001` (콘솔) | 오브젝트 스토리지 — 3 buckets: `datasets`/`models`/`mlflow`, `minio-data` 볼륨 |
| `createbuckets` | — | 1회용 — 버킷 생성 + 버저닝 ON(`datasets`/`models`) 후 종료 |
| `mlflow` | `:5000` | 추적 서버 + 모델 레지스트리 — backend=`postgres`, artifact=`minio` |
| `server` | `:4200` | Prefect 서버 + 대시보드(UI) |
| `worker` | — | 잡 실행 — `default` pool, **동시 최대 8개 job**(`--limit 8`), `restart: unless-stopped` |

> `endpoint`이 `—`인 서비스(`worker`·`createbuckets`)는 **외부에서 접속받는 포트가 없습니다.** 서버가 아니라, 자신이 서버 API(`http://server:4200/api`)로 **나가는(outbound) 연결**만 하기 때문입니다.
>
> **worker 1개 = 동시 최대 `--limit`개(현재 8개) job 실행.** 처리량을 늘리려면 `--limit`을 키우거나(`prefect worker start --pool default --limit N`) worker 수를 늘립니다(`docker compose up -d --scale worker=3`).

## 2. Docker Setup

`docker-compose.yml`이 있는 폴더에서 실행합니다.

```powershell
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
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      # POSTGRES_DB 는 지정하지 않는다(기본 DB=postgres). 4개 DB 는 init_sql 이 생성.
    ports:
      # 호스트의 catalog.py / data_uploader.ps1 이 localhost:5432 로 접속할 수 있도록 노출.
      - "5432:5432"
    volumes:
      - pg-data:/var/lib/postgresql/data
    configs:
      # 컨테이너 최초 기동 시 /docker-entrypoint-initdb.d/*.sql 이 자동 실행된다.
      - source: init_sql
        target: /docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      retries: 10

  # 2) 오브젝트 스토리지 — 실제 대용량 데이터/모델/아티팩트 (S3 호환). 콘솔: http://localhost:9001
  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    ports:
      - "9000:9000"   # S3 API
      - "9001:9001"   # 웹 콘솔
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    volumes:
      - minio-data:/data
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 5s
      retries: 10

  # 2-1) MinIO 버킷 생성 + 버저닝 ON. 한 번 실행되고 종료(one-shot)된다.
  createbuckets:
    image: minio/mc
    depends_on:
      minio:
        condition: service_healthy
    entrypoint: >
      /bin/sh -c "
      mc alias set local http://minio:9000 minioadmin minioadmin &&
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
               --backend-store-uri postgresql://postgres:postgres@postgres:5432/mlflow
               --artifacts-destination s3://mlflow"
    ports:
      - "5000:5000"
    environment:
      MLFLOW_S3_ENDPOINT_URL: http://minio:9000
      AWS_ACCESS_KEY_ID: minioadmin
      AWS_SECRET_ACCESS_KEY: minioadmin
    depends_on:
      postgres:
        condition: service_healthy
      minio:
        condition: service_healthy

  # 4) Prefect 서버 + 대시보드(UI). backend=postgres(prefect DB). 브라우저: http://localhost:4200
  server:
    image: prefecthq/prefect:3-latest
    command: prefect server start --host 0.0.0.0
    ports:
      - "4200:4200"
    environment:
      PREFECT_SERVER_DATABASE_CONNECTION_URL: postgresql+asyncpg://postgres:postgres@postgres:5432/prefect
    depends_on:
      postgres:
        condition: service_healthy

  # 5) 워커: 실제로 잡을 실행. 동시 실행 수를 여기서 제한.
  worker:
    image: prefecthq/prefect:3-latest
    command: >
      bash -c "prefect work-pool create default --type process --overwrite &&
               prefect worker start --pool default --limit 8"
    environment:
      PREFECT_API_URL: http://server:4200/api
    depends_on:
      - server
    # server 가 늦게 떠 worker 가 API(:4200) 연결에 실패해 종료돼도 자동 재시작해 다시 붙는다.
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
- **`server`** — Prefect 서버 + 대시보드(UI). backend=`postgres`(prefect DB). `4200`.
- **`worker`** — 실제 잡 실행. `default` work pool, `--limit 8`. `restart: unless-stopped`로 server가 준비될 때까지 자동 재시도.

**4개 논리 DB 생성 (init SQL 인라인)**: 별도 `init-db.sql` 파일 없이 init SQL을 `docker-compose.yml` 안에 인라인(`configs.init_sql.content`)합니다. 이 config가 postgres의 `/docker-entrypoint-initdb.d/`에 마운트되어 컨테이너 **최초 기동 시 한 번** 실행되며 4개 DB를 만듭니다.

> 데이터 카탈로그 **테이블(`datasets`)** 은 여기(인프라)서 만들지 않고, **코드에서 자동으로 만듭니다(이미 있으면 그대로 두고, 없을 때만 생성).**

## 3. Operating Models (Worker Setup)

Prefect는 **"서버(=잡 대기열) 1개 + 워커 N개"** 구조라 운영 모델을 선택할 수 있습니다.

- **현재 compose 기본값**: 워커 1개, `--limit 8`(동시 8개 job 까지 실행). 팀원들은 보통 **잡(run)만 중앙 서버에 제출**하고, 이 공용 워커가 대신 실행하므로 팀원이 각자 워커를 띄울 필요가 없습니다.
- **워커를 늘리고 싶을 때(처리량을 높이려면)**: `docker compose up -d --scale worker=3` 처럼 워커를 여러 개로 확장합니다.
- **팀원이 각자 실행해야 하는 경우**: 각 팀원의 **로컬 GPU/자원**에서 학습을 돌려야 한다면, 팀원이 자기 PC에서 같은 work pool(`default`)에 워커를 붙이면 됩니다. (붙이는 방법은 아래 [Appendix B](#appendix-b-attaching-a-worker-to-a-work-pool-from-a-local-pc) 참고)

## Appendix A. Handy Commands

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

## Appendix B. Attaching a Worker to a Work Pool from a Local PC

> **선택 사항입니다.** 중앙 공용 워커(compose의 `worker` 서비스) 하나로 충분하면 이 절은 건너뛰어도 됩니다. **팀원이 자기 PC의 로컬 자원(특히 GPU)에서 학습을 돌려야 하거나, 처리량을 분산하고 싶을 때만** 필요합니다.

Prefect의 **서버**(잡 대기열·대시보드)와 **워커**(실제 실행 주체)는 분리되어 있습니다. 따라서 팀원은 도커 서버를 건드리지 않고, **자기 PC에서 워커만 띄워 같은 서버의 work pool에 붙일 수 있습니다.** 그러면 그 팀원에게 배정된 잡은 팀원의 로컬 자원(GPU 등)에서 실행됩니다.

**전제**: 팀원 PC에서 도커 서버(`http://<서버주소>:4200`)에 네트워크로 접근 가능해야 합니다.

```powershell
# 1) 로컬 PC에 Prefect 설치
pip install prefect

# 2) 어느 서버에 붙을지 지정 (도커로 띄운 서버 주소)
#    같은 PC면 localhost, 다른 PC의 서버면 그 PC의 IP/호스트명 사용
prefect config set PREFECT_API_URL="http://<서버주소>:4200/api"

# 3) (work pool이 아직 없다면 한 번만) process 타입 풀 생성
#    compose는 'default' 풀을 이미 만들어두므로 보통 생략 가능
prefect work-pool create default --type process

# 4) 같은 'default' 풀에 워커를 붙여 대기 (이 창은 실행 상태로 유지됨)
prefect worker start --pool default
```

이렇게 하면 도커의 공용 워커와 **로컬 워커가 같은 `default` 풀**을 함께 바라보게 되고, 잡이 가용한 워커로 분산 실행됩니다.

> 풀을 팀원별로 나누고 싶다면(예: 팀원2 잡은 팀원2 PC에서만 실행), 별도 풀을 만들고 그 풀로 워커를 띄우면 됩니다.
> ```powershell
> prefect work-pool create member2-pool --type process
> prefect worker start --pool member2-pool
> ```
> 그리고 해당 잡의 deployment를 그 풀로 지정하면, 그 풀에 붙은 워커(=팀원2 PC)에서만 실행됩니다.
