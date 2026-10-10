# Prefect Concepts
Rev. 0 | Created: 2026-10-10 | Updated: 2026-10-10 15:07 CDT

- [1. Purpose](#1-purpose)
- [2. Summary](#2-summary)
- [3. Execution Architecture](#3-execution-architecture)
- [4. Job Triggering](#4-job-triggering)
  - [4.1 Prefect CLI](#41-prefect-cli)
  - [4.2 Python SDK](#42-python-sdk)
  - [4.3 Serve Mode](#43-serve-mode)
- [5. Prefect CLI](#5-prefect-cli)
- [6. Prefect @task](#6-prefect-task)
  - [6.1 Reproducing without @task](#61-reproducing-without-task)
  - [6.2 Why Use @task Then](#62-why-use-task-then)
  - [6.3 Summary](#63-summary)
- [Appendix A. Terminology](#appendix-a-terminology)
- [Appendix B. Orchestrator Benchmarking](#appendix-b-orchestrator-benchmarking)
  - [B.1 Prefect vs Dagster vs Airflow](#b1-prefect-vs-dagster-vs-airflow)
  - [B.2 Execution Pattern Across Systems](#b2-execution-pattern-across-systems)
  - [B.3 What a Pod Is](#b3-what-a-pod-is)
  - [B.4 job · task · step Compared](#b4-job--task--step-compared)

## 1. Purpose

- **Problem Statement**: Prefect 의 실행 구조, trigger 방법, CLI, `@task` 같은 일반 지식이 특정 stack 의 설치 문서에 섞여 있으면, 다른 stack 을 꾸리는 사람이 그 stack 의 사정을 걷어내며 읽어야 합니다.
- **Goal**: 실무자가 이 문서만으로 Prefect 의 실행 모드와 work pool type 을 고르고, deployment 를 CLI 나 SDK 로 trigger 하고, 자주 쓰는 CLI 와 `@task` 의 쓰임을 판단할 수 있게 합니다.
- **Non-Goal**: 특정 stack 의 설치, folder 구성, script 는 다루지 않습니다. Prefect 의 API 전체는 다루지 않습니다.

## 2. Summary

Prefect server 는 실행 정의 (deployment) 와 기록만 보관하고, 누가 코드를 실행할지는 실행 모드 (serve mode 또는 work pool) 가 정합니다. Deployment 는 어느 모드에서나 CLI 나 Python SDK 로 같은 방식으로 trigger 하며, 실행 기록과 재현은 `@flow` 만으로 되고 `@task` 는 부분 재시도와 caching 을 더합니다.

## 3. Execution Architecture

Prefect 실행 모드는 **serve mode** 와 **work pool mode** 이고, 차이는 **누가 코드를 실행하느냐** 입니다. work pool 은 type (`process`·`docker`·`kubernetes`) 에 따라 실행 주체가 달라집니다.

Table 1. Execution modes and work pool types

| Mode | Register | Code executor | Isolation | Best for |
| :---: | :---: | :---: | :---: | :---: |
| Serve Mode | `flow.serve()` | serve python | 단일 프로세스 | 단일 머신·단순 |
| Work Pool (`process`) | `flow.deploy()`<br>`prefect work-pool create --type process` | worker 컨테이너의 subprocess | worker 와 같은 컨테이너 | 격리 불필요·경량 |
| Work Pool (`docker`) | `flow.deploy()`<br>`prefect work-pool create --type docker` | flow 컨테이너 | run 마다 컨테이너 격리 | 다수 사용자·동시 실행 |
| Work Pool (`kubernetes`) | `flow.deploy()`<br>`prefect work-pool create --type kubernetes` | flow pod | run 마다 pod 격리 | 클러스터·대규모 |

- **공통 — 등록** — **server 는 코드를 실행하지 않습니다** (이름표만 보관).
- **핵심 차이 — 실행 주체** — work pool type 이 실행 주체를 정합니다. `process` 는 worker 가 자기 컨테이너 안 subprocess 로, `docker` 는 job 마다 뜨는 flow 컨테이너가, `kubernetes` 는 job 마다 뜨는 pod 가 실행합니다. 그 실행 주체의 이미지에 라이브러리가 있어야 합니다.
- **serve mode** — 단일 머신·소규모 구성에는 work pool 없이 `flow.serve()` 만 띄우는 serve mode 가 더 단순합니다.

## 4. Job Triggering

등록된 deployment 를 실제로 돌리는 (trigger) 방법은 여러 가지지만, 결국 모두 **server 의 Prefect API 에 "flow run 생성" 요청을 보내는 것**입니다 — 코드가 아니라 **deployment 이름 + 파라미터 값** 만 보냅니다. **trigger 인터페이스 (CLI·SDK) 는 실행 모드와 무관하게 같고**, 실제 실행 주체는 **실행 모드** 가 정합니다 ([§3](#3-execution-architecture)). 그래서 아래 §4.1·§4.2 는 두 모드 공통의 trigger 인터페이스이고, §4.3 이 serve mode 의 차이를 다룹니다.

> ⚠️ flow 함수를 Python 에서 직접 부르면 work pool 을 거치지 않고 부른 process 안에서 바로 실행되므로, 컨테이너 격리가 없고 deployment 와도 이어지지 않습니다. 아래 [§4.2](#42-python-sdk) 의 SDK trigger 는 `run_deployment` 입니다.

Table 2. CLI and SDK triggers

| Aspect | Prefect CLI | Python SDK |
| :---: | :---: | :---: |
| 호출 | `prefect deployment run "<flow>/<deployment>"` | `run_deployment(name=…)` |
| 파라미터 | `-p key=value` (문자열) | `parameters={…}` (파이썬 타입) |
| 반환 | run id 출력 후 종료 | `FlowRun` 객체 |
| 완료 대기 | 기본 안 함 (`--watch` 로 따라감) | 기본 대기 (`timeout=0` 이면 즉시) |
| 주 용도 | 수동·셸·CI 스텝 | 코드 내 자동 trigger·chaining |

### 4.1 Prefect CLI

  사람이 셸에서, 또는 CI 의 한 스텝으로 직접 trigger 합니다. 필요한 것은 그 셸의 `prefect` CLI 와 `PREFECT_API_URL` 설정뿐입니다.

  ```bash
  prefect deployment run "<FLOW>/<DEPLOYMENT>" -p <KEY>=<VALUE> -p <KEY>=<VALUE>
  ```

  - **파라미터** — `-p key=value` 로 하나씩 **문자열** 로 줍니다. server 가 flow 함수의 시그니처 스키마로 타입을 변환·검증합니다.
  - **반환·제어** — run 을 만들고 **id 만 출력한 뒤 바로 끝납니다** (완료를 기다리지 않음). 진행을 따라가려면 `--watch` 를 붙입니다.
  - **주 용도** — 사람이 수동으로 한 번, 셸 스크립트, CI/CD 의 한 스텝, 빠른 테스트입니다 (CLI 목록은 [§5](#5-prefect-cli)).

### 4.2 Python SDK

  다른 파이썬 코드 (앱·서비스·또 다른 flow) 가 프로그램적으로 trigger 합니다.

  ```python
  from prefect.deployments import run_deployment

  flow_run = run_deployment(                      # ask the server to create a flow run
      name="<FLOW>/<DEPLOYMENT>",                 # deployment name
      parameters={"<KEY>": "<VALUE>"},            # native Python types
  )
  print(flow_run.id, flow_run.state)              # FlowRun object — id and final state
  ```

  - **파라미터** — `parameters={…}` dict 로, **네이티브 파이썬 타입** (int·bool·list 등) 을 그대로 넘깁니다.
  - **반환·제어** — `FlowRun` **객체** 를 돌려주고, 기본값은 run 이 **끝날 때까지 대기 (poll)** 합니다 (`timeout` 으로 제어, `timeout=0` 이면 즉시 반환). 그래서 상태·결과를 코드로 받아 다음 분기에 씁니다.
  - **주 용도** — flow 안에서 다른 run 을 **자동 trigger** (fan-out·orchestration), 조건부 실행, run 객체를 받아 상태 검사·후속 chaining (A 끝나면 B) 입니다.

### 4.3 Serve Mode

  work pool·worker·이미지 빌드 없이 `<flow>.serve(name=…)` **한 프로세스가 deployment 등록과 실행을 겸하는** 단일 머신·소규모 대안입니다 (`serve()` 는 `@flow` 객체의 메서드입니다 — [§3](#3-execution-architecture)).

  ```python
  # serve mode — one process registers the deployment AND runs it (no work pool / worker).
  from my_flow import train      # the @flow object
  train.serve(name="serve")      # long-lived; Ctrl-C to stop
  ```

  - **등록+실행** — `train.serve(...)` 한 줄이 deployment 등록과 실행 프로세스를 겸합니다 (`prefect deploy`·worker·이미지 빌드 불필요).
  - **trigger** — serve 프로세스는 상시 떠 있으므로 **별도 터미널에서** trigger 하며, 방법은 **§4.1·§4.2 와 같습니다** (`prefect deployment run "train/serve"` · `run_deployment(...)`). served 프로세스가 그 run 을 자기 안에서 실행합니다.
  - **차이·적합** — run 마다 컨테이너 격리가 없고, 그 프로세스가 떠 있어야 run 이 돕니다. 다수 사용자·동시 실행·격리가 필요하면 work pool mode 를 씁니다 ([§3](#3-execution-architecture)).

## 5. Prefect CLI

`prefect` CLI 는 Prefect SDK 와 함께 설치되는 명령행 도구 (`pip install prefect`) 입니다. 대상별로 묶었습니다.

- **Profile · Server**
  - `prefect config set PREFECT_API_URL="http://<HOST_IP>:4200/api"` — client 가 바라볼 server 주소를 프로필에 1회 저장합니다.
  - `prefect config view` — 현재 활성 프로필의 설정값 (`PREFECT_API_URL` 등) 을 출력합니다. CLI 가 지금 어느 server 를 향하는지 확인합니다.
  - `prefect profile ls` — 프로필 목록을 출력합니다. 등록·조회가 어긋날 때 어떤 프로필 (어떤 `PREFECT_API_URL`) 이 활성이었는지 되짚습니다.
  - `prefect server start --host 0.0.0.0` — Prefect server 를 기동합니다.
- **Work Pool**
  - `prefect work-pool create <name> --type docker --base-job-template <file> [--overwrite]` — `docker` work pool 을 server 에 등록합니다.
  - `prefect work-pool ls [--output json]` — 등록된 work pool 을 표 (또는 JSON) 로 출력합니다 (이름·type·동시성 한도).
  - `prefect work-pool get-default-base-job-template --type docker` — 도커 worker 의 기본 base job template 을 출력합니다.
  - `prefect work-pool set-concurrency-limit <pool> <N>` — pool 전체 동시 실행 상한을 설정합니다.
- **Worker**
  - `prefect worker start --pool <name> [--limit N]` — worker 를 기동해 그 pool 을 polling 하며 job 을 실행합니다.
- **Deployment**
  - `prefect deploy` (또는 `flow.deploy(...)`) — deployment 를 등록합니다.
  - `prefect deployment ls` — server 에 등록된 deployment 를 표 (이름·ID·Work Pool) 로 출력합니다. deployment 가 의도한 pool 로 올라갔는지 확인합니다.
  - `prefect deployment inspect "<flow>/<deployment>"` — deployment 하나의 상세 (entrypoint·work pool·parameters·job_variables 등) 를 출력합니다. flow 함수의 시그니처가 바뀐 뒤 파라미터 스키마가 새로 반영됐는지 확인합니다.
  - `prefect deployment run "<flow>/<deployment>" -p <key>=<value>` — 등록된 deployment 를 파라미터와 함께 trigger 합니다 ([§4.1](#41-prefect-cli)).
  - `prefect deployment delete "<flow>/<deployment>"` — 등록된 deployment 를 server 에서 삭제합니다. 시그니처를 바꿔 다시 올릴 때는 삭제 없이 `prefect deploy` 로 덮어써도 되며, deployment 를 폐기할 때만 삭제합니다.
- **Block · Variable**
  - `prefect block ls` — server 에 등록된 블록 (`Credentials` 등) 을 표 (ID·Type·Name·Slug) 로 출력합니다. 블록은 **그 server 의 DB 에 저장** 되므로 server 마다 따로 등록해야 하며, 등록 시점의 `PREFECT_API_URL` 이 가리킨 server 에 들어갑니다.
  - `prefect variable ls` — server 에 등록된 Variable 을 출력합니다.

## 6. Prefect @task

`@task` 를 쓰지 않아도 이력 관리와 재현 (reproducibility) 은 완전히 됩니다. Prefect 에서 실행 흐름을 묶는 핵심 단위는 `@task` 가 아니라 **`@flow`** 이기 때문입니다. `@flow` 데코레이터만 붙이면 그 안의 코드가 일반 함수든 클래스든 **실행 이력과 입력 파라미터가 Prefect Server 에 기록**됩니다.

### 6.1 Reproducing without @task

  `@task` 없이 `@flow` 와 일반 함수만으로 과거 시점 (git 커밋 + MinIO 데이터 버전) 을 재현하는 구조입니다.

  ```python
  from prefect import flow
  import boto3

  # A plain Python function (not a Prefect @task).
  def download_data(minio_key):
      s3 = boto3.client("s3", endpoint_url="http://minio:9000")
      s3.download_file("ml-data", minio_key, "local.csv")     # the data version lives in the key path

  # A plain Python function (not a Prefect @task).
  def train_and_evaluate():
      accuracy = 0.95     # real training/validation logic (the git-checked-out code runs here)
      return accuracy

  # History and parameter tracking come from @flow, not @task.
  @flow(name="mlops-reproduce-pipeline")
  def reproduce_flow(git_commit_hash: str, minio_data_version: str):
      download_data(f"dataset/{minio_data_version}/dataset.csv")     # version pinned via the key path
      return train_and_evaluate()

  if __name__ == "__main__":
      # The arguments passed here are recorded in the Prefect server DB.
      reproduce_flow(git_commit_hash="a1b2c3d", minio_data_version="v3_best")
  ```

  이렇게 해도 이력·재현이 되는 이유는 둘입니다.

  - **파라미터 추적** — Prefect Server 가 `@flow` 진입 인자 (`git_commit_hash`·`minio_data_version`) 를 DB 에 기록합니다. UI 에서 그 기록을 보고 같은 파라미터로 재실행 (재현) 할 수 있습니다.
  - **상태 관리** — flow 의 성공 (Completed) / 실패 (Failed) 와 로그가 기록되므로 이력 관리에 문제가 없습니다.

### 6.2 Why Use @task Then

  `@task` 없이도 이력은 남지만, 쓰는 이유는 **실패 복구**와 **성능** 입니다.

  Table 3. What @task adds to @flow

  | Capability | @flow only | @flow + @task (recommended) |
  | :---: | :---: | :---: |
  | Partial retry | 학습 중 에러 나면 데이터부터 다시 | 성공한 단계는 두고 실패한 단계만 재시도 |
  | Step monitoring | flow 하나의 진행만 보임 | 단계별 (다운로드·학습) 시각화·시간 측정 |
  | Caching | 매번 같은 데이터를 다시 다운로드 | 같은 입력이면 그 단계를 건너뜀 (cached) |

### 6.3 Summary

  이력 관리와 과거 재현은 **`@flow` 에 파라미터 (git 커밋·MinIO 버전) 를 넘기는 것만으로 작동**합니다. 학습 소스가 클래스 덩어리라 `@task` 를 일일이 붙이기 번거롭다면, `@task` 를 생략하고 `@flow` 만 씌워도 MLOps 재현 목적에는 지장이 없습니다.

---

## Appendix A. Terminology

- **base job template**: work pool 이 띄우는 실행 단위 (container · pod 등) 의 공통 설정입니다. deployment 의 `job_variables` 가 그 기본값을 덮습니다.
- **deployment**: flow 를 어떤 work pool 과 파라미터로 실행할지 묶어 server DB 에 저장한 레코드입니다.
- **flow run**: deployment 나 flow 를 한 번 실행한 것입니다.
- **serve mode**: `flow.serve()` 한 프로세스가 deployment 등록과 실행을 겸하는 실행 모드입니다.
- **work pool**: run 이 대기하는 큐이자 실행 방식 (type) 의 정의입니다. server 안의 메타데이터입니다.
- **work pool type**: work pool 의 실행 방식 이름입니다 (`process` · `docker` · `kubernetes` 등).
- **worker**: work pool 을 polling 하다가 run 을 가져가 실행 환경을 띄우는 process 입니다.

## Appendix B. Orchestrator Benchmarking

### B.1 Prefect vs Dagster vs Airflow

  오케스트레이터를 고를 때 자주 견주는 세 python 도구입니다. 셋 다 데이터/ML 파이프라인을 스케줄·실행·관측하지만 지향이 다릅니다 — **Prefect** 는 순수 python·동적 흐름, **Dagster** 는 데이터 자산 (asset) 과 타입·테스트, **Airflow** 는 성숙한 스케줄러와 최대 생태계입니다.

  Table 4. Prefect, Dagster and Airflow

  | Aspect | Prefect | Dagster | Airflow |
  | :---: | :---: | :---: | :---: |
  | Core abstraction | `@flow` · `@task` (명령형 python) | software-defined **asset** (데이터 자산 중심) | **DAG** (task 의존 그래프) |
  | Programming model | 순수 python·동적, 런타임에 흐름 결정 | asset·graph 선언형, 타입·테스트 강조 | DAG 선언, 스케줄러 중심 |
  | Dynamic workflows | native (런타임 분기·매핑 자유) | 지원 (제약 있음) | 약함 (정적 DAG 전제) |
  | Scheduling | flow run · automation · event | schedule · sensor · asset 기반 | 강력한 cron 스케줄러 (원조) |
  | Execution isolation | work pool: process · **docker** · k8s | run launcher: docker · k8s · celery | executor: Local · Celery · **Kubernetes** |
  | UI / lineage | flow run · task · 파라미터 자동 기록 | 데이터 자산 계보 (lineage) 1급 | DAG/task 로그 · 성숙한 UI |
  | Maturity / ecosystem | 신생 · 경량, 빠른 반복 | 신생, 데이터 플랫폼 지향 | 최고참 · 최대 생태계 |
  | Best fit | 동적 ML/데이터 파이프라인, python 우선 | 데이터 자산 · 품질/테스트 중시 | 정형 배치 ETL · 대규모 스케줄 |

### B.2 Execution Pattern Across Systems

  "**가벼운 에이전트 (worker) 가 작업을 집어, 작업마다 격리된 일시적 실행 단위를 띄워 실행하고 정리**" 하는 패턴은 오케스트레이션의 업계 표준입니다. `docker` work pool 은 그 표준의 **단일 호스트 변형** 이고, 규모가 커지면 실행 단위를 컨테이너 → **pod** 로 올린 Kubernetes 변형으로 확장됩니다.

  Table 5. Worker and execution unit across systems

  | System | Worker (agent) | Execution unit | Scale |
  | :---: | :---: | :---: | :---: |
  | **Prefect** (docker pool) | worker | run 마다 **컨테이너** | 단일 호스트·소–중 |
  | **Prefect** (kubernetes pool) | worker | run 마다 **pod** | 클러스터·대 |
  | **Airflow** (KubernetesExecutor) | scheduler/executor | task 마다 **pod** | 클러스터·대 |
  | **Argo Workflows** | controller | step 마다 **pod** | 클러스터·대 |
  | **GitHub Actions / GitLab CI** | runner | job 마다 **컨테이너** | CI/CD |
  | **Kubernetes** (native Job) | controller | **pod** | 클러스터 |

### B.3 What a Pod Is

  - **pod** — Kubernetes 의 **최소 실행/배포 단위** 입니다. 컨테이너 하나 이상이 같은 네트워크·스토리지를 공유하며 한 덩어리로 스케줄됩니다. "작업 1개 → pod 1개" 가 격리 단위이며, 단일 host 에서 컨테이너가 맡는 격리 단위를 cluster 에서는 pod 가 맡습니다.

### B.4 job · task · step Compared

  이 세 단어는 동의어가 아니라 **서로 다른 단위 (granularity)** 입니다. 도구마다 이름이 달라 혼동되므로 공통 계층으로 정리합니다.

  Table 6. Workflow granularity across tools

  | Concept | Definition | Prefect | Airflow | Argo | GitHub Actions |
  | :---: | :---: | :---: | :---: | :---: | :---: |
  | **Workflow / Pipeline** | 전체 작업 그래프의 정의 | flow | DAG | Workflow | workflow |
  | **Run** | 그 정의를 한 번 실행한 인스턴스 | flow run | DAG run | Workflow (instance) | run |
  | **Task** | run 안의 한 작업 단위 (1 연산) | task | task | template | — |
  | **Step** | job/task 안의 순서 있는 하위 동작 | — | — | step | step |
  | **Job** | 제출되는 상위 작업 묶음 (실행 단위로 스케줄) | flow run ≈ job | — | — | job |

  - **job** — 시스템에 제출되어 한 덩어리로 스케줄되는 상위 작업입니다 (GitHub Actions 의 job, Kubernetes 의 Job). Prefect 에서는 한 flow run 이 사실상 여기 해당합니다.
  - **task** — run 안의 개별 작업 단위 (1 연산) 입니다 (`@task` 하나).
  - **step** — job/task 안에서 순서대로 실행되는 하위 동작입니다 (Argo·CI 의 step).

  > granularity 는 **Workflow → Run/Job → Task → Step** 순으로 좁아지고, 실행을 감싸는 껍데기는 **컨테이너 (단일 호스트) / pod (클러스터)** 입니다. 세 단어를 하나로 통일하기보다 이 계층 안에서 구분해 쓰는 것이 업계 표준에 맞습니다.
