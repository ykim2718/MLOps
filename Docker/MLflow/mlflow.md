# MLflow — Experiment Tracking & Model Registry

<sub>rev. 101</sub>

MLflow 는 실험의 **파라미터·지표를 추적** 하고, 학습된 **모델을 레지스트리로 관리·배포·서빙** 하는 도구입니다. 이 스택에서는 저장소를 두 곳으로 나눠, 가벼운 메타데이터는 메타데이터 DB 에, 실제 산출물은 오브젝트 스토리지에 둡니다.

## 1. Role

MLflow 는 저장소를 backend 와 artifact 두 층으로 나눕니다.

| Store | Location | Contents |
|-------|------|-----------|
| **Backend store** | PostgreSQL `mlflow` DB | params · metrics · tags · run · model registry 메타데이터를 저장합니다. |
| **Artifact store** | MinIO `s3://mlflow/...` | 모델·plot·파일 등 실제 산출물 (아티팩트) 을 저장합니다. |

> Prefect 가 "실행 흐름" 을, MLflow 가 "실험 기록" 을 담당하여 역할이 겹치지 않습니다. 각 단계 안에서 `mlflow.log_*` 로 같은 run 에 기록하면, 한 실행의 파라미터·지표·산출물이 한곳에 모입니다.

### Process Flow

  전체 흐름은 학습 기록부터 추론 API 구동까지 한 줄로 이어지며, 각 단계는 위의 두 store 를 읽고 씁니다.

  ```
  Tracking ───────────► Registering ────────► Deploying ────────► Serving
  (run_id 생성)          (이름 + 버전)         (Production 승격)    (REST API)

  run 안에서             best run 의 모델을    best 버전을          Production 모델을
  params·metrics·        레지스트리에          운영 단계로          예측 요청을 받는
  artifacts 로깅         v1, v2... 로 등록     승격                추론 API 로 구동
     │                      │                    │                   │
     ▼                      ▼                    ▼                   ▼
  Backend:               Backend:             Backend:            Backend:
   params, metrics        이름·버전            Stage=Production     버전 조회
  Artifact: 산출물        (모델 파일은          —                   Artifact: 모델 파일 로드
                          Artifact 에 유지)
  ```

  - 모든 단계의 **메타데이터 (run, params, metrics, name, version, stage) 는 Backend store (PostgreSQL)** 에, **실제 모델 파일·산출물은 Artifact store (MinIO)** 에 나눠 저장됩니다. Register 이후로도 모델 파일은 복사되지 않고 Artifact store 에 그대로 머물며, 레지스트리는 그 위치를 가리키는 메타데이터만 Backend store 에 추가합니다.
  - **Tracking → Registering** 순서가 강제됩니다. Registering 이 `runs:/<run_id>/model` 로 Tracking 에서 생긴 `run_id` 를 입력받기 때문입니다.
  - **Tracking** 까지는 모든 실험의 공통 단계이고, **Registering → Deploying → Serving** 은 그 중 best 모델을 배포·서빙할 때만 진행합니다.

## 2. Docker Setup

MLflow 는 도커 컨테이너로 실행됩니다. backend 인 PostgreSQL (`mlflow` DB) 과 artifact 인 MinIO (`mlflow` 버킷) 가 **먼저 떠 있어야** 정상 동작하므로, 같은 호스트에서 그 둘을 띄운 뒤 실행합니다. 이 컨테이너는 공유 네트워크 `mlops` 에서 `postgres` · `minio` 를 서비스명으로 접속하므로, 띄우기 전에 그 네트워크가 있어야 합니다.

#### Yaml

