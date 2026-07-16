> ⚠️ **This is an auto-synced copy.** Do not edit here.

# Docker CLI (Command Line Interface)

<sub>rev. 107</sub>

각 컴포넌트를 도커로 띄우고 운영할 때 공통으로 쓰는 명령을 모았습니다.

## 1. Setup

### Version

```powershell
docker compose version             # check whether Compose v2 is installed, and its version.
docker version                     # check the Docker Engine/CLI version.
```

> 신버전은 `docker compose` (공백), 구버전은 `docker-compose` (하이픈) 입니다. `docker compose version` 이 정상 출력되면 v2 환경입니다.

### Shared Network

컴포넌트들이 서비스명으로 서로 통신하려면 공유 네트워크가 있어야 합니다. 이 프로젝트는 `mlops` 네트워크를 공유하며, 최초 한 번만 만들면 됩니다. compose 파일들은 이를 `external: true` 로 참조하므로 **네트워크가 먼저 존재해야** 합니다.

#### Create / Check / Remove

```powershell
docker network create mlops        # create the shared network (once).
docker network ls                  # list networks — ready when mlops shows in the NAME column.
docker network inspect mlops       # details — check attached containers under Containers.
docker network rm mlops            # remove the network (only when no container is attached).
docker network prune               # bulk-remove networks attached nowhere (careful).
```

> 이미 있는 네트워크를 다시 `create` 하면 `already exists` 에러가 납니다. 무시해도 되며, `docker network ls` 로 존재 여부를 먼저 확인하면 깔끔합니다.

#### Attach / Detach

보통은 compose 의 `networks:` 가 자동으로 연결하므로 수동 명령은 거의 쓰지 않습니다. 임시로 붙이거나 뗄 때만 사용합니다.

```powershell
docker network connect mlops <container>       # attach a running container to the network.
docker network disconnect mlops <container>    # detach it from the network.
```

## 2. Run

compose 없이 이미지에서 컨테이너를 직접 띄웁니다. `docker run` 은 이미지로 새 컨테이너를 만들어 시작합니다.

```powershell
docker run <image>                                     # create a container from the image and run in the foreground.
docker run -d <image>                                  # run in the background (detached).
docker run -d --name <container> <image>               # run with a given name.
docker run -d -p <host>:<container> <image>            # map a host<->container port (e.g. 8080:80).
docker run -d -v <host path>:<container path> <image>  # mount a host folder into the container.
docker run -d --network <network> <image>              # run attached to the given network.
docker run --rm -it <image> bash                       # run a throwaway container, enter a shell, delete on exit.
docker run -d --restart unless-stopped <image>         # auto-restart on crash or reboot (until stopped by hand).
```

> `--restart` 정책 — `no` (기본), `on-failure[:N]` (비정상 종료 시만), `always` (항상, 재부팅 뒤에도 무조건), `unless-stopped` (always 와 같되 `docker stop` 으로 직접 멈춘 것은 재시작 안 함). 오래 떠 있어야 하는 서비스에는 `unless-stopped` 가 무난합니다. compose 에서는 서비스에 `restart: unless-stopped` 로 같은 정책을 겁니다.

## 3. Compose

### Multiple Compose Files

한 폴더에 compose 파일이 여러 개일 때는 `-f` 로 대상을 지정합니다.

```powershell
docker compose -p <Project Name> -f <file>.yml up -d   # run with the specified compose file.
docker compose -f <file>.yml logs -f      # view that file's service logs.
docker compose -f <file>.yml down         # bring down that file's stack.
```

### Scaling

같은 서비스를 여러 개로 늘려 처리량을 높입니다.

```powershell
docker compose -p <Project Name> up -d --scale <service>=3              # scale the service to 3 replicas.
docker compose -p <Project Name> -f <file>.yml up -d --scale <service>=3
```

> compose 가 만드는 컨테이너 이름은 `<Project Name>-<Service Name>-<Replica Number>` 형식입니다. Replica Number 는 보통 `1` 하나지만, `--scale <service>=3` 처럼 늘리면 `-2`·`-3` 이 추가로 생깁니다.

## 4. Operations

### Container States

컨테이너는 명령에 따라 아래 상태를 오갑니다.

| State | Command | Process | CPU | Memory | Location |
|-------|---------|---------|-----|--------|----------|
| Running | `docker run` · `docker compose up` | 실행 중 | 사용 | 사용 | 메모리 + 디스크 |
| Stopped | `docker stop` | 종료됨 | 안 씀 | 안 씀 | 디스크에 상태만 |
| Paused | `docker pause` | 얼려짐 | 안 씀 | 점유 (그대로) | 메모리에 그대로 |
| Removed | `docker rm` · `docker run --rm` | 없음 | 없음 | 없음 | 완전 삭제 |

