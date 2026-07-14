> ⚠️ **This is an auto-synced copy.** Do not edit here.

# Troubleshooting

<sub>rev. 17</sub>

운영 중 마주친 문제를 증상·원인·진단·해결 순으로 모읍니다. 새 이슈는 H2 항목으로 덧붙입니다.

## Prefect server unreachable on :4200 — empty reply / RemoteProtocolError

- **증상** — host 에서 `prefect work-pool ls` 가 `httpx.RemoteProtocolError: Server disconnected without sending a response` 로 죽습니다. raw 확인도 `curl http://127.0.0.1:4200/api/health` 가 `curl: (52) Empty reply from server` 를 돌려줍니다. 정작 server 컨테이너는 `docker ps` 에서 `Up` 이고 `0.0.0.0:4200->4200/tcp` 를 게시 중입니다.
- **원인** — server 프로세스 자체는 정상입니다. Docker Desktop (WSL2) 의 host → 컨테이너 4200 publish (docker-proxy) 가 wedge 되어, 연결은 받지만 컨테이너로 넘기지 못해 빈 응답이 납니다. 컨테이너가 오래 떠 있는 동안 Docker Desktop 갱신·WSL2 재시작 등으로 매핑이 깨질 때 나타납니다.
- **진단** — 컨테이너 **안에서** API 를 직접 두드려 server 와 포트 포워딩을 가립니다.

  ```text
  # inside the container — bypasses the host port publish
  docker exec prefect-server-prefect_server-1 python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:4200/api/health').read())"
  # -> b'true'   (server healthy)   while the host curl stays empty   => host port-forward is the culprit
  ```

  안에서는 `b'true'`, 밖에서는 빈 응답 → **포트 포워딩 문제로 확정**입니다. URL·prefect 버전과는 무관합니다 (살아 있는 server 는 어떤 버전이라도 최소한 응답은 보내므로, 빈 응답은 곧 publish 문제입니다).
- **해결** — 컨테이너를 재시작해 포트 매핑을 다시 등록합니다 (대개 이걸로 해결).

  ```powershell
  docker restart prefect-server-prefect_server-1
  # still empty? recreate the container:
  docker compose -f docker-compose.server.yml up -d --force-recreate prefect_server
  # still empty? restart Docker Desktop (resets WSL2 / vpnkit networking), then re-check
  ```
- **확인** — `curl http://127.0.0.1:4200/api/health` 가 `true`, 이어서 `prefect work-pool ls` 가 정상 출력됩니다.

  ```text
                                        Work Pools
  ┌─────────────────┬────────┬──────────────────────────────────────┬───────────────────┐
  │ Name            │ Type   │                                   ID │ Concurrency Limit │
  ├─────────────────┼────────┼──────────────────────────────────────┼───────────────────┤
  │ low_performance │ docker │ 95e189a9-0d8d-4f74-b17c-375a01f6e70f │ 4                 │
  └─────────────────┴────────┴──────────────────────────────────────┴───────────────────┘
                                (**) denotes a paused pool
  ```
- **추가 점검** — 빈 응답이 계속되면 4200 을 다른 프로세스가 잡고 있는지 봅니다. `netstat -ano | findstr :4200` 의 PID 가 Docker Desktop (`com.docker.backend`) 이 아니면 그 프로세스가 가로채는 것이니, 끄거나 server 게시 포트를 바꿉니다.

## Deployment shows "(not registered)" in healthcheck after a successful prefect deploy

- **증상** — `prefect deploy` 가 `Deployment '...' successfully created` 로 끝났는데도 `./healthcheck.sh` 가 `deployment pipeline/<tier>_deployment (not registered - prefect deploy) [FAIL]` 를 냅니다.
- **원인** — healthcheck 는 deployment 이름을 **pool 이름에서 유도**합니다 — `tier="${name%%_*}"`, `dep="pipeline/${tier}_deployment"`. 즉 pool `low_performance` 는 `low_deployment`, `high_performance` 는 `high_deployment` 를 기대합니다. `prefect deploy --name` 에 다른 이름 (예: `pipeline-low`·`pipeline-flow`) 을 주면 deployment 는 정상 생성되지만 규칙과 어긋나 healthcheck 가 못 찾습니다. 실패가 아니라 **이름 불일치**입니다.
- **진단** — 실제 이름을 기대값과 견줍니다.

  ```bash
  prefect deployment ls
  # name이 low_deployment / high_deployment 가 아니라 pipeline-low / pipeline-flow 면 불일치 확정
  ```
