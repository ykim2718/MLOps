# Prefect AI/ML Workflow Automation

<sub>rev. 92</sub>

Prefect 3 기반 AI 학습 파이프라인을 Docker 로 띄워 실행하는 환경입니다. 이 문서는 **전체 워크플로우의 인덱스 (개요)** 이고, 도구별 상세는 컴포넌트 문서로 잇습니다.

**Prefect 를 "실행 orchestrator" 로 두고**, 실험 추적·하이퍼파라미터 튜닝·데이터 보관/버전관리는 다른 도구가 맡아 **역할을 나눠 함께 씁니다**. "언제·무엇을·어떤 순서로 실행할지" 는 Prefect, "그 실행에서 나온 실험 기록·튜닝 결과·데이터/모델" 은 각 도구가 맡습니다.

---

## 1. Goals

여러 팀원이 한 server 를 공유해 AI 학습을 돌릴 때 **데이터·실험·결과를 잃지 않고 추적·재현·공유** 하는 것이 목표입니다.

1) **Lineage** — 데이터·코드·결과를 양방향으로 추적합니다.
2) **Persistence** — 모델·데이터를 catalog 에 등록해 보존하고 검색·선택 다운로드합니다 (메타 → PostgreSQL `catalog`, 실데이터 → MinIO).
3) **Versioning** — 코드·런타임·데이터 버전을 고정합니다 (데이터 버전은 불변 `minio_key` 경로에 담김 — [§7](#7-traceability)).
4) **Reproducibility** — 데이터 버전·하이퍼파라미터·시드를 고정해 동일 결과를 보장합니다.
5) **Reusability** — 워크플로우·피처를 다른 프로젝트에서 다시 씁니다.
6) **Monitoring** — Prefect / MLflow / MinIO 대시보드로 현황을 한눈에 봅니다.
7) **Scheduled Automation** — cron/interval 스케줄로 무인 실행합니다.
8) **Resource Management** — work pool·`--limit` 으로 공유 GPU/CPU 를 분배합니다.

---

## 2. Workflow Stack

스택 서비스는 도커로 실행합니다. 각 컴포넌트는 자기 폴더 (`Docker/<컴포넌트>/`) 의 `docker-compose.yml` 로 띄우고, 설치·사용법 상세는 아래 문서를 참고합니다.

| Component | Service | Role | Dashboard | Docs |
|-----------|---------|------|-----------|-----------|
| **Prefect** | `prefect_server` · `prefect_dispatcher` | 오케스트레이션 (파이프라인 실행/스케줄링). server 는 job 수집·UI, dispatcher (`prefect_dispatcher`) 는 job 마다 Pipeline Flow 컨테이너를 띄우며, 코드는 그 컨테이너가 실행합니다. | http://localhost:4200 | [prefect.md](../Docker/Prefect/prefect.md) |
| **MinIO** | `minio` | 대용량 데이터/모델/아티팩트 저장 (S3 호환). 버킷은 `datasets`·`models`·`mlflow` 입니다. | http://localhost:9001 | [minio.md](../Docker/MinIO/minio.md) |
| **Git** | git | 코드 배송·버전 고정. Pipeline Flow 컨테이너가 `git_repo`·`git_commit_hash` 을 shallow `git fetch --depth 1` + `git worktree` 로 펼쳐 실행하고, 공통 코드는 `git subtree` (nested repo) 로 심습니다. | GitHub | - |
| **MLflow** | `mlflow` | 실험 (params·metrics) 추적, 모델 레지스트리. backend=`postgres`, artifact=`minio`. | http://localhost:5000 | [mlflow.md](../Docker/MLflow/mlflow.md) |
| **PostgreSQL** | `postgres` · <br>`pgadmin` | 모든 도구의 메타데이터 DB. `prefect`·`mlflow`·`optuna`·`catalog` 4개 논리 DB 를 운영합니다. | http://localhost:5050 (pgAdmin)<br>localhost:5432 (DB) | [postgresql.md](../Docker/PostgreSQL/postgresql.md) |
| **Optuna** | python script | 하이퍼파라미터 튜닝 (trial 탐색). study storage 로 `postgres` 의 `optuna` DB 를 씁니다. | http://localhost:8080 (필요 시 기동) | [Appendix C](#appendix-c-optuna) |

> 이 스택은 한 호스트에 `postgres`·`minio`·`mlflow`·`prefect_server`·`prefect_dispatcher` (dispatcher) 를 모아 띄우고, dispatcher 가 job 마다 **Pipeline Flow 컨테이너** 를 일시적으로 띄우는 **Docker work pool** 구조입니다. 각 컨테이너는 받은 `git_repo`·`git_commit_hash` 을 shallow `git fetch` (`--depth 1`) + `git worktree` 로 펼쳐 실행하고 끝나면 스스로 파괴됩니다 (상세는 [prefect.md](../Docker/Prefect/prefect.md)).

---

## 3. ML Workflow DAG

```text
                             TRAINING LANE                                        TEST LANE
                             data/*.parquet                                     data/*.parquet
                                   │                                                  │
                                   ▼                                                  ▼
                           ┌────────────────┐                                 ┌────────────────┐
          prepare.json ───>│  train_prepare │                 prepare.json ──>│  test_prepare  │
                           └───────┬────────┘                                 └───────┬────────┘
                                   │ trainval_raw + val_start                         │ test_raw
                                   ▼                                                  ▼
                           ┌────────────────┐                                 ┌────────────────┐
                           │ train_featurize│── scaler.json + features.json ─>│ test_featurize │
                           └───────┬────────┘                                 └───────┬────────┘
                                   │ train/val.parquet                                │ test.parquet
                                   ▼                                                  ▼
                           ┌────────────────┐                                 ┌────────────────┐
       optuna.json ───────>│      train     │────────── model.txt ───────────>│      test      │
                           └───────┬────────┘                                 └───────┬────────┘
       parity_plot (train) <───────┤                                                  ├──> parity_plot (test)
   publish_artifacts (train) <─────┤ model + metrics                         metrics  └──> publish_artifacts (test)
                                   ▼                                         + pred.csv
                           ┌────────────────┐
                           │    validate    │
                           └───────┬────────┘
        parity_plot (validation) <─┤
   publish_artifacts (validation) <┤ val metrics
                                   ▼
        each stage emits both: parity_plot -> work/parity_<stage>.png ; publish_artifacts -> Prefect UI
```

