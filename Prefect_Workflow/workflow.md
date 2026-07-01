# AI/ML Workflow Automation

<sub>rev. 37</sub>

Prefect 3 기반 AI 학습 파이프라인을 Docker 로 띄워 실행하는 환경입니다. 이 문서는 **전체 워크플로우의 인덱스 (개요)** 이고, 도구별 상세는 컴포넌트 문서로 잇습니다.

**Prefect 를 "실행 orchestrator" 로 두고**, 실험 추적·하이퍼파라미터 튜닝·데이터 보관/버전관리는 다른 도구가 맡아 **역할을 나눠 함께 씁니다**. "언제·무엇을·어떤 순서로 실행할지" 는 Prefect, "그 실행에서 나온 실험 기록·튜닝 결과·데이터/모델" 은 각 도구가 맡습니다.

---

## 1. Goals

여러 팀원이 한 server 를 공유해 AI 학습을 돌릴 때 **데이터·실험·결과를 잃지 않고 추적·재현·공유** 하는 것이 목표입니다.

1) **Lineage** — 데이터·코드·결과를 양방향으로 추적합니다.
2) **Reproducibility** — 데이터 버전·하이퍼파라미터·시드를 고정해 동일 결과를 보장합니다.
3) **Persistence & Versioning** — 모델·데이터를 catalog 로 버전 보존하고 검색·선택 다운로드합니다 (메타 → PostgreSQL `catalog`, 실데이터 → MinIO).
4) **Monitoring** — Prefect / MLflow / MinIO 대시보드로 현황을 한눈에 봅니다.
5) **Reusability** — 워크플로우·피처를 다른 프로젝트에서 다시 씁니다.
6) **Scheduled Automation** — cron/interval 스케줄로 무인 실행합니다.
7) **Resource Management** — work pool·`--limit` 으로 공유 GPU/CPU 를 분배합니다.

---

## 2. Stack

스택 서비스는 도커로 실행합니다. 각 컴포넌트는 자기 폴더 (`Docker/<컴포넌트>/`) 의 `docker-compose.yml` 로 띄우고, 설치·사용법 상세는 아래 문서를 참고합니다.

| Component | Service | Role | Dashboard | Docs |
|-----------|---------|------|-----------|-----------|
| **Prefect** | `prefect_server` · `prefect_dispatcher` | 오케스트레이션 (파이프라인 실행/스케줄링). server 는 job 수집·UI, dispatcher (`prefect_dispatcher`) 는 job 마다 Pipeline Flow 컨테이너를 띄우며, 코드는 그 컨테이너가 실행합니다. | http://localhost:4200 | [prefect.md](../Docker/Prefect/prefect.md) |
| **MinIO** | `minio` | 대용량 데이터/모델/아티팩트 저장 (S3 호환). 버킷은 `datasets`·`models`·`mlflow` 입니다. | http://localhost:9001 | [minio.md](../Docker/MinIO/minio.md) |
| **MLflow** | `mlflow` | 실험 (params·metrics) 추적, 모델 레지스트리. backend=`postgres`, artifact=`minio`. | http://localhost:5000 | [mlflow.md](../Docker/MLflow/mlflow.md) |
| **PostgreSQL** | `postgres` · `pgadmin` | 모든 도구의 메타데이터 DB. `prefect`·`mlflow`·`optuna`·`catalog` 4개 논리 DB 를 운영합니다. | http://localhost:5050 (pgAdmin · DB :5432) | [postgresql.md](../Docker/PostgreSQL/postgresql.md) |
| **Optuna** | python script | 하이퍼파라미터 튜닝 (trial 탐색). study storage 로 `postgres` 의 `optuna` DB 를 씁니다. | http://localhost:8080 (필요 시 기동) | [§5](#5-optuna) |

> 이 스택은 한 호스트에 `postgres`·`minio`·`mlflow`·`prefect_server`·`prefect_dispatcher` (dispatcher) 를 모아 띄우고, dispatcher 가 job 마다 **Pipeline Flow 컨테이너** 를 일시적으로 띄우는 **Docker work pool** 구조입니다. 각 컨테이너는 받은 `git_repo`·`git_commit_hash` 을 shallow `git fetch` (`--depth 1`) + `git worktree` 로 펼쳐 실행하고 끝나면 스스로 파괴됩니다 (상세는 [prefect.md](../Docker/Prefect/prefect.md)).

### Pipeline

