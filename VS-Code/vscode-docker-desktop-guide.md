# VS Code Development with Docker Desktop and a Prebuilt Image

rev. 4
<!-- 규칙: 이 파일을 수정할 때마다 위 rev 번호를 1씩 올릴 것 (git commit 여부와 무관). -->

- 목적: Docker Desktop에서 `yrocket/pipeline-flow:latest` 이미지로 컨테이너를 실행하고, VS Code를 컨테이너 내부에 연결하여 개발 환경으로 사용.
- 원칙: 이미지는 재사용, 컨테이너는 일회용(ephemeral), 소스코드는 볼륨으로 영속화.

---

## 1. Concept Model

```
┌──────────────────────────────────────────────────────────────┐
│  IMAGE  (read-only template, cached locally · reusable)      │
│  yrocket/pipeline-flow:latest  ← pulled once via docker pull │
│  └─ (optional) FROM in a Dockerfile to add tools → my-flow:dev│
└───────────────┬──────────────────────────────────────────────┘
                │  new instance created on each 'docker run'
                ▼
┌──────────────────────────────────────────────────────────────┐
│  CONTAINER  (running instance · ephemeral)                   │
│  - auto-removed on exit when --rm is set                     │
│  - the container's internal filesystem is discarded          │
└───────────────┬──────────────────────────────────────────────┘
                │  connected via bind mount / volume
                ▼
┌──────────────────────────────────────────────────────────────┐
│  WORKSPACE  (host disk · persistent)                         │
│  where the source code lives → survives container removal    │
│  e.g. ~/projects/pipeline-flow  ⇄  /workspace in container   │
└──────────────────────────────────────────────────────────────┘
```

- 이미지: 삭제하지 않고 재사용. `pull` 1회로 로컬 캐시됨.
- 컨테이너: `--rm` 기반 일회용 사용 권장. 매 실행마다 초기 상태 → 환경 오염 및 재현성 문제 방지.
- 소스코드: 컨테이너 내부에 두지 않고 호스트 폴더를 볼륨 마운트하여 영속화.

---

## 2. Prerequisites

| 항목 | 설명 | 확인 |
|------|------|------|
| Docker Desktop | Windows/macOS용. 설치 후 실행 상태 유지 | `docker version` |
| VS Code | 최신 버전 | `code --version` |
| Dev Containers 확장 | `ms-vscode-remote.remote-containers` | 확장 탭에서 설치 |
| WSL2 (Windows) | Docker Desktop 백엔드. 설치 시 자동 안내 | `wsl -l -v` |

```bash
docker version          # Client / Server 모두 출력되면 정상
docker run hello-world  # 동작 확인
```

---

## 3. Docker Image

### 3.1 Pull the Image

```bash
docker pull yrocket/pipeline-flow:latest
docker images | grep pipeline-flow
```

- `:latest`는 원격 변경 가능성이 있어 재현성이 낮음. 장기 프로젝트는 digest 고정 권장: `docker pull yrocket/pipeline-flow@sha256:<digest>` (digest 정의는 Appendix A 참조).

### 3.2 Wrap with a Dockerfile

베이스 이미지에 추가 CLI·설정 등 도구를 얹을 때 Dockerfile로 `FROM` 하여 새 이미지를 만든다.

```dockerfile
# Dockerfile
FROM yrocket/pipeline-flow:latest

# 추가 도구 예시 (베이스가 apt 계열일 때. 패키지 매니저는 이미지에 맞게 조정)
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     git curl vim ca-certificates \
#  && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
# USER vscode
```

```bash
docker build -t my-flow:dev .
```

- Dockerfile은 이미지를 생성하며, 영속 컨테이너를 만드는 것이 아님. Dockerfile 사용 여부와 무관하게 컨테이너는 일회용 사용이 원칙.

---

## 4. VS Code Environment Setup

VS Code를 컨테이너에 연결하는 방식은 두 가지다.

- Image 사용: `.devcontainer/devcontainer.json`에 이미지(또는 Dockerfile)를 지정하면 VS Code가 컨테이너를 자동 생성·관리. 환경 재현성이 높아 권장.
- Container 사용: 사용자가 `docker run`으로 컨테이너를 직접 실행하고 VS Code가 Attach. 일회용(`--rm`) 수명을 직접 제어.

### 4.1 Using an Image (devcontainer.json)

프로젝트 루트에 `.devcontainer/devcontainer.json`을 두면 VS Code가 해당 정의대로 컨테이너를 자동 실행 및 연결한다.

B-1. 이미지 직접 사용(최소 구성):

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

B-2. Dockerfile 빌드 사용(3.2와 연결):