---

## 4. Data

### Flow

  데이터가 실제로 오가는 두 지점의 endpoint · parameter 입니다 — **upload 은 host 의 `catalog.py` 가 `spec.json` 으로**, **download 은 컨테이너 안 `pipeline.py` 가 Prefect Secret 블록으로** 합니다.

  ```text
  UPLOAD — host: catalog.py upload spec.json --path <p>  (-b <block> [--pg-host/--minio-host localhost])
    input: spec.json { minio_key, bucket, ...free-form } + --path <p> (file/folder/glob)
    creds: Credentials block (-b <block>) — minio + postgresql_catalog sections
  ┌────────────┐                        ┌─────────────┐
  │ catalog.py │─ upload file ────────> │ MinIO :9000 │  → s3://<bucket>/<minio_key>/<files>
  └──────┬─────┘                        └─────────────┘
         │                              ┌──────────────────┐
         └─ register row ─────────────> │ PostgreSQL :5432 │  → datasets(minio_key, minio_path, n_files, size, doc)
                                        └──────────────────┘

  DOWNLOAD — in-container: pipeline.py
    input: pipeline( minio_bucket="datasets", minio_key, submitter, prefect_block )
    creds: Credentials.load(prefect_block).minio — Prefect Secret block (minio section)
  ┌─────────────┐                       ┌──────────────────┐
  │ pipeline.py │─ download file ─────> │ MinIO minio:9000 │  → bucket/key → ./data/<key name>
  └─────────────┘                       └──────────────────┘
  ```

### Upload

  `catalog.py upload <spec.json> --path <경로>` 는 **`--path` 가 가리키는 파일**을 MinIO 에 올리고 `catalog` 에 레코드를 등록합니다. spec 은 **자유 형식 문서**로, 예약 키(`minio_key`·`bucket`·`member`)만 해석하고 나머지는 그대로 `doc`(JSONB) 로 보존합니다 (임의 키·중첩 허용). host 에서는 `-b <block>` 로 자격증명 블록을 고르고 컨테이너용 endpoint 를 `--pg-host/--minio-host localhost` 로 덮어씁니다. spec.json 하나에 여러 spec 을 `{minio_key: spec, ...}` 로 담았다면 `--minio-key <key>` 로 그중 하나만 올립니다 (그 키가 minio_key 가 됨).

  ```python
  # catalog.py  upload(spec, path, block) — key steps (path from CLI --path; minio_key/bucket from spec)
  files = _resolve_sources(path)               # file | folder (recursive) | glob (dir/*.csv, **)
  ensure_schema()                              # create the datasets table if missing
  if get(minio_key):                           # minio_key is immutable -> stop if it exists
      raise FileExistsError("minio_key already exists")
  for fp, rel in files:                        # upload each file -> s3://<bucket>/<minio_key>/<rel>
      s3.upload_file(str(fp), bucket, prefix + rel)
  doc = {k: v for k, v in spec.items() if k != "member"}   # store the spec verbatim -> doc JSONB
  register(minio_key, minio_path, doc,         # register the catalog row (path + counts + doc)
           n_files=n_files, size_bytes=size_bytes)
  ```

  ```powershell
  python catalog.py spec spec.json                                                          # scaffold an empty spec
  python catalog.py upload spec.json --path ./data -b <block> --pg-host localhost --minio-host localhost
  python catalog.py upload specs.json --minio-key epc/v1 --path ./data -b <block> --minio-host localhost  # pick one
  ```

  올릴 대상은 **`--path` 하나**로 정하고, 파일 한 개·여러 개·와일드카드는 그 값으로 구별됩니다 (별도 목록 없음).

  | --path | files | MinIO key |
  |---|---|---|
  | single file `data/powerconsumption.csv` | 그 파일 1개 | `<minio_key>/powerconsumption.csv` |
  | folder `data` | 폴더 아래 전부 (재귀) | `<minio_key>/<상대경로>` |
  | wildcard `data/*.parquet` | 매치 파일 (비재귀) | `<minio_key>/<파일명>` |
  | recursive wildcard `data/**/*.parquet` | 하위까지 매치 | `<minio_key>/<상대경로>` |

  ```json
  {
    "minio_key": "epc/v1",
    "bucket": "datasets",
    "provider": "alice",
    "description": {
      "source": "kaggle",
      "rows": 52416
    }
  }
  ```

  > 예약 키(`minio_key`·`bucket`·`block`) 외의 필드(`provider`·`description{…}` 등)는 형식 제약 없이 `doc` 에 그대로 저장됩니다. `--path` 값만 바꿔 위 네 경우를 씁니다 (`--path data` · `--path data/*.parquet` · `--path data/**/*.parquet`). 매치가 0건이면 `FileNotFoundError` 로 중단하고, 같은 `minio_key` 가 이미 있으면 덮지 않고 중단합니다. spec.json 엔 `path` 를 넣지 않습니다 (필수 키는 `minio_key`).

