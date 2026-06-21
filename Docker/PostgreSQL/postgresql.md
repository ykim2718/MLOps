# PostgreSQL — Backend Metadata Store

PostgreSQL 은 Prefect Automation Workflow stack의 **Backend Metadata Store** 역할을 합니다. 한 인스턴스 안에서 `prefect` · `mlflow` · `optuna` · `catalog` **4개의 논리 DB** 를 함께 운영하며, 각 도구가 자기 DB 에만 접속합니다 — **Prefect** (오케스트레이터) → `prefect`, **MLflow** (실험 추적·모델 레지스트리) → `mlflow`, **Optuna** (하이퍼파라미터 튜닝) → `optuna`, **Python** (데이터 catalog 접근 계층) → `catalog`. 실제 대용량 데이터·모델·아티팩트는 여기 두지 않고 오브젝트 스토리지에 보관하며, PostgreSQL 에는 **메타데이터 (상태·기록·catalog) 만** 저장합니다.

## 1. Role

각 논리 DB 의 용도는 다음과 같습니다.

| Database | Tool | Purpose |
|----------|------|---------|
| `prefect` | Prefect | Prefect server 가 deployment·flow run·work pool 등 오케스트레이션 메타데이터를 저장합니다. |
| `mlflow` | MLflow | MLflow 가 실험·run·파라미터·메트릭·모델 레지스트리 메타데이터를 저장합니다. |
| `optuna` | Optuna | Optuna 가 하이퍼파라미터 탐색의 study·trial 기록을 저장합니다. |
| `catalog` | Python | 데이터 catalog (어떤 데이터셋이 어디에 있는지) 테이블을 저장합니다. |

> 실제 파일 (파케이·모델 바이너리 등) 은 PostgreSQL 이 아니라 오브젝트 스토리지에 들어가고, 여기에는 그 **위치와 메타데이터만** 기록합니다.

## 2. Docker Setup

PostgreSQL 은 도커 컨테이너로 실행됩니다. `docker compose -p <Project Name> up -d` 를 실행하면 도커가 `postgres:16` 이미지를 내려받아 컨테이너로 띄우므로, **PostgreSQL 을 호스트에 따로 설치할 필요가 없습니다.** 컨테이너가 **최초로 기동될 때** 인라인된 init SQL 이 4개 DB 를 자동으로 만듭니다.

이 컨테이너는 같은 호스트의 다른 서비스 (예: 추적 server, 오케스트레이션 server) 가 `postgres` 라는 **서비스명으로 접속**하도록 공유 네트워크 `mlops` 에 붙습니다. 따라서 컨테이너를 띄우기 전에 그 네트워크가 있어야 합니다.

다음은 docker compose 를 위한 yaml과 execution command 입니다.