```jsonc
// .devcontainer/devcontainer.json
{
  "name": "pipeline-flow-dev",
  "build": { "dockerfile": "../Dockerfile", "context": ".." },
  "workspaceFolder": "/workspace",
  "customizations": {
    "vscode": { "extensions": ["ms-python.python"] }
  }
}
```

실행 절차:

1. VS Code로 프로젝트 폴더를 연다.
2. `F1` → `Dev Containers: Reopen in Container` (또는 우측 하단 `Reopen in Container` 알림).
3. VS Code가 이미지 pull/빌드 → 컨테이너 실행 → 창을 컨테이너 내부로 다시 연다.
4. 이후 터미널, 디버깅, 확장이 모두 컨테이너 내부에서 동작.

Ephemeral 관점(이 방식의 한계):

- devcontainer.json 방식의 컨테이너는 창을 닫아도 자동 삭제되지 않고 재사용됨.
- 초기 상태로 리셋: `F1` → `Dev Containers: Rebuild Container` (또는 `Rebuild Without Cache`).
- 종료 시 자동 삭제되는 완전한 ephemeral이 필요하면 4.2(Container 사용)를 쓴다.
- 소스는 호스트에 유지되므로 rebuild 시에도 코드는 보존됨.

### 4.2 Using a Container (docker run + Attach)

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

| 플래그 | 역할 |
|--------|------|
| `--rm` | 종료 시 컨테이너 자동 삭제 (ephemeral의 핵심) |
| `-it` | 인터랙티브 터미널 |
| `-v host:container` | 바인드 마운트. 코드가 호스트에 유지됨 |
| `-w` | 시작 작업 디렉터리 |
| `-p` | 포트 매핑 |
| `--name` | 컨테이너 이름 (재실행 시 이름 충돌 주의) |

- Windows PowerShell은 `$(pwd)` 대신 `${PWD}` 사용.

Attach 절차:

1. 위 `docker run`으로 컨테이너 실행.
2. `F1` → `Dev Containers: Attach to Running Container...`
3. `flow-dev` 선택 → 새 VS Code 창이 컨테이너 내부를 연다.
4. `File → Open Folder → /workspace`.

Ephemeral 관점(캐시 유지):

- `--rm`이면 종료 시 컨테이너가 자동 삭제되어 진정한 일회용이 된다.
- pip/npm 등 무거운 캐시는 named volume으로 분리하면 컨테이너를 삭제해도 캐시는 유지된다.

```bash
docker run --rm -it \
  -v "$(pwd)":/workspace \
  -v flow-cache:/home/vscode/.cache \   # named volume: 컨테이너 삭제와 무관하게 캐시 유지
  my-flow:dev bash
```

---

## 5. Workflow Summary

```bash
# 1) 이미지 준비 (최초 1회)
docker pull yrocket/pipeline-flow:latest

# 2) (선택) 도구 추가 빌드
docker build -t my-flow:dev .

# A) Container 방식: CLI 일회용 컨테이너 + Attach
docker run --rm -it -v "$(pwd)":/workspace -w /workspace my-flow:dev bash
#   → VS Code: F1 → Attach to Running Container

# B) Image 방식: devcontainer.json
#   → VS Code: 폴더 열기 → F1 → Reopen in Container
```

| 목적 | 명령/조작 |
|------|-----------|
| 초기 상태로 재시작 | `Dev Containers: Rebuild Container` |
| 컨테이너 내부 터미널 | VS Code 터미널(`` Ctrl+` ``) |
| 포트 노출 | `forwardPorts` 또는 `docker run -p` |
| 캐시 유지 | named volume (`-v flow-cache:/path`) |
| 이미지 버전 고정 | `@sha256:<digest>` |

---

## 6. Troubleshooting

| 증상 | 원인 | 해결 |
|------|------|------|
| `Cannot connect to the Docker daemon` | Docker Desktop 미실행 | 실행 상태 확인 후 재시도 |
| `docker: name is already in use` | 동일 `--name` 컨테이너 잔존 | `docker rm -f flow-dev` 후 재실행 |
| 코드 수정 소실 | 볼륨 마운트 누락 | `-v host:container` 또는 devcontainer mount 확인 |
| VS Code 확장 미표시 | 로컬에만 설치됨 | `customizations.vscode.extensions`에 추가 |
| Windows 경로 오류 | `$(pwd)` 미지원 | PowerShell은 `${PWD}` 사용 |
| pull 지연/재현 불가 | `:latest` 변동 | digest 고정 (`@sha256:...`) |
| 디스크 부족 | 이미지/컨테이너 누적 | `docker system prune` (삭제 주의) |

---

## 7. References

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