### Download

  `catalog.py download <minio_key> [dest]` 은 catalog 에서 그 key 의 `minio_path` 를 찾아 그 아래 객체를 `dest` (기본 `./<minio_key>`) 로 내려받습니다.

  ```python
  # catalog.py  download(minio_key, dest, block) — key steps
  row = get(minio_key)                         # look up the catalog row for the key
  bucket, prefix = split(row["minio_path"])    # s3://bucket/<minio_key>/
  for obj in list_objects(bucket, prefix):     # every object under the prefix
      s3.download_file(bucket, obj["Key"], dest_path)   # -> dest/<relative key>
  ```

  ```powershell
  python catalog.py download <minio_key> ./out -b <block> --pg-host localhost --minio-host localhost
  ```

  > flow 실행 중의 자동 download 는 CLI 가 아니라 컨테이너 안 `pipeline.py` 가 Prefect Secret 블록으로 합니다 (위 [Flow](#flow) 다이어그램).

---

## 5. Run

### Script Structure

`pipeline.py` 가 `pipeline_flow` 컨테이너 안에서 run 마다 만드는 폴더 구조입니다.

```text
/tmp/run-<rand>/                 # per-run temp dir (base; removed after the run)
├─ repo/                         # git init + fetch --depth 1 origin <git_commit_hash> (shallow git db)
├─ script/                       # git worktree add --detach script <git_commit_hash> (clean worktree at the commit)
│  ├─ my_flow.py                 # payload (run: python my_flow.py --data_folder ../data ...)
│  ├─ train_prepare.py, train_featurize.py, train.py, validate.py
│  ├─ test_prepare.py, test_featurize.py, test.py
│  ├─ parity_plot.py
│  ├─ prepare.json, optuna.json
│  └─ commons/                   # common repo, nested via git subtree (Appendix. B)
└─ data/                         # MinIO download target (bucket/key → here)
   └─ *.parquet
```

### Server Connection

  trigger 에 앞서 client (dispatcher 또는 job 을 trigger 하는 노드) 가 **어느 Prefect server 에 연결할지** (`PREFECT_API_URL`) 를 정합니다. **최초 1회** 설정하면 이후 모든 client 명령이 이 server 를 향합니다. 설정 방법은 두 가지이며, **환경변수가 프로필보다 우선**합니다 (환경변수 > 프로필 > 기본값). 같은 컴퓨터면 `<Host IP>` 는 `localhost`.

  **1) 환경변수** — OS 환경변수로 지정. Windows 에서 영구 등록은 `setx` (또는 시스템 속성), 현재 셸에만 임시로 줄 땐 `$env:`.

  ```powershell
  setx PREFECT_API_URL "http://<Host IP>:4200/api"     # persistent (User scope) - applies to newly opened shells
  $env:PREFECT_API_URL = "http://<Host IP>:4200/api"   # temporary - current PowerShell only
  ```

  **2) prefect CLI** — Prefect 프로필 (`~/.prefect/profiles.toml`) 에 저장.

  ```powershell
  prefect config set PREFECT_API_URL="http://<Host IP>:4200/api"
  ```

  이 주소는 job 을 **trigger** 할 때 (`prefect deployment run ...`), **deployment 를 등록** 할 때, **Prefect Secret 블록을 등록/조회** 할 때 등 server 와 통신하는 client 작업 전반에 쓰입니다. 단 이 값은 **접속 주소일 뿐**이라, 그 URL 에 Prefect 서버가 실제로 떠 있어야 합니다.

### Trigger

  등록된 deployment 를 파라미터와 함께 실행(trigger)합니다 — 팀원·코드·데이터는 `git_repo`·`git_commit_hash`·`minio_key` 파라미터로, `prefect deployment ls` 명령으로 관리자가 등록한 deployment 를 고릅니다.

  ```powershell
  # Trigger — pick the tier by deployment; heavy -> high, light -> low (params otherwise identical).
  prefect deployment run "pipeline/pipelineflow-high" -p submitter=alice -p prefect_block=yrocket -p git_repo=https://github.com/<member>/<repo>.git -p git_commit_hash=a1b2c3d -p minio_key=SYDNEY/001.parquet
  prefect deployment run "pipeline/pipelineflow-low"  -p submitter=alice -p prefect_block=yrocket -p git_repo=https://github.com/<member>/<repo>.git -p git_commit_hash=a1b2c3d -p minio_key=SYDNEY/001.parquet
  ```
  ```python
  from prefect.deployments import run_deployment

  params = {
      "submitter": "alice",
      "prefect_block": "yrocket",
      "git_repo": "https://github.com/<member>/<repo>.git",
      "git_commit_hash": "a1b2c3d",
      "minio_key": "SYDNEY/001.parquet",
  }
  run_deployment("pipeline/pipelineflow-high", parameters=params)   # or "pipeline/pipelineflow-low" for the low tier
  ```

  > 팀원마다 자기 repo·커밋을 넘기면 같은 이미지로 각자 다른 코드를 동시에 돌릴 수 있습니다 (컨테이너가 각자 사설 worktree 에 펼침). 무거운 job 은 `pipeline/pipelineflow-high`, 가벼운 job 은 `pipeline/pipelineflow-low` 로 보내 성능 등급을 고릅니다.

---

