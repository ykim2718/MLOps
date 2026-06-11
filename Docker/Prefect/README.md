# AI/ML Workflow Automation — Prefect + MinIO + MLflow + Optuna + PostgreSQL

Prefect 3 기반 AI 학습 파이프라인을 Docker로 띄우고 실행하기 위한 환경입니다.

이 프로젝트는 **Prefect를 "실행 오케스트레이터"로 두고**, 실험 추적·하이퍼파라미터 튜닝·데이터 보관/버전관리를 담당하는 다른 도구들과 **역할을 나눠 함께 쓰는 것**을 목적으로 합니다.

> "언제·무엇을·어떤 순서로 실행할지"는 Prefect가, "그 실행에서 나온 실험 기록·튜닝 결과·데이터/모델"은 각 도구가 맡습니다.

---

## 0. Overview

### Workflow의 목적 (What This Workflow Is For)

이 워크플로우는 여러 팀원이 한 서버를 공유하며 AI 학습을 돌릴 때, **데이터·실험·결과를 잃어버리지 않고 추적·재현·공유**하기 위한 네 가지를 핵심 목표로 합니다.

1. **Data catalog & selective retrieval (데이터 카탈로그 & 선택적 다운로드)**
   팀원이 **메타데이터를 검색** → 원하는 데이터셋을 **선택** → 실제 **데이터를 다운로드**합니다. 전체를 받지 않고 필요한 것만 골라 받습니다. (메타데이터는 PostgreSQL `catalog` DB, 실제 데이터는 MinIO)

2. **Data version management (데이터 버전 관리)**
   데이터셋의 **제작 이력·메타데이터를 저장**하고, 갱신 시 **이전 버전을 보존**합니다. 팀원은 **원하는 버전을 선택**해 사용할 수 있습니다. (catalog DB의 버전 레코드 + MinIO 오브젝트 버저닝)

3. **End-to-end lineage — 양방향 (계보 추적)**
   **데이터 → 코드 → 결과**(어떤 데이터로 어떤 코드를 돌려 어떤 결과가 나왔는가), 그리고 **결과 → 데이터**(이 모델/결과가 어떤 데이터 버전에서 나왔는가)로 **양방향 역추적**이 가능합니다.

4. **Monitoring (모니터링)**
   **Prefect / MLflow / MinIO** 각 대시보드로 동시에 도는 작업과 결과 현황을 한눈에 관리합니다.

