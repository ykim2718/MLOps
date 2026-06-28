# Docker CLI (Command Line Interface)

각 컴포넌트를 도커로 띄우고 운영할 때 공통으로 쓰는 명령을 모았습니다.

## 0. Version

```powershell
docker compose version             # Compose v2 설치 여부와 버전을 확인한다.
docker version                     # Docker Engine/CLI 버전을 확인한다.
```

> 신버전은 `docker compose` (공백), 구버전은 `docker-compose` (하이픈) 입니다. `docker compose version` 이 정상 출력되면 v2 환경입니다.

## 1. Shared Network

컴포넌트들이 서비스명으로 서로 통신하려면 공유 네트워크가 있어야 합니다. 이 프로젝트는 `mlops` 네트워크를 공유하며, 최초 한 번만 만들면 됩니다. compose 파일들은 이를 `external: true` 로 참조하므로 **네트워크가 먼저 존재해야** 합니다.

### 만들기 / 확인 / 삭제

  ```powershell
  docker network create mlops        # 공유 네트워크 생성 (최초 1회).
  docker network ls                  # 네트워크 목록 확인 — NAME 열에 mlops 가 보이면 준비 완료.
  docker network inspect mlops       # 상세 정보 — Containers 항목에서 붙어 있는 컨테이너를 확인한다.
  docker network rm mlops            # 네트워크 삭제 (붙은 컨테이너가 없을 때만 가능).
  docker network prune               # 어디에도 붙지 않은 네트워크를 일괄 정리한다 (주의).
  ```

  > 이미 있는 네트워크를 다시 `create` 하면 `already exists` 에러가 납니다. 무시해도 되며, `docker network ls` 로 존재 여부를 먼저 확인하면 깔끔합니다.

### 컨테이너 붙이기 / 떼기

  보통은 compose 의 `networks:` 가 자동으로 연결하므로 수동 명령은 거의 쓰지 않습니다. 임시로 붙이거나 뗄 때만 사용합니다.

  ```powershell
  docker network connect mlops <container>       # 떠 있는 컨테이너를 네트워크에 연결한다.
  docker network disconnect mlops <container>    # 네트워크에서 분리한다.
  ```

## 2. Start & Stop

```powershell
docker compose -p <Project Name> up -d           # 백그라운드 (detached) 실행 — 창을 닫아도 유지된다.
docker compose -p <Project Name> up -d --build   # 이미지를 새로 빌드하면서 실행한다.
docker compose ps                                # 컨테이너 상태를 확인한다.

docker compose stop                # 컨테이너를 정지한다 (제거하지 않는다).
docker compose start               # 정지된 컨테이너를 다시 시작한다.
docker compose restart             # 스택의 컨테이너를 재시작한다.
docker restart <container>         # 컨테이너 하나를 이름으로 재시작한다 (compose 밖에서).

docker compose down                # 정지 + 컨테이너/네트워크 제거 (named volume 의 데이터는 유지).
docker compose down -v             # named volume 까지 삭제하여 데이터를 초기화한다 (주의).
```

## 3. Status & Listing

### 호스트 전체

  ```powershell
  docker ps                          # 현재 실행 중인 컨테이너만 표시.
  docker ps -a                       # 멈춘 것까지 전부 표시 (Exited 포함).
  docker ps -q                       # 컨테이너 ID 만 표시 (스크립트용).
  docker ps --filter "name=mongo"    # 이름으로 거른다.
  docker ps --filter "network=mlops" # mlops 네트워크에 붙은 것만.
  ```

  보기 좋게 컬럼을 골라 한 줄로:

  ```powershell
  docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
  ```

### compose 스택만

  ```powershell
  docker compose ps                  # 해당 docker-compose.yml 의 컨테이너 상태만.
  docker compose ps -a               # 멈춘 것까지.
  ```

  > `docker ps` 는 **호스트 전체**, `docker compose ps` 는 **그 폴더의 compose 스택**만 봅니다. 자주 보는 열 — `STATUS` (`Up ...` = 실행 중, `Exited` = 종료), `PORTS` (`0.0.0.0:27017->27017/tcp` 처럼 호스트↔컨테이너 매핑), `NAMES` (컨테이너 이름).