```yaml
# docker-compose.yml
name: mlflow                        # Fix the project name (prefix of container and volume names).

services:
  mlflow:
    image: ghcr.io/mlflow/mlflow:latest
    command: >
      bash -c "pip install --quiet psycopg2-binary boto3 &&
               mlflow server --host 0.0.0.0 --port 5000
               --backend-store-uri postgresql://$$POSTGRES_USER:$$POSTGRES_PASSWORD@postgres:5432/mlflow
               --artifacts-destination s3://mlflow
               --allowed-hosts '*' --cors-allowed-origins '*'"
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

- `name: mlflow` 는 프로젝트명을 파일에 굳혀 둡니다. 이 값이 컨테이너·볼륨 이름의 앞가지가 되어, `-p` 를 붙이지 않아도 (다른 폴더에서 띄워도) 늘 같은 프로젝트·같은 볼륨에 붙으므로 쌓아 둔 데이터가 어긋나지 않습니다.
- `image: ghcr.io/mlflow/mlflow:latest` 는 MLflow 공식 이미지를 씁니다.
- `command` 는 컨테이너가 뜰 때 PostgreSQL/S3 드라이버를 설치한 뒤 MLflow server 를 띄웁니다. backend 는 `postgres` 서비스명으로 `mlflow` DB 에, artifact 는 `s3://mlflow` 에 연결합니다.
- `--allowed-hosts '*' --cors-allowed-origins '*'` 는 MLflow 3.x 의 localhost-only 보안 미들웨어를 풀어 줍니다. 이게 없으면 Docker 포트 매핑을 거친 (= loopback 이 아닌) 접속을 미들웨어가 연결째 끊어 host 의 `:5000` health·UI 접속이 막힙니다 (신뢰된 내부망·스터디 전제라 `*` 로 전체 허용; 더 좁히려면 호스트 목록을 나열).
- `env_file` 은 backend 계정 (`POSTGRES_USER`/`POSTGRES_PASSWORD`) 과 artifact 접속 키 (`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`), 그리고 MinIO endpoint (`MLFLOW_S3_ENDPOINT_URL`) 를 주입합니다.
- `networks: mlops` 로 같은 호스트의 `postgres` · `minio` 와 서비스명으로 통신합니다. 그 둘은 별도 compose 라 `depends_on` 을 걸 수 없으므로, `restart: unless-stopped` 로 준비될 때까지 자동 재시도합니다.

#### Execution Command

```powershell
# create the shared network mlops (ignore the error if it already exists), then start the container in the background.
docker network create mlops
docker compose up -d
```

- `docker network create mlops` — 컨테이너가 붙을 공유 외부 네트워크 `mlops` 를 만듭니다 (이미 있으면 에러는 무시되어 무해합니다).
- `docker compose up -d` — 컨테이너를 띄웁니다. 프로젝트명은 `name: mlflow` 로 파일에 굳혀져 있어 `-p` 가 필요 없습니다.
- `-d` — 백그라운드 (detached) 로 실행합니다.

`docker compose up` 으로 뜬 컨테이너 이름은 `mlflow-<Service Name>-<Replica Number>` 형식 (여기선 `mlflow-mlflow-1`) 이며, Replica Number 는 보통 `1` 이지만 `--scale <service>=3` 처럼 늘리면 `-2`·`-3` 이 추가됩니다. 실행 후 MLflow UI 는 **`http://<MLflow 호스트>:5000`** 에서 열립니다 (같은 컴퓨터에서는 `localhost`).

### Credentials

  접속 값은 `docker-compose.env` 한 파일에 모으고 컨테이너가 `env_file` 로 읽습니다. 실제 값이 담긴 `docker-compose.env` 는 `.gitignore` 로 git 추적에서 제외하고, 비밀값을 비운 `docker-compose.env_example` 만 커밋합니다.

  ```dotenv
  # docker-compose.env_example  (all values are CHANGE_ME placeholders — do not expose real values)
  POSTGRES_USER=CHANGE_ME             # backend (PostgreSQL mlflow DB) account — same value as PostgreSQL
  POSTGRES_PASSWORD=CHANGE_ME
  AWS_ACCESS_KEY_ID=CHANGE_ME         # artifact (MinIO/S3) key — same value as the MinIO root account (or an issued key)
  AWS_SECRET_ACCESS_KEY=CHANGE_ME
  MLFLOW_S3_ENDPOINT_URL=http://minio:9000
  ```

  - 명령 안에서 계정을 참조할 때는 `$$POSTGRES_USER` 처럼 `$$` 로 적습니다. `$$` 는 compose 가 `$` 로 바꿔 컨테이너 셸이 `env_file` 값으로 확장합니다.
  - 모든 `CHANGE_ME` 는 강한 값으로 교체하고, 실제 `docker-compose.env` 는 git 이 아니라 안전한 채널로 공유합니다.

## 3. Tracking

코드에서 tracking URI 를 MLflow server 로 지정한 뒤, run 안에서 파라미터·지표·산출물을 로깅합니다.

```python
import mlflow

mlflow.set_tracking_uri("http://<MLflow host>:5000")   # use localhost on the same PC
with mlflow.start_run(run_name="train"):
    mlflow.log_params({"lr": 0.01, "n_estimators": 150})   # → PostgreSQL (mlflow DB)
    mlflow.log_metric("train_acc", 0.97)                   # → PostgreSQL (mlflow DB)
    mlflow.log_artifacts("model/")                         # → MinIO (s3://mlflow/...)
```