| 목적 | 담당 구성요소 | 대시보드 |
|------|---------------|----------|
| 데이터 검색·선택·다운로드 | PostgreSQL `catalog` + MinIO | MinIO Console (http://localhost:9001) |
| 데이터 버전 관리 | `catalog` 버전 레코드 + MinIO versioning | MinIO Console |
| 양방향 계보 추적 | `catalog` ↔ Prefect run ↔ MLflow run | MLflow / Prefect UI |
| 실행·실험·결과 모니터링 | Prefect / MLflow / MinIO | http://localhost:4200 · :5000 · :9001 |

### Stack

| 구성요소 | 역할 | 접속 |
|----------|------|------|
| **Prefect** | 파이프라인 **실행/스케줄링/모니터링** (오케스트레이션) | http://localhost:4200 |
| **MLflow** | 실험(params·metrics) **추적**, 모델 **레지스트리** | http://localhost:5000 |
| **Optuna** | **하이퍼파라미터 튜닝**(trial 탐색) | (study storage는 PostgreSQL) |
| **PostgreSQL** | 모든 도구의 **메타데이터 DB** (4개 논리 DB) | :5432 |
| **MinIO** | 실제 **대용량 데이터/모델/아티팩트** 저장 (S3 호환) | http://localhost:9001 |

```mermaid
flowchart LR
    subgraph users[팀원]
      M[Member]
    end

    subgraph orch[오케스트레이션]
      P[Prefect Server + Worker<br/>:4200]
    end

    subgraph track[실험 추적]
      ML[MLflow Server<br/>:5000]
      OP[Optuna<br/>study]
    end

    subgraph meta[메타데이터]
      PG[(PostgreSQL :5432)]
    end

    subgraph blob[오브젝트 스토리지]
      MN[(MinIO :9000 / 콘솔 :9001)]
    end

    M -->|flow 제출/트리거| P
    P -->|run 상태/로그| PG
    P -->|단계 실행| ML
    P -->|튜닝| OP
    ML -->|params·metrics| PG
    OP -->|trial 결과| PG
    M -->|catalog 검색| PG
    M -->|데이터 다운로드/업로드| MN
    ML -->|artifact| MN
    P -->|데이터/모델| MN
```

### PostgreSQL — 4 Logical Databases

하나의 PostgreSQL 인스턴스 안에 **도구별 메타데이터 전용 DB 4개**를 둡니다. (대용량 바이너리는 절대 DB에 넣지 않고 MinIO에 둡니다 — [3. The Stack](#3-the-stack-minio--mlflow--optuna--postgresql) 참고)

```mermaid
flowchart TD
    PG[(PostgreSQL)]
    PG --> prefect["prefect<br/>(Prefect backend store)"]
    PG --> mlflow["mlflow<br/>(MLflow backend store)"]
    PG --> optuna["optuna<br/>(Optuna study storage)"]
    PG --> catalog["catalog<br/>(data catalog)"]
```

| DB | 용도 |
|----|------|
| `prefect` | Prefect backend store — flow/task run 상태, 스케줄, 로그 메타 |
| `mlflow` | MLflow backend store — params, metrics, tags, run/registry 메타 |
| `optuna` | Optuna study storage — trial별 params·value·상태 |
| `catalog` | Data catalog — 데이터셋 메타데이터·버전 이력·계보(lineage) |

`docker-compose.yml`로 띄우는 서비스 구성 (실행 방법은 **Appendix A. Docker Setup** 참고):

| 서비스 | 역할 | 비고 |
|--------|------|------|
| `postgres` | 메타데이터 DB (위 4개 논리 DB) | 대량 잡이면 SQLite 대신 권장 |
| `minio` | 오브젝트 스토리지 (실제 데이터/모델/아티팩트) | API :9000, 콘솔 :9001 |
| `mlflow` | MLflow 추적 서버 + 모델 레지스트리 | 브라우저: http://localhost:5000 |
| `server` | Prefect 서버 + 대시보드(UI) | 브라우저: http://localhost:4200 |
| `worker` | 실제 잡 실행 (동시 실행 수 제한) | `default` work pool, `--limit 8` |

---

## 1. About Prefect

**Prefect**는 데이터·AI/ML 파이프라인을 코드로 정의하고, 스케줄링·모니터링·재시도까지 자동화해 주는 **워크플로우 오케스트레이션(workflow orchestration) 도구**입니다. 공식 사이트: **https://www.prefect.io/**

### Key Features

- **순수 파이썬 + 데코레이터 기반**: 별도 DSL(Domain-Specific Language)이나 무거운 설정 없이, 기존 파이썬 함수에 `@flow` / `@task` 데코레이터만 붙이면 워크플로우가 됩니다. 학습 곡선이 낮습니다.
- **자동 재시도 · 상태 관리**: 태스크 실패 시 재시도(retry), 캐싱, 타임아웃 등을 선언적으로 설정할 수 있어 파이프라인이 견고해집니다.
- **관측성(Observability) 대시보드**: 웹 UI(기본 http://localhost:4200)에서 모든 flow/task run의 상태·로그·소요 시간·실패 지점을 실시간으로 확인할 수 있습니다.
- **유연한 스케줄링 & 트리거**: cron/interval 스케줄, 이벤트 기반 트리거, 수동 실행(1회성)까지 다양하게 지원합니다.
- **분산 실행(Worker / Work Pool)**: 워커와 work pool 구조로 잡을 분리 실행하고 **동시 실행 수를 제어**할 수 있어, 여러 팀원의 AI 학습 잡을 한 서버에서 관리하기에 적합합니다.
- **하이브리드 아키텍처**: 메타데이터(상태·로그)는 중앙 서버/DB가 관리하고, 실제 코드와 데이터는 사용자 인프라에서 실행되어 보안·확장성에 유리합니다.
- **다른 ML 도구와의 조합**: MLflow·Optuna·MinIO 등과 함께 써서 "실행 오케스트레이션은 Prefect, 실험 추적/튜닝/데이터 보관은 각 도구"로 역할을 나누기 좋습니다. ([3. The Stack](#3-the-stack-minio--mlflow--optuna--postgresql) 참고)

### Reusing Workflows (Flows)

한 번 정의한 flow는 **파라미터만 바꿔 여러 잡에 재사용**할 수 있는 것이 Prefect의 큰 장점입니다. 같은 학습 로직을 모델·데이터셋·실험별로 복붙하지 않아도 됩니다.

#### (1) Reuse the Same Flow via Parameters

```python
from prefect import flow, task

@task
def train_model(config):
    print(f"Epochs: {config['epochs']} / dataset: {config['dataset_path']}")
    return 0.95

@flow
def ai_training_pipeline(config: dict):
    return train_model(config)

# 동일한 flow를 설정만 바꿔 여러 번 재활용
ai_training_pipeline({"dataset_path": "s3://datasets/mnist",   "epochs": 10})
ai_training_pipeline({"dataset_path": "s3://datasets/cifar10", "epochs": 30})
```

#### (2) Compose/Reuse via Subflows

작은 flow를 하나의 "재사용 블록"으로 만들고, 상위 flow가 여러 번 호출해 분기(branch)처럼 활용합니다.

```python
@flow
def train_one(config: dict):          # 재사용 단위 (branch)
    return train_model(config)

@flow
def run_all_experiments(configs: list[dict]):
    # 같은 워크플로우 브랜치를 입력만 바꿔 반복 재활용
    return [train_one(cfg) for cfg in configs]

run_all_experiments([
    {"dataset_path": "s3://datasets/mnist",   "epochs": 10},
    {"dataset_path": "s3://datasets/cifar10", "epochs": 30},
])
```

#### (3) Reuse via Deployments with Different Parameters

같은 flow를 이름과 파라미터만 다르게 하여 여러 deployment로 등록해 두면, 팀원/실험별로 독립 실행할 수 있습니다. ([5. Method B](#method-b--register-as-a-deployment-and-trigger-on-demand) 참고)

```python
ai_training_pipeline.serve(name="member1-mnist",   parameters={"config": {"dataset_path": "s3://datasets/mnist",   "epochs": 10}})
ai_training_pipeline.serve(name="member2-cifar10", parameters={"config": {"dataset_path": "s3://datasets/cifar10", "epochs": 30}})
```

---

## 2. Prefect Configuration

이 꼭지는 Prefect 클라이언트가 **어느 서버에 연결할지**, 그리고 산출물·메타데이터를 **어디에 배치할지(placement)** 에 대한 설정을 모읍니다. (도커로 서버를 띄우는 방법은 **Appendix A. Docker Setup** 참고)

### Connecting to the Server

호스트(또는 팀원 PC)에서 도커로 띄운 Prefect 서버와 통신하도록 API 주소를 지정합니다. 최초 1회만 하면 됩니다.

```powershell
prefect config set PREFECT_API_URL="http://localhost:4200/api"
# 다른 PC의 서버에 붙으려면 localhost 대신 그 서버의 IP/호스트명 사용
prefect config view            # 현재 설정 확인
```

### Folder & Storage Structure

> **적용 범위**: 설치(최초 구성) 때만이 아니라, **모든 잡(run)에 항상 해당**합니다. 한 번 "메타데이터는 PostgreSQL, 실제 데이터는 MinIO"로 구조를 잡아두면, 이후 실행되는 모든 학습/평가 잡이 그 규칙을 따르게 됩니다.

- **대용량 데이터는 MinIO로 통일**: 데이터셋·모델 가중치·MLflow artifact·체크포인트를 모두 MinIO 버킷 하위 경로에 둡니다. (예: `s3://datasets/...`, `s3://models/...`, `s3://mlflow/...`)
- **DB(PostgreSQL)는 메타데이터 전용**: 대용량 바이너리를 절대 컬럼에 직접 넣지 않습니다. 넣으면 DB가 비대해지고 성능이 저하됩니다.
- **재현성**: DB의 메타데이터(어떤 데이터·하이퍼파라미터로 돌렸는지)와 MinIO의 실제 산출물(가중치·데이터셋)을 **경로(URI)/버전ID/해시로 연결**해 두면 실험 재현이 쉬워집니다. ([6. Data Catalog & Versioning](#6-data-catalog--versioning-minio--catalog) 참고)

예시 디렉터리 구조 — **서버(인프라)** 와 **팀원(잡 작성)** 영역을 나누어 정리합니다.

#### (1) Server-Side Layout — Configured Once by the Infra Owner

서버·워커·스토리지를 띄우는 기반 구조입니다. 한 번 만들어두면 모든 팀원이 공유합니다.

```
docker_prefect/                # 서버(인프라) 루트
├─ docker-compose.yml          # postgres + minio + mlflow + server + worker (Appendix A)
│                              #  └ 4개 DB 생성 init SQL 은 이 파일 안에 인라인(configs)
└─ (Docker 볼륨)
   ├─ pg-data                  #   PostgreSQL 메타데이터 (4개 논리 DB)
   └─ minio-data               #   MinIO 오브젝트 스토리지 (실제 데이터/모델/아티팩트)

MinIO 버킷 (실제 대용량 데이터, 전 팀원 공용)
├─ datasets/                   #   원천/가공 데이터셋 (버저닝 ON)
├─ models/                     #   학습된 모델 가중치/체크포인트
└─ mlflow/                     #   MLflow artifact store
```

#### (2) Team Member Job Folder — Written by Each Member

각 팀원은 자기 학습 **코드와 설정만** 만들면 됩니다. 이 폴더 안에는 코드만 두고, 실행 결과물은 여기에 쌓이지 않습니다(서버의 PostgreSQL/MinIO로 들어갑니다). (실제 동작 예시는 `example/` 폴더와 **Appendix C** 참고)

```
team_member_1/                 # 팀원별 작업 폴더 (코드/설정만 둠)
├─ prefect_run.py              # Prefect 오케스트레이터 (Appendix C)
├─ prefect_configuration.json  # 이번 잡의 설정 (member, experiment, n_trials 등)
└─ example/                    # 단계 스크립트 모음
   ├─ optuna.json              #   튜닝 설정
   ├─ train_dp.py  train_fe.py  train.py  train_eval.py
   └─ test_dp.py   test_fe.py   test.py   test_eval.py
```

#### Where Are Outputs Saved When You Run?

**팀원 폴더 (2)가 아니라, 서버 (1)의 PostgreSQL/MinIO에 저장됩니다.** 팀원 코드는 결과물을 자기 폴더에 쌓는 게 아니라, 서버에서 미리 준비한 **MinIO 버킷과 추적 서버를 참조**해 그쪽에 기록합니다.

| 결과물 | 저장 위치 (서버 (1) 영역) |
|--------|---------------------------|
| 학습된 모델 가중치(`.pt` 등) | MinIO `s3://models/...` |
| MLflow params·metrics | PostgreSQL `mlflow` DB |
| MLflow 모델·plot·파일(artifact) | MinIO `s3://mlflow/...` |
| Optuna trial 기록 | PostgreSQL `optuna` DB |
| 데이터셋 + 버전·메타데이터 | 실제 데이터 → MinIO `s3://datasets/...`, 메타 → PostgreSQL `catalog` DB |
| flow/task run 상태·로그 메타 | PostgreSQL `prefect` DB |

#### How to Avoid Name Collisions

전 팀원이 같은 MinIO 버킷에 결과물을 쓰기 때문에 이름이 겹칠 수 있습니다. 이를 피하는 방법은 **"일부는 도구가 자동으로, 일부는 약속된 경로 규칙(convention)으로"** 처리합니다.

| 산출물 | 충돌 방지 방식 | 비고 |
|--------|----------------|------|
| MLflow run | **자동** — `run_id`(고유값)별 폴더로 분리 | `s3://mlflow/<experiment>/<run_id>/...` |
| Prefect run | **자동** — flow run마다 고유 `id`/이름 부여 | 대시보드에서 run 단위로 구분 |
| Optuna trial | **자동** — `study_name` + `trial.number` | study가 다르면 자동 격리 |
| 직접 저장하는 파일(모델·parquet·json) | **규칙 필요** — 경로에 고유 키를 포함 | 아래 규칙 적용 |

직접 저장하는 파일은 경로에 **고유 키**(팀원/실험/run id 등)를 넣어 네임스페이스를 분리합니다. 이때 `member`·`experiment` 값은 **잡 설정 파일(`prefect_configuration.json`)에서 읽어옵니다.**

```python
import json
from prefect.runtime import flow_run

# member / experiment 를 받는 방법 (택1)
#  ① 설정 파일에서:  prefect_configuration.json
#  ② 환경변수에서:   os.environ["MEMBER"]
#  ③ flow 파라미터로: @flow def pipe(member, experiment): ...
cfg = json.load(open("prefect_configuration.json", encoding="utf-8"))
member, experiment = cfg["member"], cfg["experiment"]

run_id = flow_run.get_id()                       # Prefect가 주는 고유 run id
# MinIO 오브젝트 키에 고유 네임스페이스를 넣어 충돌 방지
out_uri = f"s3://models/{member}/{experiment}/{run_id}/model.pt"
# 예) s3://models/member1/mnist-resnet50/9f3c.../model.pt
```

> 정리: `member`·`experiment`는 **config 파일·환경변수·flow 파라미터 중 하나로 코드가 직접 받습니다**(이 프로젝트는 `prefect_configuration.json` 사용). MLflow·Prefect·Optuna 산출물은 고유 ID로 자동 격리되므로, 사람이 신경 쓸 부분은 **"직접 파일을 저장하는 MinIO 키"뿐**입니다. (날짜·랜덤 접미사보다 **run id / 데이터 해시**가 재현·추적에 유리합니다.)

---

## 3. The Stack: MinIO + MLflow + Optuna + PostgreSQL

Prefect · MLflow · Optuna · (데이터) catalog는 공통적으로 **DB에는 "메타데이터"만 저장**합니다.
모델 가중치·데이터셋·plot 같은 **실제(대용량) 데이터는 DB에 넣지 말고**, **MinIO(오브젝트 스토리지, Appendix B 참고)** 에 두고 **경로(URI)/버전ID만 DB가 참조**하도록 배치하는 것이 원칙입니다.

> 핵심 원칙: **DB = 작은 구조화 메타데이터, 대용량 바이너리 = MinIO + 경로 참조**

| 도구 | DB(PostgreSQL)에 저장되는 메타데이터 | 실제 데이터는 어디에? |
|------|--------------------------------------|------------------------|
| **Prefect** (`prefect` DB) | flow/task run 상태, 스케줄, 로그 메타, 파라미터 | 큰 결과물은 MinIO에 저장하고 run이 경로만 참조 |
| **MLflow** (`mlflow` DB) | params, metrics, tags (backend store) | 모델·plot·파일은 **artifact store** → MinIO `s3://mlflow/...` |
| **Optuna** (`optuna` DB) | trial별 params, value, 상태 (RDB storage) | 모델 체크포인트는 MinIO에 저장하고 경로를 `trial.set_user_attr()`로 기록 |
| **Catalog** (`catalog` DB) | 데이터셋 이름·버전·해시·스키마·계보 | 실제 데이터셋은 MinIO `s3://datasets/...` |

#### Optuna Study Storage

Optuna는 trial 결과를 어딘가에 저장하는데, 그 위치를 `create_study(storage=...)`로 지정합니다. 이 스택에서는 **PostgreSQL `optuna` DB를 공유 storage로 사용**합니다.

```python
import optuna
study = optuna.create_study(
    study_name="mnist-resnet50",
    storage="postgresql://postgres:postgres@localhost:5432/optuna",
    direction="maximize",
    load_if_exists=True,        # 이미 있으면 이어서 탐색
)
```

- **공유 DB(이 스택의 기본)**: `postgresql://.../optuna`. 여러 워커·여러 PC가 **하나의 study를 분산 병렬로 탐색**하거나, study 기록을 중앙에서 보존·재조회할 때 유리합니다.
- **로컬 파일 DB(대안)**: `storage="sqlite:///optuna.db"`. 단일 PC에서 study별로 가볍게 쓸 때 적합합니다.
- **지정 안 하면(기본값)**: in-memory. 프로세스가 끝나면 trial 기록이 사라집니다. 단발 스크립트 전용.

> 어느 쪽이든 Optuna가 DB에 넣는 것은 **trial 메타데이터(파라미터·점수)뿐**이고, 모델 가중치 같은 실제 산출물은 DB가 아니라 MinIO에 저장합니다(아래 참고).

#### Where to Store the Best Models (Weights)?

모델 가중치는 trial마다 생기므로, 보통 **best N개(예: best 5)만 남기고 나머지는 정리**합니다. 저장 위치는 "이 모델을 **나중에 누가·어디서 다시 쓰느냐**"로 정합니다.

| 상황 | 권장 저장 위치 |
|------|----------------|
| 나 혼자 실험, 그 PC에서만 사용 | 로컬 디스크 → 끝나면 MinIO로 업로드 |
| 결과를 팀과 공유 / 다른 PC에서 로드 / 백업 필요 | **MinIO**(`s3://models/...`) 또는 **MLflow Model Registry** |
| best 모델을 버전관리하고 배포·서빙까지 | **MLflow Model Registry** (가장 깔끔) |

```python
# 1) trial마다 MinIO에 저장하고, 경로를 trial 메타데이터로 기록
uri = f"s3://models/{study_name}/trial_{trial.number}.pt"
upload_to_minio(local_path, uri)
trial.set_user_attr("model_uri", uri)     # DB엔 "경로"만 남김

# 2) study 종료 후 best 5만 남기고 나머지 체크포인트 삭제
top5 = sorted(study.trials, key=lambda t: t.value, reverse=True)[:5]
keep = {t.user_attrs["model_uri"] for t in top5}
# keep에 없는 오브젝트 삭제

# 3) (선택) 공유·배포가 필요할 때만 best 모델을 MLflow Registry로 등록
```

> 요약: 개별 실험이면 best 5는 **MinIO로 충분**합니다. 배포·서빙까지 가면 그 모델을 **MLflow Model Registry**에 등록하면 됩니다. ([6. (6) Versioning, Deploying, and Serving](#6-data-catalog--versioning-minio--catalog) 참고)

---

## 4. Prefect Pipeline

`data preparation (dp) → feature engineering (fe) → training (train) → test` 순으로 진행할 때, 각 단계의 **산출물이 다음 단계의 입력으로 어떻게 연결**되는지를 정리합니다. 각 단계는 Prefect의 `@task`로 감싸고, `@flow`가 순서를 강제합니다(앞 단계 산출물이 있어야 다음 단계 실행). 실제 동작 코드는 `example/` 폴더와 **Appendix C**에 있습니다.

### Training Pipeline

```
[train raw parquet]
      │  train_dp.py        #data preparation
      ▼
[train transformed parquet] + [optuna.json]
      │  train_fe.py        #feature engineering
      ▼
[train_feature.parquet]  +  [fe_train.json] + [optuna.json]
      │  train.py
      ▼
[model folder] + [train.json]
      │  train_eval.py     #학습셋 성능 평가
      ▼
[train_eval.json]                                # 학습셋 평가 결과
```

### Test Pipeline (reuses model/ and fe_train.json)

```
[test raw parquet]
      │  test_dp.py         #data preparation
      ▼
[test transformed parquet]
      │  test_fe.py         #feature engineering: fe_train.json 재사용
      ▼
[test_feature.parquet]  +  [fe_test.json] + [train model folder]
      │  test.py
      ▼
[test.json]                                      # 테스트 추론 결과
      │  test_eval.py
      ▼
[test_eval.json]                                 # 테스트셋 평가 결과
```

> **train ↔ test 연결의 핵심**: test는 두 가지를 train 단계에서 그대로 가져옵니다 — ① `model/ folder`(학습된 모델), ② `fe_train.json`(train에 fit된 변환기). 변환을 test에 새로 fit하면 train/test skew가 생기므로, **fe는 train에서 fit하고 test에는 그 결과(`fe_train.json`)를 적용**해야 합니다. (`fe_test.json`은 적용 결과/메타로 남깁니다.)

### Every Stage Uses MinIO, MLflow, and Optuna

**원칙: `dp · fe · train · test`(및 eval) 모든 단계를 세 도구로 감쌉니다.**

- **MinIO**: 각 단계의 **입력을 버킷에서 내려받고(download)**, **출력을 버킷에 올립니다(upload)**. catalog에 버전·계보를 기록합니다.
- **MLflow**: 각 단계의 **파라미터·지표·산출물을 같은 run 아래 로깅**합니다.
- **Optuna**: 각 단계의 **튜닝 가능한 설정(`optuna.json`)을 탐색**합니다. (test는 학습에서 고른 best 설정을 재사용)

| 단계 | MinIO (저장소) | MLflow (기록) | Optuna (튜닝/설정) |
|------|----------------|----------------|---------------------|
| **dp** (train_dp / test_dp) | raw `download` → transformed `upload` | 데이터 통계·단계 로그 | 정제 파라미터 탐색 |
| **fe** (train_fe / test_fe) | transformed `download` → feature+fe_meta `upload` | FE 파라미터·통계 | FE 하이퍼파라미터 탐색 |
| **train** | feature `download` → model+train.json `upload` | params·metrics·model | 모델 하이퍼파라미터 탐색 |
| **test** | feature+model `download` → test.json `upload` | 추론 metrics | 학습에서 고른 best 설정 로드·적용 |
| **eval** (train_eval / test_eval) | json `download` → eval.json `upload` | 평가 metrics | 평가 임계값 등 탐색(선택) |

```
Prefect @flow (순서 강제) — 모든 단계를 MinIO·MLflow·Optuna로 감쌈
  └─ train_dp → train_fe → train → train_eval
  └─ test_dp  → test_fe  → test  → test_eval
       각 단계 공통:
         ├─ MinIO:  입력 download / 출력 upload (+ catalog에 버전·계보 기록)
         ├─ MLflow: 단계 params·metrics·artifact 로깅
         └─ Optuna: optuna.json 기반 설정 탐색 (test는 best 설정 재사용)
```

각 도구가 Prefect와 맞물리는 지점:

- **Prefect ↔ MinIO/Catalog**: 각 단계 **시작 전 입력 데이터를 MinIO에서 내려받아** "어떤 버전의 데이터/모델로 돌렸는지"를 고정하고, **끝에 산출물을 업로드**하면서 `catalog` DB에 버전·계보를 기록합니다. Prefect run id와 데이터 버전을 연결해 두면 재현이 쉬워집니다.
- **Prefect ↔ Optuna**: 튜닝을 각 단계의 task로 감싸 best 설정/하이퍼파라미터를 받아 다음 단계로 넘깁니다. (`objective`는 Optuna가 매 trial마다 호출해 하이퍼파라미터를 제안받고 점수를 반환하는 **목적 함수**입니다.)
- **Prefect ↔ MLflow**: 각 단계 task 안에서 `mlflow.log_*`로 params·metrics·산출물을 같은 run에 기록합니다. Prefect는 "실행 흐름", MLflow는 "실험 기록"을 담당해 역할이 겹치지 않습니다.

### Code: Wrapping Each Stage with MinIO + MLflow + Optuna

위 원칙을 코드로 옮기면, **모든 단계가 동일하게 MinIO(download/upload) · MLflow(log) · Optuna(설정 탐색)로 감싸집니다.** (MinIO 초기 셋업은 **Appendix B** 참고)

```python
from prefect import flow, task
from prefect.runtime import flow_run
import mlflow, boto3

# MinIO(S3 호환) 클라이언트
s3 = boto3.client("s3", endpoint_url="http://localhost:9000",
                  aws_access_key_id="minioadmin", aws_secret_access_key="minioadmin")

def download(uri, local):  # s3://bucket/key -> local
    bucket, key = uri[5:].split("/", 1); s3.download_file(bucket, key, local)

def upload(local, uri):    # local -> s3://bucket/key  (+ catalog 기록은 별도)
    bucket, key = uri[5:].split("/", 1); s3.upload_file(local, bucket, key)

@task
def train_dp():
    download("s3://datasets/train_raw.parquet", "train_raw.parquet")     # MinIO: 입력
    with mlflow.start_run(run_name="train_dp", nested=True):
        params = best_cfg("optuna.json", "dp")                          # Optuna: dp 파라미터
        run_dp("train_raw.parquet", "train_transformed.parquet", params)
        mlflow.log_params({f"dp_{k}": v for k, v in params.items()})    # MLflow
    upload("train_transformed.parquet", "s3://datasets/train_transformed.parquet")  # MinIO: 출력

@task
def train_fe():
    download("s3://datasets/train_transformed.parquet", "train_transformed.parquet")
    with mlflow.start_run(run_name="train_fe", nested=True):
        params = best_cfg("optuna.json", "fe")                          # Optuna: FE 하이퍼파라미터
        run_fe("train_transformed.parquet",
               out="train_feature.parquet", fe_meta="fe_train.json", params=params)
        mlflow.log_artifact("fe_train.json")                           # MLflow
    upload("train_feature.parquet", "s3://datasets/train_feature.parquet")
    upload("fe_train.json", "s3://datasets/fe_train.json")

@task
def train():
    download("s3://datasets/train_feature.parquet", "train_feature.parquet")
    run_id = flow_run.get_id()
    with mlflow.start_run(run_name="train", nested=True):
        best = tune("optuna.json")                                     # Optuna: 모델 하이퍼파라미터 탐색
        mlflow.log_params(best)
        acc = run_train("train_feature.parquet", "fe_train.json",
                        out_model="model/", out_meta="train.json", params=best)
        mlflow.log_metric("train_acc", acc)
        mlflow.log_artifacts("model/")                                # MLflow artifact -> MinIO
    upload("model/model.pt", f"s3://models/{run_id}/model.pt")        # MinIO: 모델

@task
def train_eval():
    with mlflow.start_run(run_name="train_eval", nested=True):
        metrics = run_eval("train.json", out="train_eval.json")
        mlflow.log_metrics(metrics)                                   # MLflow
    upload("train_eval.json", "s3://datasets/train_eval.json")

@flow                                                                 # ← Prefect가 순서를 강제
def training_pipeline():
    with mlflow.start_run(run_name="training"):                       # 부모 run
        train_dp(); train_fe(); train(); train_eval()
```

> test 파이프라인도 **완전히 동일한 패턴**입니다: `test_dp → test_fe(fe_train.json 재사용) → test(model/ 로드) → test_eval`의 각 단계를 똑같이 MinIO(download/upload) · MLflow(log) · Optuna(설정)로 감쌉니다. test 단계의 Optuna는 새로 튜닝하지 않고 **학습에서 고른 best 설정을 로드해 적용**합니다.

---

## 5. Running a Training/Test Pipeline

`prefect_run.py`(**Appendix C**)는 `prefect_configuration.json`을 읽어 `example/` 폴더의 단계들을 순서대로 실행하는 Prefect 오케스트레이터입니다. 설정 파일은 같은 폴더에 이미 준비되어 있습니다 ([prefect_configuration.json](prefect_configuration.json)).

```jsonc
// prefect_configuration.json
{
  "member": "member1",
  "experiment": "mnist-resnet50",
  "dataset_path": "s3://datasets/mnist",
  "epochs": 10,
  "n_trials": 20
}
```

서버 연결(`PREFECT_API_URL`)은 [2. Prefect Configuration](#2-prefect-configuration)에서 이미 설정했다고 가정합니다.

### Method A — Run Once Immediately (Simplest)

플로우를 직접 호출하면 **그 자리에서 즉시 1회 실행되고 종료**됩니다.
`prefect_run.py` 하단의 `.serve(...)` 대신 직접 호출만 해도 됩니다.

```python
# prefect_run.py 의 __main__ 을 아래처럼 바꾸면 1회 실행 후 종료
if __name__ == "__main__":
    full_pipeline()   # ← train + test 전체를 즉시 한 번 실행
```

```powershell
python prefect_run.py
```

실행 결과는 대시보드(http://localhost:4200)의 **Flow Runs**에서 확인할 수 있습니다.

### Method B — Register as a Deployment and Trigger On-Demand

현재 `prefect_run.py`는 끝부분이 `.serve(...)`로 되어 있습니다. 이 코드는 **즉시 실행이 아니라**, flow를 **배포(deployment)로 등록하고 그 자리에서 대기(listen)하는 "상시 대기형 서버 프로세스"** 입니다.

```python
# prefect_run.py 의 현재 __main__ (그대로 둔 경우)
if __name__ == "__main__":
    # .serve() = "지금 실행"이 아니라 "deployment로 등록 + 실행 요청을 계속 기다림"
    full_pipeline.serve(name="member1-mnist-resnet50")   # 실험 구분용 Job 이름
```

즉, `python prefect_run.py`를 실행하면 **바로 학습이 도는 게 아니라**, "member1-mnist-resnet50"이라는 deployment가 등록되고 프로세스가 **트리거(실행 요청)를 기다리는 상태**가 됩니다. 실제 실행은 아래처럼 별도로 트리거할 때 일어납니다.

```powershell
# 터미널 1: deployment 등록 + 대기 (이 창은 계속 실행 상태로 유지)
python prefect_run.py
```

```powershell
# 터미널 2: 등록된 deployment를 1회 실행하도록 트리거
prefect deployment run "ai-full-pipeline/member1-mnist-resnet50"
```

> `ai-full-pipeline`은 flow 이름(`@flow(name=...)`), `member1-mnist-resnet50`은 `.serve(name=...)`에 지정한 deployment 이름입니다.

#### Method A vs Method B

| 구분 | 방법 A (직접 호출) | 방법 B (`.serve` + deployment) |
|------|--------------------|-------------------------------|
| 실행 시점 | **즉시** 실행 후 종료 | **대기**하다가 트리거 받을 때 실행 |
| 성격 | 1회성 직접 실행 | 등록된 배포를 on-demand/스케줄로 실행 |
| 적합한 경우 | 빠른 단발 테스트 | 반복 실행·스케줄링·여러 팀원 잡 관리 |

> 한 번만 빠르게 돌릴 거라면 **방법 A**, 같은 워크플로우를 두고두고 트리거/스케줄로 재활용할 거라면 **방법 B**를 사용합니다.

---

## 6. Data Catalog & Versioning (MinIO + catalog)

여러 데이터셋·모델을 만들고 비교·재현·병렬 개발하려면 산출물(parquet·model·json)을 **버전 관리**하고, 무엇이 어디 있는지 **검색**할 수 있어야 합니다. 이 스택은 **"실제 데이터는 MinIO에, 가벼운 메타데이터·버전 이력·계보는 PostgreSQL `catalog` DB에"** 두는 방식으로 처리합니다.

> 핵심: **MinIO = 실제 데이터(버저닝 ON), `catalog` DB = 메타데이터·버전·계보 인덱스.**

#### Catalog Schema

`catalog`은 PostgreSQL `catalog` DB 안의 **테이블 하나**입니다. MinIO에 있는 실제 데이터를 가리키는 **메타데이터 장부**예요. 데이터 자체는 MinIO에, 그 데이터에 대한 **"설명·이력·위치"** 는 catalog에 둡니다.

```sql
CREATE TABLE datasets (
    id             SERIAL PRIMARY KEY,
    dataset_id     TEXT NOT NULL,        -- 'sydney_202605'
    version        TEXT NOT NULL,        -- 'v1', 'v2'
    minio_path     TEXT NOT NULL,        -- 's3://bucket/sydney_202605/v1/'
    created_by     TEXT,                 -- 'ykim'
    created_at     TIMESTAMP DEFAULT now(),
    n_files        INT,
    size_bytes     BIGINT,
    content_hash   TEXT,                 -- 무결성/중복 검증용
    prefect_run_id TEXT,                 -- 생성 flow 연결 (lineage)
    description    TEXT,                 -- 후보강
    metadata       JSONB,                -- 자유 확장 (fab, chamber, 측정조건...)
    UNIQUE(dataset_id, version)
);
```

- `UNIQUE(dataset_id, version)` — 같은 데이터셋의 같은 버전이 중복 등록되는 것을 막습니다(버전마다 한 행).
- `metadata JSONB` 가 핵심입니다 — **스키마를 바꾸지 않고** `{"fab": "fab2", "chamber": "CH3", "step": 5}` 같은 속성을 계속 보강할 수 있고, `metadata->>'fab' = 'fab2'` 처럼 검색도 됩니다.
- `prefect_run_id` 로 "이 데이터를 만든 실행"을 연결해 계보(lineage)를 추적합니다([(3) End-to-End Lineage](#3-end-to-end-lineage-양방향-계보) 참고).

#### 스키마를 코드로 반영하는 법 (권장)

**DB 생성과 테이블 생성을 분리**하는 것이 깔끔합니다.

- **DB(`catalog`) 생성** → 인프라 1회: `docker-compose.yml` 의 init SQL 이 컨테이너 최초 기동 시 만듭니다(Appendix A).
- **테이블(`datasets`) 생성** → **코드로 관리**: `CREATE TABLE IF NOT EXISTS` 를 작은 헬퍼 모듈에 두고 **flow 시작 시 멱등(idempotent)하게 호출**합니다. 스키마가 코드와 함께 버전 관리되고, 컬럼 추가 등 확장이 쉽습니다(대규모면 Alembic 같은 마이그레이션 도구 권장).

```python
# catalog.py — 카탈로그 스키마 정의 + 등록/검색 헬퍼 (flow 에서 import 해 사용)
import hashlib, psycopg2
from psycopg2.extras import Json, RealDictCursor

DSN = "postgresql://postgres:postgres@localhost:5432/catalog"

DDL = """
CREATE TABLE IF NOT EXISTS datasets (
    id             SERIAL PRIMARY KEY,
    dataset_id     TEXT NOT NULL,
    version        TEXT NOT NULL,
    minio_path     TEXT NOT NULL,
    created_by     TEXT,
    created_at     TIMESTAMP DEFAULT now(),
    n_files        INT,
    size_bytes     BIGINT,
    content_hash   TEXT,
    prefect_run_id TEXT,
    description    TEXT,
    metadata       JSONB,
    UNIQUE(dataset_id, version)
);
"""

def ensure_schema():
    """테이블이 없으면 만든다(있으면 그냥 통과). flow 시작 시 한 번 호출."""
    with psycopg2.connect(DSN) as c, c.cursor() as cur:
        cur.execute(DDL)

def register(dataset_id, version, minio_path, *, created_by=None,
             n_files=None, size_bytes=None, content_hash=None,
             prefect_run_id=None, description=None, metadata=None):
    """새 데이터셋 버전을 카탈로그에 등록. metadata 는 dict → JSONB."""
    with psycopg2.connect(DSN) as c, c.cursor() as cur:
        cur.execute(
            """INSERT INTO datasets
               (dataset_id, version, minio_path, created_by, n_files, size_bytes,
                content_hash, prefect_run_id, description, metadata)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (dataset_id, version) DO NOTHING""",
            (dataset_id, version, minio_path, created_by, n_files, size_bytes,
             content_hash, prefect_run_id, description, Json(metadata or {})))

def find(dataset_id=None, **filters):
    """이름/메타데이터로 검색. 예: find('sydney_202605', fab='fab2')"""
    sql = "SELECT * FROM datasets WHERE TRUE"
    args = []
    if dataset_id:
        sql += " AND dataset_id = %s"; args.append(dataset_id)
    for k, v in filters.items():            # metadata JSONB 키로 필터
        sql += f" AND metadata->>%s = %s"; args += [k, str(v)]
    sql += " ORDER BY created_at DESC"
    with psycopg2.connect(DSN) as c, c.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, args)
        return cur.fetchall()
```

> Prefect flow 안에서는 `ensure_schema()` → 데이터 업로드 후 `register(...)` 순으로 호출하면, 데이터 생성과 동시에 카탈로그가 채워집니다. 검색은 `find('sydney_202605', fab='fab2')` 처럼 `metadata` 키로 바로 거를 수 있습니다.

### (1) Data Catalog & Selective Retrieval — 검색 → 선택 → 다운로드

팀원은 전체를 받지 않고, **메타데이터로 검색**해 원하는 데이터셋(과 버전)만 골라 내려받습니다.

```python
import boto3
import catalog                      # 위 catalog.py 헬퍼

s3 = boto3.client("s3", endpoint_url="http://localhost:9000",
                  aws_access_key_id="minioadmin", aws_secret_access_key="minioadmin")

# 1) 검색: dataset_id + metadata 키로 카탈로그 조회 (어떤 버전들이 있는지 확인)
for row in catalog.find("sydney_202605", fab="fab2"):
    print(row["dataset_id"], row["version"], row["minio_path"])

# 2) 선택 → 3) 다운로드: 고른 버전(minio_path)의 오브젝트만 MinIO에서 내려받기
chosen = catalog.find("sydney_202605")[0]          # 최신 버전 선택(예시)
bucket, prefix = chosen["minio_path"][5:].split("/", 1)   # 's3://bucket/key/' 분해
for obj in s3.list_objects_v2(Bucket=bucket, Prefix=prefix).get("Contents", []):
    s3.download_file(bucket, obj["Key"], obj["Key"].split("/")[-1])
```

### (2) Data Version Management — 이력 저장 · 이전 버전 보존 · 버전 선택

데이터셋을 갱신할 때 **이전 버전을 덮어쓰지 않고 보존**합니다. 버전을 **경로에 박아(`.../v1/`, `.../v2/`)** 새 버전은 새 경로로 올리고, `catalog` 테이블에는 **버전마다 새 레코드(행)** 를 추가합니다. 이전 버전의 경로·레코드는 그대로 남습니다.

```python
import catalog                      # 위 catalog.py 헬퍼

# 새 버전(v2)을 새 경로로 업로드 → 이전 v1 경로는 그대로 보존
new_path = "s3://datasets/sydney_202605/v2/"
upload_dir_to_minio("local_out/", new_path)        # 폴더 통째로 업로드(예시)

# catalog 에 "새 버전" 레코드 추가 (UNIQUE(dataset_id, version) 로 중복 방지)
catalog.register(
    dataset_id="sydney_202605", version="v2", minio_path=new_path,
    created_by="ykim", prefect_run_id=flow_run.get_id(),
    metadata={"fab": "fab2", "chamber": "CH3", "step": 5, "parent_version": "v1"},
)
```

> (선택) MinIO 버킷 자체의 versioning(`mc version enable local/datasets`, Appendix B)을 함께 켜두면, 실수로 같은 키를 덮어써도 오브젝트 단위로 한 번 더 보호됩니다. 다만 **버전 관리의 1차 수단은 "경로 분리 + catalog 레코드"** 입니다.

> 팀원은 `catalog`에서 원하는 `version`을 골라 그 `minio_path`에서 내려받으면(위 (1) 코드) 그 시점의 데이터를 그대로 복원합니다. 별도 버전관리 도구 없이 경로 규칙 + catalog 레코드만으로 재현이 가능합니다.

### (3) End-to-End Lineage (양방향 계보)

`catalog` 레코드의 `prefect_run_id`(데이터를 만든 실행)와, MLflow run에 태그로 박는 입력 데이터 버전을 **서로 참조**해 두면, 데이터 ↔ 코드 ↔ 결과를 양방향으로 추적할 수 있습니다.

```
데이터(버전)  ──사용──▶  코드(Prefect flow run)  ──생성──▶  결과(MLflow run / 모델)
     ▲                                                              │
     └──────────────────  역추적 (결과 → 데이터)  ◀────────────────┘
```

- **순방향 (데이터 → 코드 → 결과)**: 어떤 데이터 버전을 어떤 flow run이 만들었고, 그 run에서 나온 MLflow run·모델이 무엇인지.
  ```sql
  -- 이 데이터 버전을 만든 실행 찾기 → 그 prefect_run_id 로 MLflow run 검색
  SELECT prefect_run_id FROM datasets
  WHERE dataset_id='sydney_202605' AND version='v2';
  ```
- **역방향 (결과 → 데이터)**: 운영 중인 모델/결과에서 출발해, 그 MLflow run 태그 → 입력 데이터 버전 → catalog 레코드 → `minio_path` 로 원본까지 거슬러 올라가기.
  ```python
  # 모델의 MLflow run 태그에 입력 데이터 버전을 박아두면 즉시 역추적 가능
  import mlflow
  from prefect.runtime import flow_run
  with mlflow.start_run() as run:
      mlflow.set_tag("input_dataset", "sydney_202605")
      mlflow.set_tag("input_version", "v2")
      mlflow.set_tag("prefect_run_id", flow_run.get_id())
  # 나중에: run 태그(input_dataset/input_version) → catalog.find(...) → minio_path 로 원본 복원
  ```

> 권장: **MLflow run에는 입력 데이터의 `dataset_id`/`version`을, `catalog` 레코드에는 만든 `prefect_run_id`를**(필요하면 `metadata` JSONB에 `mlflow_run_id`도) 서로 기록(상호 참조)해 두면 어느 방향에서 출발해도 한 번에 추적됩니다.

### (4) Monitoring — 동시 작업·결과 현황

세 대시보드로 진행 상황을 동시에 관찰합니다.

| 대시보드 | 주소 | 무엇을 보는가 |
|----------|------|----------------|
| **Prefect** | http://localhost:4200 | flow/task run 상태·로그·소요 시간·실패 지점, 스케줄/배포 |
| **MLflow** | http://localhost:5000 | 실험별 params·metrics 비교, 모델 레지스트리/버전·Stage |
| **MinIO Console** | http://localhost:9001 | 버킷·오브젝트·버전, 용량, 데이터/모델 실제 보관 현황 |

> Prefect로 "지금 무엇이 도는지", MLflow로 "어떤 실험이 더 좋은지", MinIO로 "데이터/모델이 실제로 어떻게 쌓였는지"를 각각 봅니다.

### (5) Comparing & Parallel Development

데이터셋·실험별로 `catalog`에 버전을 나눠 쌓고, MLflow에서 metrics를 비교해 best를 고릅니다. Prefect deployment를 실험별로 등록하면 동시에 돌릴 수 있습니다.

```python
# MLflow 로 여러 run 의 지표 비교 (UI 또는 API)
from mlflow.tracking import MlflowClient
client = MlflowClient()
runs = client.search_runs(experiment_ids=["1"], order_by=["metrics.test_acc DESC"])
best = runs[0]
print(best.data.metrics, best.data.tags.get("input_version"))
```

```
exp/datasetA ──▶ model_A  ─┐
                           ├─ MLflow metrics 비교 → best 선택 → Registry 등록
exp/datasetB ──▶ model_B  ─┘
```

### (6) Versioning, Deploying, and Serving the Best Model

여러 실험에서 고른 **best 모델**을 버전 관리하고 실제로 쓰는 단계입니다. **MLflow Model Registry**로 모델에 **이름 + 버전 + 단계(Stage)** 를 부여해 "지금 운영에 쓰는 모델"을 한 곳에서 관리합니다(실제 가중치 파일은 MinIO artifact store에 저장).

#### 먼저, "서빙(Serving)"이란?

> **서빙 = 학습된 모델을 "예측 요청을 받아 응답하는 API 서비스"로 띄우는 것**입니다.
> 학습이 "모델을 만드는 것"이라면, 서빙은 그 모델을 **항상 켜진 엔드포인트(예: `POST /predict`)** 로 올려, 입력 데이터를 보내면 예측값을 돌려받게 하는 단계입니다.
> - **배포(Deploy)**: 어떤 모델 버전을 운영 위치(레지스트리 Stage)에 올리는 행위.
> - **서빙(Serve)**: 그 배포된 모델을 실제로 **추론 API로 구동**하는 행위.

#### 1) 버전 관리 + 배포 (MLflow Model Registry)

```python
import mlflow

# 학습 run에서 나온 모델을 레지스트리에 "이름 + 버전"으로 등록
mlflow.set_tracking_uri("http://localhost:5000")
mlflow.register_model(model_uri="runs:/<run_id>/model", name="mnist-classifier")
# → mnist-classifier v1, v2, ... 로 버전이 쌓임

# best 버전을 운영 단계로 승격(배포)
from mlflow.tracking import MlflowClient
MlflowClient().transition_model_version_stage(
    name="mnist-classifier", version=3, stage="Production")
```

#### 2) 서빙 (Serving) — 모델을 추론 API로 띄우기

```powershell
# MLflow가 레지스트리의 Production 모델을 REST API로 구동
mlflow models serve -m "models:/mnist-classifier/Production" -p 5001
```

```powershell
# 예측 요청 (POST /invocations 로 입력을 보내면 예측을 응답)
curl -X POST http://localhost:5001/invocations `
  -H "Content-Type: application/json" `
  -d '{"inputs": [[0.1, 0.2]]}'
```

> 정리: **MinIO = 실제 데이터/아티팩트 보관 + 버저닝**, **MLflow Registry = 이름·버전·Stage로 운영 모델을 관리 + 서빙**, **catalog DB = 데이터 검색·계보 인덱스**. Prefect는 이 등록·승격·서빙 기동까지 하나의 flow로 자동화할 수 있습니다.

---

## Appendix

### A. Docker Setup

`docker-compose.yml`이 있는 폴더에서 실행합니다.

```powershell
# 전체 스택을 백그라운드(detached)로 한 번에 실행
docker compose up -d
```

실행 후 접속:

- Prefect 대시보드: **http://localhost:4200**
- MLflow UI: **http://localhost:5000**
- MinIO 콘솔: **http://localhost:9001** (기본 계정 `minioadmin` / `minioadmin`)

#### Handy Commands

```powershell
docker compose up -d            # 백그라운드 실행 (창 닫아도 유지)
docker compose up -d --build    # 이미지를 새로 빌드하면서 실행

docker compose ps               # 컨테이너 상태 확인
docker compose logs -f server   # Prefect server 로그 실시간 보기
docker compose logs -f worker   # worker가 신호를 잘 받는지 확인
docker compose logs -f mlflow   # MLflow 로그
docker compose logs -f minio    # MinIO 로그

docker compose stop             # 컨테이너 정지 (제거하지 않음)
docker compose start            # 정지된 컨테이너 다시 시작
docker compose restart worker   # 특정 서비스만 재시작

docker compose down             # 정지 + 컨테이너/네트워크 제거 (볼륨은 유지)
docker compose down -v          # 볼륨까지 삭제 (DB/MinIO 데이터 초기화)
```

#### 4개 논리 DB 생성 (init SQL 인라인)

별도 `init-db.sql` 파일을 만들 필요 없이, **init SQL을 `docker-compose.yml` 안에 인라인**합니다(`configs.init_sql.content`). 이 config를 postgres 서비스의 `/docker-entrypoint-initdb.d/`에 마운트하면 컨테이너 **최초 기동 시 한 번** 실행되어 `prefect`/`mlflow`/`optuna`/`catalog` 4개 DB를 만듭니다. (아래 compose의 `configs:` 블록 참고)

> 데이터 카탈로그 **테이블(`datasets`)** 은 여기(인프라)서 만들지 않고 **코드로 멱등 생성**합니다 — [6. Catalog Schema](#catalog-schema)의 `ensure_schema()` 참고.

#### `docker-compose.yml`

```yaml
services:
  # 1) 메타데이터 DB — prefect/mlflow/optuna/catalog 4개 논리 DB를 한 인스턴스에서 운영.
  #    init SQL 은 아래 configs.init_sql 로 yml 안에 인라인(별도 파일 불필요).
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      # POSTGRES_DB 미지정(기본 DB=postgres). 4개 DB 는 init_sql 이 생성.
    volumes:
      - pg-data:/var/lib/postgresql/data
    configs:
      - source: init_sql
        target: /docker-entrypoint-initdb.d/init.sql   # 최초 기동 시 4개 DB 생성
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      retries: 10

  # 2) 오브젝트 스토리지 — 실제 대용량 데이터/모델/아티팩트 (S3 호환). 콘솔: http://localhost:9001
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

  # 3) MLflow 추적 서버 + 모델 레지스트리. backend=postgres, artifact=MinIO. UI: http://localhost:5000
  mlflow:
    image: ghcr.io/mlflow/mlflow:latest
    command: >
      bash -c "pip install --quiet psycopg2-binary boto3 &&
               mlflow server --host 0.0.0.0 --port 5000
               --backend-store-uri postgresql://postgres:postgres@postgres:5432/mlflow
               --artifacts-destination s3://mlflow"
    ports:
      - "5000:5000"
    environment:
      MLFLOW_S3_ENDPOINT_URL: http://minio:9000
      AWS_ACCESS_KEY_ID: minioadmin
      AWS_SECRET_ACCESS_KEY: minioadmin
    depends_on:
      postgres:
        condition: service_healthy
      minio:
        condition: service_healthy

  # 4) Prefect 서버 + 대시보드(UI). 브라우저: http://localhost:4200
  server:
    image: prefecthq/prefect:3-latest
    command: prefect server start --host 0.0.0.0
    ports:
      - "4200:4200"
    environment:
      PREFECT_SERVER_DATABASE_CONNECTION_URL: postgresql+asyncpg://postgres:postgres@postgres:5432/prefect
    depends_on:
      postgres:
        condition: service_healthy

  # 5) 워커: 실제로 잡을 실행. 동시 실행 수를 여기서 제한.
  worker:
    image: prefecthq/prefect:3-latest
    # default 라는 process work pool 에서 잡을 가져와 실행.
    # --limit 8 = 한 워커가 동시에 8개까지만 실행(자원에 맞춰 조정).
    command: >
      bash -c "prefect work-pool create default --type process --overwrite &&
               prefect worker start --pool default --limit 8"
    environment:
      PREFECT_API_URL: http://server:4200/api
    depends_on:
      - server

# init SQL 을 yml 안에 인라인 — postgres 의 configs 로 마운트되어 최초 1회 실행된다.
configs:
  init_sql:
    content: |
      CREATE DATABASE prefect;
      CREATE DATABASE mlflow;
      CREATE DATABASE optuna;
      CREATE DATABASE catalog;

volumes:
  pg-data:
  minio-data:
```

#### Operating Models (Worker Setup)

Prefect는 **"서버(=잡 대기열) 1개 + 워커 N개"** 구조라 운영 모델을 선택할 수 있습니다.

- **현재 compose 기본값**: 워커 1개, `--limit 8`(동시 8개 job 까지 실행). 팀원들은 보통 **잡(run)만 중앙 서버에 제출**하고, 이 공용 워커가 대신 실행하므로 팀원이 각자 워커를 띄울 필요가 없습니다.
- **워커를 늘리고 싶을 때(처리량을 높이려면)**: `docker compose up -d --scale worker=3` 처럼 워커를 여러 개로 확장합니다.
- **팀원이 각자 실행해야 하는 경우**: 각 팀원의 **로컬 GPU/자원**에서 학습을 돌려야 한다면, 팀원이 자기 PC에서 같은 work pool(`default`)에 워커를 붙이면 됩니다. (붙이는 방법은 **Appendix D** 참고)

### B. MinIO Setup (Object Storage)

**MinIO**는 **S3와 100% 호환되는 오픈소스 오브젝트 스토리지**입니다. 클라우드(AWS) 없이 사내 서버나 로컬 도커에 띄워 "내 S3"처럼 쓸 수 있어, MLflow artifact·데이터셋·모델의 보관 위치로 사용합니다.

- **S3 (Amazon Simple Storage Service)**: AWS의 오브젝트 스토리지. 파일을 "객체(object)" 단위로 저장하며, **버킷(bucket)** 이라는 최상위 공간 안에 키(경로)로 파일을 넣습니다.
- **버킷(bucket)**: 오브젝트를 담는 최상위 컨테이너. 예: `s3://datasets/...`, `s3://models/...`, `s3://mlflow/...`
- **버저닝(versioning)**: 같은 키로 다시 올려도 이전 오브젝트를 `version_id`로 보존하는 기능. 이 스택에서 데이터 버전 관리의 1차 수단은 "경로 분리(`/v1/`, `/v2/`) + catalog 레코드"이고, MinIO 버저닝은 **덮어쓰기 사고를 막는 보조 안전장치**입니다([6. (2)](#2-data-version-management--이력-저장--이전-버전-보존--버전-선택) 참고).

#### 1) 버킷 만들기 + 버저닝 켜기 (`mc` CLI)

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

> 버킷은 MinIO 콘솔(http://localhost:9001)에서 GUI로 만들 수도 있습니다.

#### 2) 코드에서 접근 (boto3 / S3 호환)

```python
import boto3
s3 = boto3.client(
    "s3",
    endpoint_url="http://localhost:9000",      # MinIO 주소 (S3면 생략)
    aws_access_key_id="minioadmin",
    aws_secret_access_key="minioadmin",
)
s3.upload_file("model.pt", "models", "member1/mnist-resnet50/model.pt")
s3.download_file("datasets", "mnist-train.parquet", "mnist-train.parquet")
```

> 정리: **MinIO = 직접 설치하는 S3 호환 스토리지, 버킷 = 그 안의 파일 저장 공간.** 코드/설정에서 S3 주소만 MinIO 주소(`endpoint_url`)로 바꾸면 그대로 동작하므로, 로컬·온프레미스에서 S3를 대체할 수 있습니다.

### C. `prefect_run.py` + `example/` Stage Scripts

`prefect_run.py`는 `example/` 폴더의 단계 스크립트(`train_dp.py` … `test_eval.py`)를 `@task`로 감싸 순서대로 실행하는 오케스트레이터입니다.

```
docker_prefect/
├─ prefect_run.py              # 오케스트레이터 (아래 코드)
├─ prefect_configuration.json  # member / experiment / n_trials 등
└─ example/
   ├─ optuna.json
   ├─ train_dp.py  train_fe.py  train.py  train_eval.py
   └─ test_dp.py   test_fe.py   test.py   test_eval.py
```

```python
# team_member_1/prefect_run.py
import json, os, sys
from prefect import flow, task

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(THIS_DIR, "example"))

import train_dp, train_fe, train as train_mod, train_eval
import test_dp, test_fe, test as test_mod, test_eval


def load_config():
    # member / experiment 를 config 파일에서 읽는다 (환경변수/flow 파라미터로도 가능)
    with open(os.path.join(THIS_DIR, "prefect_configuration.json"), encoding="utf-8") as f:
        return json.load(f)


@task
def pull_data():
    print("[pull_data] MinIO 에서 raw 데이터 download  (예시)")

@task
def t_train_dp():   return train_dp.run()
@task
def t_train_fe():   return train_fe.run()
@task
def t_train(out_model): return train_mod.run(out_model=out_model)
@task
def t_train_eval(): return train_eval.run()
@task
def t_test_dp():    return test_dp.run()
@task
def t_test_fe():    return test_fe.run()
@task
def t_test(model_dir): return test_mod.run(model_dir=model_dir)
@task
def t_test_eval():  return test_eval.run()


@flow(name="ai-training-pipeline")
def training_pipeline(config: dict):
    # 이름 충돌 방지: member/experiment 로 출력 경로(MinIO 키)를 분리
    out_model = f"s3://models/{config['member']}/{config['experiment']}/model/"
    pull_data(); t_train_dp(); t_train_fe(); t_train(out_model); t_train_eval()
    return out_model

@flow(name="ai-test-pipeline")
def test_pipeline(model_dir: str):
    t_test_dp(); t_test_fe(); t_test(model_dir); t_test_eval()

@flow(name="ai-full-pipeline")
def full_pipeline():
    config = load_config()
    model_dir = training_pipeline(config)
    test_pipeline(model_dir)


if __name__ == "__main__":
    # 방법 A) 즉시 1회:  full_pipeline()
    # 방법 B) 배포 등록 + 트리거 대기:
    full_pipeline.serve(name="member1-mnist-resnet50")
```

> 각 단계 스크립트는 단독 실행도 가능합니다(`python example/train_dp.py`). `objective`(Optuna 목적 함수)의 의미는 `example/train.py`의 주석을 참고하세요.
>
> 참고: `example/`의 단계 스크립트는 **흐름을 보여주는 최소 stub**이라 MinIO/MLflow 호출은 생략했습니다. **모든 단계를 MinIO·MLflow·Optuna로 감싸는 실제 패턴**은 [4. Prefect Pipeline](#4-prefect-pipeline)의 "Wrapping Each Stage with MinIO + MLflow + Optuna" 코드를 참고하세요.

### D. Attaching a Worker to a Work Pool from a Local PC

Prefect의 **서버**(잡 대기열·대시보드)와 **워커**(실제 실행 주체)는 분리되어 있습니다. 따라서 팀원은 도커 서버를 건드리지 않고, **자기 PC에서 워커만 띄워 같은 서버의 work pool에 붙일 수 있습니다.** 그러면 그 팀원에게 배정된 잡은 팀원의 로컬 자원(GPU 등)에서 실행됩니다.

**전제**: 팀원 PC에서 도커 서버(`http://<서버주소>:4200`)에 네트워크로 접근 가능해야 합니다.

```powershell
# 1) 로컬 PC에 Prefect 설치
pip install prefect

# 2) 어느 서버에 붙을지 지정 (도커로 띄운 서버 주소)
#    같은 PC면 localhost, 다른 PC의 서버면 그 PC의 IP/호스트명 사용
prefect config set PREFECT_API_URL="http://<서버주소>:4200/api"

# 3) (work pool이 아직 없다면 한 번만) process 타입 풀 생성
#    compose는 'default' 풀을 이미 만들어두므로 보통 생략 가능
prefect work-pool create default --type process

# 4) 같은 'default' 풀에 워커를 붙여 대기 (이 창은 실행 상태로 유지됨)
prefect worker start --pool default
```

이렇게 하면 도커의 공용 워커와 **로컬 워커가 같은 `default` 풀**을 함께 바라보게 되고, 잡이 가용한 워커로 분산 실행됩니다.

> 풀을 팀원별로 나누고 싶다면(예: 팀원2 잡은 팀원2 PC에서만 실행), 별도 풀을 만들고 그 풀로 워커를 띄우면 됩니다.
> ```powershell
> prefect work-pool create member2-pool --type process
> prefect worker start --pool member2-pool
> ```
> 그리고 해당 잡의 deployment를 그 풀로 지정하면, 그 풀에 붙은 워커(=팀원2 PC)에서만 실행됩니다.
>
> 폴더의 `config_prefect.ps1`이 바로 이 "로컬 PC에서 워커 붙이기"를 자동화한 스크립트입니다(풀 이름은 compose의 `default`와 통일되어 있습니다).