## 4. Logs

```powershell
docker compose logs -f                  # 전체 로그를 실시간으로 본다.
docker compose logs -f <service>        # 특정 서비스의 로그만 본다.
docker compose -f <file>.yml logs -f    # 특정 compose 파일의 로그를 본다 (앞 -f = 파일 지정, 뒤 -f = follow).
```

## 5. Multiple Compose Files

한 폴더에 compose 파일이 여러 개일 때는 `-f` 로 대상을 지정합니다.

```powershell
docker compose -p <Project Name> -f <file>.yml up -d   # 지정한 compose 파일로 실행한다.
docker compose -f <file>.yml logs -f      # 그 파일의 서비스 로그를 본다.
docker compose -f <file>.yml down         # 그 파일의 스택을 내린다.
```

## 6. Scaling

같은 서비스를 여러 개로 늘려 처리량을 높입니다.

```powershell
docker compose -p <Project Name> up -d --scale <service>=3              # 해당 서비스를 3개로 늘린다.
docker compose -p <Project Name> -f <file>.yml up -d --scale <service>=3
```

> compose 가 만드는 컨테이너 이름은 `<Project Name>-<Service Name>-<Replica Number>` 형식입니다. Replica Number 는 보통 `1` 하나지만, `--scale <service>=3` 처럼 늘리면 `-2`·`-3` 이 추가로 생깁니다.

## 7. Resource Limits

컨테이너 하나가 호스트 메모리를 과도하게 먹으면 서버 전체가 멈출 수 있습니다. 실행할 때 상한을 걸어 한 컨테이너가 자원을 독차지하지 못하게 막습니다.

```powershell
docker run -d --name <container> -m <size> <image>                   # 메모리를 <size> 로 묶어 백그라운드 실행 (-m = --memory, 예: 4g).
docker run -d --name <container> -m <size> --memory-swap <size> <image>  # swap 까지 <size> 로 묶어 초과 사용을 차단한다.
docker run -d --name <container> --cpus <n> <image>                   # CPU 를 <n> 코어로 제한한다.
```

떠 있는 컨테이너의 상한을 바꾸거나 실제 사용량을 살핍니다.

```powershell
docker update -m <size> <container>  # 실행 중인 컨테이너의 메모리 상한을 바꾼다.
docker stats                       # 컨테이너별 메모리/CPU 사용량을 실시간으로 본다.
docker stats --no-stream           # 한 번만 찍고 끝낸다 (스크립트용).
```

compose 에서는 서비스에 같은 상한을 걸어 둡니다.

다음은 docker compose 를 위한 yaml 입니다.

```yaml
# docker-compose.yml — 서비스에 메모리 상한 걸기
services:
  <service>:
    mem_limit: <size>              # 이 서비스의 컨테이너를 <size> 로 제한한다 (예: 4g).
```

> 상한을 넘기면 도커가 그 컨테이너를 강제로 종료합니다 (OOM kill — `docker ps -a` 에서 `Exited` 로 보임). 메모리를 많이 쓰는 학습/추론 작업일수록 상한을 넉넉히 두되, 호스트 전체 메모리보다는 작게 잡아 다른 컨테이너의 몫을 남겨 둡니다.

## 8. Exec & One-off

```powershell
docker compose exec <service> <command>            # 떠 있는 컨테이너 안에서 명령을 1회 실행한다.
docker compose run --rm <service> <command>        # 1회용 컨테이너로 명령을 실행하고 종료한다.
```

## 9. Container Shell — 들어가기 / 나오기

떠 있는 컨테이너 안으로 **셸을 띄워 직접 들어가** 파일을 확인하거나 명령을 실행할 수 있습니다.