```yaml
# docker-compose.yml
services:
  postgres:
    image: postgres:16
    env_file:
      - docker-compose.env          # injects POSTGRES_USER / POSTGRES_PASSWORD
    ports:
      - "5432:5432"                 # expose for host python and remote workers to connect
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

```powershell
# create the shared network (ignore the error if it already exists), then start the container in the background.
docker network create mlops
docker compose -p <Project Name> up -d
```

구성 요소의 의미는 다음과 같습니다.

- `image: postgres:16` 은 공식 PostgreSQL 16 이미지를 사용한다는 뜻입니다.
- `env_file` 은 계정·비밀번호를 yml 에 평문으로 두지 않고 `docker-compose.env` 에서 읽어 주입합니다.
- `ports: "5432:5432"` 는 호스트 파이썬 (예: catalog 접속 코드) 과 다른 컴퓨터의 worker 가 접속할 수 있도록 5432 포트를 노출합니다.
- `volumes: pg-data` 는 DB 데이터를 named volume 에 영속 저장하여, 컨테이너를 지워도 데이터가 보존되게 합니다.
- `configs.init_sql` 은 별도 SQL 파일 없이 init SQL 을 yml 안에 인라인한 것이며, 컨테이너 최초 기동 시 `/docker-entrypoint-initdb.d/` 에서 한 번 실행되어 4개 DB 를 만듭니다.
- `healthcheck` 는 `pg_isready` 로 기동 완료를 확인하여, 이 DB 에 의존하는 서비스가 준비 상태를 기다릴 수 있게 합니다.
- `networks: mlops` 는 같은 호스트의 다른 서비스가 `postgres` 서비스명으로 접속하도록 공유 외부 네트워크에 연결합니다.
- `restart: unless-stopped` 는 컨테이너가 비정상 종료되어도 자동으로 다시 띄웁니다 (사용자가 직접 멈춘 경우는 제외합니다).

> ⚠️ init SQL 은 볼륨이 **비어 있는 최초 기동 때만** 실행됩니다. 이미 데이터가 있는 볼륨에서는 다시 실행되지 않으므로, DB 를 새로 만들려면 볼륨을 비우거나 (`docker compose down -v`) 아래 [Appendix B](#appendix-b-manual-database-provisioning) 처럼 수동으로 만듭니다.

실행 명령은 다음과 같습니다.

- `docker network create mlops` — 컨테이너가 붙을 공유 외부 네트워크 `mlops` 를 만듭니다 (이미 있으면 에러는 무시되어 무해합니다).
- `docker compose -p <Project Name> up -d` — `-p` 로 프로젝트명을, `-d` 로 백그라운드 (detached) 실행을 지정합니다.

`docker compose up` 으로 뜬 컨테이너 이름은 `<Project Name>-<Service Name>-<Replica Number>` 형식이며, Replica Number 는 보통 `1` 이지만 `--scale <service>=3` 처럼 늘리면 `-2`·`-3` 이 추가됩니다.

### Credentials

  접속 계정은 `docker-compose.env` 한 곳에 모으고, 컨테이너는 `env_file` 로 읽으며 호스트 파이썬은 같은 값을 환경변수로 올려 `os.environ` 에서 읽습니다. 실제 값이 담긴 `docker-compose.env` 는 `.gitignore` 로 git 추적에서 제외하고, 비밀값을 비운 `docker-compose.env_example` 만 커밋합니다.

  ```dotenv
  # docker-compose.env_example  (all values are CHANGE_ME placeholders — do not expose real values)
  POSTGRES_USER=CHANGE_ME
  POSTGRES_PASSWORD=CHANGE_ME
  ```

  - 컨테이너 셸 명령 안에서 위 값을 참조할 때는 `$$POSTGRES_USER` 처럼 `$$` 로 적습니다. `$$` 는 compose 가 `$` 로 바꿔 컨테이너 셸이 `env_file` 값으로 확장하며, `$` 단독은 compose 가 먼저 가로채므로 쓰지 않습니다.
  - 호스트 파이썬용 접속 문자열 (DSN) 은 `postgresql://<user>:<password>@<host>:5432/<db>` 형식으로 만들어 환경변수 (예: `POSTGRESQL_CATALOG_DSN`) 로 둡니다.
  - 모든 `CHANGE_ME` 는 강한 계정/비밀번호로 교체하고, 실제 `docker-compose.env` 는 git 이 아니라 안전한 채널로 공유합니다.

## 3. Access

