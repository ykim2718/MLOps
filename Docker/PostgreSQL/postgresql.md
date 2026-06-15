# PostgreSQL — Metadata Database

PostgreSQL 은 이 스택에서 **메타데이터 데이터베이스**로 쓰입니다. 한 인스턴스 안에서 `prefect` · `mlflow` · `optuna` · `catalog` **4개의 논리 DB** 를 함께 운영하며, 각 도구가 자기 DB 에만 접속합니다. 실제 대용량 데이터·모델·아티팩트는 여기 두지 않고 오브젝트 스토리지에 보관하며, PostgreSQL 에는 **메타데이터(상태·기록·카탈로그)만** 저장합니다.

## 1. Role

각 논리 DB 의 용도는 다음과 같습니다.

| database | 용도 |
|----------|------|
| `prefect` | Prefect 서버가 deployment·flow run·work pool 등 오케스트레이션 메타데이터를 저장합니다. |
| `mlflow` | MLflow 가 실험·run·파라미터·메트릭·모델 레지스트리 메타데이터를 저장합니다. |
| `optuna` | Optuna 가 하이퍼파라미터 탐색의 study·trial 기록을 저장합니다. |
| `catalog` | 데이터 카탈로그(어떤 데이터셋이 어디에 있는지) 테이블을 저장합니다. |

> 실제 파일(파케이·모델 바이너리 등)은 PostgreSQL 이 아니라 오브젝트 스토리지에 들어가고, 여기에는 그 **위치와 메타데이터만** 기록합니다.

## 2. Docker Setup

PostgreSQL 은 도커 컨테이너로 실행됩니다. `docker compose up -d` 를 실행하면 도커가 `postgres:16` 이미지를 내려받아 컨테이너로 띄우므로, **PostgreSQL 을 호스트에 따로 설치할 필요가 없습니다.** 컨테이너가 **최초로 기동될 때** 인라인된 init SQL 이 4개 DB 를 자동으로 만듭니다.

이 컨테이너는 같은 호스트의 다른 서비스(예: 추적 서버, 오케스트레이션 서버)가 `postgres` 라는 **서비스명으로 접속**하도록 공유 네트워크 `mlops` 에 붙습니다. 따라서 컨테이너를 띄우기 전에 그 네트워크가 있어야 하며, 함께 제공되는 `set_docker.ps1` 이 네트워크를 먼저 보장한 뒤 스택을 기동합니다.

```powershell
# (최초 1회) 예시 파일을 복사해 계정/비밀번호를 채운다. docker-compose.env 는 git 에 커밋하지 않는다.
Copy-Item docker-compose.env_example docker-compose.env

# 공유 네트워크를 보장하고 컨테이너를 백그라운드로 띄운다.
.\set_docker.ps1
```

아래가 `docker-compose.yml` 입니다.

```yaml
services:
  postgres:
    image: postgres:16
    env_file:
      - docker-compose.env          # POSTGRES_USER / POSTGRES_PASSWORD 를 주입한다.
    ports:
      - "5432:5432"                 # 호스트 파이썬과 원격 워커가 접속하도록 노출한다.
    volumes:
      - pg-data:/var/lib/postgresql/data
    configs:
      - source: init_sql
        target: /docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER"]
      interval: 5s
      retries: 10
    networks:
      - mlops
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

networks:
  mlops:
    external: true
```

구성 요소의 의미는 다음과 같습니다.

- `image: postgres:16` 은 공식 PostgreSQL 16 이미지를 사용한다는 뜻입니다.
- `env_file` 은 계정·비밀번호를 yml 에 평문으로 두지 않고 `docker-compose.env` 에서 읽어 주입합니다.
- `ports: "5432:5432"` 는 호스트 파이썬(예: 카탈로그 접속 코드)과 다른 컴퓨터의 워커가 접속할 수 있도록 5432 포트를 노출합니다.
- `volumes: pg-data` 는 DB 데이터를 named volume 에 영속 저장하여, 컨테이너를 지워도 데이터가 보존되게 합니다.
- `configs.init_sql` 은 별도 SQL 파일 없이 init SQL 을 yml 안에 인라인한 것이며, 컨테이너 최초 기동 시 `/docker-entrypoint-initdb.d/` 에서 한 번 실행되어 4개 DB 를 만듭니다.
- `healthcheck` 는 `pg_isready` 로 기동 완료를 확인하여, 이 DB 에 의존하는 서비스가 준비 상태를 기다릴 수 있게 합니다.
- `networks: mlops` 는 같은 호스트의 다른 서비스가 `postgres` 서비스명으로 접속하도록 공유 외부 네트워크에 연결합니다.
- `restart: unless-stopped` 는 컨테이너가 비정상 종료되어도 자동으로 다시 띄웁니다(사용자가 직접 멈춘 경우는 제외합니다).

