# Prefect Worker
Rev. 0 | Created: 2026-10-10 | Updated: 2026-10-10 09:28 CDT

- [1. Purpose](#1-purpose)
- [2. Role](#2-role)
- [3. Image](#3-image)
- [4. Container](#4-container)
- [5. run_worker.sh](#5-run_workersh)
  - [5.1 Pipeline](#51-pipeline)
  - [5.2 Method](#52-method)
  - [5.3 Input](#53-input)
- [6. Scaling](#6-scaling)
- [7. Verification](#7-verification)
- [Appendix A. Terminology](#appendix-a-terminology)
- [Appendix B. CLI (Command Line Options)](#appendix-b-cli-command-line-options)
- [Appendix C. Run Example](#appendix-c-run-example)
  - [C.1 Worker for a High-Tier Machine](#c1-worker-for-a-high-tier-machine)
  - [C.2 Worker for a Low-Tier Machine](#c2-worker-for-a-low-tier-machine)
  - [C.3 Worker with a Given LAN IP](#c3-worker-with-a-given-lan-ip)
  - [C.4 Worker for One Queue](#c4-worker-for-one-queue)
- [Appendix D. run_worker.sh](#appendix-d-run_workersh)
- [Appendix E. push_worker_image.sh](#appendix-e-push_worker_imagesh)

## 1. Purpose

- **Problem Statement**: Worker 는 run 을 실행할 machine 마다 하나씩 띄워야 하고, 잘못된 pool · queue 이름이나 server 주소로 뜨면 run 을 하나도 받지 못한 채 돕니다.
- **Goal**: 실무자가 worker image 를 registry 에 올리고, 각 machine 에서 `run_worker.sh` 로 지정한 work pool 또는 그 pool 의 work queue 하나의 run 을 실행하는 worker 를 띄울 수 있게 합니다. 잘못된 이름과 주소는 기동 전에 막습니다.
- **Non-Goal**: Work pool 과 work queue 를 만들거나 concurrency limit 을 바꾸지 않습니다. Prefect server 를 띄우지 않습니다.

## 2. Role

worker (`prefect_worker`) 는 **네 가지 일**을 합니다.

- **job polling** — **server 에 있는 work pool** (큐) 을 polling 해 job 을 가져옵니다.
- **job dispatch** — 가져온 job 을 실행 환경으로 보내 실행합니다.
- **reporting** — 실행 중 상태·로그를 server 에 보고합니다.
- **cleanup** — 실행이 끝나면 정리합니다.

worker 는 **`docker` work pool** 을 polling 해 job 마다 `pipeline_flow` 컨테이너를 띄웠다 정리합니다 — flow 코드는 **그 컨테이너가** 실행하고 worker 자신은 실행하지 않습니다. 이 스택의 `high_performance`·`low_performance` 는 [prefect-server-ko.md §3](../PrefectServer/prefect-server-ko.md#3-work-pool-registration) 에서 `--type docker` 로 등록합니다.

준비물은 **worker compose** 하나입니다 — base job template 등록은 [prefect-server-ko.md §3](../PrefectServer/prefect-server-ko.md#3-work-pool-registration), flow image 는 [prefect-flow-ko.md §3](../PrefectFlow/prefect-flow-ko.md#3-image) 에 있습니다.

## 3. Image

  docker worker 는 `prefect`·`prefect-docker` 가 필요한데, 부팅 때 설치하지 않고 **전용 이미지를 build 해 registry 에 push** 해 둡니다. Worker machine 은 이 이미지를 build 하지 않고 registry 에서 받습니다 ([§4](#4-container)).

  #### Dockerfile

  ```dockerfile
  # Dockerfile.worker
  # __version__ = "0.0.1"  # Semantic Versioning:  Version = Major.Minor.Patch
  # Worker image — a Prefect docker worker (prefect + prefect-docker only, no team libraries).
  # Built once; the worker container then runs `prefect worker start` with no per-boot install.
  FROM python:3.11.15-slim
  RUN pip install --no-cache-dir "prefect>=3,<4" prefect-docker
  ```

  - `FROM python:3.11.15-slim` — slim 베이스입니다 (`prefect`·`prefect-docker` 는 순수 python wheel 이라 slim 으로 충분하고 이미지가 가볍습니다).
  - `RUN pip install --no-cache-dir "prefect>=3,<4" prefect-docker` — worker 에 필요한 prefect·prefect-docker 를 이미지에 굽습니다 (부팅 때 설치하지 않습니다).

  #### Execution Command

  build 하는 machine 의 `PrefectWorker/` 에서 `push_worker_image.sh` 를 1회 실행합니다. Dockerfile 을 바꿀 때마다 다시 실행합니다 (코드는 [Appendix E](#appendix-e-push_worker_imagesh)).

  ```bash
  ./push_worker_image.sh                              # registry = IMAGE_REGISTRY of ../docker-compose.env
  ./push_worker_image.sh --registry localhost:12357   # on the registry machine itself
  ```

  - `--registry <host:port>` — image 를 올릴 registry 입니다. 생략하면 `../docker-compose.env` (없으면 `_example`) 의 `IMAGE_REGISTRY` 를 쓰고, 값이 비었거나 자리표시자면 build 전에 멈춥니다.
  - `--platform <list>` — build 할 CPU architecture 입니다. 기본값 `linux/amd64,linux/arm64` 는 두 architecture 의 이미지를 한 tag 로 묶고, worker machine 은 pull 할 때 자기 architecture 의 것을 받습니다.
  - `--tag <tag>` — image tag 입니다 (기본 `latest`). Worker compose 는 `latest` 를 받습니다.

  script 는 아래 `docker buildx build` 를 실행한 뒤, registry 의 tag 목록에 그 tag 가 올라갔는지 확인합니다.

  ```bash
  docker buildx build --platform <PLATFORM> -f Dockerfile.worker -t <REGISTRY>/prefect-worker:<TAG> --push .
  ```

  - `-f Dockerfile.worker` — build 할 Dockerfile 입니다.
  - `--push` — build 한 이미지를 그 registry 에 바로 올립니다.
  - `.` — build context 입니다 (이 Dockerfile 은 `COPY` 가 없어 보낼 파일은 없지만 인자는 필요합니다).

  > 두 architecture 를 한 번에 build 하려면 build 하는 machine 의 Docker 가 containerd image store 를 써야 합니다 (Docker Desktop: Settings > General > "Use containerd for pulling and storing images").

  > registry 를 띄우는 방법과 worker machine 의 `insecure-registries` 설정은 [prefect-registry-ko.md](../prefect-registry-ko.md) 를 따릅니다.

## 4. Container

  worker 는 호스트 도커 소켓을 마운트해 `pipeline_flow` 컨테이너를 띄웁니다.

  #### Yaml

  ```yaml
  # Prefect Worker — polls a docker-type work pool and, per job, spawns a pipeline_flow container
  # to run the code, then cleans it up. This container never runs code itself.
  #
  # - Mounts the host docker socket to spawn sibling containers.
  #   (Docker Desktop on Windows and macOS also exposes /var/run/docker.sock to Linux containers.)
  # - prefect + prefect-docker are baked into the image (Dockerfile.worker), so there is no per-boot install.
  # - The work pool + base job template are registered on the server (see docker-compose.server.yml),
  #   so the worker only polls the pool — no pool creation here.
  #
  # Build + push (once, multi-arch, from a build host):
  #   docker buildx build --platform linux/amd64,linux/arm64 -f Dockerfile.worker \
  #       -t <IMAGE_REGISTRY>/prefect-worker:latest --push .
  # Start:         ./run_worker.sh --work-pool high_performance   (pulls the image from IMAGE_REGISTRY)
  # __version__ = "0.0.16"
  name: prefect-worker   # compose project name baked in (replaces -p); run_worker.sh relies on it
  services:
    prefect_worker:
      # multi-arch image from the registry (prefect + prefect-docker); the pool is chosen at start, not baked in
      image: ${IMAGE_REGISTRY:?run_worker.sh sets IMAGE_REGISTRY}/prefect-worker:latest
      env_file:
        # PREFECT_API_URL: ../docker-compose.env, else the _example; run_worker.sh rejects a placeholder value
        - ${WORKER_ENV_FILE:?run_worker.sh sets WORKER_ENV_FILE}
      # --name <hostname>@<LAN IP> (set by run_worker.sh) tells the server which machine this worker runs on;
      # WORK_QUEUE_OPTION (run_worker.sh --work-queue) is "--work-queue <queue>" for a one-queue worker, else empty
      command: prefect worker start --type docker --pool ${WORK_POOL:-high_performance} ${WORK_QUEUE_OPTION:-} --limit ${WORKER_LIMIT:-8} --no-create-pool-if-not-found --name ${WORKER_NAME:?run_worker.sh sets WORKER_NAME}
      volumes:
        - /var/run/docker.sock:/var/run/docker.sock   # host docker socket, to spawn sibling containers
      networks:
        - mlops                        # same host: reach prefect_server/minio by service name
      # If the control node (API) starts late and the connection fails, restart and reconnect automatically.
      restart: unless-stopped

  # On the same host this shares the Control Node services' network. run_server.sh creates it beforehand (run_worker.sh also creates it if missing).
  # (For a worker on another machine, remove the networks block and set PREFECT_API_URL to http://<host IP>:4200/api.)
  networks:
    mlops:
      external: true
  ```

  - `volumes: /var/run/docker.sock` — worker 가 호스트 도커로 `pipeline_flow` 컨테이너를 띄우는 통로입니다. Windows 도 같은 줄로 됩니다 — Docker Desktop 이 Linux 컨테이너용으로 이 경로에 도커 소켓을 노출하기 때문입니다 (호스트의 named pipe `\\.\pipe\docker_engine` 을 컨테이너 안 `/var/run/docker.sock` 로 연결).
  - `image` — worker image 를 `<IMAGE_REGISTRY>/prefect-worker:latest` 로 registry 에서 받습니다 ([§3](#3-image)). `IMAGE_REGISTRY` 는 `run_worker.sh` 가 `docker-compose.env` 에서 읽어 export 하며, 값이 없으면 compose 가 기동 전에 멈춥니다.
  - `command` — `prefect worker start` 만 합니다. prefect·prefect-docker 는 **이미지에 구워져** 있고 `PREFECT_API_URL` 은 env_file 이 주므로, 부팅 때 설치·export 가 없습니다 (`bash -c` 도 불필요). `--type docker` 로 docker worker 임을 고정하고, `--no-create-pool-if-not-found` 로 **없는 pool 을 자동 생성하지 않습니다** (오타 이름이 들어와도 process pool 이 몰래 생기지 않고 오류로 멈춤; pool 은 server 가 이미 등록, [prefect-server-ko.md §3](../PrefectServer/prefect-server-ko.md#3-work-pool-registration)). `IMAGE_REGISTRY`·`WORKER_ENV_FILE`·`WORK_POOL`·`WORKER_LIMIT`·`WORK_QUEUE_OPTION` 은 `docker compose up` 시 셸에서 읽는 변수입니다. `WORKER_ENV_FILE` 은 `run_worker.sh` 가 고른 env 파일 (`../docker-compose.env`, 없으면 `_example`) 이고, container 는 그 파일에서 `PREFECT_API_URL` 을 받습니다.
  - `--limit` 은 이 worker 가 **동시에 띄우는 컨테이너 수의 상한** 입니다 (동시성 세 층은 [prefect-server-ko.md §3 Work Pool Registration](../PrefectServer/prefect-server-ko.md#3-work-pool-registration) 의 여러 pool 표 참고).

  #### Execution Command

  `PrefectWorker/` 에서 실행합니다.

  ```bash
  ./run_worker.sh --work-pool <pool-name> --worker-limit <limit-count>
  ```

  - 옵션은 [Appendix B](#appendix-b-cli-command-line-options), script 가 하는 일은 [§5](#5-run_workersh), machine 별 실행 예는 [Appendix C](#appendix-c-run-example) 에 있습니다.

  **머신마다 실행** — 같은 compose 를 각 컴퓨터에서 자기 등급 `WORK_POOL` 로 띄웁니다. pool 이 server 에 이미 있으니 ([prefect-server-ko.md §3](../PrefectServer/prefect-server-ko.md#3-work-pool-registration)) worker 는 polling 만 하며, 등급별 첫 머신/추가 머신 구분이 없습니다.

  worker 가 뜨는 **그 순간** server 에 자기를 알리며 (heartbeat 시작) 해당 work pool 에 **자동 등록**됩니다 — **polling 시작 = 등록** 이라 별도 절차가 없습니다. heartbeat 가 끊기면 잠시 뒤 **OFFLINE** 으로 바뀝니다 (worker 등록은 deployment 등록과 별개).

  > **보안 주의** — 도커 소켓 마운트는 worker 에 호스트 도커 전체 제어권 (사실상 root) 을 줍니다. 신뢰된 내부망·스터디 용도로 한정하고, 더 강한 격리는 Kubernetes work pool 을 고려합니다 ([prefect-ko.md Appendix F](../prefect-ko.md#appendix-f-orchestrator-benchmarking)).

## 5. run_worker.sh

Worker compose 파일은 pool 이름과 한도, worker image 의 registry 를 `docker compose up` 때 셸 변수로 읽으므로, `run_worker.sh` 가 그 값을 정해 export 합니다. Prefect API 는 worker 가 어느 machine 에서 도는지 기록하지 않아, worker 이름에 `<hostname>@<LAN IP>` 를 넣습니다. 오타 난 pool · queue 이름으로 뜬 worker 는 run 을 하나도 받지 못한 채 도므로, 이름을 server 의 목록과 먼저 대조합니다. 코드 전체는 [Appendix D](#appendix-d-run_workersh) 에 있습니다.

### 5.1 Pipeline

`run_worker.sh` 는 아래 차례로 worker container 를 띄웁니다.

1. 옵션 읽기 — `--work-pool`, `--worker-limit`, `--worker-ip`, `--work-queue`.
2. Registry 읽기 — `../docker-compose.env` 에서 `IMAGE_REGISTRY` 한 줄만 읽고, 파일이 없으면 `../docker-compose.env_example` 을 읽습니다. 값이 비었거나 `<` 가 든 자리표시자면 멈추고, 같은 파일의 `PREFECT_API_URL` 도 같은 기준으로 검사합니다.
3. 도구 확인 — `jq` 와 host 의 `prefect` CLI 가 없으면 설치 방법을 출력하고 멈춥니다.
4. Network 준비 — docker network `mlops` 가 없으면 만듭니다.
5. Pool 검증 — `prefect work-pool ls --output json` 으로 server 의 docker type pool 목록을 읽어 `--work-pool` 과 대조합니다. 목록에 없으면 번호를 붙여 보여 주고 하나를 고르게 합니다.
6. Queue 검증 — `--work-queue` 를 주었으면 `prefect work-queue inspect` 로 그 queue 가 pool 에 있는지 확인합니다. 없으면 만드는 명령을 출력하고 멈춥니다.
7. LAN IP 결정 — `--worker-ip` 가 없으면 Windows 는 default route interface (`powershell.exe`), macOS 는 default route interface 의 주소 (`route` 와 `ipconfig`), Linux 는 default route source 주소 (`ip route`) 에서 읽습니다.
8. 이름 결정 — compose project, worker 이름, queue 옵션을 정합니다 ([§5.2](#52-method)).
9. 기동 — 변수를 export 하고, `docker compose -p <project> pull` 로 이 machine 의 architecture 에 맞는 worker image 를 받은 뒤 `down` 하고 `up -d` 합니다.

### 5.2 Method

`--work-queue` 유무에 따라 compose project 와 worker 이름이 갈립니다.

Table 1. Names by queue option

| Queue option            | Compose project          | Worker name                     | Polls                   |
| :---------------------: | :----------------------: | :-----------------------------: | :---------------------: |
| none                    | `prefect-worker`         | `<hostname>@<LAN IP>`           | every queue of the pool |
| `--work-queue <queue>`  | `prefect-worker-<queue>` | `<hostname>-<queue>@<LAN IP>`   | `<queue>` only          |

- Compose project 가 다르므로 두 worker 는 한 machine 에서 나란히 돌고, `down` 은 자기 project 의 container 만 내립니다.
- Worker 이름의 `@` 뒤는 LAN IP 여서, 이름만으로 worker 가 도는 machine 을 알 수 있습니다.
- `--work-queue` 는 compose 의 `WORK_QUEUE_OPTION` 변수로 `prefect worker start` 명령에 들어갑니다. 옵션이 없으면 이 변수는 빈 값이고 명령에서 빠집니다.
- Pool 검증은 docker type pool 만 인정합니다. 이 worker 는 run 마다 docker container 를 띄우므로, 같은 이름의 process pool 은 run 을 실행할 수 없습니다.

### 5.3 Input

- Host 의 `prefect` CLI — `PREFECT_API_URL` 이 Prefect server 를 가리켜야 pool · queue 검증이 됩니다.
- `jq` — `prefect work-pool ls --output json` 의 출력을 읽습니다.
- `docker compose` — 같은 folder 의 `docker-compose.worker.yml` 을 띄웁니다.
- `../docker-compose.env` — script 가 읽는 `IMAGE_REGISTRY` (registry 의 `<host>:<port>`) 와, worker container 가 읽는 `PREFECT_API_URL` 을 담습니다. 파일이 없으면 `../docker-compose.env_example` 을 읽지만, 그 자리표시자 값으로는 script 가 멈춥니다.
- Registry 의 `prefect-worker:latest` — worker image 를 `IMAGE_REGISTRY` 에 미리 push 해 둡니다 ([§3](#3-image)). HTTP registry 면 이 machine 의 docker daemon 에 `insecure-registries` 도 있어야 pull 이 됩니다.
- Server 에 등록된 docker type work pool 과, `--work-queue` 를 쓸 때는 그 pool 의 work queue 입니다.

## 6. Scaling

  **처리량·확장** — `--limit` 을 키우거나, **다른 머신에서 worker 를 더 띄워 같은 pool 에 붙입니다** (그 머신은 `docker-compose.env` 의 `PREFECT_API_URL`=`http://<server IP>:4200/api`, `docker-compose.worker.yml` 의 `networks:` 블록 제거). 여러 worker 는 같은 prefect server 에 있는 pool 의 큐를 나눠 가집니다.

  **Queue 전용 worker** — 다른 run 이 한도를 채워도 곧바로 시작해야 하는 deployment 는 전용 work queue 에 넣고, 그 queue 만 polling 하는 worker 를 `./run_worker.sh --work-pool <pool> --work-queue <queue> --worker-limit <N>` 으로 pool 전체를 맡는 worker 옆에 띄웁니다. Work queue 의 원리 (default queue · priority · concurrency limit · status) 와 만들기 · deployment 배정 · 전용 worker · 검증 · 운영 절차는 [prefect-work-queue-ko.md](../prefect-work-queue-ko.md) 를 따릅니다.

## 7. Verification

  worker 가 ONLINE 인지 확인합니다 (pool 등록 확인은 [prefect-server-ko.md §3 Work Pool Registration](../PrefectServer/prefect-server-ko.md#3-work-pool-registration)).

  ```bash
  prefect work-pool inspect high_performance
  ```

  `inspect` 의 `status` 가 `READY` 면 그 pool 을 polling 하는 worker 가 1개 이상 떠 있다는 뜻입니다 — pool 단위 간접 확인입니다. **어느 worker 가 ONLINE 인지**·마지막 heartbeat 는 UI 의 Work Pools → 해당 pool → **Workers 탭** 에서 봅니다 ([prefect-ko.md §9](../prefect-ko.md#9-prefect-ui)).

---

## Appendix A. Terminology

- **`PREFECT_API_URL`**: worker · client 가 server API 를 찾는 주소 (`http://<host>:4200/api`) 입니다. 같은 host 면 host 가 서비스명 `prefect_server` 입니다.
- **`prefect_server`**: API · UI · scheduler · work pool 대기열을 제공하는 중앙 진입점입니다. 메타데이터 (`prefect` DB) 만 관리하고 코드는 실행하지 않습니다.
- **`prefect_worker`**: work pool 을 polling 해 job 마다 `pipeline_flow` 컨테이너를 띄우고 정리하는 worker 입니다. 코드는 실행하지 않습니다.
- **base job template**: pool 이 띄우는 flow 컨테이너의 공통 설정 (image · env · network · 메모리 상한 등) 입니다.
- **compose project**: `docker compose` 가 container · network 이름 앞에 붙이는 묶음 이름입니다. `-p` 로 정하며, `down` 은 같은 project 의 container 만 내립니다.
- **concurrency limit**: 동시에 실행할 수 있는 run 수의 상한입니다. Work pool 과 work queue 에 각각 둘 수 있고, pool 의 상한은 그 pool 의 모든 queue 에 함께 걸립니다.
- **deployment**: flow 를 어떤 work pool 과 parameter 로 실행할지 묶어 server DB (`prefect`) 에 저장한 레코드입니다.
- **flow image**: Pipeline Flow 컨테이너를 띄우는 image 입니다. deployment 의 `image` (없으면 base job template 의 `image` 기본값) 가 가리키며, 이 stack 에서는 `pipeline-flow:latest` 입니다.
- **Host**: 모든 컨테이너 (server · worker · pipeline_flow · postgres · minio · mlflow) 가 올라가는 한 대의 컴퓨터입니다.
- **LAN IP**: machine 이 내부망에서 쓰는 IPv4 주소입니다.
- **registry**: image 를 보관하고 push 와 pull 을 받는 service 입니다.
- **work pool**: job 이 대기하는 큐이자 실행 방식 (type) 의 정의입니다. server 안의 메타데이터이며 컨테이너가 아닙니다.
- **work queue**: work pool 안의 대기열입니다. Deployment 는 `work_queue_name` 으로 queue 를 정하고, 정하지 않으면 `default` queue 에 들어갑니다.
- **worker image**: worker process 가 도는 container 의 image 입니다. Prefect 와 docker worker package 를 담고 flow code 는 실행하지 않으며, 이 stack 에서는 `prefect-worker:latest` 입니다.

## Appendix B. CLI (Command Line Options)

Table 2. Command line options of run_worker.sh

| Option           | Type   | Default            | Required | Description                                                     |
| :--------------: | :----: | :----------------: | :------: | :-------------------------------------------------------------: |
| `--work-pool`    | string | `high_performance` | no       | Docker work pool to poll                                        |
| `--worker-limit` | int    | `8`                | no       | Max run containers this worker starts at once                   |
| `--worker-ip`    | IPv4   | detected           | no       | LAN IP of this machine, when detection fails                    |
| `--work-queue`   | string | none (every queue) | no       | One work queue of the pool to poll, as its own compose project  |

## Appendix C. Run Example

모든 예시는 `PrefectWorker/` folder 에서 실행합니다.

### C.1 Worker for a High-Tier Machine

`high_performance` pool 의 모든 queue 를 polling 하는 worker 를 한도 8 로 띄웁니다.

```bash
./run_worker.sh --work-pool high_performance --worker-limit 8
```

### C.2 Worker for a Low-Tier Machine

`low_performance` pool 의 모든 queue 를 polling 하는 worker 를 한도 4 로 띄웁니다.

```bash
./run_worker.sh --work-pool low_performance --worker-limit 4
```

### C.3 Worker with a Given LAN IP

LAN IP 를 자동으로 읽지 못하는 machine 에서 worker 이름에 넣을 IP 를 직접 줍니다.

```bash
./run_worker.sh --work-pool low_performance --worker-ip <LAN_IP>
```

### C.4 Worker for One Queue

`low_performance` pool 의 `urgent` queue 만 polling 하는 worker 를, pool 전체를 맡는 worker 옆에 한도 2 로 띄웁니다. `urgent` queue 를 만들고 pool 한도를 `default` queue 로 옮기는 절차는 [prefect-work-queue-ko.md](../prefect-work-queue-ko.md) 를 따르며, queue 가 server 에 먼저 있어야 합니다.

```bash
./run_worker.sh --work-pool low_performance --work-queue urgent --worker-limit 2
```

## Appendix D. run_worker.sh

각 worker 머신에서 worker compose 스택을 띄우는 기동 스크립트입니다 ([§4](#4-container)). server 기동과 work pool 등록은 별도입니다 (server 는 [prefect-server-ko.md Appendix B](../PrefectServer/prefect-server-ko.md#appendix-b-run_serversh), pool 은 `register_pool.sh` — [prefect-server-ko.md Appendix C](../PrefectServer/prefect-server-ko.md#appendix-c-register_poolsh)).

```bash
#!/usr/bin/env bash
# run_worker.sh — start the Prefect worker compose stack on a worker machine.
# __version__ = "0.0.27"  # Semantic Versioning:  Version = Major.Minor.Patch
#
# Brings up prefect_worker, which polls the given work pool. WORK_POOL/WORKER_LIMIT are read from
# this shell at "docker compose up" (compose interpolation), so they are exported below.
# (PREFECT_API_URL etc. are read by the container from the env file this script picks, exported as WORKER_ENV_FILE.)
# Runs on Windows (Git Bash / WSL), Linux and macOS; each finds the LAN IP its own way (see below).
# Work pools live on the server and are registered there (register_pool.sh), not here. Before starting,
# this script checks the work pool against the pools registered on the server; if it is missing, it lists
# the registered pools and lets you pick one (guards against typos / not-yet-registered pools).
#
#   ./run_worker.sh --work-pool high_performance    # a high-tier machine
#   ./run_worker.sh --work-pool low_performance     # a low-tier machine
#   ./run_worker.sh --work-pool low_performance --worker-ip <LAN_IP>   # when the LAN IP is not detected
#   ./run_worker.sh --work-pool low_performance --work-queue urgent --worker-limit 2   # a second worker, one queue only
#
# The worker is named '<hostname>@<LAN IP>' so the Prefect server (and dashboards reading it) can tell
# which machine each worker runs on; the Prefect API records no host for a worker otherwise.
# With --work-queue the worker polls that queue of the pool only, is named '<hostname>-<queue>@<LAN IP>', and runs
# as its own compose project (prefect-worker-<queue>), so it starts and stops beside the pool-wide worker.
#
# The worker image is pulled from IMAGE_REGISTRY (read from ../docker-compose.env, else the _example), so a new
# machine needs no local build; re-running this script pulls the latest pushed image.
#
set -euo pipefail

WORK_POOL="high_performance"   # the work pool this machine polls: high_performance | low_performance
WORKER_LIMIT=8                 # max pipeline_flow containers this machine spawns concurrently
WORKER_IP=""                   # LAN IP of this machine; empty = detected below
WORK_QUEUE=""                  # one work queue of the pool to poll; empty = every queue of the pool

while [ $# -gt 0 ]; do
    case "$1" in
        --work-pool)    WORK_POOL="$2"; shift 2 ;;
        --worker-limit) WORKER_LIMIT="$2"; shift 2 ;;
        --worker-ip)    WORKER_IP="$2"; shift 2 ;;
        --work-queue)   WORK_QUEUE="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

COMPOSE="docker-compose.worker.yml"
ENV_FILE="../docker-compose.env"   # shared address source; falls back to the committed _example

# --- Registry of the worker image: read only IMAGE_REGISTRY (sourcing the whole file would override the
# host's PREFECT_API_URL with a possible placeholder) ------------------------------------------------
[ -f "$ENV_FILE" ] || ENV_FILE="../docker-compose.env_example"
[ -f "$ENV_FILE" ] || { echo "env file not found: $ENV_FILE" >&2; exit 1; }
IMAGE_REGISTRY="$(sed -n 's/^IMAGE_REGISTRY=//p' "$ENV_FILE" | tail -n 1 | tr -d '\r')"
if [ -z "$IMAGE_REGISTRY" ] || [[ "$IMAGE_REGISTRY" == *"<"* ]]; then
    echo "IMAGE_REGISTRY missing or still a placeholder in $ENV_FILE (got '$IMAGE_REGISTRY')." >&2
    echo "Set it to the registry <host>:<port>; an HTTP registry also needs 'insecure-registries' in the docker daemon." >&2
    exit 1
fi

# The worker container reads PREFECT_API_URL from this same env file; a placeholder would start a worker that
# never reaches the server, so it is rejected here rather than inside the container.
CONTAINER_API_URL="$(sed -n 's/^PREFECT_API_URL=//p' "$ENV_FILE" | tail -n 1 | tr -d '\r')"
if [ -z "$CONTAINER_API_URL" ] || [[ "$CONTAINER_API_URL" == *"<"* ]]; then
    echo "PREFECT_API_URL missing or still a placeholder in $ENV_FILE (got '$CONTAINER_API_URL')." >&2
    echo "Copy ../docker-compose.env_example to ../docker-compose.env and set the server address there." >&2
    exit 1
fi
WORKER_ENV_FILE="$ENV_FILE"   # compose env_file; relative to this folder, which is also the compose file's folder

command -v jq >/dev/null 2>&1 || { echo "jq is required to parse 'prefect work-pool ls --output json'. Install jq and retry." >&2; exit 1; }

# The pool validation below uses the host 'prefect' CLI, so it must be installed and on PATH.
if ! command -v prefect >/dev/null 2>&1; then
    echo "prefect CLI not found on this host (needed to validate the work pool against the server)." >&2
    echo "Install it, then retry:" >&2
    echo "  pipx install prefect && pipx ensurepath     # then open a new shell, or: export PATH=\"\$HOME/.local/bin:\$PATH\"" >&2
    echo "  export PREFECT_API_URL=http://127.0.0.1:4200/api   # point at the running server (run_server.sh)" >&2
    exit 1
fi

# On the same host, worker/pipeline_flow containers reach the server by service name over the shared mlops network.
# (For a worker on another machine, remove the networks block in the worker compose and set PREFECT_API_URL to http://<host IP>:4200/api.)
docker network inspect mlops >/dev/null 2>&1 || docker network create mlops >/dev/null

# --- Validate the work pool against the pools registered on the server --------------------------
# Read the registered pools with the host prefect CLI (configured via its PREFECT_API_URL profile).
# stderr (progress / version warnings) is dropped so only the JSON on stdout is parsed.
pools_json="$(prefect work-pool ls --output json 2>/dev/null || true)"
if [ -z "$pools_json" ]; then
    echo "Could not read work pools via the host 'prefect' CLI. Ensure prefect is installed and PREFECT_API_URL points at a running server (run_server.sh), then retry." >&2
    exit 1
fi

# This worker spawns docker containers, so only docker-type pools are valid
# (a name that exists only as a process pool — e.g. one auto-created by a typo — is rejected here).
pools=()
while IFS= read -r line; do
    [ -n "$line" ] && pools+=("$line")
done < <(printf '%s' "$pools_json" | jq -r '.[] | select(.type == "docker") | .name')

if [ "${#pools[@]}" -eq 0 ]; then
    echo "No docker-type work pools are registered on the server. Run register_pool.sh (it registers --type docker) first." >&2
    exit 1
fi

match=""
for p in "${pools[@]}"; do
    if [ "$p" = "$WORK_POOL" ]; then match="$p"; break; fi
done

if [ -n "$match" ]; then
    WORK_POOL="$match"                                   # normalize to the exact registered name
else
    echo "Warning: '$WORK_POOL' is not a registered docker work pool." >&2
    echo "Registered docker work pools:"
    i=1
    for p in "${pools[@]}"; do
        printf '%3d) %s\n' "$i" "$p"
        i=$((i + 1))
    done
    read -r -p "Pick a pool number (Enter to abort): " sel
    if ! printf '%s' "$sel" | grep -qE '^[0-9]+$' || [ "$sel" -lt 1 ] || [ "$sel" -gt "${#pools[@]}" ]; then
        echo "Aborted: no valid work pool selected." >&2
        exit 1
    fi
    WORK_POOL="${pools[$((sel - 1))]}"
    echo "Using work pool '$WORK_POOL'."
fi

# --- Validate the work queue: prefect worker start would silently create a mistyped queue ------------
if [ -n "$WORK_QUEUE" ] && ! prefect work-queue inspect "$WORK_QUEUE" --pool "$WORK_POOL" >/dev/null 2>&1; then
    echo "Work queue '$WORK_QUEUE' is not in work pool '$WORK_POOL'. Create it first, e.g.:" >&2
    echo "  prefect work-queue create $WORK_QUEUE --pool $WORK_POOL --priority 1" >&2
    exit 1
fi

# --- Name the worker after this machine: <hostname>@<LAN IP> ---------------------------------------
# On Windows (Git Bash, or WSL whose own IP is internal) the LAN IP comes from the Windows default-route
# interface; on macOS (no powershell.exe, no ip) from the address of the default-route interface;
# on Linux from the source address of the default route.
if [ -z "$WORKER_IP" ] && command -v powershell.exe >/dev/null 2>&1; then
    WORKER_IP="$(powershell.exe -NoProfile -Command \
        "(Get-NetIPConfiguration | Where-Object IPv4DefaultGateway | Select-Object -First 1).IPv4Address.IPAddress" \
        2>/dev/null | tr -d '\r' || true)"
fi
if [ -z "$WORKER_IP" ] && [ "$(uname -s)" = "Darwin" ]; then
    default_iface="$(route -n get default 2>/dev/null | awk '/interface:/ {print $2; exit}' || true)"
    if [ -n "$default_iface" ]; then
        WORKER_IP="$(ipconfig getifaddr "$default_iface" 2>/dev/null || true)"
    fi
fi
if [ -z "$WORKER_IP" ] && command -v ip >/dev/null 2>&1; then
    WORKER_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") {print $(i + 1); exit}}')"
fi
if ! printf '%s' "$WORKER_IP" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo "Could not detect this machine's LAN IP (got '$WORKER_IP'); pass it with --worker-ip <ip>." >&2
    exit 1
fi
PROJECT="prefect-worker"       # the compose file's top-level name
WORK_QUEUE_OPTION=""
WORKER_NAME="$(hostname)@${WORKER_IP}"
if [ -n "$WORK_QUEUE" ]; then
    PROJECT="prefect-worker-${WORK_QUEUE}"
    WORK_QUEUE_OPTION="--work-queue ${WORK_QUEUE}"
    WORKER_NAME="$(hostname)-${WORK_QUEUE}@${WORKER_IP}"
fi
echo "Worker name: $WORKER_NAME"

# For the worker compose ${...} interpolation — export so this docker compose up sees them.
export WORK_POOL
export WORKER_LIMIT
export WORKER_NAME
export WORK_QUEUE_OPTION
export IMAGE_REGISTRY
export WORKER_ENV_FILE

# Pull the latest worker image (the arch of this machine) before restarting, so a re-run picks up a new push.
docker compose -p "$PROJECT" -f "$COMPOSE" pull

# Bring the worker stack down (keeping volumes) and back up in the background.
# -p names the project, so down only ever touches this stack (the pool-wide worker or one queue's worker).
docker compose -p "$PROJECT" -f "$COMPOSE" down
docker compose -p "$PROJECT" -f "$COMPOSE" up -d
```

## Appendix E. push_worker_image.sh

build 하는 machine 에서 worker image 를 여러 CPU architecture 로 build 해 registry 에 올리는 script 입니다 ([§3](#3-image)).

```bash
#!/usr/bin/env bash
# push_worker_image.sh — build the Prefect worker image for several CPU architectures and push it to the registry.
# __version__ = "0.0.0"  # Semantic Versioning:  Version = Major.Minor.Patch
# Author: yRocket
#
# Builds Dockerfile.worker as one multi-arch image <registry>/prefect-worker:<tag> and pushes it, so every worker
# machine (amd64 PC, arm64 Mac) pulls its own variant through run_worker.sh. The registry defaults to IMAGE_REGISTRY
# of ../docker-compose.env (else the _example), the same value run_worker.sh pulls from.
#
#   ./push_worker_image.sh                                  # registry = IMAGE_REGISTRY of ../docker-compose.env
#   ./push_worker_image.sh --registry localhost:12357       # on the registry machine itself
#   ./push_worker_image.sh --platform linux/arm64           # one architecture only
#
# A multi-arch build needs the containerd image store (Docker Desktop: Settings > General > "Use containerd for
# pulling and storing images") or a docker-container buildx builder. The final tag check reads the HTTP API of a
# plain registry:2 container.
#
set -euo pipefail

IMAGE_NAME="prefect-worker"              # the name docker-compose.worker.yml pulls
REGISTRY=""                              # <host>:<port>; empty = IMAGE_REGISTRY of the env file
PLATFORM="linux/amd64,linux/arm64"       # CPU architectures of the worker machines
TAG="latest"

usage() { echo "Usage: $0 [--registry <host:port>] [--platform <list>] [--tag <tag>]" >&2; }

while [ $# -gt 0 ]; do
    case "$1" in
        --registry|--platform|--tag)
            # a missing value would make 'shift 2' fail silently under set -e
            [ $# -ge 2 ] || { echo "$1 needs a value." >&2; usage; exit 1; }
            case "$1" in
                --registry) REGISTRY="$2" ;;
                --platform) PLATFORM="$2" ;;
                --tag)      TAG="$2" ;;
            esac
            shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

cd "$(dirname "$0")"   # Dockerfile.worker and ../docker-compose.env are relative to this folder
[ -f Dockerfile.worker ] || { echo "Dockerfile.worker not found in $(pwd)." >&2; exit 1; }

if [ -z "$REGISTRY" ]; then
    ENV_FILE="../docker-compose.env"
    [ -f "$ENV_FILE" ] || ENV_FILE="../docker-compose.env_example"
    [ -f "$ENV_FILE" ] || { echo "env file not found: $ENV_FILE" >&2; exit 1; }
    REGISTRY="$(sed -n 's/^IMAGE_REGISTRY=//p' "$ENV_FILE" | tail -n 1 | tr -d '\r')"
    REGISTRY_SOURCE="IMAGE_REGISTRY in $ENV_FILE"
else
    REGISTRY_SOURCE="--registry"
fi
if [ -z "$REGISTRY" ] || [[ "$REGISTRY" == *"<"* ]] || [[ "$REGISTRY" == */* ]]; then
    echo "Registry missing, a placeholder or not <host>:<port> (got '$REGISTRY' from $REGISTRY_SOURCE)." >&2
    echo "Set IMAGE_REGISTRY in ../docker-compose.env or pass --registry <host:port>." >&2
    exit 1
fi
if [ -z "$PLATFORM" ] || [ -z "$TAG" ]; then
    echo "--platform and --tag need non-empty values." >&2
    exit 1
fi

command -v docker >/dev/null 2>&1 || { echo "docker not found on PATH." >&2; exit 1; }
docker buildx version >/dev/null 2>&1 || { echo "docker buildx is required (Docker Desktop ships it)." >&2; exit 1; }

REF="$REGISTRY/$IMAGE_NAME:$TAG"
echo "Building $REF for $PLATFORM"
if ! docker buildx build --platform "$PLATFORM" -f Dockerfile.worker -t "$REF" --push .; then
    echo "push_worker_image.sh: ERROR: build or push of $REF failed." >&2
    echo "  A multi-arch build needs the containerd image store or a docker-container builder;" >&2
    echo "  an HTTP registry other than localhost needs 'insecure-registries' in this docker daemon." >&2
    exit 1
fi

# Confirm the registry now lists the tag, so a push that went elsewhere does not pass as done.
if command -v curl >/dev/null 2>&1; then
    tags="$(curl -s -m 10 "http://$REGISTRY/v2/$IMAGE_NAME/tags/list" || true)"
    if ! printf '%s' "$tags" | grep -q "\"$TAG\""; then
        echo "push_worker_image.sh: ERROR: pushed $REF, but the registry does not list tag '$TAG' (got: '$tags')." >&2
        exit 1
    fi
    echo "Registry lists $IMAGE_NAME tags: $tags"
else
    echo "push_worker_image.sh: WARNING: curl not found; the registry's tag list was not checked." >&2
fi
echo "pushed $REF"
```