> `pause` 는 프로세스를 얼려 CPU 는 안 쓰지만 **RAM 은 그대로 점유**합니다 (`docker unpause` 로 재개). `stop` 은 RAM 을 비우고 디스크에 상태만 남기며, `rm` 은 그 상태까지 완전히 지웁니다.

### Status & Listing

#### Host-wide

```powershell
docker ps                          # show only running containers.
docker ps -a                       # show all, including stopped (Exited too).
docker ps -q                       # show container IDs only (for scripts).
docker ps --filter "name=mongo"    # filter by name.
docker ps --filter "network=mlops" # only those attached to the mlops network.
```

보기 좋게 컬럼을 골라 한 줄로:

```powershell
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

#### Compose Stack

```powershell
docker compose ps                  # only this docker-compose.yml's containers.
docker compose ps -a               # including stopped ones.
```

> `docker ps` 는 **호스트 전체**, `docker compose ps` 는 **그 폴더의 compose 스택**만 봅니다. 자주 보는 열 — `STATUS` (`Up ...` = 실행 중, `Exited` = 종료), `PORTS` (`0.0.0.0:27017->27017/tcp` 처럼 호스트↔컨테이너 매핑), `NAMES` (컨테이너 이름).

### Start & Stop

```powershell
docker compose -p <Project Name> up -d                  # run in the background (detached) — survives closing the window.
docker compose -p <Project Name> up -d --build          # rebuild the image while starting.
docker compose -p <Project Name> up -d --force-recreate # recreate containers even if config is unchanged.
docker compose ps                                       # check container status.

docker compose stop                # stop containers (without removing).
docker compose start               # start stopped containers again.
docker compose restart             # restart the stack's containers.
docker restart <container>         # restart a single container by name (outside compose).
docker stop <container>            # stop a container seen in docker ps (name/ID, graceful).
docker kill <container>            # force-kill immediately (when stop won't work).
docker rm -f <container>           # stop and remove it (-f = even if running).

docker compose down                # stop + remove containers/networks (named-volume data kept).
docker compose down -v             # also delete named volumes, resetting data (careful).
```

### Logs

```powershell
docker compose logs -f                  # follow all logs in real time.
docker compose logs -f <service>        # follow only a specific service's logs.
docker compose -f <file>.yml logs -f    # follow a specific compose file's logs (first -f = pick file, second -f = follow).
```

### Resource Limits

컨테이너 하나가 호스트 메모리를 과도하게 먹으면 서버 전체가 멈출 수 있습니다. 실행할 때 상한을 걸어 한 컨테이너가 자원을 독차지하지 못하게 막습니다.

```powershell
docker run -d --name <container> -m <size> <image>                   # cap memory at <size> and run detached (-m = --memory, e.g. 4g).
docker run -d --name <container> -m <size> --memory-swap <size> <image>  # also cap swap at <size> to block overuse.
docker run -d --name <container> --cpus <n> <image>                   # limit CPU to <n> cores.
```

떠 있는 컨테이너의 상한을 바꾸거나 실제 사용량을 살핍니다.

```powershell
docker update -m <size> <container>  # change a running container's memory cap.
docker stats                       # watch per-container memory/CPU usage in real time.
docker stats --no-stream           # print once and exit (for scripts).
```

compose 에서는 서비스에 같은 상한을 걸어 둡니다.

다음은 docker compose 를 위한 yaml 입니다.

```yaml
# docker-compose.yml — cap a service's memory
services:
  <service>:
    mem_limit: <size>              # limit this service's container to <size> (e.g. 4g).
