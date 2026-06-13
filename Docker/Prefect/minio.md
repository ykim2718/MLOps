# MinIO — 오브젝트 스토리지

**MinIO**는 **AWS S3 (Amazon Simple Storage Service)와 100% 호환되는 오픈소스 오브젝트 스토리지**입니다. 클라우드(AWS) 없이 사내 서버나 로컬 도커에 띄워 "내 S3"처럼 쓸 수 있어, 데이터셋·모델·MLflow artifact 등 **실제 대용량 데이터의 보관 위치**로 사용합니다.

- **S3 (Amazon Simple Storage Service)**: AWS의 오브젝트 스토리지. 파일을 "객체(object)" 단위로 저장하며, **버킷(bucket)** 이라는 최상위 공간 안에 키(경로)로 파일을 넣습니다.
- **버킷(bucket)**: 오브젝트를 담는 최상위 컨테이너.
- **버저닝(versioning)**: 같은 키로 다시 올려도 이전 오브젝트를 보존하는 기능. MinIO 버저닝은 **덮어쓰기 사고를 막는 보조 안전장치**입니다.

## 1. Installing MinIO

MinIO는 이 스택에서 **도커 컨테이너로 실행**됩니다. 아래는 `docker-compose.yml`의 `minio`(및 버킷 초기화용 `createbuckets`) 부분입니다.

> 이 블록은 전체 `docker-compose.yml`의 일부입니다. `docker-compose.yml`이 있는 폴더에서 **`docker compose up -d`** 를 실행하면 도커가 `minio/minio` 이미지를 자동으로 내려받아 컨테이너로 실행하므로 **MinIO를 따로 설치할 필요가 없습니다.** 함께 정의된 `createbuckets`가 버킷 생성과 버저닝까지 끝냅니다.

```yaml
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

  # 버킷 생성 + 버저닝 ON (1회 실행 후 종료). 커뮤니티 콘솔엔 이 메뉴가 없어 mc 로 자동 처리.
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
```

- `image: minio/minio` — 공식 MinIO 서버 이미지
- `command: server /data --console-address ":9001"` — `/data`를 저장소로 쓰고 웹 콘솔을 `:9001`에 띄움
- `ports` — **두 포트는 용도가 다릅니다**: `9000` = **S3 API**(코드·`mc`·boto3 등 프로그램이 데이터를 읽고 쓰는 엔드포인트), `9001` = **웹 콘솔**(사람이 브라우저로 보는 GUI). 서로 다른 클라이언트를 위한 별개 채널이라 둘 다 노출합니다.
- `environment` — 루트 계정(= username / password): `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`
- `volumes: minio-data:/data` — 데이터를 named volume에 **영속 저장**(컨테이너를 지워도 데이터 보존)
- `healthcheck` — `mc ready local`로 기동 완료를 확인(다른 서비스가 이 상태를 기다림)
- `createbuckets` — **별도 1회용 서비스**. minio가 준비되면 `minio/mc`로 `datasets`/`models`/`mlflow` 버킷을 만들고 `datasets`/`models`에 **버저닝을 켠 뒤 종료**합니다. 커뮤니티 웹 콘솔에는 버킷/버저닝 관리 메뉴가 없어 이렇게 자동 처리하므로, 보통 **`mc`를 직접 설치하지 않아도** 버킷·버저닝이 준비됩니다.

## 2. Installing mc

`mc`(MinIO Client)는 MinIO 서버와 **별개의 CLI 도구**라 따로 설치해야 명령이 인식됩니다.

설치: `https://dl.min.io/client/mc/release/windows-amd64/mc.exe` 를 받아 `mc.exe`로 이름을 바꾸고 PATH에 있는 폴더(또는 작업 폴더)에 둡니다.

## 3. Accessing MinIO

### Upload / Download

MinIO는 S3 호환이라, 파이썬에서는 **AWS SDK인 `boto3`** 를 그대로 씁니다. `endpoint_url`만 MinIO 주소로 지정하면 실제 AWS S3 대신 MinIO에 연결되고, 나머지 API(`upload_file`/`download_file` 등)는 S3와 동일합니다.