- `with mlflow.start_run(...)` 의 `__enter__()` 는 새 run 을 만들어 **활성 run 으로 지정하고 `run_id` 를 발급** 합니다. 그래서 블록 안의 `log_params` · `log_metric` · `log_artifacts` 는 인자로 run 을 넘기지 않아도 모두 이 활성 run 에 자동으로 묶입니다.
- 블록을 벗어날 때 호출되는 `__exit__()` 는 **run 을 종료 처리** 합니다 — 정상 종료면 상태를 `FINISHED`, 블록 안에서 예외가 나면 `FAILED` 로 기록하고 활성 run 을 해제합니다. `with` 를 쓰면 예외가 나도 run 이 끝까지 열린 채 남지 않습니다.
- `log_params` / `log_metric` 으로 남긴 값은 backend (PostgreSQL `mlflow` DB) 에 저장되어 UI 에서 실험 간 비교에 쓰입니다.
- `log_artifacts` 로 올린 파일은 artifact store (MinIO `s3://mlflow/...`) 에 저장됩니다.
- 여러 run 의 산출물은 `run_id` 별 폴더로 자동 격리되므로 (`s3://mlflow/<experiment>/<run_id>/...`), 이름 충돌을 사람이 신경 쓸 필요가 없습니다.

### Without `with`

  `with` 는 편의일 뿐 필수는 아닙니다. run 객체를 직접 받아 쓰고 끝에 직접 닫아도 됩니다.

  ```python
  import mlflow

  mlflow.set_tracking_uri("http://<MLflow host>:5000")
  run = mlflow.start_run(run_name="train")   # start the run — receive the object directly.
  mlflow.log_params({"lr": 0.01})
  mlflow.log_metric("train_acc", 0.97)
  mlflow.end_run()                            # you must end it yourself.
  ```

  - `with` 를 안 쓰면 `start_run()` 으로 연 run 을 **`end_run()` 으로 직접 닫아야** 합니다. 안 닫으면 run 이 계속 활성 상태로 남아, 이후 `log_*` 가 엉뚱한 run 에 붙거나 같은 프로세스에서 새 run 을 열지 못합니다.
  - 예외가 나도 자동으로 `FAILED` 처리되지 않으므로, `try / finally` 로 `end_run()` 을 보장하는 게 안전합니다. 이 종료 보장을 자동으로 해주는 것이 `with` 입니다.

### Checking the run_id

  ```python
  with mlflow.start_run(run_name="train") as run:
      print(run.info.run_id)              # check via the run object from the block
      print(mlflow.active_run().info.run_id)   # or via the current active run
  ```

  - `start_run()` 이 돌려주는 run 객체의 **`run.info.run_id`** 로 얻습니다 (`with ... as run:` 또는 변수로 받음).
  - 객체를 안 받았으면 **`mlflow.active_run().info.run_id`** 로 현재 활성 run 의 id 를 조회합니다 (활성 run 이 없으면 `None`).
  - 이 `run_id` 가 §4 의 `runs:/<run_id>/model` 에 그대로 들어갑니다. MLflow UI 의 run 상세 페이지에서도 확인할 수 있습니다.

### Find, load & download runs

  Tracking 이 남긴 결과는 **`run_id` 가 열쇠** 입니다. 지표로 run 을 검색해 `run_id` 를 찾고, 그 run 의 모델을 `runs:/<run_id>/...` 로 로드하거나 내려받습니다.

  ```python
  import mlflow

  # (1) search — pick top runs by metric ("best" is by log_metric value).
  best5 = mlflow.search_runs(
      experiment_names=["mnist"],
      order_by=["metrics.val_acc DESC"],   # ranking metric
      max_results=5,
  )
  run_id = best5.loc[0, "run_id"]              # the best run's id

  # (2) load — load straight into memory without downloading, then infer.
  model = mlflow.pyfunc.load_model(f"runs:/{run_id}/model")
  pred = model.predict(X)

  # (3) download — fetch the artifacts to a local folder.
  path = mlflow.artifacts.download_artifacts(f"runs:/{run_id}/model")
  ```

  - 검색 (`search_runs`) 은 backend (Postgres) 의 지표를 읽으므로 Tracking 이 선행돼 있어야 합니다.
  - 같은 `runs:/<run_id>/model` URI 를 로드·다운로드·등록 (§4) 에 모두 씁니다 — 한 run 을 가리키는 하나의 키입니다.

## 4. Registration

