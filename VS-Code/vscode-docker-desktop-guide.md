> ⚠️ **This is an auto-synced copy. Do not edit here.**

# VS Code Development with Docker Desktop and a Prebuilt Image

Rev. 36 | Created: 2026-07-14 | Updated: 2026-08-14 21:32 CDT

Docker Desktop에서 `yrocket/pipeline-flow:latest` 이미지로 컨테이너를 실행하고, VS Code를 컨테이너 내부에 연결하여 개발 환경으로 사용한다.

이 문서는 Docker Desktop을 사용하는 **Windows 10/11**을 기준으로 기술한다. **Ubuntu(리눅스)** 에서도 이미지·컨테이너·`devcontainer.json`·VS Code 연결 방식은 동일하며, 다만 Docker Desktop 대신 **Docker Engine을 네이티브로 사용**한다는 점만 다르다. 이 차이에서 비롯되는 WSL·`vmmem` 관련 내용(Appendix B, C)은 Windows에만 해당한다.

---

## 1. Work Flow

```
┌── Docker Desktop (host runtime) ───────────────────────────────┐
│                                                                │
│  ┌────────────────────────┐           ┌────────────────────┐   │
│  │ Prebuilt Image         │           │ Container          │   │
│  │ yrocket/pipeline-flow  │───run────▶│ (ephemeral)        │   │
│  │ (docker pull / build)  │           │ /workspace         │   │
│  └────────────────────────┘           └────────────────────┘   │
│                                           ▲     ▲              │
└───────────────────────────────────────────│─────│──────────────┘
                    bind mount (-v)         │     │ connect:
                ┌───────────────────────────┘     │ Reopen / Attach
                ▼                                 │
   ┌────────────────────────┐           ┌────────────────────┐
   │ Host source folder     │           │ VS Code            │
   │ (your project on host) │           │ (Dev Containers)   │
   └────────────────────────┘           └────────────────────┘
```

- Docker Desktop: 호스트에서 이미지·컨테이너를 실행하는 엔진 (daemon). 아래 모든 동작이 그 위에서 일어난다.
- Prebuilt Image: `docker pull`로 받아 로컬 캐시되는 컨테이너의 원본 템플릿.
- Container: 이미지로부터 생성되는 일회용 실행 인스턴스. VS Code가 여기에 연결된다.
- VS Code: `Reopen in Container` 또는 `Attach`로 컨테이너 내부에 붙어 개발.
- Workspace: 호스트 소스 폴더를 컨테이너 `/workspace`에 bind mount → 컨테이너 삭제와 무관하게 영속.

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

## 3. VS Code

VS Code를 컨테이너에 연결하는 방식은 두 가지다.

- Image 사용: `.devcontainer/devcontainer.json`에 이미지(또는 Dockerfile)를 지정하면 VS Code가 컨테이너를 자동 생성·관리. 환경 재현성이 높아 권장.
- Container 사용: 사용자가 `docker run`으로 컨테이너를 직접 실행하고 VS Code가 Attach. 일회용(`--rm`) 수명을 직접 제어.

### 3.1 Prerequisites

VS Code에 **Dev Containers extension**(`ms-vscode-remote.remote-containers`)을 설치해야 한다. 아래 두 방식 모두 이 extension이 있어야 동작한다. (extension 탭 `Ctrl/Cmd + Shift + X`에서 "Dev Containers" 검색 → 설치)

### 3.2 Using an Image (devcontainer.json)

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

1. VS Code로 open folder 를 한다. `${localWorkspaceFolder}`는 "연 폴더로 자동 결정" 된다.
2. `F1`(= Open Command Palette = `Ctrl+Shift+P`) → `Dev Containers: Reopen in Container`.
3. VS Code가 컨테이너 생성·실행 → 창을 컨테이너 내부로 다시 연다. 이때 이미지가 로컬에 없으면 pull, `build`(Dockerfile)를 지정한 경우에만 build 한다. 이미 이미지를 받아뒀고 도구 추가(Dockerfile)가 없으면 pull/build는 건너뛰고 캐시된 이미지로 바로 컨테이너를 만든다.
4. 이후 터미널, 디버깅, extension이 모두 컨테이너 내부에서 동작.

참고: 컨테이너에 연결된 VS Code 창을 닫으면 컨테이너는 stopped 상태가 되고(실행 종료), 삭제되지 않아 다음에 재사용된다. 초기화하려면 `F1` → `Dev Containers: Rebuild Container`. 소스는 호스트에 있으므로 rebuild 해도 보존된다.

### 3.3 Using a Container (docker run + Attach)

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
  -v flow-cache:/root/.cache \   # cache kept in a named volume (image user = root)
  my-flow:dev bash
```

### 3.4 Verification

컨테이너에 제대로 연결됐는지 VS Code 통합 터미널(`` Ctrl+` ``)에서 확인한다.

```bash
whoami              # container user (e.g. root or vscode)
hostname            # random container ID = you are inside the container
pwd                 # expected: /workspace
python --version    # the image's runtime is available
ls -la /workspace   # your opened folder's files are listed (bind mount works)
```

- 프롬프트가 리눅스이고 `hostname`이 랜덤 문자열이면 컨테이너 내부에 붙은 것이다.
- `pwd`가 `/workspace`이고 `ls /workspace`에 연 폴더의 파일이 보이면 bind mount가 정상이다.
- VS Code 좌측 하단 초록 배지에 `Dev Container: pipeline-flow` 표시도 함께 확인한다.

---

## 4. References

- Dev Containers: https://code.visualstudio.com/docs/devcontainers/containers
- devcontainer.json 레퍼런스: https://containers.dev/implementors/json_reference/
- Docker Desktop: https://docs.docker.com/desktop/
- Docker volumes: https://docs.docker.com/storage/volumes/