## 6. my_flow.py

  Prefect orchestrator (`pipeline.py`) 가 `script/` 와 `data/` 를 미리 받아 두고 실행 정보 (`--submitter`) 와 데이터 경로 (`--data_folder`) 를 CLI 인자로 넘기므로, payload 는 `argparse` 로 받아 씁니다. 서버·MLflow 없이 로컬에서 배선만 빠르게 확인할 땐 `--run-on local` 로 ephemeral 실행합니다. 아래는 각 단계 함수·설정 변수가 실제 파일 (`train_prepare.py` … `optuna.json`) 을 대신하는 **dry run** 으로, 실 ML 없이 workflow 배선만 검증합니다 (실제 파일은 [example/dry_run/my_flow.py](example/dry_run/my_flow.py)).

  ```python
  """example/dry_run/my_flow.py — git-delivered ML payload, Prefect dry run.

  Validates workflow wiring only: each @task and config variable stands in for the
  real example/ file (train_prepare.py … optuna.json). No real ML — every stage just
  records that it ran, while train_prepare also counts the files under --data_folder.

  Run by pipeline.py (orchestrator, prefect.md §4.3):
      python my_flow.py --submitter <m> --data_folder <dir>

  Local debugging — run ephemerally with no Prefect server (MLflow tracking also skipped):
      python my_flow.py --run-on local --data_folder <dir>
  """
  __version__ = "0.0.20"

  import argparse
  import os
  from pathlib import Path
  from typing import Any, Dict, Literal

  import mlflow
  from prefect import flow, get_run_logger, task
  from prefect.artifacts import create_markdown_artifact

  State = Dict[str, str]                            # per-stage status map (stage -> "ok") threaded through the flow
  Stages = Literal["", "train_prepare", "train_featurize", "train", "validate",
                   "test_prepare", "test_featurize", "test"]  # pipeline stage names

  prepare_json: Dict[str, Any] = {
      "__version__": "0.0.0",
      "train": {
          "split": [0.8, 0.2]
      },
      "validate": {
      },
      "test": {
      }
  }  # stand-in for prepare.json (free-form / nested)
  optuna_json: Dict[str, Any] = {
      "__version__": "0.0.0",
      "environment": {
      },
      "search_space": {
      }
  }  # stand-in for optuna.json

  STAGES = ("train_prepare", "train_featurize", "train", "validate",
            "test_prepare", "test_featurize", "test")


  @task(task_run_name="train_prepare", retries=2, retry_delay_seconds=5)
  def train_prepare(state: State, data_folder: str, prepare_json: Dict[str, Any]) -> State:
      log = get_run_logger()
      data = Path(data_folder)
      n_files = sum(1 for p in data.rglob("*") if p.is_file()) if data.exists() else 0
      log.info(f"train_prepare: {n_files} files under {data_folder}")   # Prefect run log
      log.info(f"train_prepare: prepare_json = {prepare_json}")
      mlflow.log_metric("n_data_files", n_files)                        # MLflow (metric -> tracking store)
      mlflow.log_param("train_prepare.prepare_json", prepare_json)      # MLflow (config visible in the run)
      return {**state, "train_prepare": "ok"}


  @task(task_run_name="train_featurize", retries=2, retry_delay_seconds=5)
  def train_featurize(state: State) -> State:
      return {**state, "train_featurize": "ok"}


  def _optuna_demo() -> None:
      """Tiny Optuna study (dry run): minimize (x-2)^2 over 5 trials. Uses the shared postgres study
      via POSTGRESQL_OPTUNA_DSN (bridged by pipeline.py); in-memory when that env is absent (e.g.
      --run-on local). Best-effort - skipped if optuna isn't installed."""
      log = get_run_logger()
      try:
          import optuna
      except Exception as e:                                           # optuna not in the image -> skip
          log.warning(f"optuna skipped (not installed): {e}")
          return
      optuna.logging.set_verbosity(optuna.logging.WARNING)
      storage = os.environ.get("POSTGRESQL_OPTUNA_DSN") or None        # shared postgres study, else in-memory
      study = optuna.create_study(direction="minimize", storage=storage,
                                  study_name="dry_run", load_if_exists=bool(storage))
      study.optimize(lambda t: (t.suggest_float("x", -10, 10) - 2) ** 2, n_trials=5)
      log.info(f"optuna best: x={study.best_params['x']:.3f} value={study.best_value:.4f} "
               f"(storage={'postgres' if storage else 'in-memory'})")
      mlflow.log_metric("optuna_best_value", float(study.best_value))  # active MLflow run set in the flow
      mlflow.log_param("optuna_best_x", float(study.best_params["x"]))


  @task(task_run_name="train", retries=2, retry_delay_seconds=5)
  def train(state: State, optuna_json: Dict[str, Any]) -> State:
      log = get_run_logger()
      log.info(f"train: optuna_json = {optuna_json}")                  # Prefect run log
      mlflow.log_param("train.optuna_json", optuna_json)               # MLflow (config visible in the run)
      _optuna_demo()                                                   # tiny Optuna HPO demo (best-effort)
      return {**state, "train": "ok"}


  @task(task_run_name="validate", retries=2, retry_delay_seconds=5)
  def validate(state: State) -> State:
      return {**state, "validate": "ok"}


  @task(task_run_name="test_prepare", retries=2, retry_delay_seconds=5)
  def test_prepare(state: State, prepare_json: Dict[str, Any]) -> State:
      log = get_run_logger()
      log.info(f"test_prepare: prepare_json = {prepare_json}")         # Prefect run log
      mlflow.log_param("test_prepare.prepare_json", prepare_json)      # MLflow (config visible in the run)
      return {**state, "test_prepare": "ok"}


  @task(task_run_name="test_featurize", retries=2, retry_delay_seconds=5)
  def test_featurize(state: State) -> State:
      return {**state, "test_featurize": "ok"}


  @task(task_run_name="test", retries=2, retry_delay_seconds=5)
  def test(state: State) -> State:
      return {**state, "test": "ok"}


  # report tasks — submitted concurrently after train/validate/test; MLflow is logged in the flow
  # (main thread) since a .submit() task runs in another thread where the active MLflow run is not set.
  @task(task_run_name="parity_plot-{stage}", retries=2, retry_delay_seconds=5)
  def parity_plot(state: State, stage: Stages = "") -> str:
      get_run_logger().info(f"parity_plot after {stage} ({len(state)} stages so far)")
      return f"parity_plot.{stage}"


  @task(task_run_name="publish_artifacts-{stage}", retries=2, retry_delay_seconds=5)
  def publish_artifacts(state: State, stage: Stages = "") -> str:
      log = get_run_logger()
      log.info(f"publish_artifacts: {stage} result = {state}")         # Prefect run log
      try:
          create_markdown_artifact(key=f"result-{stage}",
                                   markdown=f"# {stage} result\n\n`{state}`")   # Prefect UI artifact
      except Exception as e:                                           # no Prefect API backend -> skip
          log.warning(f"artifact skipped: {e}")
      return f"publish_artifacts.{stage}"


  @flow(name="my_flow", flow_run_name="{submitter}", log_prints=True)
  def my_flow(*, submitter: str = "local", data_folder: str = "./data") -> State:
      log = get_run_logger()
      log.info(f"dry run: submitter={submitter} "
               f"data={data_folder} prepare={prepare_json} optuna={optuna_json}")

      reports = []
      # point MLflow at the tracking server, else it logs to a local ./mlruns and never reaches
      # the dashboard. container: http://mlflow:5000; host: set MLFLOW_TRACKING_URI. local -> no-op shim.
      mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"))
      mlflow.set_experiment("dry_run")                 # named experiment (else lands in "Default")
      with mlflow.start_run(run_name=f"{submitter}"):  # -> experiment "dry_run" on the MLflow server
          s = train_prepare({}, data_folder, prepare_json)           # train branch
          s = train_featurize(s)
          s = train(s, optuna_json)
          reports += [parity_plot.submit(s, "train"), publish_artifacts.submit(s, "train")]
          s = validate(s)
          reports += [parity_plot.submit(s, "validate"), publish_artifacts.submit(s, "validate")]
          s = test_prepare(s, prepare_json)                          # test branch
          s = test_featurize(s)
          s = test(s)
          reports += [parity_plot.submit(s, "test"), publish_artifacts.submit(s, "test")]

          published = sorted(f.result() for f in reports)            # resolve report futures (raise on failure)
          for key in published:
              mlflow.log_param(key, "ok")                            # MLflow: parity_plot.* / publish_artifacts.*

      ran = sorted(s)
      assert set(ran) == set(STAGES), f"missing stages: {set(STAGES) - set(ran)}"
      log.info(f"dry run ok: stages={ran} reports={published}")
      return s


  def parse_args() -> argparse.Namespace:
      p = argparse.ArgumentParser()
      p.add_argument("--submitter", default="local")
      p.add_argument("--data_folder", default="./data")
      # optional (default server) so pipeline.py's pool call (no --run-on) is unaffected;
      # pass --run-on local for standalone debugging with no Prefect server.
      p.add_argument("--run-on", choices=["local", "server"], default="server",
                     help="local: run ephemerally with no server (local debugging); "
                          "server: record the run on the Prefect server (PREFECT_API_URL)")
      return p.parse_args()


  class _NoOpMLflow:
      """No-op MLflow stand-in for --run-on local: skips all tracking calls.
      start_run() returns a null context; log_metric / log_param / ... become no-ops."""
      def start_run(self, *args, **kwargs):
          from contextlib import nullcontext
          return nullcontext()

      def __getattr__(self, _name):
          return lambda *args, **kwargs: None


  if __name__ == "__main__":
      a = parse_args()
      if a.run_on == "local":                                 # local debug: no Prefect server, no MLflow
          import logging
          logging.getLogger("prefect._internal.concurrency").setLevel(logging.CRITICAL)  # mute ephemeral EventsWorker noise
          mlflow = _NoOpMLflow()                              # rebind module global -> every mlflow.* call is a no-op
          from prefect.settings import PREFECT_API_URL, temporary_settings
          with temporary_settings({PREFECT_API_URL: ""}):     # disable PREFECT_API_URL -> ephemeral run
              my_flow(submitter=a.submitter, data_folder=a.data_folder)
      else:                                                   # use the configured Prefect + MLflow servers
          my_flow(submitter=a.submitter, data_folder=a.data_folder)
  ```