> ⚠️ init SQL 은 볼륨이 **비어 있는 최초 기동 때만** 실행됩니다. 이미 데이터가 있는 볼륨에서는 다시 실행되지 않으므로, DB 를 새로 만들고 싶으면 볼륨을 비우거나(`docker compose down -v`) 아래 [Appendix A](#appendix-a-manual-database-provisioning) 처럼 수동으로 만듭니다.

## 3. Access

컨테이너가 5432 를 노출하므로, 호스트나 다른 컴퓨터에서 표준 PostgreSQL 클라이언트로 접속할 수 있습니다. 접속 정보는 코드에 박지 말고 환경변수나 파라미터로 주입합니다([§4](#4-credentials) 참고).

### Python (`psycopg2` / SQLAlchemy)

```python
import os
import psycopg2

# DSN 예: postgresql://<user>:<password>@<host>:5432/catalog
conn = psycopg2.connect(os.environ["POSTGRESQL_CATALOG_DSN"])
with conn.cursor() as cur:
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    for (name,) in cur.fetchall():
        print(name)
conn.close()
```

```python
# SQLAlchemy 로 접속하는 경우(pandas.read_sql 등과 함께 쓰기 좋습니다)
import os
from sqlalchemy import create_engine

engine = create_engine(os.environ["POSTGRESQL_CATALOG_DSN"])
```

### CLI (`psql`)

```powershell
# 호스트는 같은 PC 면 localhost, 다른 PC 면 서버의 IP/호스트명을 쓴다.
psql -h <host> -p 5432 -U <user> -d catalog

# 컨테이너 안의 psql 을 그대로 쓰는 방법(호스트에 psql 을 설치하지 않은 경우)
docker compose exec postgres psql -U <user> -d catalog -c "\l"   # 논리 DB 목록 확인
```

> 카탈로그 **테이블(예: `datasets`)** 은 인프라에서 만들지 않고 **코드에서 자동으로 만듭니다**(이미 있으면 그대로 두고, 없을 때만 생성합니다). 인프라는 빈 `catalog` DB 까지만 준비합니다.

## 4. Credentials

접속 계정은 `docker-compose.env` 한 곳에 모으고, 컨테이너는 `env_file` 로 읽으며 호스트 파이썬은 같은 값을 환경변수로 올려 `os.environ` 에서 읽습니다. 실제 값이 담긴 `docker-compose.env` 는 `.gitignore` 로 git 추적에서 제외하고, 비밀값을 비운 `docker-compose.env_example` 만 커밋합니다.

```dotenv
# docker-compose.env_example  (모든 값은 CHANGE_ME placeholder — 실제 값 노출 금지)
POSTGRES_USER=CHANGE_ME
POSTGRES_PASSWORD=CHANGE_ME
```

- 컨테이너 셸 명령 안에서 위 값을 참조할 때는 `$$POSTGRES_USER` 처럼 `$$` 로 적습니다. `$$` 는 compose 가 `$` 로 바꿔 컨테이너 셸이 `env_file` 값으로 확장하며, `$` 단독은 compose 가 먼저 가로채므로 쓰지 않습니다.
- 호스트 파이썬용 접속 문자열(DSN)은 `postgresql://<user>:<password>@<host>:5432/<db>` 형식으로 만들어 환경변수(예: `POSTGRESQL_CATALOG_DSN`)로 둡니다.
- 모든 `CHANGE_ME` 는 강한 계정/비밀번호로 교체하고, 실제 `docker-compose.env` 는 git 이 아니라 안전한 채널로 공유합니다.

## Appendix A. Manual Database Provisioning

init SQL 은 빈 볼륨의 최초 기동 때만 실행되므로, **이미 운영 중인 인스턴스에 DB 를 추가**하거나 **호스트에 직접 설치한 PostgreSQL 을 쓸 때**는 아래처럼 수동으로 만듭니다.

```powershell
# 컨테이너 안에서 psql 로 4개 DB 를 만든다(이미 있으면 에러만 나고 무해하다).
docker compose exec postgres psql -U <user> -c "CREATE DATABASE prefect;"
docker compose exec postgres psql -U <user> -c "CREATE DATABASE mlflow;"
docker compose exec postgres psql -U <user> -c "CREATE DATABASE optuna;"
docker compose exec postgres psql -U <user> -c "CREATE DATABASE catalog;"

# 생성 확인
docker compose exec postgres psql -U <user> -c "\l"
```

## Appendix B. Handy Commands

```powershell
docker compose up -d                 # 백그라운드 실행(창을 닫아도 유지)
docker compose ps                    # 컨테이너 상태 확인
docker compose logs -f postgres      # 로그 실시간 보기
docker compose exec postgres psql -U <user> -d <db>   # 컨테이너 안 psql 접속

docker compose stop                  # 컨테이너 정지(제거하지 않음)
docker compose start                 # 정지된 컨테이너 다시 시작

docker compose down                  # 정지 + 컨테이너/네트워크 제거(볼륨은 유지)
docker compose down -v               # 볼륨까지 삭제(DB 데이터 초기화 — 4개 DB 재생성됨)
```
