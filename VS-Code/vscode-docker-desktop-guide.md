# VS Code Development with Docker Desktop and a Prebuilt Image

rev. 3
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

## 3. Image and Container Strategy

### 3.1 Pull the Image

```bash
docker pull yrocket/pipeline-flow:latest
docker images | grep pipeline-flow
```

- `:latest`는 원격 변경 가능성이 있어 재현성이 낮음. 장기 프로젝트는 다이제스트 고정 권장: `docker pull yrocket/pipeline-flow@sha256:<digest>`

### 3.2 Whether to Use a Dockerfile

- 길 A — 이미지 직접 사용(Dockerfile 불필요): 베이스 이미지가 필요한 구성을 모두 포함한 경우. 최소 구성.
- 길 B — Dockerfile로 `FROM` 후 도구 추가: 베이스 이미지에 추가 CLI, 설정 등을 얹는 경우.

```dockerfile
# Dockerfile (길 B)
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

### 3.3 Run the Container as Ephemeral

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

### 3.4 Ephemeral vs Persistent

| 상황 | 권장 | 이유 |
|------|------|------|
| 일반 개발 | ephemeral (`--rm`) | 매 실행 초기 상태, 재현성 확보 |
| 무거운 캐시(pip/npm/데이터) 유지 | named volume 추가 | `--rm`이어도 캐시는 볼륨에 유지 |
| DB 등 상태 보존 서비스 | persistent (named volume) | 데이터 유실 방지 |

```bash
# 캐시는 유지하되 컨테이너는 일회용
docker run --rm -it \
  -v "$(pwd)":/workspace \
  -v flow-cache:/home/vscode/.cache \
  my-flow:dev bash
```

---

## 4. VS Code Environment Setup

- 방식 A(Attach): 설정 파일 불필요, 1회성. 재현성 없음.
- 방식 B(devcontainer.json): 환경 재현 가능. 권장.

### 4.1 Method A — Attach to a Running Container

1. 3.3의 `docker run`으로 컨테이너 실행.
2. `F1` → `Dev Containers: Attach to Running Container...`
3. `flow-dev` 선택 → 새 VS Code 창이 컨테이너 내부를 염.
4. `File → Open Folder → /workspace`.

### 4.2 Method B — `.devcontainer/devcontainer.json`

프로젝트 루트에 `.devcontainer/devcontainer.json`을 두면 VS Code가 해당 정의대로 컨테이너를 자동 실행 및 연결함.

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

B-2. Dockerfile 빌드 사용(3.2 길 B와 연결):

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

1. VS Code로 프로젝트 폴더를 염.
2. `F1` → `Dev Containers: Reopen in Container` (또는 우측 하단 `Reopen in Container` 알림).
3. VS Code가 이미지 pull/빌드 → 컨테이너 실행 → 창을 컨테이너 내부로 다시 염.
4. 이후 터미널, 디버깅, 확장이 모두 컨테이너 내부에서 동작.

### 4.3 Ephemeral Limitations

- devcontainer.json 방식의 컨테이너는 창을 닫아도 자동 삭제되지 않고 재사용됨.
- 초기 상태로 리셋: `F1` → `Dev Containers: Rebuild Container` (또는 `Rebuild Without Cache`).
- 종료 시 자동 삭제되는 완전한 ephemeral이 필요하면 `docker run --rm` + 방식 A(Attach)를 사용.
- 소스는 호스트에 유지되므로 rebuild 시에도 코드는 보존됨.

---

## 5. Workflow Summary

```bash
# 1) 이미지 준비 (최초 1회)
docker pull yrocket/pipeline-flow:latest

# 2) (선택) 도구 추가 빌드
docker build -t my-flow:dev .

# 3-A) CLI 일회용 컨테이너 + Attach
docker run --rm -it -v "$(pwd)":/workspace -w /workspace my-flow:dev bash
#   → VS Code: F1 → Attach to Running Container

# 3-B) devcontainer.json 방식
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
| pull 지연/재현 불가 | `:latest` 변동 | 다이제스트 고정 (`@sha256:...`) |
| 디스크 부족 | 이미지/컨테이너 누적 | `docker system prune` (삭제 주의) |

---

## 7. References

- Dev Containers: https://code.visualstudio.com/docs/devcontainers/containers
- devcontainer.json 레퍼런스: https://containers.dev/implementors/json_reference/
- Docker Desktop: https://docs.docker.com/desktop/
- Docker volumes: https://docs.docker.com/storage/volumes/