```powershell
# 들어가기 — 떠 있는 컨테이너의 대화형 셸에 접속한다 (-it = 입력 가능한 터미널).
docker compose exec -it <service> bash             # bash 가 없는 경우 sh 로 대체한다.
docker compose exec -it <service> sh               # alpine 등 경량 이미지 (bash 미포함)

# 컨테이너 이름으로 직접 접속 (compose 밖에서 — docker ps 로 이름 확인).
docker exec -it <container> bash
```

나오기는 컨테이너를 멈추지 않고 셸만 빠져나옵니다.

```text
exit            # 셸 종료 후 호스트로 복귀 (또는 Ctrl-D). 컨테이너는 계속 떠 있다.
Ctrl-P, Ctrl-Q  # docker attach 로 붙은 경우, 컨테이너를 멈추지 않고 분리 (detach) 한다.
```

> `exec` 로 들어간 셸을 `exit` 하면 그 셸 세션만 끝나고 **컨테이너는 계속 실행** 됩니다. 컨테이너 자체를 멈추려면 [§2](#2-start--stop) 의 `docker compose stop` / `down` 을 씁니다. 셸이 없는 컨테이너에는 1회용 셸 컨테이너로 같은 네트워크에 붙어 접근합니다 (`docker run -it --rm --network <network> <image> sh`).

## 10. Linux — sudo 없이 docker 쓰기

리눅스에서는 docker 데몬 소켓을 root 가 소유하므로 기본적으로 명령마다 `sudo` 가 필요합니다. 내 계정을 `docker` 그룹에 넣으면 `sudo` 없이 쓸 수 있습니다.

먼저 시스템에 어떤 그룹이 있는지, `docker` 그룹이 이미 있는지 확인합니다.

```bash
getent group                    # 시스템의 전체 그룹 목록을 본다.
getent group docker             # docker 그룹만 조회 — 한 줄이 나오면 이미 존재 (없으면 출력 없음).
cut -d: -f1 /etc/group | sort   # 그룹 이름만 정렬해서 본다 (가독성).
```

`docker` 그룹이 없을 때만 만들고, 내 계정을 그 그룹에 추가합니다.

```bash
sudo groupadd docker            # docker 그룹 생성 (보통 설치 시 이미 있다 — 없을 때만).
sudo usermod -aG docker $USER   # 현재 사용자를 docker 그룹에 추가한다.
```

그룹 변경은 **새 로그인 세션부터** 적용됩니다. 다음 중 하나로 반영합니다.

```bash
newgrp docker                   # 현재 셸에 즉시 적용 (재로그인 대신 임시 적용).
# 또는 로그아웃 후 다시 로그인 (SSH 면 연결을 끊고 재접속). 확실한 방법.
```

적용됐는지 확인:

```bash
groups                          # 출력에 docker 가 보이면 적용됨.
docker ps                       # sudo 없이 정상 동작하면 완료.
```

> **보안 주의** — `docker` 그룹은 사실상 root 권한과 같습니다 (컨테이너로 호스트 파일시스템을 마운트할 수 있음). 신뢰하는 1인 개발 머신에서만 쓰고, 공용 서버에서는 `sudo` 를 유지하는 편이 안전합니다.

## Appendix A. Terminology

- **build context** — `docker build` 가 이미지를 구울 때 도커 데몬에 통째로 보내는 파일 묶음. 보통 `Dockerfile` 이 있는 폴더가 기준이며, `COPY`·`ADD` 는 이 안의 파일만 집어올 수 있습니다. `.dockerignore` 로 보낼 파일을 추려 묶음을 가볍게 합니다.

## Appendix B. Build & Run

도커는 **이미지를 굽는 단계**와 **컨테이너를 띄우는 단계**로 나뉩니다. 두 단계는 각각 다른 파일이 맡습니다.

$$\text{Dockerfile} \longrightarrow \text{Build (이미지 생성)}$$

$$\text{docker-compose.yml} \longrightarrow \text{Run (컨테이너 가동)}$$
