# MongoDB — Document Database

MongoDB 는 이 스택에서 **도큐먼트 데이터베이스**로 쓰입니다. [DB-Engines 랭킹](https://db-engines.com/en/ranking) 기준 **2026년 현재 관계형 (relational) DB 를 제외하면 가장 인기 있는 DB 엔진** 으로, 비관계형 (NoSQL) 계열에서 1위입니다. 데이터를 행·열의 테이블이 아니라 **도큐먼트 (JSON 형태의 BSON)** 로 저장하며, 한 인스턴스 안에서 `yControl` · `yImprove` 같은 여러 **논리 DB** 를 함께 운영합니다. 각 DB 는 **collection** (관계형 DB 의 테이블에 해당) 을 담고, collection 은 도큐먼트를 담습니다. PostgreSQL 과 달리 빈 DB·collection 을 미리 만들지 않고, **첫 쓰기 (insert) 시점에 자동 생성** 됩니다.

## 1. Role

MongoDB 는 스키마가 고정되지 않은 애플리케이션 도큐먼트를 저장하는 데 쓰입니다. 이 스택이 쓰는 논리 DB 와 collection 예시는 다음과 같습니다 (collection 은 코드가 처음 쓸 때 생깁니다).

| Database | Collections |
|----------|-------------|
| `yControl` | `heatbeat` · `schedule_board` · `schedule_log` · `project_log` · `watching_usa` |
| `yImprove` | `heatbeat` · `macro_trend` · `micro_trend` · `real_time_news__ebest` |

> PostgreSQL 의 init SQL 처럼 DB 를 미리 만드는 단계가 **없습니다** — MongoDB 는 도큐먼트를 처음 insert 하는 순간 그 DB 와 collection 을 자동으로 만듭니다. 인프라는 인증이 켜진 빈 인스턴스까지만 준비합니다.

## 2. Docker Setup

MongoDB 는 도커 컨테이너로 실행됩니다. `docker compose up -d` 를 실행하면 도커가 `mongo:7` 이미지를 내려받아 컨테이너로 띄우므로, **MongoDB 를 호스트에 따로 설치할 필요가 없습니다.** 컨테이너가 **데이터 볼륨이 빈 최초 기동** 일 때 `MONGO_INITDB_ROOT_USERNAME` / `MONGO_INITDB_ROOT_PASSWORD` 로 `admin` DB 에 루트 계정을 만들고 인증을 켭니다.

이 컨테이너는 같은 호스트의 다른 서비스 (예: REST API) 가 `mongo` 라는 **서비스명으로 접속** 하도록 공유 네트워크 `mlops` 에 붙습니다. 따라서 컨테이너를 띄우기 전에 그 네트워크가 있어야 합니다.

```powershell
# (최초 1회) 예시 파일을 복사해 루트 계정을 채운다. docker-compose.env 는 git 에 커밋하지 않는다.
Copy-Item docker-compose.env_example docker-compose.env

# 공유 네트워크 mlops 를 만들고(이미 있으면 에러는 무시) 컨테이너를 백그라운드로 띄운다.
docker network create mlops
docker compose up -d
```

아래가 `docker-compose.yml` 입니다.

```yaml
services:
  mongo:
    image: mongo:7
    env_file:
      - docker-compose.env          # MONGO_INITDB_ROOT_USERNAME / MONGO_INITDB_ROOT_PASSWORD 를 주입한다.
    ports:
      - "27017:27017"               # 호스트 파이썬·도구와 다른 컴퓨터가 접속하도록 노출한다.
    volumes:
      - mongo-data:/data/db
    healthcheck:
      test: ["CMD-SHELL", "mongosh -u $$MONGO_INITDB_ROOT_USERNAME -p $$MONGO_INITDB_ROOT_PASSWORD --quiet --eval 'db.adminCommand({ ping: 1 })'"]
      interval: 5s
      retries: 10
    networks:
      - mlops
    restart: unless-stopped

volumes:
  mongo-data:

networks:
  mlops:
    external: true
```

구성 요소의 의미는 다음과 같습니다.

- `image: mongo:7` 은 공식 MongoDB 7 이미지를 사용한다는 뜻입니다.
- `env_file` 은 루트 계정 (`MONGO_INITDB_ROOT_USERNAME` / `MONGO_INITDB_ROOT_PASSWORD`) 을 yml 에 평문으로 두지 않고 `docker-compose.env` 에서 읽어 주입합니다.
- `ports: "27017:27017"` 는 호스트 파이썬·도구와 다른 컴퓨터가 접속할 수 있도록 27017 포트를 노출합니다.
- `volumes: mongo-data:/data/db` 는 DB 데이터를 named volume 에 영속 저장하여, 컨테이너를 지워도 데이터가 보존되게 합니다.
- `healthcheck` 는 `mongosh` 로 `db.adminCommand({ ping: 1 })` 을 보내 기동 완료를 확인합니다. 명령 안의 `$$MONGO_INITDB_ROOT_USERNAME` 처럼 `$$` 는 compose 가 `$` 로 바꿔 컨테이너 셸이 `env_file` 값으로 확장합니다.
- `networks: mlops` 는 같은 호스트의 다른 서비스가 `mongo` 서비스명으로 접속하도록 공유 외부 네트워크에 연결합니다.
- `restart: unless-stopped` 는 컨테이너가 비정상 종료되어도 자동으로 다시 띄웁니다 (사용자가 직접 멈춘 경우는 제외합니다).
- PostgreSQL 의 init SQL 같은 **DB 생성 단계가 없습니다** — DB·collection 은 첫 insert 때 자동으로 생성됩니다.

> ⚠️ 루트 계정은 볼륨이 **빈 최초 기동 때만** 만들어집니다. 이미 데이터가 있는 볼륨에서는 `MONGO_INITDB_*` 를 바꿔도 반영되지 않으므로, 계정을 다시 잡고 싶으면 볼륨을 비우거나 (`docker compose down -v`) 아래 [§5](#5-granular-database-access-control) 처럼 `mongosh` 로 수동 생성합니다.

## 3. Access

컨테이너가 27017 을 노출하므로, 호스트나 다른 컴퓨터에서 표준 MongoDB 클라이언트로 접속할 수 있습니다. 접속 정보는 코드에 박지 말고 환경변수나 파라미터로 주입합니다 ([§4](#4-credentials) 참고). 루트·일반 사용자는 `admin` DB 에 만들어지므로 연결 문자열에 **`authSource=admin`** 을 붙입니다.

### Python (`pymongo`)

```python
import os
from pymongo import MongoClient

# URI 예: mongodb://<user>:<password>@<host>:27017/?authSource=admin
client = MongoClient(os.environ["MONGODB_URI"])
db = client["yControl"]                                            # DB 선택 (없으면 첫 쓰기 때 생성)
db["schedule_board"].insert_one({"task": "demo", "done": False})  # collection 도 자동 생성
for doc in db["schedule_board"].find({"done": False}):
    print(doc)
```

### CLI (`mongosh`)

```powershell
# 호스트는 같은 PC 면 localhost, 다른 PC 면 server 의 IP/호스트명을 쓴다.
mongosh "mongodb://<user>:<password>@<host>:27017/?authSource=admin"

# 컨테이너 안의 mongosh 를 그대로 쓰는 방법(호스트에 설치하지 않은 경우)
docker compose exec mongo mongosh -u <user> -p <password> --eval "show dbs"
```

> collection 은 인프라에서 만들지 않고 **코드에서 첫 쓰기 때 자동으로 만들어집니다**. 인프라는 인증이 켜진 빈 인스턴스까지만 준비합니다.

## 4. Credentials

접속 계정은 `docker-compose.env` 한 곳에 모으고, 컨테이너는 `env_file` 로 읽으며 호스트 파이썬은 같은 값을 환경변수로 올려 `os.environ` 에서 읽습니다. 실제 값이 담긴 `docker-compose.env` 는 `.gitignore` 로 git 추적에서 제외하고, 비밀값을 비운 `docker-compose.env_example` 만 커밋합니다.

```dotenv
# docker-compose.env_example  (모든 값은 CHANGE_ME placeholder — 실제 값 노출 금지)
MONGO_INITDB_ROOT_USERNAME=CHANGE_ME
MONGO_INITDB_ROOT_PASSWORD=CHANGE_ME
```

- 컨테이너 셸 명령 (예: healthcheck) 안에서 위 값을 참조할 때는 `$$MONGO_INITDB_ROOT_USERNAME` 처럼 `$$` 로 적습니다. `$$` 는 compose 가 `$` 로 바꿔 컨테이너 셸이 `env_file` 값으로 확장하며, `$` 단독은 compose 가 먼저 가로채므로 쓰지 않습니다.
- 호스트 파이썬용 연결 문자열 (URI) 은 `mongodb://<user>:<password>@<host>:27017/?authSource=admin` 형식으로 만들어 환경변수 (예: `MONGODB_URI`) 로 둡니다.
- 루트·일반 사용자는 `admin` DB 에 만들어지므로, 그 계정으로 인증할 때는 `authSource=admin` 이 필요합니다.
- 모든 `CHANGE_ME` 는 강한 계정/비밀번호로 교체하고, 실제 `docker-compose.env` 는 git 이 아니라 안전한 채널로 공유합니다.

## 5. Granular Database Access Control

루트 계정 (`MONGO_INITDB_ROOT_USERNAME`) 은 모든 DB 에 전권을 가지므로 **팀원·서비스에게 직접 주지 않습니다.** 대신 MongoDB 의 **user** 를 만들어 **DB 별로 읽기 전용 / 읽기·쓰기** 권한을 좁혀 부여합니다. MongoDB 는 **role** 로 권한을 제어하며, 내장 role `read` (읽기 전용)·`readWrite` (읽기·쓰기) 를 DB 단위로 지정합니다.

아래는 루트 계정으로 `admin` DB 에 접속해 실행합니다.

```powershell
docker compose exec mongo mongosh -u <root-user> -p <root-password> --authenticationDatabase admin
```

```javascript
// (1) 사용자 생성 — DB 별로 role 을 지정한다. 사용자 정보는 admin DB 에 저장된다.
use admin
db.createUser({
  user: "analyst",
  pwd:  "CHANGE_ME",
  roles: [
    { role: "readWrite", db: "yControl" },   // yControl 은 읽기·쓰기
    { role: "read",      db: "yImprove" }     // yImprove 는 읽기 전용
  ]
})

// (2) 확인 · 변경 · 삭제
db.getUser("analyst")                                                  // 권한 확인
db.grantRolesToUser("analyst", [{ role: "read", db: "yReport" }])      // role 추가
db.revokeRolesFromUser("analyst", [{ role: "read", db: "yImprove" }])  // role 회수
db.dropUser("analyst")                                                 // 사용자 삭제
```

- 이 사용자는 연결 문자열에 `authSource=admin` 을 붙여 인증합니다 (`mongodb://analyst:<pwd>@<host>:27017/yControl?authSource=admin`). 사용자 정보가 `admin` DB 에 있기 때문입니다.
- 내장 role 은 DB 단위입니다 — `read`·`readWrite` 외에 관리용 `dbAdmin`·`dbOwner`, 인스턴스 전역 `readAnyDatabase`·`root` 등이 있습니다. 팀원에게는 보통 필요한 DB 에 `read` / `readWrite` 만 줍니다.

## Appendix A. Terminology

- **mongosh** — MongoDB Shell. MongoDB 에 접속해 명령을 실행하는 공식 CLI 이며, `mongo:7` 이미지에 함께 들어 있습니다.
- **database** — collection 을 담는 최상위 논리 단위 (관계형 DB 의 database 에 해당). 첫 쓰기 때 자동 생성됩니다.
- **collection** — 도큐먼트를 담는 그릇 (관계형 DB 의 테이블에 해당). 스키마가 고정되지 않습니다.
- **document** — MongoDB 의 기본 레코드. 필드-값 쌍으로 이뤄진 JSON 형태이며 내부적으로 **BSON** (Binary JSON) 으로 저장됩니다.
- **authSource** — 사용자 자격증명이 저장된 DB. 사용자를 `admin` 에 만들면 연결 시 `authSource=admin` 을 지정합니다.

## Appendix B. MongoDB CLI

`mongosh` 로 DB·collection·document·사용자를 다룹니다. 이 문서에서 쓰는 주요 명령만 정리합니다.

| Category | Command | Description |
|----------|---------|-------------|
| Connect | `mongosh "mongodb://<user>:<pwd>@<host>:27017/?authSource=admin"` | 인증과 함께 접속합니다. |
| Connect | `docker compose exec mongo mongosh -u <user> -p <pwd>` | 컨테이너 안의 mongosh 로 접속합니다. |
| Database | `show dbs` · `use <db>` · `db.dropDatabase()` | DB 목록·선택·삭제. |
| Collection | `show collections` · `db.createCollection("<c>")` | collection 목록·생성 (보통 첫 insert 로 자동 생성). |
| Write | `db.<c>.insertOne({...})` · `db.<c>.insertMany([...])` | 도큐먼트 삽입. |
| Read | `db.<c>.find({<filter>})` · `db.<c>.findOne({...})` · `db.<c>.countDocuments({...})` | 조회. |
| Update | `db.<c>.updateOne({<filter>}, { $set: {...} })` | 수정. |
| Delete | `db.<c>.deleteOne({<filter>})` · `db.<c>.deleteMany({...})` | 삭제. |
| Index | `db.<c>.createIndex({ <field>: 1 })` | 인덱스 생성. |
| User | `db.createUser({...})` · `db.getUsers()` · `db.dropUser("<u>")` | 사용자 관리 (`admin` DB 에서). |
| Admin | `db.adminCommand({ ping: 1 })` | server 상태 확인 (healthcheck 와 동일). |

> mongosh 안에서 `db` 는 현재 선택된 DB (`use <db>`) 를 가리킵니다. 사용자 생성·조회는 `use admin` 후 실행합니다.