```text
                             TRAINING LANE                                        TEST LANE
                             data/*.parquet                                     data/*.parquet
                                   │                                                  │
                                   ▼                                                  ▼
                           ┌────────────────┐                                 ┌────────────────┐
          prepare.json ───▶│  train_prepare │                 prepare.json ──▶│  test_prepare  │
                           └───────┬────────┘                                 └───────┬────────┘
                                   │ trainval_raw + val_start                         │ test_raw
                                   ▼                                                  ▼
                           ┌────────────────┐                                 ┌────────────────┐
                           │ train_featurize│── scaler.json + features.json ─▶│ test_featurize │
                           └───────┬────────┘                                 └───────┬────────┘
                                   │ train/val.parquet                                │ test.parquet
                                   ▼                                                  ▼
                           ┌────────────────┐                                 ┌────────────────┐
       optuna.json ───────▶│      train     │────────── model.txt ───────────▶│      test      │
                           └───────┬────────┘                                 └───────┬────────┘
       parity_plot (train) ◀───────┤                                                  ├──▶ parity_plot (test)
   publish_artifacts (train) ◀─────┤ model + metrics                         metrics  └──▶ publish_artifacts (test)
                                   ▼                                         + pred.csv
                           ┌────────────────┐
                           │    validate    │
                           └───────┬────────┘
        parity_plot (validation) ◀─┤
   publish_artifacts (validation) ◀┤ val metrics
                                   ▼
        each stage emits both: parity_plot -> work/parity_<stage>.png ; publish_artifacts -> Prefect UI
```

  `pipeline.py` 가 `pipeline_flow` 컨테이너 안에서 run 마다 만드는 폴더 구조입니다.

  ```text
  /tmp/run-<rand>/                 # per-run temp dir (base; removed after the run)
  ├─ repo/                         # git init + fetch --depth 1 origin <git_commit_hash> (shallow git db)
  ├─ script/                       # git worktree add --detach script <git_commit_hash> (clean worktree at the commit)
  │  ├─ my_flow.py                 # payload — the team's entry (run: python my_flow.py --data_folder ../data ...)
  │  └─ ...                        # the rest of the team repo at <git_commit_hash>
  └─ data/                         # MinIO download target (bucket/key → here)
     └─ <object>                   # e.g. Bennelong Point
  ```

---

## 3. Data

### Flow

  데이터가 실제로 오가는 두 지점의 endpoint · parameter 입니다 — **upload 은 host 의 `catalog.py` 가 `spec.json` 으로**, **download 은 컨테이너 안 `pipeline.py` 가 Prefect Secret 블록으로** 합니다.

  ```text
  UPLOAD — host: catalog.py upload spec.json  (-m <member> [--pg-host/--minio-host localhost])
    input: spec.json { dataset_id, version, path, bucket, metadata, created_by }
    creds: Credentials block (member) — minio + postgresql_catalog sections
  ┌────────────┐                        ┌─────────────┐
  │ catalog.py │─ upload file ────────▶ │ MinIO :9000 │  → s3://<bucket>/<id>/<version>/<files>
  └──────┬─────┘                        └─────────────┘
         │                              ┌──────────────────┐
         └─ register row ─────────────▶ │ PostgreSQL :5432 │  → datasets(minio_path, n_files, size, metadata)
                                        └──────────────────┘

  DOWNLOAD — in-container: pipeline.py
    input: pipeline( minio_bucket="datasets", minio_key, member )
    creds: Credentials.load(member).minio — Prefect Secret block (minio section)
  ┌─────────────┐                       ┌──────────────────┐
  │ pipeline.py │─ download file ─────▶ │ MinIO minio:9000 │  → bucket/key → ./data/<key name>
  └─────────────┘                       └──────────────────┘
  ```

