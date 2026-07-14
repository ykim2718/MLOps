# VS Code Development with Docker Desktop and a Prebuilt Image

rev. 10
<!-- 규칙: 이 파일을 수정할 때마다 위 rev 번호를 1씩 올릴 것 (git commit 여부와 무관). -->

- 목적: Docker Desktop에서 `yrocket/pipeline-flow:latest` 이미지로 컨테이너를 실행하고, VS Code를 컨테이너 내부에 연결하여 개발 환경으로 사용.
- 원칙: 이미지는 재사용, 컨테이너는 일회용(ephemeral), 소스코드는 볼륨으로 영속화.

---

## 1. Work Flow

```
┌─────────────────────────────────────────────────────────────┐
│  IMAGE  (read-only template, cached locally · reusable)     │
│  1. $ docker pull yrocket/pipeline-flow:latest              │
│  2. (optional) $ docker build -t my-flow:dev .   # add tools│
└───────────────┬─────────────────────────────────────────────┘
                │  create a container from the image
                ▼
┌─────────────────────────────────────────────────────────────┐
│  CONTAINER  (running instance · ephemeral)                  │
│  3.1 .devcontainer/devcontainer.json                        │
│      → VS Code: open folder → F1 → Reopen in Container      │
│  3.2 $ docker run --rm -it -v "$(pwd)":/workspace \         │
│          -w /workspace my-flow:dev bash                     │
│      → VS Code: F1 → Attach to Running Container            │
│      (3.1 and 3.2 are alternatives — choose one)            │
└───────────────┬─────────────────────────────────────────────┘
                │  bind mount / volume (-v)
                ▼
┌─────────────────────────────────────────────────────────────┐
│  WORKSPACE  (host disk · persistent)                        │
│  source code lives here → survives container removal        │
└─────────────────────────────────────────────────────────────┘
```

- 이미지: 삭제하지 않고 재사용. `pull` 1회로 로컬 캐시됨.
- 컨테이너: `--rm` 기반 일회용 사용 권장. 매 실행마다 초기 상태 → 환경 오염 및 재현성 문제 방지.
- 소스코드: 컨테이너 내부에 두지 않고 호스트 폴더를 볼륨 마운트하여 영속화.

---

## 2. Docker Image

### 2.1 Pull the Image

```bash
docker pull yrocket/pipeline-flow:latest
docker images | grep pipeline-flow
```