§3 Tracking 에서 기록한 run 중 운영에 쓸 모델 (보통 지표가 가장 좋은 run) 을 골라 **이름 + 버전** 으로 레지스트리에 올리는 단계입니다. 모델 파일은 이미 Tracking 때 artifact store (MinIO) 에 저장돼 있으므로 여기서 다시 저장·복사하지 않고, 레지스트리는 그 모델을 가리키는 **이름·버전·Stage 메타데이터만 Backend store (PostgreSQL) 에 추가** 합니다. 즉 Registration 은 "모델을 새로 저장" 하는 게 아니라 이미 저장된 모델에 **관리용 이름·버전 식별자를 부여** 해 배포·서빙으로 넘길 수 있게 하는 단계입니다.

> Registry 는 개발 (실험) 단계의 필수가 아닙니다 — 실험·비교만 할 때는 Tracking 만으로 충분합니다 (§3 의 run 검색 참고). 모델을 **이름으로 버전 관리·공유** 하거나 **배포·서빙 (§5)** 으로 넘길 때 비로소 필요해지는, 개발과 배포 사이의 입구 단계입니다.

```python
import mlflow

# register the model from the training run into the registry as "name + version".
mlflow.register_model(model_uri="runs:/<run_id>/model", name="mnist-classifier")
# → versions stack up as mnist-classifier v1, v2, ...
```

`model_uri` 의 `runs:/<run_id>/model` 은 MLflow 전용 URI 규칙으로, 일반형은 **`runs:/<run_id>/<artifact_path>`** 입니다.

- **`runs:`** 는 "tracking 서버에 기록된 run 을 기준으로 아티팩트를 찾아라" 는 스킴 (scheme) 입니다. MinIO 의 실제 경로 (`s3://...`) 를 직접 쓰지 않아도, MLflow 가 `run_id` 로 그 run 의 artifact 위치를 조회해 실제 경로로 바꿔줍니다.
- **`<run_id>`** 는 Tracking 의 `start_run()` 이 발급한 그 run 식별자입니다.
- **`model`** 은 그 run 안에서 모델을 기록한 아티팩트 경로명입니다 (모델을 `model` 경로로 로깅했을 때). 결국 `s3://mlflow/<experiment>/<run_id>/model/` 을 가리킵니다.

### Find, load & download models

  레지스트리에 올린 모델은 **이름 + 버전 (또는 Stage)** 이 열쇠입니다. 무엇이 등록됐는지 조회하고, `models:/<name>/<버전 또는 Stage>` 로 로드하거나 내려받습니다.

  ```python
  import mlflow
  from mlflow.tracking import MlflowClient
  client = MlflowClient()

  # (1) search — query registered name, version, Stage, source run, and actual location.
  for m in client.search_registered_models():
      print(m.name)
  for v in client.search_model_versions("name='mnist-classifier'"):
      print(v.version, v.current_stage, v.run_id, v.source)
  prod = client.get_latest_versions("mnist-classifier", stages=["Production"])

  # (2) load — load directly by name + Stage, then infer.
  model = mlflow.pyfunc.load_model("models:/mnist-classifier/Production")
  pred = model.predict(X)

  # (3) download — fetch locally by version or Stage.
  path = mlflow.artifacts.download_artifacts("models:/mnist-classifier/3")
  ```

  - `current_stage` 는 `None` / `Staging` / `Production` / `Archived`, `source` 는 실제 모델 파일 위치 (MinIO 경로) 입니다. GUI 로는 MLflow UI 의 **Models** 탭에서 같은 정보를 봅니다.
  - `runs:/` 는 "그 run 이 남긴 원본 산출물" 을, `models:/` 는 "레지스트리에 이름·버전으로 등록된 모델" 을 가리킵니다 — 같은 파일을 가리키더라도 접근 키가 다릅니다.
  - MinIO 원본을 그대로 받으려면 `source` 경로 (`s3://mlflow/...`) 에서 `mc cp` 나 boto3 로 받아도 됩니다.

## 5. Deployment & Serving

> **배포 (Deploy)** 는 어떤 모델 버전을 운영 위치 (레지스트리 Stage) 에 올리는 행위이고, **서빙 (Serve)** 은 그 배포된 모델을 예측 요청을 받아 응답하는 **추론 API 로 구동** 하는 행위입니다.

### 1) Deploy

  ```python
  from mlflow.tracking import MlflowClient

  # promote the best version to the production stage (deploy).
  MlflowClient().transition_model_version_stage(
      name="mnist-classifier", version=3, stage="Production")
  ```

### 2) Serve

  ```powershell
  # run the registry's Production model as a REST API.
  mlflow models serve -m "models:/mnist-classifier/Production" -p 5001

  # prediction request — POST input to /invocations and it responds with predictions.
  curl -X POST http://localhost:5001/invocations `
    -H "Content-Type: application/json" `
    -d '{"inputs": [[0.1, 0.2]]}'
  ```
