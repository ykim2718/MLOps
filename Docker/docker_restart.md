# Docker Automatic Restart

<sub>rev. 9</sub>

docker compose 만으로 스스로 복구되는 container 를 구성하는 방법을 다룹니다. container 가 죽거나 고장났을 때 자동으로 다시 띄우는 두 경로를 정리합니다. **restart policy** 는 container 가 **exit** 될 때, **healthcheck + autoheal** 은 container 는 살아있는데 안의 process 만 죽거나 hang 될 때를 담당합니다. 둘은 보완 관계이며, 두 경로 모두 최종적으로 `docker restart` 에 도달합니다. 예시로 Temporal server 1.25 의 dev/quickstart image (`temporalio/auto-setup:1.25`) 를 사용합니다.

```
                   ┌───────────────┐
                   │ docker daemon │
                   └───────┬───────┘
                           │
            ┌──────────────┴───────────────┐
            │                              │
   ┌──────────────────┐          ┌──────────────────┐
   │  restart policy  │          │ healthcheck.test │
   │ (unless-stopped) │          │ (every interval) │
   └────────┬─────────┘          └────────┬─────────┘
            │                             │
            │ container exit              │ retries consecutive
            │ (PID 1 dies / crash /       │ failures (exit != 0)
            │  host reboot)               ▼
            │                Health.Status = unhealthy
            │                   (set by the daemon)
            │                             │
            │                 [willfarrell/autoheal]
            │           polls every AUTOHEAL_INTERVAL (5s)
            │           matches autoheal label + unhealthy
            │                             │
            └──────────────┬──────────────┘
                           ▼
                  ┌────────────────┐
                  │ docker restart │
                  └────────────────┘
```

## 1. Restart Policy