- `:latest`는 원격 변경 가능성이 있어 재현성이 낮음. 장기 프로젝트는 digest 고정 권장: `docker pull yrocket/pipeline-flow@sha256:<digest>` (digest 정의는 [Appendix A](#appendix-a-terminology) 참조).

### 2.2 Wrap with a Dockerfile

베이스 이미지에 추가 CLI·설정 등 도구를 얹을 때 Dockerfile로 `FROM` 하여 새 이미지를 만든다.

```dockerfile
# Dockerfile
FROM yrocket/pipeline-flow:latest

# Example: add tools (when the base is apt-based; adjust the package manager to the image)
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     git curl vim ca-certificates \
#  && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
# USER vscode
```

```bash
docker build -t my-flow:dev .
```

---

## 3. VS Code Environment Setup

VS Code를 컨테이너에 연결하는 방식은 두 가지다.

- Image 사용: `.devcontainer/devcontainer.json`에 이미지(또는 Dockerfile)를 지정하면 VS Code가 컨테이너를 자동 생성·관리. 환경 재현성이 높아 권장.
- Container 사용: 사용자가 `docker run`으로 컨테이너를 직접 실행하고 VS Code가 Attach. 일회용(`--rm`) 수명을 직접 제어.

### 3.1 Using an Image (devcontainer.json)

프로젝트 루트에 `.devcontainer/devcontainer.json`을 두면 VS Code가 해당 정의대로 컨테이너를 자동 실행 및 연결한다.

이미지 직접 사용(최소 구성):

```jsonc
// .devcontainer/devcontainer.json
{
  "name": "pipeline-flow",
  "image": "yrocket/pipeline-flow:latest",
  "workspaceFolder": "/workspace",
  "workspaceMount": "source=${localWorkspaceFolder},target=/workspace,type=bind",
  "customizations": {
    "vscode": {
      "extensions": ["ms-python.python", "ms-azuretools.vscode-docker"],
      "settings": { "terminal.integrated.defaultProfile.linux": "bash" }
    }
  },
  "forwardPorts": [8080],
  "postCreateCommand": "echo 'container ready'"
}
```

실행 절차:

1. VS Code로 프로젝트 폴더를 연다.
2. `F1` → `Dev Containers: Reopen in Container` (또는 우측 하단 `Reopen in Container` 알림).
3. VS Code가 이미지 pull/빌드 → 컨테이너 실행 → 창을 컨테이너 내부로 다시 연다.
4. 이후 터미널, 디버깅, 확장이 모두 컨테이너 내부에서 동작.

참고: 컨테이너에 연결된 VS Code 창을 닫으면 컨테이너는 stopped 상태가 되고(실행 종료), 삭제되지 않아 다음에 재사용된다. 초기화하려면 `F1` → `Dev Containers: Rebuild Container`. 소스는 호스트에 있으므로 rebuild 해도 보존된다.

### 3.2 Using a Container (docker run + Attach)

컨테이너를 직접 일회용으로 띄운 뒤 VS Code로 Attach 한다.

```bash
docker run --rm -it \
  --name flow-dev \
  -v "$(pwd)":/workspace \
  -w /workspace \
  -p 8080:8080 \
  my-flow:dev \
  bash
```

플래그:

- `--rm` — 종료 시 컨테이너 자동 삭제 (ephemeral의 핵심)
- `-it` — 인터랙티브 터미널
- `-v host:container` — 바인드 마운트. 코드가 호스트에 유지됨
- `-w` — 시작 작업 디렉터리
- `-p` — 포트 매핑
- `--name` — 컨테이너 이름 (재실행 시 이름 충돌 주의)
- Windows PowerShell은 `$(pwd)` 대신 `${PWD}` 사용.

Attach 절차:

1. 위 `docker run`으로 컨테이너 실행.
2. `F1` → `Dev Containers: Attach to Running Container...`
3. `flow-dev` 선택 → 새 VS Code 창이 컨테이너 내부를 연다.
4. `File → Open Folder → /workspace`.

참고: `--rm` 컨테이너는 종료 시 사라지므로 컨테이너 안에서 `pip install` 한 것도 함께 없어진다. pip/npm 캐시처럼 재다운로드가 아까운 경로만 named volume(`-v <이름>:<컨테이너경로>`)으로 빼두면 컨테이너와 별개로 유지된다.

```bash
docker run --rm -it \
  -v "$(pwd)":/workspace \
  -v flow-cache:/home/vscode/.cache \   # cache kept in a named volume
  my-flow:dev bash
```

---

## 4. References

- Dev Containers: https://code.visualstudio.com/docs/devcontainers/containers
- devcontainer.json 레퍼런스: https://containers.dev/implementors/json_reference/
- Docker Desktop: https://docs.docker.com/desktop/
- Docker volumes: https://docs.docker.com/storage/volumes/

---

## Appendix A. Terminology

- **Image (이미지)**: 컨테이너 실행에 필요한 파일시스템과 설정을 담은 읽기 전용 템플릿. `docker pull`로 취득해 로컬에 캐시된다.
- **Container (컨테이너)**: 이미지로부터 생성된 실행 인스턴스. `docker run` 시마다 새로 만들어진다.
- **Ephemeral (일회용)**: 종료와 함께 삭제되어 상태가 남지 않는 컨테이너. `docker run --rm`으로 실현한다.
- **Digest (다이제스트)**: 이미지 내용을 식별하는 SHA-256 해시값으로 `@sha256:<hash>` 형식으로 표기한다. 이동 가능한 태그(`:latest`)와 달리 내용이 바뀌면 값도 바뀌므로, 특정 이미지 버전을 불변으로 고정(pinning)할 때 사용한다. 예) `yrocket/pipeline-flow@sha256:abc123...`
- **Bind mount (바인드 마운트)**: 호스트의 특정 폴더를 컨테이너 경로에 직접 연결하는 방식. `-v host:container`. 소스코드 영속화에 사용.
- **Named volume (네임드 볼륨)**: Docker가 관리하는 영속 저장소. 컨테이너 삭제와 무관하게 데이터가 유지되어 캐시·DB 등에 사용.
