# Troubleshooting

<sub>rev. 12</sub>

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

- **증상** — `prefect deploy` 가 `Deployment '...' successfully created` 로 끝났는데도 `./healthcheck.sh` 가 `deployment pipeline/pipelineflow-<tier> (not registered - prefect deploy) [FAIL]` 를 냅니다.
- **원인** — healthcheck 는 deployment 이름을 **pool 이름에서 유도**합니다 — `tier="${name%%_*}"`, `dep="pipeline/pipelineflow-$tier"`. 즉 pool `low_performance` 는 `pipelineflow-low`, `high_performance` 는 `pipelineflow-high` 를 기대합니다. `prefect deploy --name` 에 다른 이름 (예: `pipeline-low`·`pipeline-flow`) 을 주면 deployment 는 정상 생성되지만 규칙과 어긋나 healthcheck 가 못 찾습니다. 실패가 아니라 **이름 불일치**입니다.
- **진단** — 실제 이름을 기대값과 견줍니다.

  ```bash
  prefect deployment ls
  # name이 pipelineflow-low / pipelineflow-high 가 아니라 pipeline-low / pipeline-flow 면 불일치 확정
  ```
- **해결** — 잘못된 이름을 지우고 규칙대로 재배포합니다 (`--name` 은 `pipelineflow-<tier>`).

  ```bash
  cd ~/prefect/PipelineFlow
  prefect deployment delete 'pipeline/pipeline-low'
  prefect deployment delete 'pipeline/pipeline-flow'
  prefect deploy --prefect-file pipelineflow-low.yml  --name pipelineflow-low  --no-prompt
  prefect deploy --prefect-file pipelineflow-high.yml --name pipelineflow-high --no-prompt
  ```
- **확인** — `./healthcheck.sh` 의 두 deployment 줄이 `[ OK ]` 로 바뀝니다. pool tier 와 deployment suffix 가 맞아야 (`low_performance`↔`pipelineflow-low`, `high_performance`↔`pipelineflow-high`) 통과합니다.

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
