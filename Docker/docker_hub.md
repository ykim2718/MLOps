# Docker Hub (Image Registry)

<sub>rev. 1</sub>

이미지를 Docker Hub 에 올리고 받는 명령을 모았습니다. `<user>` 는 Docker Hub 계정, `<repo>` 는 저장소 이름, `<tag>` 는 버전표 (예: `1.0`, `latest`) 입니다.

## 1. Auth

### Login

```powershell
docker login                       # Docker Hub 에 로그인한다 (사용자명·비밀번호 또는 토큰 입력).
docker login -u <user>             # 사용자명을 미리 넣고 비밀번호만 입력한다.
docker logout                      # 저장된 로그인 정보를 지운다.
```

> 비밀번호 대신 **Access Token** 을 권장합니다 (Docker Hub → Account Settings → Security 에서 발급). CI 나 공용 머신에서는 특히 토큰을 씁니다. 토큰을 stdin 으로 넘기려면 `echo <token> | docker login -u <user> --password-stdin` 을 씁니다.

## 2. Upload — tag · push

올리려면 먼저 로컬 이미지에 `<user>/<repo>:<tag>` 형식의 **이름표 (tag)** 를 붙이고 push 합니다.

### Tag

```powershell
docker tag <image>:<tag> <user>/<repo>:<tag>   # 로컬 이미지에 Docker Hub 용 이름을 붙인다.
docker images                                  # 붙은 이름과 태그를 확인한다.
```

### Push

```powershell
docker push <user>/<repo>:<tag>       # 지정 태그를 Docker Hub 에 올린다.
docker push --all-tags <user>/<repo>  # 그 저장소의 모든 태그를 한 번에 올린다.
```

> push 전에 `docker login` 이 되어 있어야 하고, `<user>` 가 로그인 계정과 같아야 합니다. 처음 push 하면 저장소가 자동으로 만들어집니다 (기본 public — 비공개로 두려면 Docker Hub 에서 먼저 private 저장소를 만듭니다).

## 3. Download — pull

### Pull

```powershell
docker pull <user>/<repo>:<tag>    # Docker Hub 에서 이미지를 받는다.
docker pull <image>:<tag>          # 공식 이미지 (library) 를 받는다 (예: python:3.10-slim).
docker pull <user>/<repo>          # 태그를 생략하면 latest 를 받는다.
```

> 태그를 생략하면 `latest` 로 받습니다. 재현성이 중요하면 항상 태그를 명시하거나, 내용에 고정되는 digest (`<user>/<repo>@sha256:...`) 로 받습니다.

## 4. Search & Inspect

```powershell
docker search <keyword>                        # Docker Hub 에서 이미지를 검색한다.
docker manifest inspect <user>/<repo>:<tag>    # 원격 이미지의 플랫폼·레이어 정보를 받지 않고 본다.
docker image inspect <image>:<tag>             # 이미 받은 로컬 이미지의 상세 정보를 본다.
```

> `docker search` 는 이름·설명만 훑습니다. 태그 목록은 Docker Hub 웹 (`hub.docker.com/r/<user>/<repo>/tags`) 에서 보거나 `manifest inspect` 로 확인합니다.

## Appendix A. Terminology

- **image reference** — 이미지를 가리키는 전체 이름 `[<registry>/]<user>/<repo>:<tag>`. registry 를 생략하면 Docker Hub (`docker.io`), tag 를 생략하면 `latest` 로 봅니다.
- **tag** — 한 저장소 안의 버전표 (`1.0`·`latest` 등). 같은 저장소에 여러 태그가 붙고, 옮겨 달 수 있습니다.
- **digest** — 이미지 내용을 가리키는 불변 해시 (`@sha256:...`). 태그는 옮겨질 수 있어도 digest 는 그 내용에 고정됩니다.
- **Access Token** — 비밀번호 대신 쓰는 인증 토큰. Docker Hub 계정 설정에서 발급·폐기하며 권한 범위를 정할 수 있습니다.

## Appendix B. Push & Pull

이미지는 로컬에서 이름표를 달아 Docker Hub 에 올리고, 다른 호스트가 그 이름으로 받아 씁니다.

$$\text{Local Image} \xrightarrow{\ \text{tag · push}\ } \text{Docker Hub} \xrightarrow{\ \text{pull}\ } \text{Another Host}$$