- **해결** — 잘못된 이름을 지우고 규칙대로 재배포합니다 (`--name` 은 `<tier>_deployment`).

  ```bash
  cd ~/prefect/PipelineFlow
  prefect deployment delete 'pipeline/pipeline-low'
  prefect deployment delete 'pipeline/pipeline-flow'
  prefect deploy --prefect-file low_deployment.yml  --name low_deployment  --no-prompt
  prefect deploy --prefect-file high_deployment.yml --name high_deployment --no-prompt
  ```
- **확인** — `./healthcheck.sh` 의 두 deployment 줄이 `[ OK ]` 로 바뀝니다. pool tier 와 deployment 이름이 맞아야 (`low_performance`↔`low_deployment`, `high_performance`↔`high_deployment`) 통과합니다.

## Stale OFFLINE workers never pruned (old server yaml without worker_pruner sidecar)

- **증상** — healthcheck 의 `dispatchers (server records)` 줄에 `N offline(stale)` 이 하루가 지나도 사라지지 않고 계속 쌓입니다.
- **원인** — Prefect server 는 죽은 worker 를 OFFLINE 으로 표시만 하고 지우지 않습니다. 청소는 server stack 의 `worker_pruner` 사이드카 (`prune_loop.sh`, 1시간 주기) 가 맡습니다. 예전 `docker-compose.server.yml` 로 띄운 stack 에는 이 사이드카가 없어 stale 이 영영 남습니다. server 결함이 아니라 **사이드카 부재**입니다.
- **진단** — 사이드카 컨테이너 유무를 봅니다.

  ```bash
  docker ps -a --filter name=worker_pruner
  # 아무것도 안 나오면 예전 yaml 확정 (사이드카 미기동)
  ```
- **해결** — `prefect_server` 는 그대로 두고 사이드카만 더해 올립니다 (server 무중단). server 의 `~/prefect/PrefectServer/` 에 ① `prune_loop.sh` (repo 의 PrefectServer 파일) 를 `docker-compose.server.yml` 과 같은 폴더에 두고, ② compose 의 `services:` 아래에 사이드카 블록을 더합니다.

  ```yaml
  worker_pruner:
    image: alpine:3                     # tiny; installs curl + jq at start (no python image)
    depends_on:
      - prefect_server
    environment:
      - PREFECT_API_URL=http://prefect_server:4200/api   # internal server API the sidecar prunes via
      - PRUNE_INTERVAL_SECONDS=3600                       # prune cadence (hourly)
    volumes:
      - ./prune_loop.sh:/prune_loop.sh:ro
    command: ["sh", "-c", "tr -d '\\r' < /prune_loop.sh | sh"]   # strip CR (Windows EOL) then run
    networks:
      - mlops
    restart: unless-stopped
  ```

  그 서비스만 지정해 올리면 이미 떠 있는 `prefect_server` 는 정의가 같아 건드리지 않습니다.

  ```bash
  cd ~/prefect/PrefectServer
  docker compose -f docker-compose.server.yml up -d worker_pruner
  ```
- **확인** — 사이드카가 뜨고 곧 stale 을 비웁니다.

  ```bash
  docker logs --tail 20 prefect-server-worker_pruner-1
  #   -> "worker_pruner: pruning OFFLINE workers every 3600s ..." 시작 줄
  #   -> 곧 "worker_pruner: pruned offline <pool>/DockerWorker ..." 로 정리
  ```

  이후 `./healthcheck.sh` 의 `offline(stale)` 수가 0 으로 줄어듭니다. 지금 쌓인 것을 기다리지 않고 비우려면 한 사이클을 손으로 돌립니다 (pool 별 worker filter → OFFLINE 이름 → `curl -X DELETE`).

## prefect_server crash-loop (`Up N seconds`) — alembic `TimeoutError`, 원격 Postgres 도달 불가

