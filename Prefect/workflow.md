# AI/ML Workflow Automation — Prefect + MinIO + MLflow + Optuna + PostgreSQL

Prefect 3 기반 AI 학습 파이프라인을 Docker 로 띄우고 실행하기 위한 환경입니다. 이 문서는 **전체 워크플로우의 인덱스 (개요)** 로, 각 도구의 상세는 해당 컴포넌트 문서로 연결합니다.

이 프로젝트는 **Prefect 를 "실행 오케스트레이터" 로 두고**, 실험 추적·하이퍼파라미터 튜닝·데이터 보관/버전관리를 담당하는 다른 도구들과 **역할을 나눠 함께 쓰는 것** 을 목적으로 합니다. "언제·무엇을·어떤 순서로 실행할지" 는 Prefect 가 맡고, "그 실행에서 나온 실험 기록·튜닝 결과·데이터/모델" 은 각 도구가 맡습니다.

---

## 1. Goals

이 워크플로우는 여러 팀원이 한 server 를 공유하며 AI 학습을 돌릴 때, **데이터·실험·결과를 잃지 않고 추적·재현·공유** 하기 위한 다음을 목표로 합니다.

1. **Lineage (계보 추적)** — 데이터·코드·결과를 양방향으로 역추적합니다 (데이터+코드 → 결과, 결과 → 데이터+코드).
2. **Monitoring (모니터링)** — Prefect / MLflow / MinIO 대시보드로 진행·결과 현황을 한눈에 봅니다.
3. **Reproducibility (재현성)** — 데이터 버전·모델 구조·하이퍼파라미터·시드를 고정해 동일 결과를 보장합니다.
4. **Reusability (재사용성)** — 한 번 만든 워크플로우·피처를 다른 프로젝트에서도 다시 씁니다.
5. **Persistence (영속성)** — 학습된 모델·상태를 스토리지에 안전하게 저장·유지합니다.
6. **Resource Management (자원 관리)** — GPU/CPU 공유 자원을 work pool 과 `--limit` 으로 분배해 충돌 없이 돌립니다.
7. **Scheduled Automation (예약형 자동화)** — cron/interval 스케줄로 무인 실행을 돌립니다.
8. **Data Versioning (데이터 버전 관리)** — 데이터 catalog 로 검색·선택적 다운로드를 제공합니다 (메타데이터는 PostgreSQL `catalog` DB, 실제 데이터는 MinIO).

## 2. Stack

스택의 서비스는 도커로 실행합니다. 각 컴포넌트는 자기 폴더 (`Docker/<컴포넌트>/`) 의 `docker-compose.yml` 로 띄우며, 상세 설치·사용법은 아래 문서를 참고합니다.