### Upload

  `catalog.py upload <spec.json>` 은 spec 의 `path` 가 가리키는 파일을 MinIO 에 올리고 `catalog` 에 버전 레코드를 등록합니다. host 에서는 `-m <member>` 로 자격증명 블록을 고르고 컨테이너용 endpoint 를 `--pg-host/--minio-host localhost` 로 덮어씁니다.

  ```python
  # catalog.py  upload(spec, member) — key steps (dataset_id/version/path/bucket come from spec)
  files = _resolve_sources(spec["path"])       # file | folder (recursive) | glob (dir/*.csv, **)
  ensure_schema()                              # create the datasets table if missing
  if get(dataset_id, version):                 # versions are immutable -> stop if it exists
      raise FileExistsError("version already exists")
  for fp, rel in files:                        # upload each file -> s3://<bucket>/<id>/<version>/<rel>
      s3.upload_file(str(fp), bucket, prefix + rel)
  register(dataset_id, version, minio_path,    # register the catalog row (path + counts + metadata)
           n_files=n_files, size_bytes=size_bytes, metadata=spec.get("metadata"))
  ```

  ```powershell
  python catalog.py spec spec.json                                                    # scaffold an empty spec
  python catalog.py upload spec.json -m <member> --pg-host localhost --minio-host localhost
  ```

  올릴 대상은 spec 의 **`path` 하나**로 정하고, 파일 한 개·여러 개·와일드카드는 그 `path` 값으로 구별됩니다 (별도 목록 필드 없음).

  | path | files | MinIO key |
  |---|---|---|
  | single file `data/powerconsumption.csv` | 그 파일 1개 | `<id>/<version>/powerconsumption.csv` |
  | folder `data` | 폴더 아래 전부 (재귀) | `<id>/<version>/<상대경로>` |
  | wildcard `data/*.parquet` | 매치 파일 (비재귀) | `<id>/<version>/<파일명>` |
  | recursive wildcard `data/**/*.parquet` | 하위까지 매치 | `<id>/<version>/<상대경로>` |

  ```json
  {"dataset_id": "epc", "version": "v1", "path": "data/powerconsumption.csv",
   "bucket": "datasets", "created_by": "ykim", "metadata": {"source": "kaggle"}}
  ```

  > `path` 만 바꿔 위 네 경우를 씁니다 (`"path": "data"` · `"path": "data/*.parquet"` · `"path": "data/**/*.parquet"`). 매치가 0건이면 `FileNotFoundError` 로 중단하고, 같은 `dataset_id`/`version` 이 이미 있으면 덮지 않고 중단합니다.