---

## 7. Traceability

여러 팀원이 결과를 잃지 않고 추적·재현·재사용하도록, 한 실행의 **입력·관계·산출물** 을 파라미터·태그·장부로 못 박습니다. Prefect 는 orchestrator 일 뿐 버전을 보관하지 않으므로, 아래 다섯 축을 명시적으로 고정합니다.

### Lineage

데이터·코드·결과를 양방향으로 추적합니다. `catalog` 레코드 (`minio_key`·`doc`·`prefect_run_id`) 와 MLflow run 태그 (입력 `input_minio_key`, git 커밋 SHA) 를 **서로 참조** 해 두면 세 축이 한 실행에서 묶입니다.

```
data (minio_key) ──used by──> code (Prefect run @ git SHA) ──produces──> result (MLflow run / model)
   ▲                                                                          │
   └──────────────────────  trace back (result → code → data)  <─────────────┘
```

- **Forward** — 어떤 데이터를 어떤 커밋의 flow run 이 썼고, 그 run 에서 나온 MLflow run·모델이 무엇인지 따라갑니다.
- **Backward** — 운영 모델의 MLflow run 태그 (`input_minio_key`·git SHA) → `catalog.find(...)` · `git checkout <SHA>` 로 원본 데이터·코드까지 거슬러 올라갑니다.
- **Model ↔ code** — MLflow 는 git repo 안에서 run 을 돌리면 커밋 SHA 를 자동 태그하므로 "이 모델이 어떤 코드로 학습됐나" 가 남습니다.
- **History** — `python catalog.py list`·`find <minio_key>` (데이터·메타·등록 시각, [Appendix A](#appendix-a-catalogpy-cli)) · `git log <git_commit_hash>` (코드 이력) · MLflow UI (run·파라미터·메트릭·모델 단계) 로 각 축의 이력을 봅니다.

### Persistence

모델·데이터를 catalog 에 등록해 보존하고 검색·선택 다운로드합니다 — 메타는 PostgreSQL `catalog` 장부에, 실데이터·아티팩트는 MinIO 에 남습니다. 컨테이너는 run 마다 파괴돼도 결과는 이 두 저장소에 남아 나중에 `minio_key` 로 되찾습니다.

### Versioning

코드·런타임·데이터 버전을 고정합니다.

| Axis | Pinned by | Meaning |
|------|-----------|---------|
| **Code** | `git_repo`·`git_commit_hash` (shallow `git fetch --depth 1` + `git worktree add <commit>`) | 어떤 repo·커밋으로 실행할지 — 커밋 고정 시 완전 재현 |
| **Runtime** | Pipeline Flow image tag (`pipeline-flow:<tag>`) | 라이브러리 + orchestrator 버전 |
| **Data** | `minio_key` (catalog `datasets`, 불변 key) | 어떤 데이터를 쓸지 — 버전이 key 경로에 담긴 불변 경로 |

- **Code** — trigger 시 `git_commit_hash` (SHA) 를 넘기면 컨테이너가 그 커밋을 `git worktree` 로 펼쳐 실행하므로 항상 같은 코드가 돕니다. 브랜치명은 "그 시점 최신" 이라 재현이 안 되니, 재현엔 SHA 를 씁니다.
- **Runtime** — 이미지 태그가 라이브러리 + orchestrator 를 고정합니다. 라이브러리를 바꾸면 새 태그로 빌드합니다 (`latest` 는 가변이라 재현엔 명시 태그).
- **Data** — `minio_key` 는 불변이라 같은 key = 같은 바이트입니다. catalog 가 그 key ↔ 메타(`doc`)·등록 시각을 장부로 보관합니다.

### Reproducibility

데이터 버전·하이퍼파라미터·시드를 고정해 동일 결과를 보장합니다. 과거 실행을 되살리려면 그때의 **세 좌표** (코드 SHA · 런타임 태그 · 데이터 key) 를 그대로 넘겨 다시 trigger 합니다.

```powershell
# same SHA/key as before; if the runtime tag changed, target the deployment registered under that tag.
prefect deployment run "pipeline/pipelineflow-high" -p git_repo=<repo> -p git_commit_hash=<recorded SHA> -p minio_key=<recorded key>
```

- 세 축이 같으면 **같은 입력 → 같은 결과** 가 보장됩니다. 브랜치명·`latest` 태그·가변 key 를 쓰면 재현이 깨지니, 재현엔 항상 고정 좌표 (SHA · 명시 태그 · 불변 key) 를 씁니다.

> **Private repo** — 런타임 `git fetch` 대상이 private 이면 토큰이 필요합니다. Prefect Secret 으로 토큰을 받아 인증 URL (`git_repo`) 로 fetch 하거나 git credential helper 를 설정합니다. public repo 면 그대로 됩니다.

### Reusability

워크플로우·피처를 다른 프로젝트에서 다시 씁니다. 공통 단계·유틸·catalog 접근 계층을 common repo (nested repository, [Appendix B](#appendix-b-common-repo-nested-repository)) 로 묶어 여러 팀원 repo 가 `git subtree` 로 함께 심어 씁니다.

---

## 8. Inference

학습이 끝나 MLflow 레지스트리에 `Production` 으로 승격된 모델을 불러와 추론하는 단계입니다. 여기서도 **Prefect 는 실행·재시도·로깅을, MLflow 는 모델의 실제 다운로드·로드를** 맡아 역할을 나눕니다.

```python
from prefect import task, flow
import mlflow

@task(retries=3)                       # ← Prefect's role: execution, retries, logging
def load_prod_model():
    return mlflow.pyfunc.load_model(   # ← MLflow's role: actual download/load
        "models:/mnist-classifier/Production")

@flow
def inference_flow():
    model = load_prod_model()
    ...
```

- **Prefect (`@task(retries=3)` / `@flow`)** — 언제·어떤 순서로 실행할지, 실패 시 재시도·로깅을 맡습니다.
- **MLflow (`mlflow.pyfunc.load_model`)** — `models:/mnist-classifier/Production` 으로 레지스트리에서 실제 모델을 내려받아 로드합니다.

---

## Appendix A. catalog.py CLI

`catalog.py` 는 데이터 카탈로그 (PostgreSQL `catalog` DB 장부) 와 MinIO 객체를 함께 다루는 접근 계층이자 CLI 입니다. flow 에서 라이브러리로 import 해 쓰거나 ([§4 Data](#4-data)), 아래 CLI 로 직접 둘러보기·업로드·다운로드·삭제합니다. **catalog.py 는 컨테이너 밖에서 실행** 되므로 자격증명은 Prefect 프로필 ([§5 Server Connection](#server-connection) 의 `prefect config set PREFECT_API_URL=...`) 로 연결된 **Prefect Secret 블록** 에서 가져옵니다 (멤버별 `Credentials` 블록은 아래 [Credentials](#credentials-prefect-block), 없으면 default). 프로세스 환경변수나 `docker-compose.env` 파일은 쓰지 않습니다 (그 파일은 컨테이너 스택용이라 host 의 catalog.py 가 찾을 수 없음). 업로드·다운로드·삭제는 boto3 로 처리하므로 `mc` 가 필요 없습니다.

**Target** 은 명령이 접속하는 곳입니다 (**PostgreSQL** = catalog DB 장부, **MinIO** = 객체 저장소). 각 명령은 실행 시작 시 접속 대상 (PostgreSQL DSN — 비밀번호 가림 · MinIO endpoint) 과 **자격증명 출처** (`[creds: prefect-block (block=…) | default (localhost)]`) 를 stderr 로 먼저 출력해 "어디로 접속해 도는지, 자격증명을 어디서 가져왔는지" 를 알립니다. `-b <block>` 로 블록을 주면 `prefect-block (block=…)`, `-b` 없이 돌리면 `default (localhost)` 로 표시됩니다. `-b` 를 **줬는데** credentials.py import 실패나 블록 로드 실패(서버 미연결·블록 없음)면 조용히 default 로 안 가고 오류로 즉시 중단합니다. `--version`/`-V` 로 버전을 확인합니다.

| Command | Target | Purpose |
|---|---|---|
| `list` | PostgreSQL | 등록된 데이터셋 목록 (minio_key 요약) |
| `find <minio_key> [key=value ...]` | PostgreSQL | minio_key prefix + doc 최상위 키=값 검색 |
| `spec [out.json]` | (local) | 빈 upload spec.json 뼈대 생성 (채워서 `upload` 에 사용; 기본 `spec.json`) |
| `upload <spec.json> --path P [--minio-key key] [--register-only]` | MinIO + PostgreSQL | `--path` 의 파일/폴더/glob 을 MinIO 적재 + catalog 등록 (메타는 spec; `--minio-key` 면 spec 이 `{key: spec, ...}` 중 하나). `--register-only` 는 업로드를 건너뛰고 MinIO 에 이미 있는 그 key 의 객체로 catalog 행만 등록 (`--path` 불필요; 업로드가 MinIO 는 됐는데 등록 전에 끊긴 경우 복구용) |
| `download <minio_key> [dest]` | PostgreSQL + MinIO | 그 key 의 객체 다운로드 (dest 기본 `./<minio_key>`) |
| `remove <minio_key> [--yes]` | MinIO + PostgreSQL | 그 key 의 MinIO 객체 + catalog 행 영구 삭제 |
| `objects [minio_key]` | MinIO | MinIO 에 실제로 있는 객체 나열 (catalog 무관; minio_key prefix 로 한정) |

MinIO·PostgreSQL 에 접속하는 명령에는 `-b <block>` (자격증명 블록 선택) 와 `--pg-host`/`--minio-host` (endpoint host 만 덮어쓰기, creds 불변) 를 붙일 수 있습니다 — 컨테이너용 블록을 host 에서 쓸 때 유용합니다 (`spec` 은 로컬 파일 생성이라 해당 없음). 자세한 것은 아래 [Credentials](#credentials-prefect-block).

catalog.py 는 자격증명 블록 클래스 (`credentials.py`, `../Docker/Prefect`) 를 import 하므로, host 에서 실행 전 그 폴더를 `PYTHONPATH` 에 1회 넣습니다 (경로는 repo 위치에 맞춰 `Resolve-Path` 로 풉니다).

```powershell
# catalog_cli.ps1
# Add-PyPath: prepend a .py file's folder to PYTHONPATH (dedup, keep existing) so its module can be imported.
function Add-PyPath([string]$file) {
    $dir = Split-Path (Resolve-Path $file) -Parent
    $rest = $env:PYTHONPATH -split ';' | Where-Object { $_ -and $_ -ne $dir }
    $env:PYTHONPATH = (@($dir) + $rest) -join ';'
}
Add-PyPath ..\Docker\Prefect\credentials.py   # catalog.py imports credentials.py from this folder
$env:PYTHONPATH

python catalog.py list                              # registered datasets (minio_key summary)
python catalog.py find epc fab=fab2                 # search by minio_key prefix + doc key=value
python catalog.py spec spec.json                    # write an empty upload spec template
python catalog.py upload spec.json --path ./out     # upload files at --path + register (JSON spec)
python catalog.py upload specs.json --minio-key epc/v1 --path ./out  # pick one from a {key: spec} file
python catalog.py upload spec.json --minio-key epc/v1 --register-only  # register objects already in MinIO (no upload)
python catalog.py download epc/v1 ./out             # dest omitted -> ./<minio_key>
python catalog.py remove epc/v1 --yes               # delete objects + catalog row for the key
python catalog.py objects epc                       # raw MinIO objects (not the catalog)
```

`upload` 의 `spec.json` 예시입니다. 예약 키(`minio_key`·`bucket`·`block`) 외의 필드는 형식 제약 없이 `doc`(JSONB) 로 그대로 저장됩니다 (임의 키·중첩 허용 — 아래 `description` 처럼 객체도 가능).

```json
{"minio_key": "epc/v1", "bucket": "datasets",
 "provider": "zoo",
 "description": {"fab": "fab2", "chamber": "CH3", "rows": 52416}}
```

> `minio_key` 는 불변 (immutable) 입니다 — 같은 key 가 MinIO 나 catalog 에 이미 있으면 `upload` 는 덮어쓰지 않고 중단합니다 (새 key 로 다시 시도). 업로드가 MinIO 는 됐는데 catalog 등록 전에 끊겼다면 `--register-only` 로 재업로드 없이 catalog 행만 등록해 복구합니다. `remove` 는 MinIO 객체 (모든 버전·삭제마커) 와 catalog 행을 영구 삭제하므로 `--yes` 없이는 `DELETE` 입력을 요구합니다.

host 에서 컨테이너용 블록 (endpoint 가 `postgres`·`minio` 서비스명) 으로 접속할 때는 `-b <block>` 로 블록을 고르고 `--pg-host`/`--minio-host` 로 host 만 `localhost` 로 바꿉니다.

```powershell
python catalog.py upload spec.json --path ./out -b <block> --pg-host localhost --minio-host localhost
python catalog.py remove <minio_key> -b <block> --pg-host localhost --minio-host localhost
```

### Credentials (Prefect block)

  catalog.py 가 읽는 자격증명은 **팀원마다 하나인 `Credentials` 블록** (블록 이름 = 팀원 이름, 소문자·숫자·대시) 에 담겨 있고, 관리자가 `credentials.py` 로 1회 등록합니다 (`python credentials.py --json-path <member>.json --block-name <member>` — [prefect.md](../Docker/Prefect/prefect.md) §5 Credentials). 한 블록 안에 네 섹션 (nested dict, `SecretDict` 로 가림; `mlflow` 는 optional) 이 들어 있습니다.

  | Section | Fields | Target |
  |---|---|---|
  | `minio` | `endpoint` · `access_key` · `secret_key` | MinIO |
  | `postgresql_catalog` | `endpoint` · `username` · `password` · `database` | PostgreSQL (`catalog` DB) |
  | `postgresql_optuna` | `endpoint` · `username` · `password` · `database` | PostgreSQL (`optuna` DB, flow·Optuna 용) |
  | `mlflow` (optional) | `endpoint` | MLflow (tracking URI; flow 로깅용) |

  - **`-b <block>`** 가 어느 팀원 블록을 읽을지 정합니다. catalog.py 는 그중 `minio` + `postgresql_catalog` 두 섹션만 씁니다 (`postgresql_optuna`·`mlflow` 는 flow 용 — pipeline.py 가 `mlflow` endpoint 를 payload 에 `MLFLOW_TRACKING_URI` 로 넘김). `-b` 를 **안 주면** default (localhost) 로 돌고 배너에 `[creds: default (localhost)]`, 주면 `[creds: prefect-block (block=…)]` 로 출처가 표시됩니다. `-b` 를 **줬는데** credentials.py import 실패나 블록 로드 실패(서버 미연결·블록 없음)면 조용히 default 로 안 떨어지고 오류로 즉시 중단합니다 (silent-default 방지 — `credentials.py` 는 catalog.py 옆이나 `PYTHONPATH` 에 있어야 함).
  - **`--pg-host` / `--minio-host`** 는 블록 endpoint 의 host 만 덮어씁니다 (creds·port 불변). 컨테이너용 블록 (endpoint 가 `postgres`·`minio` 서비스명) 을 host 에서 쓸 때 `--pg-host localhost --minio-host localhost` 로 붙입니다.
  - `PREFECT_API_URL` (Prefect 프로필) 은 이 블록을 받기 위한 **접속점** 일 뿐 catalog 데이터가 아닙니다. 프로세스 환경변수·`docker-compose.env` 는 쓰지 않습니다.

  > **권한 차단은 MinIO policy 로** — 팀원 블록의 `minio` 키가 곧 그 팀원의 MinIO 신원입니다. 진짜 사용자별 차단은 **그 키가 MinIO 에서 버킷 policy 로 제한** 되어 있어야 실제로 막히고, 그렇지 않으면 격리는 경로에 `{member}` 등 고유 키를 넣어 나누는 규칙 (`s3://.../{member}/...`) 에 의존합니다. Prefect 블록 자체엔 사용자별 접근제어가 없습니다.

---

## Appendix B. Common Repo (Nested Repository)

공통 코드 (공통 단계·유틸·catalog 접근 계층 등) 를 여러 팀원 repo 에서 함께 쓰려면 공통 repo 를 각 repo 안에 **nested repository** 로 만들어 심습니다. `git subtree` 로 공통 repo 를 하위 경로 (`<path>`) 에 합쳐 한 커밋 트리로 관리하므로, runtime 의 shallow `git fetch` + `git worktree` 가 공통 코드까지 한 번에 펼칩니다 (submodule 과 달리 별도 init/fetch 가 없습니다).

```powershell
# Creation — add the common repo under <path> as a squashed subtree (once).
git subtree add  --prefix=<path> <url> <branch> --squash

# Update — pull the latest common repo into <path>.
git subtree pull --prefix=<path> <url> <branch> --squash
```

---

## Appendix C. Optuna

Optuna 는 하이퍼파라미터를 trial 단위로 탐색하는 튜닝 도구입니다. `objective` (목적 함수) 를 매 trial 마다 호출해 하이퍼파라미터를 제안받고 점수를 반환받으며, 그 점수로 다음 trial 을 더 똑똑하게 고릅니다. 이 스택에는 Optuna 전용 도커 서비스가 없고, **라이브러리로 코드에 포함** 되어 study 기록만 PostgreSQL 의 `optuna` DB 에 저장합니다.

```python
import os, optuna

study = optuna.create_study(
    study_name="mnist-resnet50",
    storage=os.environ["POSTGRESQL_OPTUNA_DSN"],   # shared storage (PostgreSQL optuna DB)
    direction="maximize",
    load_if_exists=True,        # resume if it already exists
)
study.optimize(objective, n_trials=20)
```

- **공유 DB (기본)** — `POSTGRESQL_OPTUNA_DSN` (`postgresql://.../optuna`). 여러 worker·여러 PC 가 하나의 study 를 분산 병렬로 탐색하거나 기록을 중앙에 보존할 때 유리합니다.
- **로컬 파일 (대안)** — `sqlite:///optuna.db`. 단일 PC 에서 가볍게 쓸 때 적합합니다.
- Optuna 가 DB 에 넣는 것은 trial 메타데이터 (파라미터·점수) 뿐이고, 모델 가중치 같은 실제 산출물은 MinIO 에 저장합니다.
- **Dashboard** — 상시 서비스가 아니라 필요할 때 띄웁니다: `optuna-dashboard postgresql://<user>:<pw>@localhost:5432/optuna` → `http://localhost:8080`. 위 `optuna` DB 의 trial 기록 (파라미터·점수·수렴 곡선) 을 브라우저로 봅니다.
