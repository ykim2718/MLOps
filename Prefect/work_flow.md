# AI/ML Workflow Automation — Prefect + MinIO + MLflow + Optuna + PostgreSQL

Prefect 3 기반 AI 학습 파이프라인을 Docker 로 띄우고 실행하기 위한 환경입니다. 이 문서는 **전체 워크플로우의 인덱스 (개요)** 로, 각 도구의 상세는 해당 컴포넌트 문서로 연결합니다.

이 프로젝트는 **Prefect 를 "실행 orchestrator" 로 두고**, 실험 추적·하이퍼파라미터 튜닝·데이터 보관/버전관리를 담당하는 다른 도구들과 **역할을 나눠 함께 쓰는 것** 을 목적으로 합니다. "언제·무엇을·어떤 순서로 실행할지" 는 Prefect 가 맡고, "그 실행에서 나온 실험 기록·튜닝 결과·데이터/모델" 은 각 도구가 맡습니다.

---

## 1. Goals

이 워크플로우는 여러 팀원이 한 server 를 공유하며 AI 학습을 돌릴 때, **데이터·실험·결과를 잃지 않고 추적·재현·공유** 하기 위한 다음을 목표로 합니다.

1) **Lineage (계보)** — 데이터·코드·결과를 양방향으로 추적합니다.
2) **Reproducibility (재현)** — 데이터 버전·하이퍼파라미터·시드를 고정해 동일 결과를 보장합니다.
3) **Persistence & Versioning (보존·버전)** — 모델·데이터를 catalog 로 버전 보존하고 검색·선택 다운로드합니다 (메타 → PostgreSQL `catalog`, 실데이터 → MinIO).
4) **Monitoring (모니터링)** — Prefect / MLflow / MinIO 대시보드로 현황을 한눈에 봅니다.
5) **Reusability (재사용)** — 워크플로우·피처를 다른 프로젝트에서 다시 씁니다.
6) **Resource Management (자원 관리)** — work pool·`--limit` 으로 공유 GPU/CPU 를 분배합니다.
7) **Scheduled Automation (자동화)** — cron/interval 스케줄로 무인 실행합니다.

## 2. Stack

스택의 서비스는 도커로 실행합니다. 각 컴포넌트는 자기 폴더 (`Docker/<컴포넌트>/`) 의 `docker-compose.yml` 로 띄우며, 상세 설치·사용법은 아래 문서를 참고합니다.