---

## Appendix A. Terminology

- **Bind mount**: 호스트의 특정 폴더를 컨테이너 경로에 직접 연결하는 방식. `-v host:container`. 소스코드 영속화에 사용.
- **Container**: 이미지로부터 생성된 실행 인스턴스. `docker run` 시마다 새로 만들어진다.
- **Digest**: 이미지 내용을 식별하는 SHA-256 해시값으로 `@sha256:<hash>` 형식으로 표기한다. 이동 가능한 태그(`:latest`)와 달리 내용이 바뀌면 값도 바뀌므로, 특정 이미지 버전을 불변으로 고정(pinning)할 때 사용한다. 예) `yrocket/pipeline-flow@sha256:abc123...`
- **Ephemeral**: 종료와 함께 삭제되어 상태가 남지 않는 컨테이너. `docker run --rm`으로 실현한다.
- **Image**: 컨테이너 실행에 필요한 파일시스템과 설정을 담은 읽기 전용 템플릿. `docker pull`로 취득해 로컬에 캐시된다.
- **Named volume**: Docker가 관리하는 영속 저장소. 컨테이너 삭제와 무관하게 데이터가 유지되어 캐시·DB 등에 사용.
- **WSL (Windows Subsystem for Linux)**: Windows에서 리눅스를 실행하는 기능. WSL2는 경량 가상머신(VM)으로 리눅스 커널을 돌리며, Windows용 Docker Desktop의 리눅스 엔진이 이 위에서 동작한다. 이 VM의 메모리가 작업관리자에 `vmmem`으로 표시된다(Appendix C 참조).

---

## Appendix B. WSL CLI

Windows에서 Docker Desktop은 WSL2 위에서 동작하므로, 엔진 상태 확인·재기동·메모리 관리는 대부분 `wsl` 명령으로 한다. `wsl` 명령은 Windows 셸(cmd/PowerShell)에서 실행한다. 이 문서에서 사용한 명령을 정리한다.

- `wsl -- <command>` — 기본 배포판 안에서 명령 실행.
  - `wsl -- free -h` — WSL2 VM의 실제 메모리 사용량
  - `wsl -- cat /proc/meminfo` — 상세
- `wsl --shutdown` — 모든 WSL 배포판과 VM을 즉시 종료. 멈춘(hang) 엔진 복구, `vmmem` 메모리 즉시 해제에 사용. 이후 Docker Desktop을 다시 실행한다.
- `wsl --update` — WSL 커널·구성 요소를 최신화. WSLg·`autoMemoryReclaim` 등 최신 기능 확보.
- `wsl -d <distro>` — 특정 배포판을 실행. 예) `wsl -d Ubuntu`.
- `wsl -l -v` — 설치된 배포판 목록과 상태(`Running`/`Stopped`)·WSL 버전 표시. `docker-desktop`이 `Running`이어야 엔진이 살아 있다.

---

## Appendix C. Virtual Memory

Docker Desktop(Windows)은 WSL2 경량 VM 위에서 리눅스 엔진을 실행한다. 이 VM이 쓰는 메모리가 작업관리자에 **`vmmem`**(최신 Windows 11에서는 **`vmmemWSL`**)로 표시된다. 유휴 상태에서도 메모리를 잘 반환하지 않아 크게 잡혀 보일 수 있다.

**OS 비교**

| OS | Docker 실행 방식 | `vmmem` 프로세스 | 유휴 메모리 |
|----|------------------|------------------|-------------|
| Windows 10 | WSL2 VM 위 리눅스 엔진 | 있음 (`vmmem`) | 잘 안 반환 → 절약 설정 필요 |
| Windows 11 | 동일 (WSL2) | 있음 (`vmmem` 또는 `vmmemWSL`) | 동일 → 절약 설정 필요 |
| Ubuntu (리눅스) | Docker Engine 네이티브(호스트 커널) | 없음 | 커널이 자동 회수 → 문제 없음 |

- vmmem 이슈는 Windows 버전이 아니라 **WSL2(VM) 방식** 때문이며 Win10·Win11 공통이다. Windows 11이라고 자동 면제되지 않으며, 관건은 WSL 버전이다.
- Ubuntu는 VM이 없어 `vmmem` 자체가 없고 별도 조치가 불필요하다.

**메모리 사용량 확인**

`wsl --` 뒤의 명령은 Windows 셸(cmd/PowerShell)에서 실행하며, WSL2 리눅스가 보고하는 메모리 사용량을 보여준다.

```powershell
wsl -- free -h            # memory the WSL2 VM actually uses (used/free/buff-cache)
wsl -- cat /proc/meminfo  # more detail
```

- 작업관리자에 보이는 `vmmem` 크기는 PowerShell `Get-Process vmmem, vmmemWSL`로 확인한다.

**메모리 절약 (Windows 10 / 11 공통)**

1. 사용자 홈(`C:\Users\<user>\.wslconfig`)에 설정 파일 생성:

```ini
[wsl2]
memory=4GB          # max RAM the WSL2 VM may use (tune to your PC)
processors=4        # optional CPU limit
swap=2GB

[experimental]
autoMemoryReclaim=gradual   # return idle memory back to Windows
```

2. 적용:

```powershell
wsl --update      # ensure a recent WSL (autoMemoryReclaim support)
wsl --shutdown    # then restart Docker Desktop
```

3. 개발하지 않을 때는 `wsl --shutdown` 또는 Docker Desktop을 **Quit** → `vmmem` 메모리가 즉시 해제된다.

- WSL2 백엔드에서는 Docker Desktop `Settings`에 메모리 슬라이더가 없고 위 `.wslconfig`가 그 역할을 한다.
