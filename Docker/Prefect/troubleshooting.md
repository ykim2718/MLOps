# Troubleshooting

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