container 의 **exit** 에 반응합니다. exit 은 곧 **PID 1 종료** 이므로 (→ [Container Lifecycle & PID 1](#container-lifecycle--pid-1)), server process 가 PID 1 이면 그 죽음이 container exit 으로 전파되어 여기서 복구됩니다.

  ```yaml
  services:
    temporal:
      image: temporalio/auto-setup:1.25
      restart: unless-stopped        # auto-recovery from crash / reboot
  ```

| Policy | Behavior |
| --- | --- |
| `no` | 재시작하지 않습니다 (기본). |
| `on-failure[:N]` | exit code ≠ 0 일 때만, 최대 N 회 재시작합니다. |
| `always` | 항상 재시작합니다 (수동 stop 후 daemon 재시작 시에도 다시 뜸). |
| `unless-stopped` | 항상 재시작하되 **명시적 `docker stop` 은 제외** 합니다. reboot 생존. **권장**. |

한계: restart policy 는 **exit 만** 봅니다. container 가 running 인데 안의 server 만 죽거나 hang 인 경우는 못 잡습니다 → [2. Healthcheck & Autoheal](#2-healthcheck--autoheal).

### Container Lifecycle & PID 1

container 수명은 **PID 1 하나에 묶여 있습니다**: **PID 1 이 종료되면 container 도 종료** 됩니다 (자식 process 가 남아있든 무관). restart policy 는 이 이벤트를 감시합니다.

PID 1 이 누가 되는지는 image 의 `ENTRYPOINT`/`CMD` 가 결정합니다.

  ```sh
  # last line of entrypoint.sh
  exec temporal-server start    # exec replaces the shell with the server → server becomes PID 1  ✅
  temporal-server start         # no exec → shell stays PID 1, server runs as a child (PID 7)  ❌
  ```

- **server 가 PID 1 (경우 A)** — server crash → PID 1 종료 → container exit → restart policy 가 복구합니다. 공식 `temporalio/*` image 가 이 방식입니다 (`exec` 사용).
- **wrapper 가 PID 1 (경우 B)** — server (자식) crash → PID 1 (shell) 생존 → container 는 running 유지 → restart policy 는 못 봅니다 → "running container, dead server" zombie 가 됩니다. custom image 라면 entrypoint 를 반드시 `exec <server>` 로 끝낼 것.

## 2. Healthcheck & Autoheal

container 가 running 이어도 안의 server 가 죽거나 hang 인 경우를 담당하는 경로입니다. healthcheck 가 감지하고, autoheal 이 `docker restart` 를 실행합니다.

### Healthcheck & Health.Status

  ```yaml
      healthcheck:
        test: ["CMD","temporal","operator","cluster","health","--address","localhost:7233"]
        interval: 30s
        timeout: 10s
        retries: 3
  ```

- 위 `test` 는 container 안에서 `temporal` CLI 를 실행해 `localhost:7233` 의 frontend 로 gRPC health check 를 보냅니다. 실패 경로는 세 가지입니다: server process 가 죽어 port 가 닫혔으면 connection refused 로 즉시 실패하고, server 가 hang 이면 응답이 없어 `timeout` (10s) 초과로 Docker 가 명령을 강제 종료하며, process 가 떠 있어도 frontend 가 SERVING 상태가 아니면 CLI 가 스스로 실패합니다. 세 경우 모두 exit code ≠ 0 이 되고, 이것이 연속 `retries` (3) 회 반복되면 daemon 이 `Health.Status` 를 `unhealthy` 로 설정합니다.
- `test` 명령은 **사용자가 작성** 합니다. Docker 는 이를 `interval` 마다 실행하는 **mechanism 만** 제공합니다. 명령이 무엇을 검사할지는 전적으로 작성자가 정하며, Docker 는 PID 1 을 따로 모니터링하지 않습니다.
- 판정은 **exit code** 로만 합니다: `0` = healthy, `1` = unhealthy, `2` = **reserved (사용 금지)**.
- Docker **daemon** 이 exit code 를 읽어, 연속 `retries` 회 실패 시 container 의 **`Health.Status`** 를 `unhealthy` 로 설정합니다 (`healthy` / `unhealthy` / `starting`). `docker ps` 의 STATUS 나 `docker inspect` 로 확인합니다.
- 주의: **restart policy 는 `Health.Status` 를 보지 않습니다.** unhealthy 여도 daemon 이 스스로 재시작하지 않으므로, 조치할 주체가 따로 필요합니다 → [Autoheal](#autoheal).

### Autoheal

`unhealthy` container 를 실제로 재시작하는 주체입니다.

  ```yaml
    autoheal:
      image: willfarrell/autoheal
      environment: [AUTOHEAL_CONTAINER_LABEL=autoheal]   # label key to watch
      volumes: ["/var/run/docker.sock:/var/run/docker.sock"]
      restart: unless-stopped
  ```

  대상 container 에는 label 을 붙입니다.

  ```yaml
    temporal:
      labels: [autoheal=true]
  ```

- 동작: `AUTOHEAL_INTERVAL` (**기본 5s**) 마다 Docker 에 질의해, **`autoheal=true` label + `Health.Status=unhealthy`** 인 container 를 모두 찾아 `docker restart` 합니다.
- `AUTOHEAL_CONTAINER_LABEL` 은 값이 변하는 게 아니라 **"어떤 label key 를 감시할지" 정하는 고정 설정** 입니다 (기본 `autoheal`). `=all` 로 두면 label 무관하게 healthcheck 있는 모든 container 를 감시합니다.
- 범위: `docker.sock` 으로 daemon 전체를 보므로 **같은 compose 파일이 아니라 호스트의 모든 container** 가 대상입니다. 따라서 **호스트당 autoheal 은 하나만** 띄우고, 각 stack 에 중복 등록하지 않습니다.
- 관련 env: `AUTOHEAL_START_PERIOD` (기본 0).

## 3. Docker Compose Example

  ```yaml
  services:
    temporal:
      image: temporalio/auto-setup:1.25       # server is PID 1 (exec)
      ports: ["7233:7233"]
      restart: unless-stopped                  # exit / reboot path
      labels: [autoheal=true]                  # hang / zombie path
      healthcheck:
        test: ["CMD","temporal","operator","cluster","health","--address","localhost:7233"]
        interval: 30s
        timeout: 10s
        retries: 3

    autoheal:                                  # one per host
      image: willfarrell/autoheal
      environment: [AUTOHEAL_CONTAINER_LABEL=autoheal]
      volumes: ["/var/run/docker.sock:/var/run/docker.sock"]
      restart: unless-stopped
  ```

- **server crash** → PID 1 exit → container exit → `restart: unless-stopped` 가 복구합니다.
- **server hang / zombie** → healthcheck 실패 → `Health.Status=unhealthy` → autoheal 이 `docker restart` 를 실행합니다.

## Appendix A. Terminology

- **PID** — process ID. Linux kernel 이 각 process 에 부여하는 고유 번호입니다.
- **PID 1** — 각 PID namespace 의 첫 process 입니다. container 는 자체 PID namespace 를 가지므로 `ENTRYPOINT`/`CMD` 로 뜬 첫 process 가 PID 1 이 되며, PID 1 이 종료되면 container 도 종료됩니다.
