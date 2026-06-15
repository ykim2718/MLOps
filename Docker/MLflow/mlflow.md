# MLflow — Experiment Tracking & Model Registry

MLflow 는 실험의 **파라미터·지표를 추적** 하고, 학습된 **모델을 레지스트리로 관리·배포·서빙** 하는 도구입니다. 이 스택에서는 저장소를 두 곳으로 나눠, 가벼운 메타데이터는 메타데이터 DB 에, 실제 산출물은 오브젝트 스토리지에 둡니다.

## 1. Role

MLflow 는 저장소를 backend 와 artifact 두 층으로 나눕니다.

| Store | Location | Contents |
|-------|------|-----------|
| **Backend store** | PostgreSQL `mlflow` DB | params · metrics · tags · run · model registry 메타데이터를 저장합니다. |
| **Artifact store** | MinIO `s3://mlflow/...` | 모델·plot·파일 등 실제 산출물 (아티팩트) 을 저장합니다. |

> Prefect 가 "실행 흐름" 을, MLflow 가 "실험 기록" 을 담당하여 역할이 겹치지 않습니다. 각 단계 안에서 `mlflow.log_*` 로 같은 run 에 기록하면, 한 실행의 파라미터·지표·산출물이 한곳에 모입니다.

## 2. Docker Setup

MLflow 는 도커 컨테이너로 실행됩니다. backend 인 PostgreSQL (`mlflow` DB) 과 artifact 인 MinIO (`mlflow` 버킷) 가 **먼저 떠 있어야** 정상 동작하므로, 같은 호스트에서 그 둘을 띄운 뒤 실행합니다. 이 컨테이너는 공유 네트워크 `mlops` 에서 `postgres` · `minio` 를 서비스명으로 접속하므로, 띄우기 전에 그 네트워크가 있어야 합니다.

```powershell
# (최초 1회) 예시 파일을 복사해 backend/artifact 접속 값을 채운다. docker-compose.env 는 git 에 커밋하지 않는다.
Copy-Item docker-compose.env_example docker-compose.env

# 공유 네트워크 mlops 를 만들고(이미 있으면 에러는 무시) 컨테이너를 백그라운드로 띄운다.
docker network create mlops
docker compose up -d
```

실행 후 MLflow UI 는 **`http://<MLflow 호스트>:5000`** 에서 열립니다 (같은 컴퓨터에서는 `localhost`).

```yaml
services:
  mlflow:
    image: ghcr.io/mlflow/mlflow:latest
    command: >
      bash -c "pip install --quiet psycopg2-binary boto3 &&
               mlflow server --host 0.0.0.0 --port 5000
               --backend-store-uri postgresql://$$POSTGRES_USER:$$POSTGRES_PASSWORD@postgres:5432/mlflow
               --artifacts-destination s3://mlflow"
    env_file:
      - docker-compose.env          # POSTGRES_USER/PASSWORD, AWS_ACCESS_KEY_ID/SECRET, MLFLOW_S3_ENDPOINT_URL
    ports:
      - "5000:5000"
    networks:
      - mlops
    restart: unless-stopped

networks:
  mlops:
    external: true
```

구성 요소의 의미는 다음과 같습니다.

- `command` 는 컨테이너가 뜰 때 PostgreSQL/S3 드라이버를 설치한 뒤 MLflow server 를 띄웁니다. backend 는 `postgres` 서비스명으로 `mlflow` DB 에, artifact 는 `s3://mlflow` 에 연결합니다.
- `env_file` 은 backend 계정 (`POSTGRES_USER`/`POSTGRES_PASSWORD`) 과 artifact 접속 키 (`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`), 그리고 MinIO endpoint (`MLFLOW_S3_ENDPOINT_URL`) 를 주입합니다.
- `networks: mlops` 로 같은 호스트의 `postgres` · `minio` 와 서비스명으로 통신합니다. 그 둘은 별도 compose 라 `depends_on` 을 걸 수 없으므로, `restart: unless-stopped` 로 준비될 때까지 자동 재시도합니다.

## 3. Tracking

코드에서 tracking URI 를 MLflow server 로 지정한 뒤, run 안에서 파라미터·지표·산출물을 로깅합니다.

```python
import mlflow

mlflow.set_tracking_uri("http://<MLflow 호스트>:5000")   # 같은 PC 면 localhost
with mlflow.start_run(run_name="train"):
    mlflow.log_params({"lr": 0.01, "n_estimators": 150})   # → mlflow DB
    mlflow.log_metric("train_acc", 0.97)                   # → mlflow DB
    mlflow.log_artifacts("model/")                         # → MinIO(s3://mlflow/...)
```

- `log_params` / `log_metric` 으로 남긴 값은 backend (PostgreSQL `mlflow` DB) 에 저장되어 UI 에서 실험 간 비교에 쓰입니다.
- `log_artifacts` 로 올린 파일은 artifact store (MinIO `s3://mlflow/...`) 에 저장됩니다.
- 여러 run 의 산출물은 `run_id` 별 폴더로 자동 격리되므로 (`s3://mlflow/<experiment>/<run_id>/...`), 이름 충돌을 사람이 신경 쓸 필요가 없습니다.