| Component | Service | Role | Dashboard | Docs |
|-----------|---------|------|-----------|-----------|
| **Prefect** | `prefect_server` · `prefect_dispatcher` | 오케스트레이션 (파이프라인 실행/스케줄링). server 는 job 수집·UI, dispatcher (`prefect_dispatcher`) 는 job 마다 Pipeline Flow 컨테이너를 띄우며, 코드는 그 컨테이너가 실행합니다. | http://localhost:4200 | [prefect.md](../Docker/Prefect/prefect.md) |
| **MinIO** | `minio` | 대용량 데이터/모델/아티팩트 저장 (S3 호환). 버킷은 `datasets`·`models`·`mlflow` 입니다. | http://localhost:9001 | [minio.md](../Docker/MinIO/minio.md) |
| **MLflow** | `mlflow` | 실험 (params·metrics) 추적, 모델 레지스트리. backend=`postgres`, artifact=`minio`. | http://localhost:5000 | [mlflow.md](../Docker/MLflow/mlflow.md) |
| **PostgreSQL** | `postgres` | 모든 도구의 메타데이터 DB. `prefect`·`mlflow`·`optuna`·`catalog` 4개 논리 DB 를 운영합니다. | :5432 | [postgresql.md](../Docker/PostgreSQL/postgresql.md) |
| **Optuna** | (라이브러리) | 하이퍼파라미터 튜닝 (trial 탐색). study storage 로 `postgres` 의 `optuna` DB 를 씁니다. | — | [§5](#5-optuna) |

> 이 스택은 한 호스트에 `postgres`·`minio`·`mlflow`·`prefect_server`·`prefect_dispatcher` (dispatcher) 를 모아 띄우고, dispatcher 가 job 마다 **Pipeline Flow 컨테이너** 를 일시적으로 띄우는 **Docker work pool** 구조입니다. 각 컨테이너는 받은 `git_repo`·`git_commit` 을 `git fetch` + `git worktree` 로 펼쳐 실행하고 끝나면 스스로 파괴됩니다 (상세는 [prefect.md](../Docker/Prefect/prefect.md)).

## 3. Data Flow

```
[ Member ]
   ├─ submit/trigger python flow ─▶ [ Prefect Server + Dispatcher  :4200 ]  (orchestration)
   ├─ data catalog search ───────▶ [ PostgreSQL  :5432 ]
   └─ data download/upload ──────▶ [ MinIO  API :9000 / console :9001 ]

[ Prefect Server + Dispatcher ]
   ├─ run stages ─────▶ [ MLflow  :5000 ]   ├─ params·metrics ─▶ [ PostgreSQL ]
   ├─ tuning ─────────▶ [ Optuna study ]    └─ artifact ───────▶ [ MinIO ]
   ├─ run state/logs ─▶ [ PostgreSQL ]
   └─ data/models ────▶ [ MinIO ]
```

> 공통 원칙: **DB = 작은 구조화 메타데이터, 대용량 바이너리 = MinIO + 경로 (URI) 참조.** 모델 가중치·데이터셋·plot 같은 실제 데이터는 DB 에 넣지 않고 MinIO 에 두며, DB 에는 그 경로·버전ID·해시만 기록합니다.

---

## 4. Pipeline

`data preparation(dp) → feature engineering(fe) → training(train) → test` 순으로 진행하며, 각 단계의 산출물이 다음 단계의 입력이 됩니다. 각 단계는 Prefect `@task` 로 감싸고 `@flow` 가 순서를 강제합니다 (앞 단계 산출물이 있어야 다음 단계가 실행됩니다). 이 파이프라인은 팀 payload (`train.py`) 로 작성되어 Prefect orchestrator 가 실행합니다 (아래 [§7. Python Execution](#7-python-execution), [prefect.md](../Docker/Prefect/prefect.md) §4.3).

```
[train raw] → train_dp → [transformed] → train_fe → [feature + fe_train.json]
           → train → [model/ + train.json] → train_eval → [train_eval.json]

[test raw]  → test_dp  → [transformed] → test_fe(reuse fe_train.json) → [feature]
           → test(load model/) → [test.json] → test_eval → [test_eval.json]
```

> **train ↔ test 연결의 핵심**: test 는 train 에서 두 가지를 그대로 가져옵니다 — ① `model/` (학습된 모델), ② `fe_train.json` (train 에 fit 된 변환기). 변환을 test 에 새로 fit 하면 train/test skew 가 생기므로, fe 는 train 에서 fit 하고 test 에는 그 결과를 적용합니다.

### Every Stage Uses MinIO, MLflow, Optuna

  모든 단계 (`dp`·`fe`·`train`·`test`·`eval`) 를 세 도구로 동일하게 감쌉니다.

  - **MinIO** — 각 단계의 입력을 버킷에서 내려받고 (download), 출력을 버킷에 올리며 (upload), `catalog` 에 버전·계보를 기록합니다.
  - **MLflow** — 각 단계의 파라미터·지표·산출물을 같은 run 아래 로깅합니다.
  - **Optuna** — 각 단계의 튜닝 가능한 설정 (`optuna.json`) 을 탐색합니다 (test 는 학습에서 고른 best 설정을 재사용합니다).

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

---

## 6. Data Catalog

여러 데이터셋·모델을 만들고 비교·재현하려면 산출물을 **버전 관리** 하고 무엇이 어디 있는지 **검색** 할 수 있어야 합니다. 이 스택은 실제 데이터를 MinIO 에, 가벼운 메타데이터·버전 이력·계보를 PostgreSQL `catalog` DB 에 두는 방식으로 처리합니다.

`catalog` 은 `catalog` DB 안의 테이블 하나 (`datasets`) 이며, MinIO 의 실제 데이터를 가리키는 **메타데이터 장부** 입니다. 이 장부를 다루는 **catalog 접근 계층** (테이블 생성·버전 등록·검색) 이 워크플로우에서 데이터의 위치·버전·계보를 기록합니다.

### Versioning

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

### Lineage

  `catalog` 레코드의 `prefect_run_id` (데이터를 만든 실행) 와, MLflow run 태그에 기록하는 입력 데이터 버전을 **서로 참조** 해 두면 데이터 ↔ 코드 ↔ 결과를 양방향으로 추적할 수 있습니다.

  ```
  data (version) ──used by──▶ code (Prefect run) ──produces──▶ result (MLflow run / model)
     ▲                                                              │
     └────────────────────  trace back (result → data)  ◀──────────┘
  ```

  - **순방향** — 어떤 데이터 버전을 어떤 flow run 이 만들었고, 그 run 에서 나온 MLflow run·모델이 무엇인지 추적합니다.
  - **역방향** — 운영 모델의 MLflow run 태그 (`input_dataset`/`input_version`) → `catalog.find(...)` → `minio_path` 로 원본까지 거슬러 올라갑니다.

### Output Placement & Name Collision

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

## 7. Python Execution

### Server Connection

  Python client (dispatcher 또는 job 을 trigger 하는 노드) 가 **어느 Prefect server 에 연결할지** 주소를 지정합니다. **최초 1회** 설정하면 이후 모든 client 명령이 이 server 를 향합니다.

  ```powershell
  prefect config set PREFECT_API_URL="http://<Host IP>:4200/api"
  # Use localhost for <Host IP> on the same computer.
  ```

  이 설정은 job 을 **trigger** 할 때 (`prefect deployment run ...`), **deployment 를 등록** 할 때, **Prefect Secret 블록을 등록/조회** 할 때 등 server 와 통신하는 client 작업 전반에 필요합니다.

### Code-to-Container Flow

  trigger 는 코드를 보내지 않습니다. server 는 **deployment 의 참조 + 실행 파라미터** (`git_repo`·`git_commit`·`minio_version`) 만 전달하고, 컨테이너가 그 repo·커밋을 `git fetch` + `git worktree` 로 펼쳐 실행합니다.

  ```
  [client] trigger(git_repo, git_commit, minio_version) -> [server] enqueue run -> [prefect_dispatcher] pull the job
                                                                              |
                                                                              +- (1) spawn a container from the Pipeline Flow image
                                                                              +- (2) git fetch <git_repo>; git worktree add <dir> <git_commit>   (Step A)
                                                                              +- (3) prepare minio_version data, run code      (Step B/C)
                                                                              +- (4) save results, then auto-remove            (Step D)
  ```

### ML Payload Sample

  git 으로 전달되어 컨테이너 안에서 `python train.py` 로 실행되는 **실제 ML 코드** 예시입니다. 단계 (dp·fe·train·test) 를 **Prefect `@task`** 로 감싸고 `@flow` 로 묶으면, 컨테이너 env 의 `PREFECT_API_URL` 덕분에 이 payload 가 **자기 flow run 과 task** 를 server 에 보고해 **대시보드에서 단계별로** 보입니다 (orchestrator run 과는 별개 flow run). `flow_run_name` 을 `member`·커밋으로 지으면 **누구의 run 인지** 도 구분됩니다. orchestrator ([prefect.md](../Docker/Prefect/prefect.md) §4.3) 가 이 코드를 하위 프로세스로 부릅니다 — 바뀌는 부분은 이 payload 이고, `git_commit` 으로 어떤 버전을 돌릴지 지정합니다.

  ```python
  # train.py — git-delivered ML payload; Prefect @task makes each step show in the UI (illustrative)
  import os
  import mlflow
  from prefect import flow, task
  from sklearn.ensemble import RandomForestClassifier
  from sklearn.metrics import accuracy_score

  def _run_name() -> str:                                  # label the run by member + commit (UI shows whose run)
      return f"{os.environ.get('MEMBER', '?')}@{os.environ.get('GIT_COMMIT', '?')[:7]}"

  @task
  def data_prep(version):                                  # dp — read this data version directly from MinIO (Step B)
      return load_dataset(version)

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

  @flow(name="train", flow_run_name=_run_name)             # the team's own flow run; the 4 tasks nest under it
  def train():
      mlflow.set_tracking_uri("http://mlflow:5000")        # MLflow tracking server
      with mlflow.start_run():                             # MLflow auto-tags the git commit
          feat = feature_eng(data_prep(os.environ["MINIO_VERSION"]))
          clf  = train_model(feat)
          acc  = test_model(clf, feat)
          mlflow.log_metric("val_accuracy", acc)           # metric -> PostgreSQL (mlflow DB)
          mlflow.sklearn.log_model(clf, "model")           # artifact -> MinIO

  if __name__ == "__main__":
      train()
  ```

  > 필요한 자격증명 (`MINIO_*`·`catalog`·`optuna`) 은 [prefect.md](../Docker/Prefect/prefect.md) §5 처럼 `Secret.load(...)` 로 받습니다. MLflow 는 git repo 안에서 돌면 git 커밋을 자동 태그하므로 모델 ↔ 코드가 연결됩니다 (§8).

### Deployment & Trigger

  **Pipeline Flow 이미지 ([prefect.md](../Docker/Prefect/prefect.md) §4.1, `pipeline-flow:latest`)** 에 **orchestrator (`pipeline.py`) 가 들어 있으므로**, deployment entrypoint 를 **`pipeline.py:pipeline` 로 명시** 해 그 이미지로 등록합니다 (server·dispatcher 이미지가 아니라 `pipeline_flow` 이미지입니다). 이 등록은 **플랫폼·관리자가 1회** 하며 팀원 payload (`train.py`) 에는 넣지 않습니다. 팀원·코드베이스 구분은 **`git_repo`·`git_commit` 파라미터** 로, **성능 등급** 은 **등급별 deployment** (`pipeline/pipelineflow-high`·`pipeline/pipelineflow-low` — 각각 등급 pool 에 바인딩) 로 처리합니다 ([prefect.md](../Docker/Prefect/prefect.md) §1·§4.2).

  ```powershell
  # Register once (admin); definitions in pipelineflow-{high,low}.yml (see prefect.md §4.2), one per tier.
  prefect deploy --file pipelineflow-high.yml --name pipelineflow-high
  prefect deploy --file pipelineflow-low.yml  --name pipelineflow-low
  ```

  ```powershell
  # Trigger — pick the tier by deployment; heavy -> high, light -> low (params otherwise identical).
  prefect deployment run "pipeline/pipelineflow-high" -p member=alice -p git_repo=https://github.com/<member>/<repo>.git -p git_commit=a1b2c3d -p minio_version=v3_best
  prefect deployment run "pipeline/pipelineflow-low"  -p member=alice -p git_repo=https://github.com/<member>/<repo>.git -p git_commit=a1b2c3d -p minio_version=v3_best
  ```
  ```python
  from prefect.deployments import run_deployment
  params = {"member": "alice", "git_repo": "https://github.com/<member>/<repo>.git", "git_commit": "a1b2c3d", "minio_version": "v3_best"}
  run_deployment("pipeline/pipelineflow-high", parameters=params)   # or "pipeline/pipelineflow-low" for the low tier
  ```

  > 팀원마다 자기 repo·커밋을 넘기면 같은 이미지로 각자 다른 코드를 동시에 돌릴 수 있습니다 (컨테이너가 각자 사설 worktree 에 펼침). 무거운 job 은 `pipeline/pipelineflow-high`, 가벼운 job 은 `pipeline/pipelineflow-low` 로 보내 성능 등급을 고릅니다.

  ---

## 8. Code Delivery & Versioning

Prefect 자체는 코드를 버전관리하지 않습니다 (orchestrator 일 뿐). 이 구성에서는 **세 축** 으로 버전이 고정됩니다.

| Axis | Pinned by | Meaning |
|------|-----------|---------|
| **Code version** | `git_repo`·`git_commit` parameters (`git fetch` + `git worktree add <commit>`) | 어떤 repo·커밋으로 실행할지 — 커밋 고정 시 완전 재현 |
| **Runtime version** | Pipeline Flow image tag | 라이브러리 + orchestrator 버전 |
| **Data version** | `minio_version` parameter | 어떤 데이터 버전을 쓸지 (불변 경로) |

- **코드 버전** — trigger 시 `git_repo` 와 `git_commit` (SHA) 를 넘기면, 컨테이너가 그 repo 를 `git fetch` 한 뒤 그 커밋을 `git worktree` 로 펼쳐 실행하므로 항상 같은 코드가 돕니다. 브랜치명을 넘기면 "그 시점 최신" 이 됩니다.
- **런타임 버전** — 이미지 태그 (`pipeline-flow:latest`) 가 라이브러리를 고정합니다. 라이브러리를 바꾸면 새 태그로 빌드합니다.
- **모델 ↔ 코드 연결** — MLflow 는 git repo 안에서 run 을 돌리면 git 커밋 SHA 를 자동 태그로 남기므로, "이 모델이 어떤 코드로 학습됐나" 는 MLflow 의 git 커밋 태그로 추적됩니다 (데이터 lineage 는 카탈로그가 담당).

> **Private repo** — 런타임 `git fetch` 대상이 private repo 면 토큰이 필요합니다. 토큰을 Prefect Secret 으로 받아 인증된 URL (`git_repo`) 로 fetch 하거나 git credential helper 를 설정합니다. public repo 면 그대로 됩니다.

---

## 9. Inference

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
