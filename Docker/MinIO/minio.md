# MinIO — Object Storage

**MinIO**는 **AWS S3 (Amazon Simple Storage Service) 와 100% 호환되는 오픈소스 오브젝트 스토리지**입니다. 클라우드 (AWS) 없이 사내 server 나 로컬 도커에 띄워 "내 S3"처럼 쓸 수 있어, 데이터셋·모델·MLflow artifact 등 **실제 대용량 데이터의 보관 위치**로 사용합니다.

- **S3 (Amazon Simple Storage Service)**: AWS의 오브젝트 스토리지. 파일을 "객체 (object)" 단위로 저장하며, **버킷 (bucket)** 이라는 최상위 공간 안에 키 (경로) 로 파일을 넣습니다.
- **버킷 (bucket)**: 오브젝트를 담는 최상위 컨테이너.
- **버저닝 (versioning)**: 같은 키로 다시 올려도 이전 오브젝트를 보존하는 기능. MinIO 버저닝은 **덮어쓰기 사고를 막는 보조 안전장치**입니다.

## 1. MinIO Installation

MinIO 는 도커 컨테이너로 실행됩니다. 아래는 MinIO 의 `docker-compose.yml` 입니다. `docker compose up -d` 를 실행하면 도커가 `minio/minio` 이미지를 자동으로 내려받아 컨테이너로 띄우므로 **MinIO 를 호스트에 따로 설치할 필요가 없습니다.** `minio/minio` 이미지에는 `mc` 클라이언트가 함께 들어 있어, **한 서비스가 server 기동과 버킷 생성·버저닝까지 모두 처리** 합니다.

이 컨테이너는 같은 호스트의 다른 서비스 (예: 실험 추적 server) 가 `minio` 라는 **서비스명으로 접속** 하도록 공유 네트워크 `mlops` 에 붙습니다. 따라서 컨테이너를 띄우기 전에 그 네트워크가 있어야 합니다.

```powershell
# (최초 1회) 예시 파일을 복사해 루트 계정을 채운다. docker-compose.env 는 git 에 커밋하지 않는다.
Copy-Item docker-compose.env_example docker-compose.env

# 공유 네트워크 mlops 를 만들고(이미 있으면 에러는 무시) 컨테이너를 백그라운드로 띄운다.
docker network create mlops
docker compose up -d
```

```yaml
services:
  minio:
    image: minio/minio
    env_file:
      - docker-compose.env          # MINIO_ROOT_USER / MINIO_ROOT_PASSWORD 를 주입한다.
    ports:
      - "9000:9000"   # S3 API
      - "9001:9001"   # 웹 console
    volumes:
      - minio-data:/data
    # server 를 백그라운드로 띄우고 → 준비되면 mc 로 버킷 생성 + 버저닝 → wait 로 server 를 포그라운드 유지.
    entrypoint: >
      /bin/sh -c "
      minio server /data --console-address ':9001' &
      until mc alias set local http://localhost:9000 $$MINIO_ROOT_USER $$MINIO_ROOT_PASSWORD 2>/dev/null; do sleep 1; done &&
      mc mb --ignore-existing local/datasets local/models local/mlflow &&
      mc version enable local/datasets &&
      mc version enable local/models &&
      wait
      "
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 5s
      retries: 10
    networks:
      - mlops
    restart: unless-stopped

volumes:
  minio-data:

networks:
  mlops:
    external: true
```

구성 요소의 의미는 다음과 같습니다.