- **증상** — prefect_server 가 계속 재시작합니다. `docker compose ps` 의 STATUS 가 `Up 11 seconds` 처럼 짧게 리셋되고 (같은 stack 의 `worker_pruner` 는 `Up N minutes`), `register_pool.sh` 의 pool 생성이 성공 메시지 없이 조용히 재시도만 반복합니다.
- **원인** — server 는 기동 시 Postgres 에 붙어 alembic DB migration 을 돌립니다. DB 에 도달하지 못하면 로그가 **인증 에러가 아니라** `TimeoutError` → `Application startup failed. Exiting.` 로 끝나고, `restart: unless-stopped` 때문에 무한 재시작합니다. 자격증명 (`PREFECT_SERVER_DATABASE_CONNECTION_URL`) 문제가 아니라 **네트워크 도달 문제**입니다 — 대개 DB 호스트 (특히 Windows + Docker Desktop) 의 방화벽이 LAN 인바운드 5432 를 막고 있습니다. Docker 가 `0.0.0.0:5432` 로 게시해도 Windows Defender 방화벽이 외부 유입을 차단합니다.
- **진단** — 로그에서 `TimeoutError` 를 확인한 뒤, 도달 가능성을 컨테이너 → 호스트 → DB 머신 순으로 좁힙니다.

  ```bash
  # (1) 죽는 이유 — alembic TimeoutError 인지 (인증 에러면 원인이 다름)
  sudo docker logs --tail 60 prefect-server-prefect_server-1

  # (2) 컨테이너 안에서 Postgres 5432 도달? (3s 뒤 timeout 이면 도달 불가)
  sudo docker compose -f docker-compose.server.yml exec -T prefect_server \
    python -c 'import socket; socket.create_connection(("192.168.0.13",5432),3); print("reachable")'

  # (3) 호스트에서도 안 되나 — 컨테이너 network 문제 vs DB 문제 가르기
  timeout 3 bash -c '</dev/tcp/192.168.0.13/5432' && echo OPEN || echo "BLOCKED/CLOSED"

  # (4) 호스트도 BLOCKED 면 머신 자체는 사나 (응답의 ttl=128 이면 Windows host)
  ping -c 2 192.168.0.13
  ```

  (2)(3) 모두 실패 + ping 성공 → 머신은 살아있고 **5432 포트만 막힘** → DB 호스트 방화벽·게시 확인. (3)만 `OPEN` 이고 (2) 실패 → 컨테이너 network 라우팅 문제 (LAN 으로 못 나감).
- **해결** — DB 호스트에서 컨테이너·포트 게시·방화벽을 확인하고 인바운드 5432 를 엽니다.

  ```powershell
  # on the Postgres host (Windows) — container up & publishing 0.0.0.0:5432 ?
  docker ps --filter "name=postgres"
  Test-NetConnection 127.0.0.1 -Port 5432        # local True but remote blocked => firewall

  # admin PowerShell — allow LAN inbound 5432 (scope to the subnet)
  New-NetFirewallRule -DisplayName "PostgreSQL 5432" -Direction Inbound `
      -Protocol TCP -LocalPort 5432 -Action Allow -RemoteAddress 192.168.0.0/24
  ```

  Linux DB 호스트라면 `sudo ufw allow from 192.168.0.0/24 to any port 5432 proto tcp`.
- **확인** — 방화벽 허용 후 server 머신에서 `timeout 3 bash -c '</dev/tcp/192.168.0.13/5432' && echo OPEN` 가 `OPEN` 이면 도달됩니다. server 를 다시 세워 migration 을 통과시킵니다.

  ```bash
  sudo docker compose -f docker-compose.server.yml up -d --force-recreate prefect_server
  sudo docker compose -f docker-compose.server.yml ps            # STATUS 가 Up N minutes 로 유지
  sudo docker logs --tail 15 prefect-server-prefect_server-1     # 정상 기동, TimeoutError 없음
  ```

  STATUS 가 유지되고 `TimeoutError` 가 사라지면 `register_pool.sh` 도 바로 `Created work pool ...` 를 냅니다. 같은 원리로 다른 backing service (MinIO 9000 · MLflow 5000 · MongoDB 27017) 도 원격 호스트의 인바운드 방화벽이 열려야 LAN 에서 붙습니다 — 설치 시 [prefect.md §3](prefect.md) 의 포트 도달성 선검증으로 미리 걸러야 합니다.