```

> 상한을 넘기면 도커가 그 컨테이너를 강제로 종료합니다 (OOM kill — `docker ps -a` 에서 `Exited` 로 보임). 메모리를 많이 쓰는 학습/추론 작업일수록 상한을 넉넉히 두되, 호스트 전체 메모리보다는 작게 잡아 다른 컨테이너의 몫을 남겨 둡니다.

### Disk & Cleanup

이미지·컨테이너·볼륨·빌드 캐시가 쌓여 디스크를 먹으면 정리합니다.

```powershell
docker system df                      # show what's using disk (images, containers, volumes, cache).
docker system prune -a --volumes      # remove unused images/cache/volumes (deletes — careful).
```

> `prune -a --volumes` 는 **떠 있지 않은** 이미지·컨테이너와 **아무 데도 안 붙은** 볼륨·캐시를 지웁니다. 되살릴 수 없으니 지우기 전에 `docker system df` 로 무엇이 빠지는지 확인합니다.

## 5. Container Access

### Exec & One-off

```powershell
docker compose exec <service> <command>            # run a command once inside a running container.
docker compose run --rm <service> <command>        # run a command in a throwaway container, then exit.
```

### Container Shell — Enter / Exit

떠 있는 컨테이너 안으로 **셸을 띄워 직접 들어가** 파일을 확인하거나 명령을 실행할 수 있습니다.

```powershell
# Enter — attach to a running container's interactive shell (-it = input-capable terminal).
docker compose exec -it <service> bash             # fall back to sh if bash is absent.
docker compose exec -it <service> sh               # alpine and other slim images (no bash)

# Attach directly by container name (outside compose — get the name from docker ps).
docker exec -it <container> bash
```

나오기는 컨테이너를 멈추지 않고 셸만 빠져나옵니다.

```text
exit            # leave the shell back to the host (or Ctrl-D). the container keeps running.
Ctrl-P, Ctrl-Q  # if attached via docker attach, detach without stopping the container.
```

떠 있는 컨테이너가 없을 때는, 이미지에서 바로 1회용 셸을 띄워 안을 들여다봅니다. 이미지에 entrypoint 가 걸려 있으면 `--entrypoint` 로 덮어 bash 를 띄웁니다.

```powershell
docker run --rm -it <image>:<tag> bash                    # run a throwaway container from the image and enter a shell (--rm = delete on exit).
docker run --rm -it --entrypoint /bin/bash <image>:<tag>  # override the entrypoint with bash (when an entrypoint blocks it).
```

> `exec` 로 들어간 셸을 `exit` 하면 그 셸 세션만 끝나고 **컨테이너는 계속 실행** 됩니다. 컨테이너 자체를 멈추려면 [Start & Stop](#start--stop) 의 `docker compose stop` / `down` 을 씁니다. 셸이 없는 컨테이너에는 1회용 셸 컨테이너로 같은 네트워크에 붙어 접근합니다 (`docker run -it --rm --network <network> <image> sh`).

## 6. Host

### Linux — docker without sudo

리눅스에서는 docker 데몬 소켓을 root 가 소유하므로 기본적으로 명령마다 `sudo` 가 필요합니다. 내 계정을 `docker` 그룹에 넣으면 `sudo` 없이 쓸 수 있습니다.

먼저 시스템에 어떤 그룹이 있는지, `docker` 그룹이 이미 있는지 확인합니다.

```bash
getent group                    # list all groups on the system.
getent group docker             # query only the docker group — one line means it exists (no output if not).
cut -d: -f1 /etc/group | sort   # show group names sorted (readability).
```

`docker` 그룹이 없을 때만 만들고, 내 계정을 그 그룹에 추가합니다.

```bash
sudo groupadd docker            # create the docker group (usually present after install — only if missing).
sudo usermod -aG docker $USER   # add the current user to the docker group.
```

그룹 변경은 **새 로그인 세션부터** 적용됩니다. 다음 중 하나로 반영합니다.

```bash
newgrp docker                   # apply immediately in the current shell (temporary, instead of re-login).
# or log out and back in (over SSH, disconnect and reconnect). the sure way.
```

적용됐는지 확인:

```bash
groups                          # applied if docker shows in the output.
docker ps                       # done if it works without sudo.
```

> **보안 주의** — `docker` 그룹은 사실상 root 권한과 같습니다 (컨테이너로 호스트 파일시스템을 마운트할 수 있음). 신뢰하는 1인 개발 머신에서만 쓰고, 공용 서버에서는 `sudo` 를 유지하는 편이 안전합니다.

## Appendix A. Terminology

- **build context** — `docker build` 가 이미지를 구울 때 도커 데몬에 통째로 보내는 파일 묶음. 보통 `Dockerfile` 이 있는 폴더가 기준이며, `COPY`·`ADD` 는 이 안의 파일만 집어올 수 있습니다. `.dockerignore` 로 보낼 파일을 추려 묶음을 가볍게 합니다.

## Appendix B. Build & Run

도커는 **이미지를 굽는 단계**와 **컨테이너를 띄우는 단계**로 나뉩니다. 두 단계는 각각 다른 파일이 맡습니다.

$$\text{Dockerfile} \longrightarrow \text{Build (이미지 생성)}$$

$$\text{docker-compose.yml} \longrightarrow \text{Run (컨테이너 가동)}$$