- `image: minio/minio` 는 공식 MinIO server 이미지를 사용한다는 뜻이며, 이 이미지에는 `mc` 클라이언트도 함께 들어 있어 같은 컨테이너 안에서 버킷을 만들 수 있습니다.
- `entrypoint` 는 server 를 **백그라운드로 띄운 뒤** (`minio server ... &`), `until` 로 server 가 준비될 때까지 재시도하여 alias 를 잡고, `mc` 로 `datasets`/`models`/`mlflow` 버킷을 만들고 `datasets`/`models` 에 버저닝을 켭니다. 마지막 `wait` 가 백그라운드 server 프로세스를 기다려 **컨테이너를 계속 떠 있게** 합니다 (이게 없으면 mc 명령 후 컨테이너가 종료됩니다).
  - 컨테이너 **안** 이라 endpoint 는 서비스명이 아니라 `http://localhost:9000` 입니다.
  - `--ignore-existing` 으로 버킷이 이미 있으면 통과하고, 버저닝도 멱등하므로 **재기동해도 안전** 합니다.
  - `$$VAR` (예: `$$MINIO_ROOT_USER`) 는 compose 가 `$` 로 바꿔 컨테이너 셸이 `env_file` 값으로 확장합니다.
  - 커뮤니티 웹 console 에는 버킷/버저닝 관리 메뉴가 없어 이렇게 `mc` 로 자동 처리하므로, 보통 `mc` 를 따로 설치하지 않아도 버킷·버저닝이 준비됩니다.
- `ports` 의 두 포트는 용도가 다릅니다. `9000` 은 **S3 API** (코드·`mc`·boto3 등 프로그램이 데이터를 읽고 쓰는 endpoint) 이고, `9001` 은 **웹 console** (사람이 브라우저로 보는 GUI) 이라, 서로 다른 클라이언트를 위한 별개 채널이므로 둘 다 노출합니다.
- `env_file` 은 루트 계정 (`MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`) 을 yml 에 평문으로 두지 않고 `docker-compose.env` 에서 읽어 주입합니다.
- `volumes: minio-data:/data` 는 데이터를 named volume 에 영속 저장하여, 컨테이너를 지워도 데이터가 보존되게 합니다.
- `healthcheck` 는 `mc ready local` 로 기동 완료를 확인하여, 다른 서비스가 이 상태를 기다릴 수 있게 합니다.
- `networks: mlops` 는 같은 호스트의 다른 서비스가 `minio` 서비스명으로 접속하도록 공유 외부 네트워크에 연결합니다.

## 2. mc Installation

`mc` (MinIO Client) 는 MinIO server 와 **별개의 CLI 도구**입니다. 두 가지 방법으로 쓸 수 있습니다.

**① 호스트에 설치** — `https://dl.min.io/client/mc/release/windows-amd64/mc.exe` 를 받아 `mc.exe` 로 이름을 바꾸고 PATH 에 있는 폴더 (또는 작업 폴더) 에 둡니다.

**② 도커 컨테이너 셸에서 사용 (설치 불필요)** — `minio/minio` 이미지에는 `mc` 가 함께 들어 있으므로, **떠 있는 `minio` 컨테이너의 셸에서 바로 `mc` 를 쓸 수 있습니다.** 기동 시 `local` alias 도 이미 설정돼 있어 별도 등록 없이 명령이 동작합니다.

```powershell
# 떠 있는 minio 컨테이너에서 mc 를 1회 실행
docker compose exec minio mc ls local

# 컨테이너 셸로 들어가서 여러 명령을 실행(나올 때는 exit)
docker compose exec -it minio sh
#  (컨테이너 셸 안) mc ls local  /  mc version info local/datasets  …  →  exit
```