| Component | Service | Role | Dashboard | Docs |
|-----------|---------|------|-----------|-----------|
| **Prefect** | `prefect_server` · `prefect_worker` | 오케스트레이션 (파이프라인 실행/스케줄링). server 는 job 수집·UI, 디스패처 (`prefect_worker`) 는 job 마다 Pipeline Flow 컨테이너를 띄워 실행을 맡습니다. | http://localhost:4200 | [prefect.md](../Docker/Prefect/prefect.md) |
| **MinIO** | `minio` | 대용량 데이터/모델/아티팩트 저장 (S3 호환). 버킷은 `datasets`·`models`·`mlflow` 입니다. | http://localhost:9001 | [minio.md](../Docker/MinIO/minio.md) |
| **MLflow** | `mlflow` | 실험 (params·metrics) 추적, 모델 레지스트리. backend=`postgres`, artifact=`minio`. | http://localhost:5000 | [mlflow.md](../Docker/MLflow/mlflow.md) |
| **PostgreSQL** | `postgres` | 모든 도구의 메타데이터 DB. `prefect`·`mlflow`·`optuna`·`catalog` 4개 논리 DB 를 운영합니다. | :5432 | [postgresql.md](../Docker/PostgreSQL/postgresql.md) |
| **Optuna** | (라이브러리) | 하이퍼파라미터 튜닝 (trial 탐색). study storage 로 `postgres` 의 `optuna` DB 를 씁니다. | — | [§5](#5-optuna) |

> 이 스택은 한 호스트에 `postgres`·`minio`·`mlflow`·`prefect_server`·`prefect_worker` (디스패처) 를 모아 띄우고, 디스패처가 job 마다 **Pipeline Flow 컨테이너** 를 일시적으로 띄우는 **Docker work pool** 구조입니다. 각 컨테이너는 받은 `git_commit` 으로 checkout 해 실행하고 끝나면 스스로 파괴됩니다 (상세는 [prefect.md](../Docker/Prefect/prefect.md)).

## 3. Data Flow

```
[ Member ]
   ├─ submit/trigger python flow ─▶ [ Prefect Server + Worker  :4200 ]  (orchestration)
   ├─ data catalog search ───────▶ [ PostgreSQL  :5432 ]
   └─ data download/upload ──────▶ [ MinIO  API :9000 / console :9001 ]

[ Prefect Server + Worker ]
   ├─ run stages ─────▶ [ MLflow  :5000 ]   ├─ params·metrics ─▶ [ PostgreSQL ]
   ├─ tuning ─────────▶ [ Optuna study ]    └─ artifact ───────▶ [ MinIO ]
   ├─ run state/logs ─▶ [ PostgreSQL ]
   └─ data/models ────▶ [ MinIO ]
```

> 공통 원칙: **DB = 작은 구조화 메타데이터, 대용량 바이너리 = MinIO + 경로 (URI) 참조.** 모델 가중치·데이터셋·plot 같은 실제 데이터는 DB 에 넣지 않고 MinIO 에 두며, DB 에는 그 경로·버전ID·해시만 기록합니다.

---

## 4. Pipeline

`data preparation(dp) → feature engineering(fe) → training(train) → test` 순으로 진행하며, 각 단계의 산출물이 다음 단계의 입력이 됩니다. 각 단계는 Prefect `@task` 로 감싸고 `@flow` 가 순서를 강제합니다 (앞 단계 산출물이 있어야 다음 단계가 실행됩니다). 각 단계를 오케스트레이션하는 방식은 아래 [§7. Orchestrator](#7-orchestrator) 를 참고합니다.

```
[train raw] → train_dp → [transformed] → train_fe → [feature + fe_train.json]
           → train → [model/ + train.json] → train_eval → [train_eval.json]

[test raw]  → test_dp  → [transformed] → test_fe(fe_train.json 재사용) → [feature]
           → test(model/ 로드) → [test.json] → test_eval → [test_eval.json]
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
    storage=os.environ["POSTGRESQL_OPTUNA_DSN"],   # 공유 storage (PostgreSQL optuna DB)
    direction="maximize",
    load_if_exists=True,        # 이미 있으면 이어서 탐색
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
import catalog                       # catalog 접근 계층

catalog.ensure_schema()              # datasets 테이블 멱등 생성 (flow 시작 시 1회)
catalog.register("sydney_202605", "v2", "s3://datasets/sydney_202605/v2/",
                 created_by="zoo", prefect_run_id="<run_id>",
                 metadata={"fab": "fab2", "chamber": "CH3"})   # metadata (dict) → JSONB
rows = catalog.find("sydney_202605", fab="fab2")               # 검색 (dataset_id + metadata 키)
```

### Lineage

`catalog` 레코드의 `prefect_run_id` (데이터를 만든 실행) 와, MLflow run 태그에 기록하는 입력 데이터 버전을 **서로 참조** 해 두면 데이터 ↔ 코드 ↔ 결과를 양방향으로 추적할 수 있습니다.

```
데이터(버전) ──사용──▶ 코드(Prefect run) ──생성──▶ 결과(MLflow run / 모델)
     ▲                                                      │
     └────────────────  역추적 (결과 → 데이터)  ◀──────────┘
```

- **순방향** — 어떤 데이터 버전을 어떤 flow run 이 만들었고, 그 run 에서 나온 MLflow run·모델이 무엇인지 추적합니다.
- **역방향** — 운영 모델의 MLflow run 태그 (`input_dataset`/`input_version`) → `catalog.find(...)` → `minio_path` 로 원본까지 거슬러 올라갑니다.

### Output Placement & Name Collision

전 팀원이 같은 MinIO 버킷에 결과물을 쓰므로 이름이 겹칠 수 있습니다. MLflow run (`run_id`)·Prefect run (`id`)·Optuna trial (`study_name`+`number`) 은 **자동으로 격리** 되고, 직접 저장하는 파일만 경로에 고유 키를 넣어 분리합니다.

```python
# member / experiment 는 job 설정·환경변수·flow 파라미터 중 하나로 받는다.
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

> 위에서 코드가 **직접 접속**하는 곳은 MinIO 와 PostgreSQL 의 `catalog`·`optuna` DB 뿐입니다 — `mlflow`·`prefect` DB 는 MLflow server·Prefect server 가 대신 접속합니다. 자격증명 (`MINIO_*` / `POSTGRESQL_CATALOG_DSN` / `POSTGRESQL_OPTUNA_DSN`) 셋업은 [prefect.md](../Docker/Prefect/prefect.md) §6 Credentials, DB 별 권한 분리는 [postgresql.md](../Docker/PostgreSQL/postgresql.md) §5 를 참고합니다.

---

## 7. Orchestrator

오케스트레이터 flow 는 job 설정 (member·experiment·n_trials 등) 을 읽어 각 단계 (`train_dp` … `test_eval`) 를 `@task` 로 감싸 순서대로 실행하고, 각 단계 산출물을 MinIO 에 업로드한 뒤 catalog 에 등록합니다.

```python
@flow(name="ai-full-pipeline")
def full_pipeline():
    config = load_config()
    catalog.ensure_schema()                     # 테이블 보장 (멱등)
    ctx = _make_ctx(config)                      # member/experiment/version/run_id (train·test 공유)
    model_dir = training_pipeline(config, ctx)
    test_pipeline(model_dir, ctx)
```

- **버전**: `ctx["version"] = "run-<runid8>"` — 한 번 돌릴 때마다 새 데이터 버전이 생기고 `prefect_run_id` 로 계보가 연결됩니다.
- **graceful**: catalog/MinIO 가 떠 있지 않아도 (스택 미기동) 등록·업로드는 경고만 출력하고 로컬 파이프라인은 끝까지 실행됩니다.

### Execution

server 연결 (`PREFECT_API_URL`) 을 설정한 뒤 (상세는 [prefect.md](../Docker/Prefect/prefect.md) §5·§6), 다음 방식으로 실행합니다.

- **Docker work pool (주력)** — 팀 공통 이미지 (Pipeline Flow) 로 deployment 를 등록한 뒤 `prefect deployment run "pipeline/<deployment>" -p git_commit=<commit> -p minio_version=<ver>` 로 trigger 하면, 디스패처가 job 마다 컨테이너를 띄우고 그 컨테이너가 `git checkout <commit>` 후 실행합니다. 팀원마다 자기 커밋을 넘겨 동시에 독립 실행할 수 있습니다.
- **Serve mode (단순)** — `full_pipeline.serve(name="...")` 로 등록·대기시킨 뒤 trigger 합니다. `.serve()` 를 띄운 프로세스가 직접 실행하므로 단일 머신·단순 구성에 적합합니다.

> 버전 고정 (git_commit = 코드 버전, 이미지 태그 = 런타임 버전, minio_version = 데이터 버전) 의 상세는 [prefect.md](../Docker/Prefect/prefect.md) §7 을 참고합니다. 실행 결과는 Prefect 대시보드 (http://localhost:4200) 의 Flow Runs 에서 확인합니다.

---

## 8. Inference

학습이 끝나 MLflow 레지스트리에 `Production` 으로 승격된 모델을 불러와 추론하는 단계입니다. 여기서도 **Prefect 는 실행·재시도·로깅을, MLflow 는 모델의 실제 다운로드·로드를** 맡아 역할을 나눕니다.

```python
from prefect import task, flow
import mlflow

@task(retries=3)                       # ← Prefect 의 역할: 실행·재시도·로깅
def load_prod_model():
    return mlflow.pyfunc.load_model(   # ← MLflow 의 역할: 실제 다운로드·로드
        "models:/mnist-classifier/Production")

@flow
def inference_flow():
    model = load_prod_model()
    ...
```

- **Prefect (`@task(retries=3)` / `@flow`)** — 언제·어떤 순서로 실행할지, 실패 시 재시도·로깅을 맡습니다.
- **MLflow (`mlflow.pyfunc.load_model`)** — `models:/mnist-classifier/Production` 으로 레지스트리에서 실제 모델을 내려받아 로드합니다.
