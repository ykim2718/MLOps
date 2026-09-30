# Prefect Work Queue
Rev. 3 | Created: 2026-09-30 | Updated: 2026-09-30 13:01 CDT

- [1. Purpose](#1-purpose)
- [2. Summary](#2-summary)
- [3. Taxonomy and its Hierarchy](#3-taxonomy-and-its-hierarchy)
  - [3.1 Placement](#31-placement)
- [4. Principle](#4-principle)
  - [4.1 Default Queue](#41-default-queue)
  - [4.2 Priority](#42-priority)
  - [4.3 Concurrency Limit](#43-concurrency-limit)
  - [4.4 Status](#44-status)
  - [4.5 Worker Polling](#45-worker-polling)
- [5. Application](#5-application)
  - [5.1 Creating a Queue](#51-creating-a-queue)
  - [5.2 Moving the Concurrency Limit](#52-moving-the-concurrency-limit)
  - [5.3 Assigning a Deployment](#53-assigning-a-deployment)
  - [5.4 Starting a Dedicated Worker](#54-starting-a-dedicated-worker)
  - [5.5 Verification](#55-verification)
  - [5.6 Operation](#56-operation)
  - [5.7 Failure Cases](#57-failure-cases)
- [References](#references)
- [Appendix A. Terminology](#appendix-a-terminology)
- [Appendix B. Work Queue CLI](#appendix-b-work-queue-cli)
- [Appendix C. Urgent Queue](#appendix-c-urgent-queue)
  - [C.1 Purpose](#c1-purpose)
  - [C.2 Method](#c2-method)
  - [C.3 Server State](#c3-server-state)

## 1. Purpose

- **Problem Statement**: work pool 하나의 concurrency limit 과 worker 의 `--limit` 을 그 pool 의 모든 deployment 가 나눠 쓰므로, 오래 도는 run 이 한도를 채우면 곧바로 시작해야 하는 run 도 `Late` 상태로 기다린다. Prefect 에는 도는 run 을 멈추고 자리를 넘기는 preemption 이 없다.
- **Goal**: 실무자의 Prefect Work Pool & Queue Guide 로서, 실무자가 work queue 를 만들고, deployment 를 그 queue 에 배정하고, 그 queue 만 polling 하는 worker 를 띄워, 지정한 deployment 의 run 이 pool 의 다른 run 이 한도를 채운 상태에서도 그 queue 의 한도 안에서 바로 시작하게 한다.
- **Non-Goal**: work pool 등록, base job template, worker image build, Prefect server 설치는 다루지 않는다.

## 2. Summary

Work queue 는 work pool 안의 대기열이며, priority 와 concurrency limit 과 pause 를 queue 단위로 둔다. Pool 은 실행 방식과 pool 전체 한도를 정하고, queue 는 그 pool 안에서 어느 run 을 먼저 내줄지와 몇 개까지 내줄지를 정한다. Deployment 는 `work_queue_name` 으로 자기 run 이 들어갈 queue 를 정하고, 정하지 않으면 pool 의 `default` queue 에 들어간다. Worker 는 pool 하나에 붙어 그 pool 의 queue 전부를 polling 하거나, `--work-queue` 로 지정한 queue 만 polling 한다.

급한 deployment 는 아래 네 단계로 전용 queue 에 넣고 전용 worker 를 붙인다.

1. `prefect work-queue create <QUEUE> --pool <POOL> --priority 1` 로 queue 를 만든다 ([5.1](#51-creating-a-queue)).
2. Pool 의 concurrency limit 을 지우고 같은 값을 `default` queue 에 건다. Pool 한도는 그 pool 의 모든 queue 에 함께 걸리므로, 남겨 두면 전용 queue 의 run 도 pool 한도에 막힌다 ([5.2](#52-moving-the-concurrency-limit)).
3. Deployment 를 `work_queue_name=<QUEUE>` 로 등록한다 ([5.3](#53-assigning-a-deployment)).
4. `prefect worker start --pool <POOL> --work-queue <QUEUE> --limit <N>` 으로 그 queue 만 polling 하는 worker 를 pool 전체를 맡는 worker 옆에 띄운다 ([5.4](#54-starting-a-dedicated-worker)).

네 단계를 실제 pool 에 적용한 예와 그 server 의 상태는 [Appendix C](#appendix-c-urgent-queue) 에 있다.

## 3. Taxonomy and its Hierarchy

Run 이 놓이는 자리는 server, work pool, work queue 의 세 층이고, worker 는 pool 하나에 붙어 그 pool 의 queue 전부 또는 지정한 queue 에서 run 을 가져간다.

```text
Prefect server
└── work pool <POOL>                     type (docker | process | kubernetes ...), base job template,
    │                                    pool concurrency limit (caps every queue below)
    ├── work queue "default"             priority 1 at pool creation; runs of deployments with no work_queue_name
    ├── work queue <QUEUE>               priority p, queue concurrency limit, status READY | NOT_READY | PAUSED
    │   └── flow run, flow run, ...      runs of deployments whose work_queue_name = <QUEUE>
    └── work queue ...

worker A   --pool <POOL>                        polls every queue of the pool, up to --limit runs at once
worker B   --pool <POOL> --work-queue <QUEUE>   polls <QUEUE> only, up to its own --limit
```

<a id="fig-1"></a>
Fig 1. Work pool, work queue, run and worker

위 층의 한도는 아래 층에 그대로 남는다. Pool 은 run 을 띄우는 방식과 pool 전체의 동시 실행 상한을 정하고, queue 는 그 안에서 순서 (priority) 와 개수 (queue concurrency limit) 와 멈춤 (pause) 을 정하며, worker 는 자기가 가져올 queue 와 한 번에 띄울 개수를 정한다. Queue 한도를 크게 잡아도 pool 한도를 넘지 못하고, worker 의 `--limit` 을 크게 잡아도 queue 한도와 pool 한도를 넘지 못한다.

### 3.1 Placement

Table 1. What each layer decides

| Layer      | Decides                                         | Set by                                     |
| :--------: | :---------------------------------------------: | :----------------------------------------: |
| work pool  | type, base job template, pool concurrency limit | `prefect work-pool create`, `set-concurrency-limit` |
| work queue | priority, queue concurrency limit, pause        | `prefect work-queue create`, `set-concurrency-limit`, `pause` |
| deployment | the queue its runs enter                        | `work_queue_name` at deploy time           |
| worker     | which queues it polls, runs at once             | `prefect worker start --work-queue`, `--limit` |

요구에 따라 손대는 층이 갈린다.

Table 2. Mechanism by need

| Need                                              | Mechanism                                        | Section                                   |
| :-----------------------------------------------: | :----------------------------------------------: | :---------------------------------------: |
| pool 이 차 있어도 특정 run 을 바로 시작            | dedicated queue with priority 1 + dedicated worker | [5.1](#51-creating-a-queue), [5.4](#54-starting-a-dedicated-worker) |
| 특정 종류 run 의 동시 수를 제한                    | queue concurrency limit                          | [4.3](#43-concurrency-limit)              |
| 특정 종류 run 을 잠시 멈춤                          | queue pause                                      | [5.6](#56-operation)                      |
| 특정 machine 에서만 특정 run 을 실행                | dedicated queue + every other worker on `--work-queue` of its own queues | [4.5](#45-worker-polling) |
| image, network, memory 상한이 다른 run             | separate work pool                               | out of scope                              |

Queue 는 한 pool 안에서 순서와 개수를 나누고, 실행 방식이 갈리면 pool 을 나눈다.

## 4. Principle

### 4.1 Default Queue

Pool 을 만들면 server 가 `default` 라는 queue 를 priority 1 로 함께 만든다 [[1](#ref-1)]. Deployment 에 `work_queue_name` 이 없으면 그 deployment 의 run 은 `default` queue 에 들어간다 [[2](#ref-2)]. Deployment 가 pool 에 없는 queue 이름을 대면 server 가 등록 시점에 그 이름의 queue 를 만든다 [[2](#ref-2)]. 이 자동 생성은 priority 를 받지 않으므로, priority 를 정하려면 deployment 등록 전에 queue 를 먼저 만든다 ([5.1](#51-creating-a-queue)).

### 4.2 Priority

Priority 는 pool 안에서 겹치지 않는 양의 정수이고, 숫자가 작을수록 먼저 내주며 1 이 가장 앞이다 [[3](#ref-3)]. Server 는 앞 순위 queue 의 기다리는 run 을 모두 내준 뒤에 다음 순위 queue 의 run 을 내준다. 동시 실행 한도에 여유가 있어도 이 순서는 바뀌지 않는다 [[3](#ref-3)]. Priority 는 기다리는 run 에만 작용하고, 이미 도는 run 은 그대로 둔다.

Priority 를 주지 않고 만든 queue 는 비어 있는 가장 앞 순위를 받고, 빈 순위가 없으면 가장 뒤 순위 다음을 받는다 [[1](#ref-1)]. 이미 있는 순위를 주면 server 가 나머지 queue 의 순위를 한 칸씩 뒤로 밀어 겹침을 없앤다 [[1](#ref-1)]. `--priority 1` 로 만든 queue 는 `default` 를 2 로 밀어내고 가장 앞 순위가 된다.

### 4.3 Concurrency Limit

동시 실행 상한은 세 자리에 있고, run 은 셋 가운데 가장 작은 값에 막힌다.

Table 3. Three concurrency limits

| Scope      | Command                                             | Applies to                                  |
| :--------: | :-------------------------------------------------: | :-----------------------------------------: |
| work pool  | `prefect work-pool set-concurrency-limit <POOL> <N>` | every run of every queue of the pool        |
| work queue | `prefect work-queue set-concurrency-limit <QUEUE> <N> --pool <POOL>` | runs of that queue                          |
| worker     | `prefect worker start --limit <N>`                  | runs that one worker process has started    |

Pool 한도는 그 pool 의 모든 queue 에 함께 걸린다 [[3](#ref-3)]. 전용 queue 와 전용 worker 를 두어도 pool 한도가 차 있으면 전용 queue 의 run 도 기다린다. 그래서 급한 run 을 위한 자리를 떼어 두려면 pool 한도를 지우고 같은 값을 `default` queue 에 걸어, 한도를 나머지 run 에만 남긴다 ([5.2](#52-moving-the-concurrency-limit)). Worker 의 `--limit` 은 그 worker 하나가 동시에 띄우는 run 의 수이며, 같은 queue 를 polling 하는 worker 가 둘이면 queue 의 run 은 두 worker 의 `--limit` 을 합한 수까지 동시에 돌 수 있다.

### 4.4 Status

Queue 는 `READY`, `NOT_READY`, `PAUSED` 세 상태를 갖는다 [[3](#ref-3)].

- `READY` 는 최근 60 초 안에 worker 가 그 queue 를 polling 한 상태이다.
- `NOT_READY` 는 60 초 넘게 polling 이 없는 상태이며, run 은 queue 에 쌓이고 worker 가 오면 `READY` 로 돌아간다.
- `PAUSED` 는 `prefect work-queue pause` 로 멈춘 상태이며, 새 run 을 내주지 않는다. `resume` 하면 worker 가 다시 polling 할 때까지 `NOT_READY` 로 있다.

### 4.5 Worker Polling

Worker 는 pool 하나에 붙고, `--work-queue` 를 주지 않으면 그 pool 의 모든 queue 를 polling 한다 [[4](#ref-4)]. `--work-queue` 는 여러 번 줄 수 있고, 주면 그 queue 들만 polling 한다 [[4](#ref-4)].

Queue 의 run 은 그 queue 를 polling 하는 worker 가운데 먼저 가져간 쪽이 실행한다. Pool 전체를 맡는 worker 도 전용 queue 를 polling 하므로, 전용 worker 는 그 queue 에 한도를 더할 뿐이다. 특정 queue 의 run 을 특정 machine 에서만 돌리려면, 다른 machine 의 worker 가 모두 `--work-queue` 로 자기 queue 만 polling 하게 하여 그 queue 를 polling 하는 worker 를 그 machine 의 것 하나로 남긴다.

## 5. Application

아래 명령은 `prefect` CLI 가 있고 `PREFECT_API_URL` 이 server 를 가리키는 shell 에서 실행한다. `<POOL>` 은 이미 등록된 work pool 의 이름이고, `<QUEUE>` 는 새로 만들 queue 의 이름이다.

### 5.1 Creating a Queue

Queue 는 `prefect work-queue create` 로 pool 을 지정해 만든다.

```bash
prefect work-queue create <QUEUE> --pool <POOL> --priority 1      # once per queue
prefect work-queue ls --pool <POOL>                               # name, priority, limit of every queue
```

- `--priority 1` 은 이 queue 를 pool 의 가장 앞 순위에 둔다 ([4.2](#42-priority)).
- `--limit <N>` 을 함께 주면 queue concurrency limit 을 만들 때 건다. 뒤에 `set-concurrency-limit` 으로 바꿀 수 있다.
- Queue 이름은 deployment 의 `work_queue_name` 과 worker 의 `--work-queue` 에 그대로 들어가므로, 세 곳에서 같은 글자를 쓴다.

### 5.2 Moving the Concurrency Limit

Pool 한도를 지우고 같은 값을 `default` queue 에 건다.

```bash
prefect work-pool clear-concurrency-limit <POOL>                        # a pool limit caps every queue
prefect work-queue set-concurrency-limit default <N> --pool <POOL>      # keep the old cap on the other runs
```

- `<N>` 은 지우기 전 pool 한도와 같은 값으로 두어, 전용 queue 밖의 run 이 받는 한도를 그대로 유지한다.
- 전용 queue 의 한도는 전용 worker 의 `--limit` 이 맡는다 ([5.4](#54-starting-a-dedicated-worker)). Queue 에도 한도를 걸려면 `set-concurrency-limit <QUEUE> <M> --pool <POOL>` 을 더한다.
- Pool 한도를 남겨 두면 전용 worker 가 떠 있어도 전용 queue 의 run 이 pool 한도에 막힌다 ([4.3](#43-concurrency-limit)).

### 5.3 Assigning a Deployment

Deployment 는 등록할 때 `work_queue_name` 으로 queue 를 정한다. Python SDK 는 `deploy()` 의 인자로 준다.

```python
# Python
from prefect import flow

@flow
def my_flow():
    ...

my_flow.deploy(
    name="my-deployment",
    work_pool_name="<POOL>",
    work_queue_name="<QUEUE>",      # omit it and the run enters the pool's default queue
    image="<IMAGE>",
    build=False, push=False,
)
```

`prefect deploy` 로 등록하는 yaml 은 `work_pool` 아래에 `work_queue_name` 을 둔다.

```yaml
# YAML
deployments:
  - name: my-deployment
    entrypoint: my_flow.py:my_flow
    work_pool:
      name: <POOL>
      work_queue_name: <QUEUE>      # omit it and the run enters the pool's default queue
```

등록 뒤 `prefect deployment inspect "<FLOW>/<DEPLOYMENT>"` 의 출력에서 `work_queue_name` 이 `<QUEUE>` 인지 확인한다. Queue 를 바꾸려면 `work_queue_name` 을 고쳐 다시 등록한다. 이미 만들어진 run 은 만들어질 때의 queue 에 남는다.

### 5.4 Starting a Dedicated Worker

전용 worker 는 같은 pool 에 `--work-queue` 를 붙여 띄운다.

```bash
prefect work-queue inspect <QUEUE> --pool <POOL>                      # stop here if the queue is missing
prefect worker start --pool <POOL> --work-queue <QUEUE> --limit <N> --name <HOSTNAME>-<QUEUE>
```

- `--work-queue <QUEUE>` 로 이 worker 는 `<QUEUE>` 만 polling 한다. Pool 전체를 맡는 worker 는 그대로 두고 옆에 띄운다.
- `--limit <N>` 은 이 worker 가 동시에 띄우는 run 의 수이며, 급한 run 에 떼어 두는 한도가 된다.
- `--name` 에 queue 이름을 넣어 두면 UI 의 worker 목록에서 어느 worker 가 전용인지 이름으로 가려진다.
- 띄우기 전에 `inspect` 로 queue 가 pool 에 있는지 확인한다. 이름이 틀린 worker 는 deployment 의 run 이 들어가는 queue 를 polling 하지 않으므로 그 run 을 받지 못한다.

### 5.5 Verification

Queue 가 만들어졌고, deployment 가 그 queue 에 있고, worker 가 polling 하는지를 차례로 본다.

```bash
prefect work-queue ls --pool <POOL>                                  # the queue with its priority and limit
prefect deployment inspect "<FLOW>/<DEPLOYMENT>"                      # work_queue_name = <QUEUE>
prefect work-queue inspect <QUEUE> --pool <POOL>                      # status READY when a worker polls it
prefect work-queue preview <QUEUE> --pool <POOL> --hours 1            # runs scheduled into the queue
```

UI 에서는 Work Pools 에서 pool 을 열어 Work Queues tab 에서 queue 의 상태와 priority 와 한도를 보고, Workers tab 에서 worker 의 이름과 마지막 heartbeat 를 본다. Run 이 `Late` 로 머물면 [5.7](#57-failure-cases) 의 표에서 원인을 찾는다.

### 5.6 Operation

운영 중의 변경은 모두 `prefect work-queue` 하위 명령으로 한다 ([Appendix B](#appendix-b-work-queue-cli)).

```bash
prefect work-queue pause <QUEUE> --pool <POOL>                        # stop handing out runs; they wait in the queue
prefect work-queue resume <QUEUE> --pool <POOL>
prefect work-queue set-concurrency-limit <QUEUE> <M> --pool <POOL>
prefect work-queue clear-concurrency-limit <QUEUE> --pool <POOL>
prefect work-queue delete <QUEUE> --pool <POOL>                       # after no deployment names this queue
```

- `pause` 는 새 run 을 내주지 않을 뿐 도는 run 은 끝까지 돌고, 기다리는 run 은 queue 에 남아 `resume` 뒤에 나간다.
- `delete` 는 그 queue 를 `work_queue_name` 으로 쓰는 deployment 를 먼저 다른 queue 로 옮긴 뒤에 한다.
- Priority 를 바꾸려면 queue 를 지우고 원하는 `--priority` 로 다시 만든다. Server 가 나머지 queue 의 순위를 다시 매긴다 ([4.2](#42-priority)).

### 5.7 Failure Cases

Table 4. Symptom, cause and fix

| Symptom                                                     | Cause                                                        | Fix                                                    |
| :---------------------------------------------------------: | :----------------------------------------------------------: | :----------------------------------------------------: |
| 전용 worker 가 `READY` 인데 전용 queue 의 run 이 `Late`     | pool concurrency limit 이 남아 있음                           | [5.2](#52-moving-the-concurrency-limit)                |
| 전용 queue 의 run 을 pool 전체 worker 가 실행                | 두 worker 가 같은 queue 를 polling 하며 먼저 가져간 쪽이 실행  | 의도한 동작, [4.5](#45-worker-polling)                  |
| 전용 worker 가 떠 있는데 run 을 하나도 받지 않음              | `--work-queue` 이름이 deployment 의 `work_queue_name` 과 다름  | `inspect` 로 이름 대조, [5.4](#54-starting-a-dedicated-worker) |
| Queue 가 `NOT_READY`                                        | 60 초 넘게 polling 하는 worker 가 없음                          | worker 기동, [4.4](#44-status)                          |
| 한도에 여유가 있는데 뒤 순위 queue 의 run 이 기다림           | 앞 순위 queue 에 기다리는 run 이 남아 있음                      | 의도한 동작, [4.2](#42-priority)                        |
| Deployment 등록 뒤 pool 에 모르는 queue 가 생김               | `work_queue_name` 에 없는 이름을 대어 server 가 자동 생성        | 이름 교정 뒤 재등록, 빈 queue 는 `delete`, [4.1](#41-default-queue) |

## References

<a id="ref-1"></a>
[1] PrefectHQ. [src/prefect/server/models/workers.py](https://github.com/PrefectHQ/prefect/blob/main/src/prefect/server/models/workers.py). Prefect source, `create_work_pool` and `create_work_queue`.<br>
<a id="ref-2"></a>
[2] PrefectHQ. [src/prefect/server/api/deployments.py](https://github.com/PrefectHQ/prefect/blob/main/src/prefect/server/api/deployments.py). Prefect source, `create_deployment`.<br>
<a id="ref-3"></a>
[3] Prefect. [Work pools](https://docs.prefect.io/v3/concepts/work-pools). Prefect 3 documentation, Concepts.<br>
<a id="ref-4"></a>
[4] Prefect. [prefect worker](https://docs.prefect.io/v3/api-ref/cli/worker). Prefect 3 documentation, CLI reference.<br>
<a id="ref-5"></a>
[5] Prefect. [prefect work-queue](https://docs.prefect.io/v3/api-ref/cli/work-queue). Prefect 3 documentation, CLI reference.

---

## Appendix A. Terminology

- **concurrency limit**: 동시에 실행할 수 있는 run 수의 상한. Work pool, work queue, worker 에 각각 둘 수 있고, run 은 셋 가운데 가장 작은 값에 막힌다.
- **default queue**: pool 을 만들 때 server 가 priority 1 로 함께 만드는 queue. `work_queue_name` 이 없는 deployment 의 run 이 들어간다.
- **deployment**: flow 를 어느 pool 과 queue 에서 어떤 parameter 로 실행할지 server 에 등록한 실행 정의.
- **flow run**: deployment 하나를 한 번 실행한 것. Server 가 만들어 queue 에 넣고 worker 가 가져가 실행한다.
- **Late**: 예정 시각이 지났는데 worker 가 아직 가져가지 않은 run 의 상태.
- **preemption**: 도는 run 을 멈추고 그 자리를 다른 run 에 넘기는 것. Prefect 에는 없다.
- **priority**: pool 안에서 queue 마다 겹치지 않게 매긴 양의 정수. 작을수록 먼저 내준다.
- **work pool**: Prefect server 에 등록된, run 을 모아 두고 실행 방식 (type) 을 정하는 단위.
- **work queue**: work pool 안의 대기열. Priority, concurrency limit, pause 를 queue 단위로 갖는다.
- **worker**: work pool 을 polling 하다가 run 을 가져가 실행하는 process. 한 pool 에 붙고, 그 pool 의 queue 전부 또는 지정한 queue 만 polling 한다.

## Appendix B. Work Queue CLI

Table 5. prefect work-queue subcommands

| Subcommand                | Arguments and options                              | Effect                                                  |
| :-----------------------: | :------------------------------------------------: | :-----------------------------------------------------: |
| `create`                  | `<QUEUE> --pool <POOL> [--priority <P>] [--limit <N>]` | queue 생성                                              |
| `ls`                      | `[--pool <POOL>] [--match <PREFIX>] [--verbose]`   | queue 목록과 priority 와 한도                            |
| `inspect`                 | `<QUEUE> --pool <POOL>`                            | queue 하나의 상태와 설정                                 |
| `preview`                 | `<QUEUE> --pool <POOL> [--hours <H>]`              | 앞으로 `<H>` 시간 안에 이 queue 로 들어올 run            |
| `read-runs`               | `<QUEUE> --pool <POOL>`                            | worker 가 polling 한 것처럼 지금 내줄 run 을 읽음        |
| `pause`                   | `<QUEUE> --pool <POOL>`                            | 새 run 내주기 중단                                       |
| `resume`                  | `<QUEUE> --pool <POOL>`                            | 내주기 재개                                              |
| `set-concurrency-limit`   | `<QUEUE> <N> --pool <POOL>`                        | queue 한도 설정                                          |
| `clear-concurrency-limit` | `<QUEUE> --pool <POOL>`                            | queue 한도 제거                                          |
| `delete`                  | `<QUEUE> --pool <POOL>`                            | queue 삭제                                               |

옵션의 정확한 이름과 기본값은 `prefect work-queue <SUBCOMMAND> --help` 가 그 CLI 판 기준으로 보여 준다 [[5](#ref-5)].

## Appendix C. Urgent Queue

`low_performance` pool 의 `urgent` queue 는 도는 run 을 취소하는 deployment 하나를 위해 만들었다. 이 appendix 는 그 queue 를 만든 목적, 적용한 명령, 그리고 적용 뒤 server 에서 읽은 상태를 적는다.

### C.1 Purpose

`webull-subscribe` 는 시세 stream 을 구독하며 끝나지 않고 도는 run 이고, `webull-subscribe-stop` 은 그 run 을 취소하는 run 이다. 둘 다 `low_performance` pool 에 있으므로, 구독 run 과 다른 run 이 pool 한도를 채운 상태에서 `default` queue 에 들어간 취소 run 은 `Late` 로 기다리고, 취소하려던 run 은 그동안 계속 돈다. 취소 run 을 `urgent` queue 에 두고 그 queue 만 polling 하는 worker 를 붙여, 한도와 무관하게 바로 시작하게 한다.

Table 6. Deployments of the pool that the urgent queue serves

| Deployment                      | Queue     | Parameters                                                  | Schedule |
| :-----------------------------: | :-------: | :---------------------------------------------------------: | :------: |
| `finance/webull-subscribe`      | `default` | subscribe quote and snapshot of given symbols, save to a given collection | none     |
| `finance/webull-subscribe-stop` | `urgent`  | `cancel_deployment_runs -deployment webull-subscribe`       | none     |

두 deployment 는 schedule 없이 사람이 trigger 한다. 취소 run 은 deployment 이름 `webull-subscribe` 의 도는 run 을 취소하고 끝난다.

### C.2 Method

[2. Summary](#2-summary) 의 네 단계 가운데 1, 3, 4 를 `low_performance` pool 에 적용했고, step 2 는 [C.3](#c3-server-state) 의 상태대로 아직 남아 있다.

```bash
prefect work-queue create urgent --pool low_performance --priority 1        # step 1
prefect work-pool clear-concurrency-limit low_performance                  # step 2, first half
prefect work-queue set-concurrency-limit default 6 --pool low_performance  # step 2, second half
prefect worker start --pool low_performance --work-queue urgent --name <HOSTNAME>-urgent@<LAN_IP>   # step 4
```

- Step 3 은 `finance/webull-subscribe-stop` 을 `work_pool_name="low_performance"`, `work_queue_name="urgent"` 로 등록한 것이다 ([5.3](#53-assigning-a-deployment)).
- 전용 worker 는 pool 전체를 맡는 worker `<HOSTNAME>@<LAN_IP>` 와 같은 machine 에서 돈다. 이름 뒤의 `-urgent` 가 전용 worker 를 가리킨다 ([5.4](#54-starting-a-dedicated-worker)).
- Step 2 의 `6` 은 pool 에 걸려 있던 한도이다 ([C.3](#c3-server-state)).

### C.3 Server State

적용 뒤 `prefect` CLI 로 읽은 server 의 상태이다. Queue 와 deployment 와 worker 는 C.2 대로 있고, pool 한도는 아직 pool 에 남아 있다.

```text
Work Queues in Work Pool 'low_performance'
┏━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┓
┃ Name    ┃ Priority ┃ Concurrency Limit ┃
┡━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━┩
│ urgent  │ 1        │ None              │
│ default │ 2        │ None              │
└─────────┴──────────┴───────────────────┘
```

- `urgent` 가 priority 1 이고, pool 을 만들 때 1 이었던 `default` 는 2 로 밀렸다 ([4.2](#42-priority)).
- `prefect work-pool inspect low_performance` 의 `concurrency_limit` 은 `6` 이고, 두 queue 의 한도는 `None` 이다. Step 2 의 두 명령은 아직 적용되지 않은 상태이며, pool 의 run 이 6 개 돌면 `urgent` queue 의 run 도 pool 한도에 막혀 기다린다 ([4.3](#43-concurrency-limit)). C.2 의 두 번째와 세 번째 명령을 실행하면 한도가 `default` queue 로 옮겨 간다.
- `low_performance` pool 의 worker 는 `<HOSTNAME>@<LAN_IP>` 와 `<HOSTNAME>-urgent@<LAN_IP>` 둘이고 모두 `ONLINE` 이다. `urgent` queue 는 두 worker 가 함께 polling 하므로, 취소 run 은 둘 중 먼저 가져간 쪽이 실행한다 ([4.5](#45-worker-polling)).
- `prefect deployment inspect "finance/webull-subscribe-stop"` 의 `work_queue_name` 은 `urgent` 이고, `finance/webull-subscribe` 의 것은 `default` 이다.