> 컨테이너 **안** 에서는 endpoint 가 `http://localhost:9000` (같은 컨테이너의 server) 입니다. 호스트에 설치한 `mc` 로 접속할 때는 `http://<서버>:9000` 을 씁니다 ([§5](#5-read-only--scoped-access-keys) 의 alias 등록 참고).

## 3. Access

MinIO는 S3 호환이라 두 가지 클라이언트로 접근합니다 — **파이썬은 AWS SDK `boto3`**, **CLI는 `mc` (MinIO Client)**. `endpoint_url` (boto3) 또는 alias (mc) 만 MinIO 주소로 지정하면 실제 AWS S3와 동일하게 동작합니다.

> 아래 예시는 **`datasets` 버킷의 `SYDNEY/` 폴더에 `001.parquet` … `010.parquet`** 가 있다고 가정합니다 (객체 키: `SYDNEY/001.parquet` … `SYDNEY/010.parquet`).

### Python (`boto3`)

```python
import io, os, boto3, pandas as pd

# ── 환경변수/파라미터 ──
ENDPOINT   = os.environ.get("MINIO_ENDPOINT", "http://localhost:9000")
ACCESS_KEY = os.environ["MINIO_ACCESS_KEY"]
SECRET_KEY = os.environ["MINIO_SECRET_KEY"]
BUCKET     = "datasets"               # 버킷명
PREFIX     = "SYDNEY/"                # 폴더(접두사)
KEY        = "SYDNEY/001.parquet"     # 단일 객체 키

s3 = boto3.client(
    "s3",
    endpoint_url=ENDPOINT,
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
)

# ── list: PREFIX 폴더의 객체 나열 (페이지네이션) ──
for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=PREFIX):
    for obj in page.get("Contents", []):
        print(obj["Key"], obj["Size"])               # SYDNEY/001.parquet 12345 ...

# ── download: 객체 1개 → 로컬 파일 ──
s3.download_file(BUCKET, KEY, "001.parquet")

# ── download: 폴더(PREFIX) 통째로 — prefix 의 모든 객체를 받아 같은 구조로 저장 ──
for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=PREFIX):
    for obj in page.get("Contents", []):
        key = obj["Key"]                                  # 예: SYDNEY/001.parquet
        os.makedirs(os.path.dirname(key), exist_ok=True)  # 로컬에 SYDNEY/ 폴더 생성
        s3.download_file(BUCKET, key, key)                # → ./SYDNEY/001.parquet … 010.parquet

# ── upload: 로컬 파일 → 객체 키 ──
s3.upload_file("001.parquet", BUCKET, KEY)

# ── streaming: 다운로드(디스크 저장) 없이 메모리로 바로 읽기 ──
body = s3.get_object(Bucket=BUCKET, Key=KEY)["Body"].read()
df = pd.read_parquet(io.BytesIO(body))               # 로컬 파일 안 만들고 DataFrame 으로

# ── 대용량: Range 로 일부 바이트만 부분 읽기 (전체를 안 받고 앞부분/특정 구간만) ──
head = s3.get_object(Bucket=BUCKET, Key=KEY,
                     Range="bytes=0-1048575")["Body"].read()   # 0~1048575 = 첫 1MB(1024*1024)
# 다음 구간은 Range="bytes=1048576-2097151" 처럼 구간을 옮겨가며 청크로 반복(이어받기)
```

- 인자: **`Bucket`** (버킷명) + **`Key`** (버킷 안 객체 경로, 예: `SYDNEY/001.parquet`) + **`Filename`** (로컬 경로).
- `download_file`/`upload_file` 은 **디스크를 거치고**, **`get_object` 은 메모리로 스트리밍**합니다 (대용량은 `Range` 로 부분 읽기 가능).
- `s3fs`/`pyarrow` 를 쓰면 `pd.read_parquet("s3://datasets/SYDNEY/001.parquet", storage_options=...)` 처럼 `s3://` 를 직접 읽을 수도 있습니다.

### CLI (`mc`)

```powershell
# alias 등록 (한 번) — 이후 'local' 로 참조
# 형식: mc alias set <alias> <url> <ACCESS_KEY> <SECRET_KEY>
#   <ACCESS_KEY> = MINIO_ROOT_USER, <SECRET_KEY> = MINIO_ROOT_PASSWORD (실제 값은 docker-compose.env)
mc alias set local http://<서버>:9000 <ACCESS_KEY> <SECRET_KEY>

# ── list ──
mc ls local/datasets/SYDNEY/                  # SYDNEY/ 폴더 객체 나열
mc ls --recursive local/datasets/SYDNEY/      # 하위까지 재귀

# ── download (get) ──
mc cp local/datasets/SYDNEY/001.parquet .\               # 1개 → 현재 폴더
mc cp --recursive local/datasets/SYDNEY/ .\SYDNEY\       # 폴더 통째로

# ── upload (put) ──
mc cp .\001.parquet local/datasets/SYDNEY/               # 1개
mc cp --recursive .\SYDNEY\ local/datasets/SYDNEY/       # 폴더 통째로

# ── streaming: 다운로드 없이 표준출력으로 흘려보내기 ──
mc cat local/datasets/SYDNEY/001.parquet > 001.parquet               # 파일로 리다이렉트
mc cat local/datasets/SYDNEY/001.parquet | <명령>                    # 파이프로 바로 처리
```

> 정리: **`boto3` = 파이썬 코드 안에서, `mc` = 터미널에서** 같은 객체에 list / download / upload / streaming 합니다. 둘 다 S3 주소만 MinIO (`endpoint_url` / alias) 로 바꾸면 되므로, 로컬·온프레미스에서 S3를 그대로 대체합니다.

## 4. Credentials

접속 계정은 `docker-compose.env` 한 곳에 모으고, 컨테이너는 `env_file` 로 읽으며 호스트 파이썬 (boto3)·`mc` 는 같은 값을 환경변수로 올려 `os.environ` 등에서 읽습니다. 실제 값이 담긴 `docker-compose.env` 는 `.gitignore` 로 git 추적에서 제외하고, 비밀값을 비운 `docker-compose.env_example` 만 커밋합니다.

```dotenv
# docker-compose.env_example  (모든 값은 CHANGE_ME placeholder — 실제 값 노출 금지)
MINIO_ROOT_USER=CHANGE_ME
MINIO_ROOT_PASSWORD=CHANGE_ME
```

- 컨테이너 셸 명령 (예: entrypoint) 안에서 위 값을 참조할 때는 `$$MINIO_ROOT_USER` 처럼 `$$` 로 적습니다. `$$` 는 compose 가 `$` 로 바꿔 컨테이너 셸이 `env_file` 값으로 확장하며, `$` 단독은 compose 가 먼저 가로채므로 쓰지 않습니다.
- 호스트 파이썬·`mc` 는 이 루트 계정을 access key/secret key 로 써서 접속합니다 (`MINIO_ROOT_USER`=access key, `MINIO_ROOT_PASSWORD`=secret key). 코드에 기록하지 말고 환경변수 (예: `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY`) 로 둡니다.
- 모든 `CHANGE_ME` 는 강한 계정/비밀번호로 교체하고, 실제 `docker-compose.env` 는 git 이 아니라 안전한 채널로 공유합니다.
- 루트 계정은 전권이므로 **팀원에게 직접 주지 말고**, 권한을 좁힌 별도 access key 를 발급해 씁니다 ([§5](#5-read-only--scoped-access-keys) 참고).

## 5. Read-Only & Scoped Access Keys

루트 계정 (`MINIO_ROOT_USER`) 은 모든 버킷에 읽기·쓰기·삭제·관리가 가능하므로 **팀원에게 주면 안 됩니다.** 팀원에게는 **권한을 좁힌 별도 계정 (access key)** 을 발급합니다. MinIO는 **정책 (policy)** 으로 권한을 제어하며, 내장 정책 `readonly` (읽기 전용)·`readwrite`·`writeonly`가 있고, 직접 정책을 만들 수도 있습니다.

> 아래 `mc admin ...` 명령은 **관리자**가, 루트 자격증명으로 등록한 alias (예: `local`) 로 실행합니다.
> `mc alias set local http://<서버>:9000 <ACCESS_KEY> <SECRET_KEY>` ([Access](#3-access) 참고)

### (1) 읽기 전용 사용자 만들기 (내장 `readonly`)

```powershell
# 사용자 생성(이름 + 비밀키) 후 readonly 정책 부여
mc admin user add local member1 <member1-secret>
mc admin policy attach local readonly --user member1
```

이제 `member1` / `<member1-secret>` 를 access key/secret key 로 쓰면 **모든 버킷을 다운로드 (GetObject)·조회 (ListBucket) 만** 할 수 있고, 업로드·삭제는 거부됩니다.

```python
import boto3

# ── 환경변수/파라미터 ──
ENDPOINT   = "http://<서버>:9000"     # 같은 PC 면 localhost
ACCESS_KEY = "member1"
SECRET_KEY = "<member1-secret>"
BUCKET     = "datasets"

s3 = boto3.client("s3", endpoint_url=ENDPOINT,
                  aws_access_key_id=ACCESS_KEY, aws_secret_access_key=SECRET_KEY)
s3.download_file(BUCKET, "mnist-train.parquet", "mnist-train.parquet")  # OK (읽기)
# s3.upload_file(...)  → AccessDenied (쓰기 금지)
```

> ⚠️ **주의**: 읽기 전용 키로는 학습 파이프라인이 결과를 **업로드 (`s3://models/...`) 하거나 저장할 수 없습니다.** 따라서 **데이터를 내려받기만 하는 소비자형 팀원**에게 적합합니다. 팀원이 직접 파이프라인을 돌려 산출물을 남겨야 한다면 아래 (2) 처럼 **자기 영역에만 쓰기**를 허용하세요.

### (2) 버킷별 권한을 가진 Access Key 발급 (서비스 계정 + 인라인 정책)

**서비스 계정 (access key 쌍) 에 정책을 직접 붙여 "버킷별 권한 조정"까지 한 번에** 할 수 있습니다. 즉 별도의 프로그램용 키 발급 ((1) 의 사용자 비번과 분리) 과 버킷 한정 권한을 **한 단계로 합칩니다.** 서비스 계정은 기본적으로 상위 사용자의 정책을 상속하지만, `--policy` 로 **인라인 정책**을 주면 그 범위로 더 좁혀집니다.

먼저 "공유 데이터는 읽되, 남의 산출물은 수정하지 못하고 **자기 영역 (`models/member1/*`) 에만 쓰기**" 같은 정책 (JSON) 을 준비합니다.

```json
// member1-policy.json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": ["arn:aws:s3:::datasets", "arn:aws:s3:::datasets/*"] },
    { "Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": ["arn:aws:s3:::models/member1/*"] }
  ]
}
```

이 정책은 AWS IAM 과 같은 구조입니다:

- **`Version`** — 정책 문법 버전. `2012-10-17` 고정값 (AWS IAM 호환).
- **`Statement`** — 권한 규칙 배열 (규칙을 여러 개 나열 가능). 각 규칙은:
  - **`Effect`** — `Allow` (허용) 또는 `Deny` (거부).
  - **`Action`** — 대상 동작. `s3:GetObject`=다운로드, `s3:PutObject`=업로드, `s3:ListBucket`=목록 조회.
  - **`Resource`** — 대상 범위 (ARN). `arn:aws:s3:::<bucket>`=버킷 자체 (ListBucket 용), `arn:aws:s3:::<bucket>/<prefix>/*`=그 안의 객체들.
- 위 예시 의미: **`datasets` 버킷은 읽기·목록만**, **`models/member1/*` 에만 읽기+쓰기** → 공유 데이터는 못 바꾸고 자기 영역에만 산출물을 남깁니다.

```powershell
# 사용자 1회 생성(로그인 주체)
mc admin user add local member1 <member1-login-secret>

# 버킷 한정 인라인 정책을 가진 프로그램용 access key 발급 (← 키 발급 + 버킷 권한을 한 번에)
mc admin user svcacct add --policy .\member1-policy.json local member1
#   → Access Key / Secret Key 가 출력됨. 이 쌍을 팀원에게 전달.
#   읽기 전용만 주려면 위 JSON 에서 PutObject 줄을 빼면 된다.
```

- **`<member1-login-secret>`** = 이 MinIO **사용자 (`member1`) 의 로그인 비밀번호**입니다 (웹 console 로그인·관리용 주체 비번). 실제로는 강한 값으로 바꿔 입력하세요. 팀원이 **프로그램에서 쓰는 키는 이 비번이 아니라**, 위 `svcacct add` 가 출력한 **Access Key / Secret Key** 입니다 (둘은 별개).

> 대안: 정책을 **사용자에게** 붙이고 (`mc admin policy create` → `attach`) 서비스 계정은 인라인 정책 없이 발급해 **상속**시켜도 결과는 같습니다. 사용자를 여러 키로 나눠 쓸 거면 사용자 정책 방식이, 키마다 권한을 다르게 줄 거면 인라인 방식이 편합니다.

### (3) 확인 · 해제

```powershell
mc admin user list local                       # 사용자 목록
mc admin user info local member1               # 부여된 정책 확인
mc admin user svcacct list local member1       # 발급된 access key 목록
mc admin policy detach local readonly --user member1   # 사용자 정책 해제
mc admin user svcacct rm local <access-key>    # 특정 access key 폐기(키 회전)
mc admin user disable local member1            # 사용자 일시 비활성화(또는 remove 로 삭제)
```

### (4) 발급한 Key 를 팀원이 쓰는 법 (하드코딩 금지)

발급한 **Access Key / Secret Key** 는 코드에 기록하지 말고 **환경변수나 파라미터**로 주입하여, 코드가 `os.environ` 에서 읽게 합니다.

```powershell
# 환경변수로 주입 (boto3 등 클라이언트 공통)
$env:MINIO_ENDPOINT   = "http://<서버>:9000"   # 같은 PC 면 localhost, 다른 PC 면 server IP/호스트
$env:MINIO_ACCESS_KEY = "<발급된 access key>"
$env:MINIO_SECRET_KEY = "<발급된 secret key>"
```

> 정리: **소비자형 팀원 → 내장 `readonly`** (1), **자기 산출물을 남겨야 하는 팀원 → 버킷 한정 정책을 가진 서비스 계정** (2). 어느 쪽이든 루트 (`MINIO_ROOT_USER`) 는 server admin 만 보유하고, 팀원은 발급받은 스코프 키를 환경변수로 씁니다 (4).

## Appendix A. Terminology

- **mc** — MinIO Client. MinIO·S3 호환 스토리지를 다루는 CLI 도구이며, `minio/minio` 이미지에 함께 들어 있습니다.
- **bucket** — 오브젝트를 담는 최상위 컨테이너 (S3 의 최상위 저장 공간).

## Appendix B. MinIO Client CLI

`mc` (MinIO Client) 로 버킷·오브젝트·사용자·정책을 다룹니다. 이 문서에서 쓰는 주요 명령만 정리합니다 (`mc` 설치·실행은 [§2](#2-mc-installation) 참고).

| Category | Command | Description |
|----------|---------|-------------|
| Alias | `mc alias set <alias> <url> <ACCESS_KEY> <SECRET_KEY>` | server 를 alias 로 등록합니다 (이후 `local` 등으로 참조). |
| Object | `mc ls [--recursive] [--versions] <alias>/<bucket>/<prefix>` | 객체 목록을 봅니다 (버전 포함 조회 가능). |
| Object | `mc cp [--recursive] <src> <dst>` | 복사 — 다운로드 (`local/...` → `.`) / 업로드 (`.` → `local/...`). |
| Object | `mc cat <alias>/<bucket>/<key>` | 객체를 표준출력으로 스트리밍합니다 (다운로드 없이 파이프). |
| Bucket | `mc mb [--ignore-existing] <alias>/<bucket>` | 버킷을 만듭니다 (`--ignore-existing` 은 멱등). |
| Versioning | `mc version enable\|info <alias>/<bucket>` | 버저닝을 켜거나 상태를 조회합니다. |
| Health | `mc ready <alias>` | server 준비 상태를 확인합니다 (healthcheck 에서 사용). |
| Admin | `mc admin user add <alias> <user> <secret>` | 사용자를 만듭니다. |
| Admin | `mc admin policy attach <alias> <policy> --user <user>` | 사용자에 정책을 부여합니다 (`readonly` 등). |
| Admin | `mc admin user svcacct add [--policy <file>] <alias> <user>` | 프로그램용 access key 를 발급합니다 (인라인 정책 가능). |
| Admin | `mc admin user list\|info` · `svcacct list\|rm` · `policy detach` · `user disable` | 사용자·키·정책을 확인하고 해제합니다. |

> 권한을 좁힌 키 발급·정책 운영의 상세는 [§5](#5-read-only--scoped-access-keys), 버킷·버저닝 수동 처리는 Appendix C 를 참고합니다.

## Appendix C. Manual Bucket Provisioning & Versioning (`mc` CLI)

보통은 `minio` 서비스가 기동 시 자동 처리하므로 불필요합니다. **스택을 쓰지 않거나 버킷·버저닝을 직접 제어하고 싶을 때만** 아래처럼 수동으로 실행합니다 (`mc` 설치는 [mc Installation](#2-mc-installation) 참고).

```powershell
# MinIO Client(mc) 로 server alias 등록
mc alias set local http://<서버>:9000 <ACCESS_KEY> <SECRET_KEY>

# 버킷 생성
mc mb local/datasets
mc mb local/models
mc mb local/mlflow

# 데이터 버킷에 versioning 켜기 (이전 버전 보존)
mc version enable local/datasets
mc version enable local/models
```

> ⚠️ MinIO **커뮤니티 console (:9001) 에는 버킷 생성·버저닝 관리 메뉴가 없습니다** (관리 기능이 상용 제품으로 분리됨). 따라서 위 `mc` CLI를 사용하세요. `mc`를 호스트에 설치하지 않았다면, 떠 있는 `minio` 컨테이너에 `mc` 가 들어 있으므로 `docker compose exec minio mc ...` 로 실행하면 됩니다 ([mc Installation](#2-mc-installation) ② 참고).

## Appendix D. Versioning Verification

버킷에 버저닝이 실제로 켜졌는지 확인하는 방법입니다.

> 커뮤니티 웹 console 에는 버저닝 표시가 없으므로 `mc` 또는 `boto3` 로 확인합니다.

mc가 설치되었을 경우,

```powershell
# (1) 상태 조회 — "versioning is enabled" 또는 "is un-versioned" 출력
mc version info local/datasets

# (2) 모든 버킷의 버저닝 상태를 한 번에 조회
mc ls local --json | ForEach-Object { ($_ | ConvertFrom-Json).key } | ForEach-Object { mc version info "local/$_" }

# (3) 동작 검증 — 같은 키로 두 번 올린 뒤 버전이 쌓이는지 확인
mc cp a.txt local/datasets/test.txt        # 1차
mc cp a.txt local/datasets/test.txt        # 2차(덮어쓰기)
mc ls --versions local/datasets/test.txt   # 버전이 2개로 보이면 versioning 동작 중
```

docker 컨테이너 셸로 확인할 경우 (호스트에 mc 를 설치하지 않아도 됨), 떠 있는 `minio` 컨테이너 셸에서 확인합니다. `minio/minio` 이미지에 `mc` 가 있고 기동 시 `local` alias 가 이미 설정돼 있어, alias 등록 없이 바로 확인됩니다.

```powershell
# 1회 실행
docker compose exec minio mc version info local/datasets

# 컨테이너 셸로 들어가서 여러 버킷을 확인(나올 때는 exit)
docker compose exec -it minio sh
#  (컨테이너 셸 안)
mc version info local/datasets
mc version info local/models
mc version info local/mlflow
exit
```

python (boto3) 이 설치되었을 경우,

```python
import boto3

# ── 환경변수/파라미터 ──
ENDPOINT   = "http://<서버>:9000"     # 같은 PC 면 localhost
ACCESS_KEY = "<ACCESS_KEY>"
SECRET_KEY = "<SECRET_KEY>"
BUCKET     = "datasets"

s3 = boto3.client("s3", endpoint_url=ENDPOINT,
                  aws_access_key_id=ACCESS_KEY, aws_secret_access_key=SECRET_KEY)
print(s3.get_bucket_versioning(Bucket=BUCKET).get("Status"))   # "Enabled" 또는 None
```