### Download

  `catalog.py download <id> [version] [dest]` 은 catalog 에서 `minio_path` 를 찾아 (version 생략 시 최신) 그 아래 객체를 `dest` (기본 `./<id>`) 로 내려받습니다.

  ```python
  # catalog.py  download(dataset_id, version, dest, member) — key steps
  row = get(dataset_id, version)               # version omitted -> latest row
  bucket, prefix = split(row["minio_path"])    # s3://bucket/<id>/<version>/
  for obj in list_objects(bucket, prefix):     # every object under the prefix
      s3.download_file(bucket, obj["Key"], dest_path)   # -> dest/<relative key>
  ```

  ```powershell
  python catalog.py download <id> <version> ./out -m <member> --pg-host localhost --minio-host localhost
  ```

  > flow 실행 중의 자동 download 는 CLI 가 아니라 컨테이너 안 `pipeline.py` 가 Prefect Secret 블록으로 합니다 (위 [Flow](#flow) 다이어그램).

### List

  여러 데이터셋·모델을 만들고 비교·재현하려면 산출물을 **버전 관리** 하고 무엇이 어디 있는지 **검색** 할 수 있어야 합니다. 이 스택은 실제 데이터를 MinIO 에, 가벼운 메타데이터·버전 이력·계보를 PostgreSQL `catalog` DB 에 둡니다.

  `catalog` 은 `catalog` DB 안의 테이블 하나 (`datasets`) 이며, MinIO 의 실제 데이터를 가리키는 **메타데이터 장부** 입니다. 이 장부를 다루는 **catalog 접근 계층** (테이블 생성·버전 등록·검색) 이 워크플로우에서 데이터의 위치·버전·계보를 기록합니다. 전체 명령은 [Appendix A. catalog.py CLI](#appendix-a-catalogpy-cli) 를 참고합니다.

  ```powershell
  python catalog.py list -m <member> --pg-host localhost                                 # datasets summary (latest)
  python catalog.py versions <id> -m <member> --pg-host localhost                        # version history
  python catalog.py tree --files -m <member> --pg-host localhost --minio-host localhost  # id > version tree (+ counts)
  python catalog.py find <id> fab=fab2 -m <member> --pg-host localhost                   # search by metadata key=value
  ```

#### Versioning

  데이터셋을 갱신할 때 이전 버전을 덮어쓰지 않고 보존합니다. 버전을 경로에 넣어 (`.../v1/`, `.../v2/`) 새 버전은 새 경로로 올리고, `catalog` 테이블에는 버전마다 새 레코드를 추가합니다.

  - **MinIO 경로 규칙**: `s3://datasets/<DatasetId>/<Version>/...`
  - **이름 규칙 (`DatasetId`·`Version`)**: 소문자·숫자·`_`·`.` 만 사용합니다 (공백·대문자·`-` 불가). 이 값이 그대로 MinIO 경로와 catalog 키가 되기 때문입니다.

  ```python
  import catalog                       # catalog access layer

  catalog.ensure_schema()              # create the datasets table idempotently (once at flow start)
  catalog.register("sydney_202605", "v2", "s3://datasets/sydney_202605/v2/",
                   created_by="zoo", prefect_run_id="<run_id>",
                   metadata={"fab": "fab2", "chamber": "CH3"})   # metadata (dict) → JSONB
  rows = catalog.find("sydney_202605", fab="fab2")               # search (dataset_id + metadata keys)
  ```

#### Lineage

  `catalog` 레코드의 `prefect_run_id` (데이터를 만든 실행) 와, MLflow run 태그에 기록하는 입력 데이터 버전을 **서로 참조** 해 두면 데이터 ↔ 코드 ↔ 결과를 양방향으로 추적할 수 있습니다.

  ```
  data (version) ──used by──▶ code (Prefect run) ──produces──▶ result (MLflow run / model)
     ▲                                                              │
     └────────────────────  trace back (result → data)  ◀──────────┘
  ```

  - **순방향** — 어떤 데이터 버전을 어떤 flow run 이 만들었고, 그 run 에서 나온 MLflow run·모델이 무엇인지 추적합니다.
  - **역방향** — 운영 모델의 MLflow run 태그 (`input_dataset`/`input_version`) → `catalog.find(...)` → `minio_path` 로 원본까지 거슬러 올라갑니다.

#### Output Placement & Name Collision

  전 팀원이 같은 MinIO 버킷에 결과물을 쓰므로 이름이 겹칠 수 있습니다. MLflow run (`run_id`)·Prefect run (`id`)·Optuna trial (`study_name`+`number`) 은 **자동으로 격리** 되고, 직접 저장하는 파일만 경로에 고유 키를 넣어 분리합니다.

  ```python
  # member / experiment comes from a job setting, env var, or flow parameter.
  out_uri = f"s3://models/{member}/{experiment}/{run_id}/model.pt"
  ```

  | Artifact | Location |
  |--------|-----------|
  | 학습된 모델 가중치 | MinIO `s3://models/...` |
  | MLflow params·metrics | PostgreSQL `mlflow` DB |
  | MLflow 모델·plot·artifact | MinIO `s3://mlflow/...` |
  | Optuna trial 기록 | PostgreSQL `optuna` DB |
  | 데이터셋 + 버전·메타데이터 | 실제 데이터 → MinIO `s3://datasets/...`, 메타 → PostgreSQL `catalog` DB |
  | flow/task run 상태·로그 | PostgreSQL `prefect` DB |

  > 위에서 코드가 **직접 접속**하는 곳은 MinIO 와 PostgreSQL 의 `catalog`·`optuna` DB 뿐입니다 — `mlflow`·`prefect` DB 는 MLflow server·Prefect server 가 대신 접속합니다. 자격증명 (`MINIO_*` / `POSTGRESQL_CATALOG_DSN` / `POSTGRESQL_OPTUNA_DSN`) 셋업은 [prefect.md](../Docker/Prefect/prefect.md) §5 Credentials, DB 별 권한 분리는 [postgresql.md](../Docker/PostgreSQL/postgresql.md) §4 Granular Database Access Control 를 참고합니다.

---

## 4. Script

팀 payload 와 단계별 스크립트로 이루어진 ML 코드 구조입니다. orchestrator (`pipeline.py`) 가 git 으로 이 repo 를 받아 `python my_flow.py` 로 실행합니다 ([§6. Python Execution](#6-python-execution)).

```text
script/                          # team repo, git-delivered into a per-run worktree (§6)
├─ my_flow.py                    # payload entry — @flow wires the stages (run: python my_flow.py --data_folder ...)
├─ train_dp.py · train_fe.py · train.py · train_eval.py   # train branch: dp → fe → train → eval
├─ test_dp.py  · test_fe.py  · test.py  · test_eval.py    # test branch:  dp → fe → test  → eval
├─ optuna.json                   # tuning config (n_trials · direction · fe)
└─ common/                       # team common repo, nested via git subtree (below)
```

### Team Common Repo (Nested Repository)

  공통 코드 (공통 단계·유틸·catalog 접근 계층 등) 를 여러 팀원 repo 에서 함께 쓰려면 공통 repo 를 각 repo 안에 **nested repository** 로 만들어 심습니다. `git subtree` 로 공통 repo 를 하위 경로 (`<path>`) 에 합쳐 한 커밋 트리로 관리하므로, runtime 의 shallow `git fetch` + `git worktree` 가 공통 코드까지 한 번에 펼칩니다 (submodule 과 달리 별도 init/fetch 가 없습니다).

  ```powershell
  # Creation — add the common repo under <path> as a squashed subtree (once).
  git subtree add  --prefix=<path> <url> <branch> --squash

  # Update — pull the latest common repo into <path>.
  git subtree pull --prefix=<path> <url> <branch> --squash
  ```

---

## 5. Optuna

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

---

## 6. Python Execution

### Server Connection

  Python client (dispatcher 또는 job 을 trigger 하는 노드) 가 **어느 Prefect server 에 연결할지** 주소를 지정합니다. **최초 1회** 설정하면 이후 모든 client 명령이 이 server 를 향합니다.

  ```powershell
  prefect config set PREFECT_API_URL="http://<Host IP>:4200/api"
  # Use localhost for <Host IP> on the same computer.
  ```

  이 설정은 job 을 **trigger** 할 때 (`prefect deployment run ...`), **deployment 를 등록** 할 때, **Prefect Secret 블록을 등록/조회** 할 때 등 server 와 통신하는 client 작업 전반에 필요합니다.

### Code-to-Container Flow

  trigger 는 코드를 보내지 않습니다. server 는 **deployment 의 참조 + 실행 파라미터** (`git_repo`·`git_commit_hash`·`minio_key`) 만 전달하고, 컨테이너가 그 repo·커밋을 shallow `git fetch` (`--depth 1`) + `git worktree` 로 펼쳐 실행합니다.

  ```
  [client] trigger(git_repo, git_commit_hash, minio_key) -> [server] enqueue run -> [prefect_dispatcher] pull the job
                                                                              |
                                                                              +- (1) spawn a container from the Pipeline Flow image
                                                                              +- (2) git fetch --depth 1 <git_repo> <git_commit_hash>; git worktree add --detach <dir> <git_commit_hash>   (Step A)
                                                                              +- (3) download minio_key data, run code         (Step B/C)
                                                                              +- (4) save results, then auto-remove            (Step D)
  ```

### ML Payload Sample

  git 으로 전달되어 컨테이너 안에서 `python my_flow.py` 로 실행되는 **실제 ML 코드** 예시입니다. 단계 (dp·fe·train·test) 를 **Prefect `@task`** 로 감싸 `@flow` 로 묶으면, 컨테이너 env 의 `PREFECT_API_URL` 덕분에 이 payload 가 **자기 flow run 과 task** 를 server 에 보고해 **대시보드에서 단계별로** 보입니다 (orchestrator run 과는 별개 flow run). `flow_run_name` 을 `member`·커밋으로 지으면 **누구의 run 인지** 도 갈립니다. orchestrator ([prefect.md](../Docker/Prefect/prefect.md) §4.3) 가 이 코드를 하위 프로세스로 부릅니다 — 바뀌는 부분은 이 payload, `git_commit_hash` 으로 돌릴 버전을 지정합니다. orchestrator 가 데이터를 `data/` 로 미리 받아 두고 실행 정보 (`--git_repo`·`--git_commit_hash`·`--member`) 와 그 경로 (`--data_folder`) 를 CLI 인자로 넘기므로, payload 는 `argparse` 로 받아 씁니다.

  ```python
  # my_flow.py — git-delivered ML payload; Prefect @task makes each step show in the UI (illustrative)
  import argparse
  import mlflow
  from prefect import flow, task
  from sklearn.ensemble import RandomForestClassifier
  from sklearn.metrics import accuracy_score

  @task
  def data_prep(data_dir):                                 # dp — read the files pipeline.py downloaded into --data_folder (Step B)
      return load_dataset(data_dir)

  @task
  def feature_eng(raw):                                    # fe
      return build_features(raw)

  @task
  def train_model(feat):                                   # train
      clf = RandomForestClassifier(n_estimators=300, random_state=42)
      clf.fit(feat.X_tr, feat.y_tr)
      return clf

  @task
  def test_model(clf, feat):                               # test
      return accuracy_score(feat.y_val, clf.predict(feat.X_val))

  @flow(name="my_flow", flow_run_name="{member}@{git_commit_hash}")   # the team's own flow run; the 4 tasks nest under it
  def my_flow(data_dir, member="", git_commit_hash=""):
      mlflow.set_tracking_uri("http://mlflow:5000")        # MLflow tracking server
      with mlflow.start_run():                             # MLflow auto-tags the git commit
          feat = feature_eng(data_prep(data_dir))
          clf  = train_model(feat)
          acc  = test_model(clf, feat)
          mlflow.log_metric("val_accuracy", acc)           # metric -> PostgreSQL (mlflow DB)
          mlflow.sklearn.log_model(clf, "model")           # artifact -> MinIO

  if __name__ == "__main__":
      p = argparse.ArgumentParser()                        # pipeline.py passes these as CLI args (§4.3)
      p.add_argument("--data_folder"); p.add_argument("--member", default=""); p.add_argument("--git_commit_hash", default="")
      p.add_argument("--git_repo", default="")             # accepted for completeness; unused here
      a = p.parse_args()
      my_flow(a.data_folder, a.member, a.git_commit_hash)
  ```

  > 데이터 다운로드용 `MINIO_*` 는 orchestrator (`pipeline.py`) 가 쓰고, payload 가 직접 쓰는 자격증명 (`catalog`·`optuna`·MLflow 아티팩트용) 은 [prefect.md](../Docker/Prefect/prefect.md) §5 처럼 `Secret.load(...)` 로 받습니다. MLflow 는 git repo 안에서 돌면 git 커밋을 자동 태그하므로 모델 ↔ 코드가 연결됩니다 (§7).

### Deployment & Trigger

  **Pipeline Flow 이미지 ([prefect.md](../Docker/Prefect/prefect.md) §4.1, `pipeline-flow:latest`)** 에 **orchestrator (`pipeline.py`) 가 들어 있으므로**, deployment entrypoint 를 **`pipeline.py:pipeline` 로 명시** 해 그 이미지로 등록합니다 (server·dispatcher 이미지가 아니라 `pipeline_flow` 이미지입니다). 이 등록은 **플랫폼·관리자가 1회** 하며 팀원 payload (`my_flow.py`) 에는 넣지 않습니다. 팀원·코드베이스 구분은 **`git_repo`·`git_commit_hash` 파라미터** 로, **성능 등급** 은 **등급별 deployment** (`pipeline/pipelineflow-high`·`pipeline/pipelineflow-low` — 각각 등급 pool 에 바인딩) 로 처리합니다 ([prefect.md](../Docker/Prefect/prefect.md) §1·§4.2).

  ```powershell
  # Register once (admin); definitions in pipelineflow-{high,low}.yml (see prefect.md §4.2), one per tier.
  prefect deploy --prefect-file pipelineflow-high.yml --name pipelineflow-high --no-prompt
  prefect deploy --prefect-file pipelineflow-low.yml  --name pipelineflow-low  --no-prompt
  ```

  ```powershell
  # Trigger — pick the tier by deployment; heavy -> high, light -> low (params otherwise identical).
  prefect deployment run "pipeline/pipelineflow-high" -p member=alice -p git_repo=https://github.com/<member>/<repo>.git -p git_commit_hash=a1b2c3d -p minio_key=SYDNEY/001.parquet
  prefect deployment run "pipeline/pipelineflow-low"  -p member=alice -p git_repo=https://github.com/<member>/<repo>.git -p git_commit_hash=a1b2c3d -p minio_key=SYDNEY/001.parquet
  ```
  ```python
  from prefect.deployments import run_deployment
  params = {"member": "alice", "git_repo": "https://github.com/<member>/<repo>.git", "git_commit_hash": "a1b2c3d", "minio_key": "SYDNEY/001.parquet"}
  run_deployment("pipeline/pipelineflow-high", parameters=params)   # or "pipeline/pipelineflow-low" for the low tier
  ```

  > 팀원마다 자기 repo·커밋을 넘기면 같은 이미지로 각자 다른 코드를 동시에 돌릴 수 있습니다 (컨테이너가 각자 사설 worktree 에 펼침). 무거운 job 은 `pipeline/pipelineflow-high`, 가벼운 job 은 `pipeline/pipelineflow-low` 로 보내 성능 등급을 고릅니다.

---

## 7. Code Delivery & Versioning

Prefect 자체는 코드를 버전관리하지 않습니다 (orchestrator 일 뿐). 이 구성에서는 **세 축** 으로 버전이 고정됩니다.

| Axis | Pinned by | Meaning |
|------|-----------|---------|
| **Code version** | `git_repo`·`git_commit_hash` parameters (shallow `git fetch --depth 1` + `git worktree add <commit>`) | 어떤 repo·커밋으로 실행할지 — 커밋 고정 시 완전 재현 |
| **Runtime version** | Pipeline Flow image tag | 라이브러리 + orchestrator 버전 |
| **Data version** | `minio_key` parameter | 어떤 데이터 버전을 쓸지 (버전이 key 경로에 담긴 불변 경로) |

- **코드 버전** — trigger 시 `git_repo` 와 `git_commit_hash` (SHA) 를 넘기면, 컨테이너가 그 repo 를 shallow `git fetch` (`--depth 1`) 한 뒤 그 커밋을 `git worktree` 로 펼쳐 실행하므로 항상 같은 코드가 돕니다. 브랜치명을 넘기면 "그 시점 최신" 이 됩니다.
- **런타임 버전** — 이미지 태그 (`pipeline-flow:latest`) 가 라이브러리를 고정합니다. 라이브러리를 바꾸면 새 태그로 빌드합니다.
- **모델 ↔ 코드 연결** — MLflow 는 git repo 안에서 run 을 돌리면 git 커밋 SHA 를 자동 태그로 남기므로, "이 모델이 어떤 코드로 학습됐나" 는 MLflow 의 git 커밋 태그로 추적됩니다 (데이터 lineage 는 카탈로그가 담당).

> **Private repo** — 런타임 `git fetch` 대상이 private repo 면 토큰이 필요합니다. 토큰을 Prefect Secret 으로 받아 인증된 URL (`git_repo`) 로 fetch 하거나 git credential helper 를 설정합니다. public repo 면 그대로 됩니다.

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

`catalog.py` 는 데이터 카탈로그 (PostgreSQL `catalog` DB 장부) 와 MinIO 객체를 함께 다루는 접근 계층이자 CLI 입니다. flow 에서 라이브러리로 import 해 쓰거나 ([§3 Data Catalog](#3-data)), 아래 CLI 로 직접 둘러보기·업로드·다운로드·삭제합니다. **catalog.py 는 컨테이너 밖에서 실행** 되므로 자격증명은 Prefect 프로필 ([§6 Server Connection](#6-python-execution) 의 `prefect config set PREFECT_API_URL=...`) 로 연결된 **Prefect Secret 블록** 에서 가져옵니다 (멤버별 `Credentials` 블록은 아래 [Credentials](#credentials-prefect-block), 없으면 default). 프로세스 환경변수나 `docker-compose.env` 파일은 쓰지 않습니다 (그 파일은 컨테이너 스택용이라 host 의 catalog.py 가 찾을 수 없음). 업로드·다운로드·삭제는 boto3 로 처리하므로 `mc` 가 필요 없습니다.

**Target** 은 명령이 접속하는 곳입니다 (**PostgreSQL** = catalog DB 장부, **MinIO** = 객체 저장소). 각 명령은 실행 시작 시 접속 대상 (PostgreSQL DSN — 비밀번호 가림 · MinIO endpoint) 과 **자격증명 출처** (`[creds: prefect-block (member=…) | default]`) 를 stderr 로 먼저 출력해 "어디로 접속해 도는지, 자격증명을 어디서 가져왔는지" 를 알립니다. Prefect 서버 블록에서 가져오면 `prefect-block`, 서버 미연결·블록 없음이면 `default` 로 표시됩니다. `--version`/`-V` 로 버전을 확인합니다.

| Command | Target | Purpose |
|---|---|---|
| `list` | PostgreSQL | 데이터셋 목록 (최신 버전 요약) |
| `versions <id>` | PostgreSQL | 한 데이터셋의 버전 이력 |
| `tree [id] [--files]` | PostgreSQL (+MinIO `--files`) | 데이터셋 > 버전 트리 (`--files` 면 MinIO 파일 종류별 개수) |
| `find <id> [key=value ...]` | PostgreSQL | metadata 키=값 검색 |
| `spec [out.json]` | (local) | 빈 upload spec.json 뼈대 생성 (채워서 `upload` 에 사용; 기본 `spec.json`) |
| `upload <spec.json>` | MinIO + PostgreSQL | MinIO 적재 + catalog 등록 (JSON spec) |
| `download <id> [version] [dest]` | PostgreSQL + MinIO | 버전 객체 다운로드 (version 생략 시 최신, dest 기본 `./<id>`) |
| `remove <id> [version] [--yes]` | MinIO + PostgreSQL | MinIO + catalog 에서 영구 삭제 (version 생략 시 데이터셋 전체) |
| `objects [id]` | MinIO | MinIO 에 실제로 있는 객체 나열 (catalog 무관) |

MinIO·PostgreSQL 에 접속하는 명령에는 `-m <member>` (자격증명 블록 선택) 와 `--pg-host`/`--minio-host` (endpoint host 만 덮어쓰기, creds 불변) 를 붙일 수 있습니다 — 컨테이너용 블록을 host 에서 쓸 때 유용합니다 (`spec` 은 로컬 파일 생성이라 해당 없음). 자세한 것은 아래 [Credentials](#credentials-prefect-block).

catalog.py 는 자격증명 블록 클래스 (`credentials.py`, `../Docker/Prefect`) 를 import 하므로, host 에서 실행 전 그 폴더를 `PYTHONPATH` 에 1회 넣습니다 (경로는 repo 위치에 맞춰 `Resolve-Path` 로 풉니다).

```powershell
# put credentials.py (Credentials block class, ../Docker/Prefect) on PYTHONPATH; once per session
$env:PYTHONPATH = (Resolve-Path ..\Docker\Prefect).Path

python catalog.py list                              # dataset summary (latest version)
python catalog.py versions sydney_202605            # one dataset's version history
python catalog.py tree --files                      # dataset > version tree (+ file-type counts)
python catalog.py find sydney_202605 fab=fab2       # search by metadata key=value
python catalog.py spec spec.json                    # write an empty upload spec template
python catalog.py upload spec.json                  # upload to MinIO + register (JSON spec)
python catalog.py download sydney_202605 v2 ./out   # version omitted -> latest; dest -> ./<id>
python catalog.py remove sydney_202605 v2 --yes     # version omitted -> whole dataset
python catalog.py objects sydney_202605             # raw MinIO objects (not the catalog)
```

`upload` 의 `spec.json` 예시입니다.

```json
{"dataset_id": "sydney_202605", "version": "v2", "path": "./out",
 "bucket": "datasets", "created_by": "zoo", "description": "fab2 CH3",
 "metadata": {"fab": "fab2", "chamber": "CH3"}}
```

> 버전은 불변 (immutable) 입니다 — 같은 `dataset_id`/`version` 이 MinIO 나 catalog 에 이미 있으면 `upload` 는 덮어쓰지 않고 중단합니다 (버전을 올려 다시 시도). `remove` 는 MinIO 객체 (모든 버전·삭제마커) 와 catalog 행을 영구 삭제하므로 `--yes` 없이는 `DELETE` 입력을 요구합니다.

host 에서 컨테이너용 블록 (endpoint 가 `postgres`·`minio` 서비스명) 으로 접속할 때는 `-m <member>` 로 블록을 고르고 `--pg-host`/`--minio-host` 로 host 만 `localhost` 로 바꿉니다.

```powershell
python catalog.py upload spec.json -m <member> --pg-host localhost --minio-host localhost
python catalog.py remove <id> <version> -m <member> --pg-host localhost --minio-host localhost
```

### Credentials (Prefect block)

  catalog.py 가 읽는 자격증명은 **팀원마다 하나인 `Credentials` 블록** (블록 이름 = 팀원 이름, 소문자·숫자·대시) 에 담겨 있고, 관리자가 `credentials.py` 로 1회 등록합니다 (`python credentials.py --json-path <member>.json --block-name <member>` — [prefect.md](../Docker/Prefect/prefect.md) §5 Credentials). 한 블록 안에 세 섹션 (nested dict, `SecretDict` 로 가림) 이 들어 있습니다.

  | Section | Fields | Target |
  |---|---|---|
  | `minio` | `endpoint` · `access_key` · `secret_key` | MinIO |
  | `postgresql_catalog` | `endpoint` · `username` · `password` · `database` | PostgreSQL (`catalog` DB) |
  | `postgresql_optuna` | `endpoint` · `username` · `password` · `database` | PostgreSQL (`optuna` DB, flow·Optuna 용) |

  - **`-m <member>`** 가 어느 팀원 블록을 읽을지 정합니다. catalog.py 는 그중 `minio` + `postgresql_catalog` 두 섹션만 씁니다 (`postgresql_optuna` 는 flow 용). 블록이 없거나 서버 미연결이면 default (localhost) 로 떨어지고, 배너에 `[creds: prefect-block (member=…)]` 또는 `[creds: default]` 로 출처가 표시됩니다.
  - **`--pg-host` / `--minio-host`** 는 블록 endpoint 의 host 만 덮어씁니다 (creds·port 불변). 컨테이너용 블록 (endpoint 가 `postgres`·`minio` 서비스명) 을 host 에서 쓸 때 `--pg-host localhost --minio-host localhost` 로 붙입니다.
  - `PREFECT_API_URL` (Prefect 프로필) 은 이 블록을 받기 위한 **접속점** 일 뿐 catalog 데이터가 아닙니다. 프로세스 환경변수·`docker-compose.env` 는 쓰지 않습니다.

  > **권한 차단은 MinIO policy 로** — 팀원 블록의 `minio` 키가 곧 그 팀원의 MinIO 신원입니다. 진짜 사용자별 차단은 **그 키가 MinIO 에서 버킷 policy 로 제한** 되어 있어야 실제로 막히고, 그렇지 않으면 격리는 경로 규칙 `s3://.../{member}/...` ([§3 Output Placement](#3-data)) 에 의존합니다. Prefect 블록 자체엔 사용자별 접근제어가 없습니다.
