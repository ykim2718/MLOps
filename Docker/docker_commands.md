# Docker Commands

각 컴포넌트를 도커로 띄우고 운영할 때 공통으로 쓰는 명령을 모았습니다. 명령은 해당 `docker-compose.yml` 이 있는 폴더에서 실행하며, `<network>` · `<service>` · `<file>` 은 실제 이름으로 바꿔 씁니다.

## 1. Shared Network

컴포넌트들이 서비스명으로 서로 통신하려면 공유 네트워크가 있어야 합니다. 최초 한 번만 만들면 됩니다.

```powershell
docker network create <network>    # 공유 네트워크 생성(이미 있으면 에러는 무시)
docker network ls                  # 네트워크 목록 확인
docker network inspect <network>   # 어떤 컨테이너가 붙어 있는지 확인
docker network rm <network>        # 네트워크 삭제(붙은 컨테이너가 없을 때)
```

## 2. Start & Stop

```powershell
docker compose up -d               # 백그라운드(detached) 실행 — 창을 닫아도 유지된다.
docker compose up -d --build       # 이미지를 새로 빌드하면서 실행한다.
docker compose ps                  # 컨테이너 상태를 확인한다.

docker compose stop                # 컨테이너를 정지한다(제거하지 않는다).
docker compose start               # 정지된 컨테이너를 다시 시작한다.
docker compose restart             # 컨테이너를 재시작한다.

docker compose down                # 정지 + 컨테이너/네트워크 제거(named volume 의 데이터는 유지).
docker compose down -v             # named volume 까지 삭제하여 데이터를 초기화한다(주의).
```

## 3. Logs

```powershell
docker compose logs -f             # 전체 로그를 실시간으로 본다.
docker compose logs -f <service>   # 특정 서비스의 로그만 본다.
```

## 4. Multiple Compose Files

한 폴더에 compose 파일이 여러 개일 때는 `-f` 로 대상을 지정합니다.

```powershell
docker compose -f <file>.yml up -d        # 지정한 compose 파일로 실행한다.
docker compose -f <file>.yml logs -f      # 그 파일의 서비스 로그를 본다.
docker compose -f <file>.yml down         # 그 파일의 스택을 내린다.
```

## 5. Scaling

같은 서비스를 여러 개로 늘려 처리량을 높입니다.

```powershell
docker compose up -d --scale <service>=3           # 해당 서비스를 3개로 늘린다.
docker compose -f <file>.yml up -d --scale <service>=3
```

## 6. Exec & One-off

```powershell
docker compose exec <service> <command>            # 떠 있는 컨테이너 안에서 명령을 1회 실행한다.
docker compose run --rm <service> <command>        # 1회용 컨테이너로 명령을 실행하고 종료한다.
```

## 7. Container Shell — 들어가기 / 나오기

떠 있는 컨테이너 안으로 **셸을 띄워 직접 들어가** 파일을 확인하거나 명령을 실행할 수 있습니다.

```powershell
# 들어가기 — 떠 있는 컨테이너의 대화형 셸에 접속한다(-it = 입력 가능한 터미널).
docker compose exec -it <service> bash             # bash 가 없는 경우 sh 로 대체한다.
docker compose exec -it <service> sh               # alpine 등 경량 이미지(bash 미포함)

# 컨테이너 이름으로 직접 접속(compose 밖에서 — docker ps 로 이름 확인).
docker exec -it <container> bash
```

나오기는 컨테이너를 멈추지 않고 셸만 빠져나옵니다.

```text
exit            # 셸 종료 후 호스트로 복귀(또는 Ctrl-D). 컨테이너는 계속 떠 있다.
Ctrl-P, Ctrl-Q  # docker attach 로 붙은 경우, 컨테이너를 멈추지 않고 분리(detach)한다.
```

> `exec` 로 들어간 셸을 `exit` 하면 그 셸 세션만 끝나고 **컨테이너는 계속 실행** 됩니다. 컨테이너 자체를 멈추려면 [§2](#2-start--stop) 의 `docker compose stop` / `down` 을 씁니다. 셸이 없는 컨테이너에는 1회용 셸 컨테이너로 같은 네트워크에 붙어 접근합니다(`docker run -it --rm --network <network> <image> sh`).