컨테이너가 5432 를 노출하므로, 호스트나 다른 컴퓨터에서 표준 PostgreSQL 클라이언트로 접속할 수 있습니다. 접속 정보는 코드에 기록하지 말고 환경변수나 파라미터로 주입합니다 ([§2 의 Credentials](#credentials) 참고).

### Python (`psycopg2` / SQLAlchemy)

  ```python
  import os
  import psycopg2

  # DSN example: postgresql://<user>:<password>@<host>:5432/catalog
  conn = psycopg2.connect(os.environ["POSTGRESQL_CATALOG_DSN"])
  with conn.cursor() as cur:
      cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
      for (name,) in cur.fetchall():
          print(name)
  conn.close()
  ```

  ```python
  # connecting via SQLAlchemy (handy with pandas.read_sql, etc.)
  import os
  from sqlalchemy import create_engine

  engine = create_engine(os.environ["POSTGRESQL_CATALOG_DSN"])
  ```

### CLI (`psql`)

  ```powershell
  # use localhost for the host on the same PC, or the server's IP/hostname on another.
  psql -h <host> -p 5432 -U <user> -d catalog

  # use the container's psql directly (when psql isn't installed on the host)
  docker compose exec postgres psql -U <user> -d catalog -c "\l"   # list the logical DBs
  ```

  > catalog **테이블 (예: `datasets`)** 은 인프라에서 만들지 않고 **코드에서 자동으로 만듭니다** (이미 있으면 그대로 두고, 없을 때만 생성합니다). 인프라는 빈 `catalog` DB 까지만 준비합니다.

## 4. Granular Database Access Control

슈퍼유저 (`POSTGRES_USER`) 는 4개 논리 DB 전부에 전권을 가지므로 **팀원·서비스에게 직접 주지 않습니다.** 대신 PostgreSQL 의 **role** (= 사용자) 을 만들어 **DB 별로 읽기 전용 / 읽기·쓰기** 권한을 좁혀 부여합니다. 권한은 계층적이라 ① DB 접속 (`CONNECT`) → ② 스키마 사용 (`USAGE`) → ③ 테이블 동작 (`SELECT`/`INSERT`/…) 을 함께 줘야 하며, 스키마·테이블 권한은 **대상 DB 에 접속한 상태**에서 실행해야 합니다 (DB 마다 따로).

아래 SQL 은 슈퍼유저로 접속해 실행합니다. `-d` 로 대상 DB 를 지정합니다.

```powershell
# connect to the target DB (e.g. catalog) as the superuser and run a single SQL line.
docker compose exec postgres psql -U <superuser> -d catalog -c "<SQL>"

# for multiple lines, enter the container psql shell (type \q to leave).
docker compose exec -it postgres psql -U <superuser> -d catalog
```

### (1) 접속 사용자 (role) 만들기

  로그인 가능한 사용자를 만듭니다. role 은 인스턴스 전역이라 이 단계는 어느 DB 에 접속해 실행해도 됩니다.

  ```sql
  -- create login-capable users (CREATE USER is an alias for a ROLE with LOGIN)
  CREATE ROLE analyst LOGIN PASSWORD 'CHANGE_ME';
  CREATE ROLE writer  LOGIN PASSWORD 'CHANGE_ME';
  ```

### (2) DB 별 읽기 전용 (read) 권한 부여

  대상 DB (예: `catalog`) 에 **접속한 상태**에서 실행합니다.

  ```sql
  -- while connected with psql -U <superuser> -d catalog:
  GRANT CONNECT ON DATABASE catalog TO analyst;                 -- ① allow connecting to this DB
  GRANT USAGE   ON SCHEMA   public  TO analyst;                 -- ② use the public schema
  GRANT SELECT  ON ALL TABLES IN SCHEMA public TO analyst;      -- ③ read existing tables
  -- also auto-allow reading future tables (otherwise new tables have no permission)
  ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO analyst;
  ```

### (3) DB 별 읽기·쓰기 (read/write) 권한 부여

  대상 DB (예: `mlflow`) 에 **접속한 상태**에서 실행합니다. 쓰기에는 시퀀스 (serial/identity 자동증가 컬럼) 권한도 함께 필요합니다.

  ```sql
  -- while connected with psql -U <superuser> -d mlflow:
  GRANT CONNECT ON DATABASE mlflow TO writer;                                       -- ① connect
  GRANT USAGE, CREATE ON SCHEMA public TO writer;                                   -- ② use the schema + allow creating tables
  GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA public TO writer; -- ③ read/write existing tables
  GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA public TO writer; --   sequences (auto-increment PK)
  -- also auto-apply the same permissions to future tables/sequences
  ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO writer;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO writer;
  ```

  > `ALTER DEFAULT PRIVILEGES` 는 **그 명령을 실행한 role 이 이후 만드는 객체**에만 적용됩니다. 위처럼 슈퍼유저로 실행하면 슈퍼유저가 만든 테이블에 적용되며 (이 스택의 `catalog` 테이블은 코드가 슈퍼유저로 만듭니다), 다른 role 이 만들 객체까지 포함하려면 `FOR ROLE <creator>` 를 붙입니다.

### (4) 회수 · 삭제 · 확인

  ```sql
  -- revoke permissions (e.g. drop write but keep read)
  REVOKE INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM writer;
  REVOKE CONNECT ON DATABASE mlflow FROM analyst;

  -- delete a user — first clean up the permissions and owned objects of that role.
  DROP OWNED BY analyst;     -- remove permissions/owned objects granted to analyst (run in each DB)
  DROP ROLE analyst;         -- drop the role

  -- check (psql meta-commands)
  \du                        -- list roles and their attributes
  \l                         -- list DBs + access privileges
  \dp                        -- table-level privileges in the connected DB
  ```

  > 위 `\` 로 시작하는 것은 SQL 이 아니라 **psql 클라이언트 전용 메타명령**입니다. 컨테이너 psql 셸에 접속한 상태 (`docker compose exec -it postgres psql -U <superuser> -d <db>`) 에서 입력합니다. `\du`·`\l` 는 인스턴스 전역이라 어느 DB 에 접속해 실행해도 되고, `\dp` 는 권한을 보려는 **대상 DB 에 접속한 상태**에서 실행합니다.

  > 기본적으로 모든 DB 는 `PUBLIC` (모든 role) 에 `CONNECT` 가 열려 있습니다. 특정 DB 를 **명시적으로 허가한 role 만** 접속하게 하려면 `REVOKE CONNECT ON DATABASE <db> FROM PUBLIC;` 로 기본 접속을 닫은 뒤 (2)·(3) 의 `GRANT CONNECT` 로 필요한 role 에만 엽니다. (PostgreSQL 15+ 부터 `public` 스키마의 `CREATE` 권한은 기본적으로 `PUBLIC` 에서 회수되어 있습니다.)

## Appendix A. SQL Commands

본문 ([§4](#4-granular-database-access-control) 등) 에서 쓰는 SQL 명령을 정리합니다. 슈퍼유저로 접속해 실행하며, 스키마·테이블 권한은 **대상 DB 에 접속한 상태**에서 실행합니다.

| Category | Command | Description |
|----------|---------|-------------|
| Role | `CREATE ROLE <name> LOGIN PASSWORD '<pwd>';` | 로그인 가능한 사용자 (role) 를 만듭니다. |
| Grant (connect) | `GRANT CONNECT ON DATABASE <db> TO <role>;` | 그 DB 에 접속을 허용합니다. |
| Grant (schema) | `GRANT USAGE, CREATE ON SCHEMA public TO <role>;` | 스키마 사용 (+ `CREATE` 면 테이블 생성) 을 허용합니다. |
| Grant (read) | `GRANT SELECT ON ALL TABLES IN SCHEMA public TO <role>;` | 기존 테이블을 읽게 합니다. |
| Grant (write) | `GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO <role>;` | 기존 테이블을 읽고 쓰게 합니다. |
| Grant (sequence) | `GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO <role>;` | 시퀀스 (자동증가 PK) 를 쓰게 합니다. |
| Default privileges | `ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT <privs> ON TABLES TO <role>;` | 앞으로 생길 테이블에도 같은 권한을 자동 적용합니다. |
| Revoke | `REVOKE <privs> ON <object> FROM <role>;` | 권한을 회수합니다. |
| Drop | `DROP OWNED BY <role>;` · `DROP ROLE <role>;` | role 의 권한·소유 객체를 정리한 뒤 사용자를 삭제합니다. |
| Database | `CREATE DATABASE <db>;` | 논리 DB 를 만듭니다 (init SQL·수동 프로비저닝). |

> `\du` · `\l` · `\dp` 는 SQL 이 아니라 psql 클라이언트 메타명령입니다 ([§4](#4-granular-database-access-control) 참고).

## Appendix B. Manual Database Provisioning

init SQL 은 빈 볼륨의 최초 기동 때만 실행되므로, **이미 운영 중인 인스턴스에 DB 를 추가**하거나 **호스트에 직접 설치한 PostgreSQL 을 쓸 때**는 아래처럼 수동으로 만듭니다.

```powershell
# create the 4 DBs with psql inside the container (harmless — just errors if they already exist).
docker compose exec postgres psql -U <user> -c "CREATE DATABASE prefect;"
docker compose exec postgres psql -U <user> -c "CREATE DATABASE mlflow;"
docker compose exec postgres psql -U <user> -c "CREATE DATABASE optuna;"
docker compose exec postgres psql -U <user> -c "CREATE DATABASE catalog;"

# verify creation
docker compose exec postgres psql -U <user> -c "\l"
```