```python
import boto3
s3 = boto3.client(
    "s3",
    endpoint_url="http://localhost:9000",      # MinIO 주소 (실제 AWS S3면 생략)
    aws_access_key_id="minioadmin",
    aws_secret_access_key="minioadmin",
)

# 업로드: 로컬 파일 → 버킷의 객체 키
s3.upload_file(
    Filename="model.pt",                       # 올릴 로컬 파일 경로
    Bucket="models",                           # 대상 버킷
    Key="member1/mnist-resnet50/model.pt",     # 버킷 안에서의 객체 키(경로+이름)
)

# 다운로드: 버킷의 객체 → 로컬 파일
s3.download_file(
    Bucket="datasets",                         # 가져올 버킷
    Key="mnist-train.parquet",                 # 가져올 객체 키
    Filename="mnist-train.parquet",            # 저장할 로컬 파일 경로
)
```

- `Filename` — **로컬** 파일 경로 (업로드: 올릴 원본 파일 / 다운로드: 저장할 위치)
- `Bucket` — 대상 버킷 이름 (예: `datasets`, `models`)
- `Key` — 버킷 안에서 객체를 식별하는 **키**(폴더처럼 보이는 경로 + 파일명). 예: `member1/mnist-resnet50/model.pt`

> 정리: **MinIO = 직접 설치하는 S3 호환 스토리지, 버킷 = 그 안의 파일 저장 공간.** 코드/설정에서 S3 주소만 MinIO 주소(`endpoint_url`)로 바꾸면 그대로 동작하므로, 로컬·온프레미스에서 S3를 대체할 수 있습니다.

## Appendix A. Manual Bucket Provisioning & Versioning (`mc` CLI)

보통은 `createbuckets`가 자동 처리하므로 불필요합니다. **스택을 쓰지 않거나 버킷·버저닝을 직접 제어하고 싶을 때만** 아래처럼 수동으로 실행합니다(`mc` 설치는 [Installing mc](#2-installing-mc) 참고).

```powershell
# MinIO Client(mc) 로 서버 alias 등록
mc alias set local http://localhost:9000 minioadmin minioadmin

# 버킷 생성
mc mb local/datasets
mc mb local/models
mc mb local/mlflow

# 데이터 버킷에 versioning 켜기 (이전 버전 보존)
mc version enable local/datasets
mc version enable local/models
```

> ⚠️ MinIO **커뮤니티 콘솔(:9001)에는 버킷 생성·버저닝 관리 메뉴가 없습니다** (관리 기능이 상용 제품으로 분리됨). 따라서 위 `mc` CLI를 사용하세요. `mc`를 호스트에 설치하지 않았다면, **`mc`가 들어 있는 도커 컨테이너의 셸로 들어가서** 실행하면 됩니다(스택 컨테이너가 `docker compose up -d`로 실행 중일 때):
>
> ```bash
> # 1) mc 가 포함된 컨테이너 셸로 진입 (1회용 컨테이너)
> docker run -it --rm --network prefect_default --entrypoint /bin/sh minio/mc
>
> # 2) 아래는 '컨테이너 셸 안'에서 실행하는 명령들
> mc alias set local http://minio:9000 minioadmin minioadmin
> mc mb --ignore-existing local/datasets local/models local/mlflow
> mc version enable local/datasets
> mc version enable local/models
> exit            # 셸 종료(컨테이너 제거)
> ```

## Appendix B. Verifying Versioning

버킷에 버저닝이 실제로 켜졌는지 확인하는 방법입니다.

> 커뮤니티 웹 콘솔에는 버저닝 표시가 없으므로 `mc` 또는 `boto3` 로 확인합니다.

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

docker의 stack container가 실행중일 때,

```powershell
docker run --rm --network prefect_default --entrypoint /bin/sh minio/mc -c "mc alias set local http://minio:9000 minioadmin minioadmin; mc version info local/datasets; mc version info local/models; mc version info local/mlflow"
```

python(boto3)이 설치되었을 경우,

```python
import boto3
s3 = boto3.client("s3", endpoint_url="http://localhost:9000",
                  aws_access_key_id="minioadmin", aws_secret_access_key="minioadmin")
print(s3.get_bucket_versioning(Bucket="datasets").get("Status"))   # "Enabled" 또는 None
```
