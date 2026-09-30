# Docker Hub (Image Registry)
Rev. 8 | Created: 2026-07-03 | Updated: 2026-09-30 07:59 CDT

- [1. Auth](#1-auth)
- [2. Upload — commit · tag · push](#2-upload--commit--tag--push)
- [3. Download — pull](#3-download--pull)
- [4. Search & Inspect](#4-search--inspect)
- [5. Private Registry](#5-private-registry)
- [Appendix A. Terminology](#appendix-a-terminology)
- [Appendix B. Push & Pull](#appendix-b-push--pull)

이미지를 Docker Hub 와 사설 registry 에 올리고 받는 명령을 모았습니다. `<user>` 는 Docker Hub 계정, `<image>` 는 이미지 이름, `<tag>` 는 `0.0`·`latest` 같은 버전명, `<host>` 는 사설 registry 를 띄운 machine 의 LAN IP 입니다.

## 1. Auth

### Login

```powershell
docker login                       # Docker Hub 에 로그인한다 (사용자명·비밀번호 또는 토큰 입력).
docker login -u <user>             # 사용자명을 미리 넣고 비밀번호만 입력한다.
docker logout                      # 저장된 로그인 정보를 지운다.
```

> 비밀번호 대신 **Access Token** 을 권장합니다 (Docker Hub → Account Settings → Security 에서 발급). CI 나 공용 머신에서는 특히 토큰을 씁니다. 토큰을 stdin 으로 넘기려면 `echo <token> | docker login -u <user> --password-stdin` 을 씁니다.

## 2. Upload — commit · tag · push

올릴 이미지를 만들고 (`commit` 하거나 Dockerfile 로 빌드), `<user>/<image>:<tag>` 형식의 **이름표 (tag)** 를 붙여 push 합니다.

### Commit — container to image

떠 있거나 멈춘 컨테이너의 현재 상태를 그대로 이미지로 굳힙니다. 컨테이너 안에서 손본 내용을 이미지로 남길 때 씁니다.

```powershell
docker ps -a                                    # commit 할 컨테이너의 이름/ID 를 확인한다.
docker commit <container> <user>/<image>:<tag>   # 컨테이너의 현재 상태를 이미지로 만든다.
docker commit -m "<message>" -a "<author>" <container> <user>/<image>:<tag>  # 커밋 메시지·작성자를 남긴다.
docker push <user>/<image>:<tag>                 # 만든 이미지를 Docker Hub 로 올린다 (로그인 필요).
```

> `commit` 은 컨테이너의 파일시스템 변경을 통째로 이미지로 굳힙니다 (이력이 남는 Dockerfile 빌드와 달리 재현은 안 됨). 급히 스냅샷을 남길 땐 편하지만, 계속 관리할 이미지는 Dockerfile 로 빌드하는 편이 낫습니다. commit 때 `<user>/<image>` 로 이름 지었으니 바로 push 되고, 다른 이름으로 바꿔 올리려면 아래 Tag 를 씁니다.

### Tag

```powershell
docker tag <image>:<tag> <user>/<image>:<tag>   # 로컬 이미지에 Docker Hub 용 이름을 붙인다.
docker images                                  # 붙은 이름과 태그를 확인한다.
```

### Push

```powershell
docker push <user>/<image>:<tag>       # 지정 태그를 Docker Hub 에 올린다.
docker push --all-tags <user>/<image>  # 그 저장소의 모든 태그를 한 번에 올린다.
```

> push 전에 `docker login` 이 되어 있어야 하고, `<user>` 가 로그인 계정과 같아야 합니다. 처음 push 하면 저장소가 자동으로 만들어집니다 (기본 public — 비공개로 두려면 Docker Hub 에서 먼저 private 저장소를 만듭니다).

## 3. Download — pull

### Pull

```powershell
docker pull <user>/<image>:<tag>    # Docker Hub 에서 이미지를 받는다.
docker pull <image>:<tag>          # 공식 이미지 (library) 를 받는다 (예: python:3.10-slim).
docker pull <user>/<image>          # 태그를 생략하면 latest 를 받는다.
```

> 태그를 생략하면 `latest` 로 받습니다. 재현성이 중요하면 항상 태그를 명시하거나, 내용에 고정되는 digest (`<user>/<image>@sha256:...`) 로 받습니다.

## 4. Search & Inspect

```powershell
docker search <keyword>                        # Docker Hub 에서 이미지를 검색한다.
docker manifest inspect <user>/<image>:<tag>    # 원격 이미지의 플랫폼·레이어 정보를 받지 않고 본다.
docker image inspect <image>:<tag>             # 이미 받은 로컬 이미지의 상세 정보를 본다.
```

> `docker search` 는 이름·설명만 훑습니다. 태그 목록은 Docker Hub 웹 (`hub.docker.com/r/<user>/<image>/tags`) 에서 보거나 `manifest inspect` 로 확인합니다.

## 5. Private Registry

사설 registry 는 `registry:2` image 로 LAN 안에 띄우는 image 저장 server 입니다. Docker Hub 와 같은 push·pull 명령을 쓰며, 상대 쪽에 없는 layer 만 주고받으므로 code 만 바뀐 image 는 바뀐 layer 만 전송됩니다.

### Server

```yaml
# docker-compose.yml
# __version__ = "0.1.1.2026.9.30"  # Semantic Versioning: Major.Minor.Patch.Date(YYYY.M.D)
# 0.1.0: kick-off; private image registry on port 5000, images kept in the registry-data volume
# 0.1.1: host port 12357 (5000 is taken by MLflow); the registry itself still listens on 5000 inside

name: registry                      # Fix the project name (prefix of container and volume names).

services:
  registry:
    image: registry:2
    container_name: registry
    ports:
      - "12357:5000"  # push as localhost:12357/<image> on this machine, pull as <this machine's LAN IP>:12357/<image>
    volumes:
      - registry-data:/var/lib/registry
    healthcheck:
      # the v2 API root answers 200 while the registry serves
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:5000/v2/"]
      interval: 30s
      timeout: 5s
      retries: 3
    restart: unless-stopped

volumes:
  registry-data:
```

```bash
# Bash, in Docker/Registry
docker compose up -d                       # start the registry in the background
curl http://localhost:12357/v2/_catalog     # list the repositories the registry holds
```

> 다른 machine 이 pull 하려면 registry 를 띄운 machine 의 방화벽에서 TCP 12357 inbound 를 엽니다.

### Push

```bash
# Bash, on the registry machine
docker tag <image>:<tag> localhost:12357/<image>:<tag>   # name the image for the registry
docker push localhost:12357/<image>:<tag>                # upload only the layers the registry lacks
```

> registry 를 띄운 machine 에서는 `localhost:12357` 로 push 합니다. docker 는 localhost 의 registry 에 한해 TLS 없는 HTTP 접속을 허용하므로 daemon 설정을 고치지 않습니다.

### Pull

TLS 없는 registry 에서 받으려면 받는 machine 의 docker daemon 에 그 주소를 insecure registry 로 등록합니다.

```json
// /etc/docker/daemon.json
{
  "insecure-registries": ["<host>:12357"]
}
```

```bash
# Bash, on the pulling machine
sudo systemctl restart docker            # reload daemon.json
docker pull <host>:12357/<image>:<tag>    # download only the layers this machine lacks
```

> `daemon.json` 에 다른 key 가 이미 있으면 파일을 덮어쓰지 않고 `insecure-registries` 만 더합니다. Docker Desktop 은 Settings → Docker Engine 의 JSON 에 같은 key 를 넣습니다.

---

## Appendix A. Terminology

- **image reference** — 이미지를 가리키는 전체 이름 `[<registry>/]<user>/<image>:<tag>`. registry 를 생략하면 Docker Hub (`docker.io`), tag 를 생략하면 `latest` 로 봅니다.
- **tag** — 한 저장소 안의 버전표 (`1.0`·`latest` 등). 같은 저장소에 여러 태그가 붙고, 옮겨 달 수 있습니다.
- **digest** — 이미지 내용을 가리키는 불변 해시 (`@sha256:...`). 태그는 옮겨질 수 있어도 digest 는 그 내용에 고정됩니다.
- **Access Token** — 비밀번호 대신 쓰는 인증 토큰. Docker Hub 계정 설정에서 발급·폐기하며 권한 범위를 정할 수 있습니다.
- **registry** — image 를 저장하고 push·pull 로 주고받는 server. Docker Hub 는 공개 registry 이고, `registry:2` image 로 사설 registry 를 띄웁니다.
- **layer** — image 를 이루는 파일시스템 변경 단위. push·pull 은 상대 쪽에 없는 layer 만 전송합니다.
- **insecure registry** — TLS 없이 HTTP 로 접속하는 registry. docker 는 localhost 를 빼면 daemon 설정에 등록한 주소만 허용합니다.
- **TLS** — 접속을 암호화하고 server 의 인증서를 확인하는 protocol. HTTPS 가 HTTP 에 TLS 를 얹은 것입니다.

## Appendix B. Push & Pull

이미지는 로컬에서 이름표를 달아 Docker Hub 에 올리고, 다른 호스트가 그 이름으로 받아 씁니다.

$$\text{Local Image} \xrightarrow{\ \text{tag · push}\ } \text{Docker Hub} \xrightarrow{\ \text{pull}\ } \text{Another Host}$$