## 4. Model Registry — Versioning, Deploying, Serving

여러 실험에서 고른 **best 모델** 을 **이름 + 버전 + 단계 (Stage)** 로 관리하고 실제로 구동하는 단계입니다. 실제 가중치 파일은 artifact store (MinIO) 에 저장되고, 레지스트리는 그 모델의 이름·버전·운영 단계를 가리킵니다.

> **배포 (Deploy)** 는 어떤 모델 버전을 운영 위치 (레지스트리 Stage) 에 올리는 행위이고, **서빙 (Serve)** 은 그 배포된 모델을 예측 요청을 받아 응답하는 **추론 API 로 구동** 하는 행위입니다.

### 1) Register & Deploy

```python
import mlflow
from mlflow.tracking import MlflowClient

mlflow.set_tracking_uri("http://<MLflow 호스트>:5000")   # 같은 PC 면 localhost

# 학습 run 에서 나온 모델을 레지스트리에 "이름 + 버전" 으로 등록한다.
mlflow.register_model(model_uri="runs:/<run_id>/model", name="mnist-classifier")
# → mnist-classifier v1, v2, ... 로 버전이 쌓인다.

# best 버전을 운영 단계로 승격(배포)한다.
MlflowClient().transition_model_version_stage(
    name="mnist-classifier", version=3, stage="Production")
```

### 2) Serve

```powershell
# 레지스트리의 Production 모델을 REST API 로 구동한다.
mlflow models serve -m "models:/mnist-classifier/Production" -p 5001

# 예측 요청 — POST /invocations 로 입력을 보내면 예측을 응답한다.
curl -X POST http://localhost:5001/invocations `
  -H "Content-Type: application/json" `
  -d '{"inputs": [[0.1, 0.2]]}'
```

## 5. Where to Store Best Models

모델 가중치는 trial 마다 생기므로, 보통 best N개 (예: best 5) 만 남기고 나머지는 정리합니다. 저장 위치는 "이 모델을 나중에 누가·어디서 다시 쓰느냐" 로 정합니다.

| Situation | Recommended Location |
|------|----------------|
| 혼자 실험하고 그 PC 에서만 사용한다 | 로컬 디스크에 두었다가 끝나면 MinIO 로 업로드한다. |
| 결과를 팀과 공유하거나 다른 PC 에서 로드·백업한다 | MinIO (`s3://models/...`) 또는 MLflow Model Registry 에 둔다. |
| best 모델을 버전 관리하고 배포·서빙까지 한다 | MLflow Model Registry 를 쓰는 것이 가장 깔끔하다. |

```python
# 1) trial 마다 MinIO 에 저장하고, 경로를 trial 메타데이터로 기록한다(DB 에는 경로만 남긴다).
uri = f"s3://models/{study_name}/trial_{trial.number}.pt"
upload_to_minio(local_path, uri)
trial.set_user_attr("model_uri", uri)

# 2) study 종료 후 best 5 만 남기고 나머지 체크포인트를 삭제한다.
top5 = sorted(study.trials, key=lambda t: t.value, reverse=True)[:5]
keep = {t.user_attrs["model_uri"] for t in top5}

# 3) (선택) 공유·배포가 필요할 때만 best 모델을 MLflow Registry 로 등록한다.
```

> 개별 실험이면 best 모델은 MinIO 로 충분하고, 배포·서빙까지 가면 그 모델을 MLflow Model Registry 에 등록합니다.

## 6. Credentials

접속 값은 `docker-compose.env` 한 파일에 모으고 컨테이너가 `env_file` 로 읽습니다. 실제 값이 담긴 `docker-compose.env` 는 `.gitignore` 로 git 추적에서 제외하고, 비밀값을 비운 `docker-compose.env_example` 만 커밋합니다.

```dotenv
# docker-compose.env_example  (모든 값은 CHANGE_ME placeholder — 실제 값 노출 금지)
POSTGRES_USER=CHANGE_ME             # backend(PostgreSQL mlflow DB) 계정 — PostgreSQL 쪽과 같은 값
POSTGRES_PASSWORD=CHANGE_ME
AWS_ACCESS_KEY_ID=CHANGE_ME         # artifact(MinIO/S3) 키 — MinIO 루트 계정(또는 발급한 키)과 같은 값
AWS_SECRET_ACCESS_KEY=CHANGE_ME
MLFLOW_S3_ENDPOINT_URL=http://minio:9000
```

- 명령 안에서 계정을 참조할 때는 `$$POSTGRES_USER` 처럼 `$$` 로 적습니다. `$$` 는 compose 가 `$` 로 바꿔 컨테이너 셸이 `env_file` 값으로 확장합니다.
- 모든 `CHANGE_ME` 는 강한 값으로 교체하고, 실제 `docker-compose.env` 는 git 이 아니라 안전한 채널로 공유합니다.
