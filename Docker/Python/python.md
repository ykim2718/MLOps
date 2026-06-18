# Python — Application Runtime Container

이 컨테이너는 이 스택에서 **파이썬 애플리케이션 실행 환경**으로 쓰입니다. 버전을 `3.11.15` 로 고정한 이미지를 빌드하여, 호스트에 파이썬이나 의존성을 따로 설치하지 않고도 동일한 환경에서 분석·학습 코드를 실행합니다. 데이터베이스 컨테이너 (예: MongoDB) 가 데이터를 저장하는 역할이라면, 이 컨테이너는 그 데이터를 읽어 **연산을 수행하고 결과를 만들어 내는 역할**을 맡습니다.

## 1. Introduction

파이썬 분석·학습 코드는 NumPy·TensorFlow·TA-Lib 처럼 버전과 네이티브 라이브러리에 민감한 패키지에 의존합니다. 이를 각 개발자의 호스트에 직접 설치하면 OS·파이썬 버전 차이로 "내 PC 에서는 되는데" 문제가 생깁니다. 이 컨테이너는 그 의존성 전체를 이미지 안에 고정해, **누가 어느 OS 에서 띄워도 같은 파이썬 3.11.15 환경**을 보장합니다.

- **버전 고정** — 베이스 이미지를 `python:3.11.15` 로 고정해 인터프리터 버전을 통일합니다.
- **의존성 고정** — `requirements.txt` 의 모든 패키지를 버전까지 핀 (pin) 하여 빌드 시 한 번만 설치하고 이미지 레이어에 남깁니다.
- **네이티브 빌드 포함** — TA-Lib·ucrdtw 처럼 C 라이브러리 컴파일이 필요한 패키지를 `Dockerfile` 안에서 빌드합니다.
- **공유 네트워크 합류** — 같은 호스트의 다른 서비스 (postgres·minio·mlflow·prefect·mongo) 가 `python` 이라는 서비스명으로 접근하도록 공유 네트워크 `mlops` 에 붙습니다.

이 컨테이너는 데이터베이스처럼 항상 떠 있는 상주 서비스가 아니라, **코드를 실행하고 끝나면 종료되는 단발성 (one-shot) 컨테이너**로 설계되었습니다 (`restart: "no"`). 따라서 "기동 → 실행 → 종료" 가 한 사이클이며, 종료 코드와 로그는 컨테이너가 사라지기 전까지 남아 확인할 수 있습니다.

## 2. Docker Setup

파이썬 환경은 도커 컨테이너로 실행됩니다. 데이터베이스 컨테이너가 공식 이미지 (`mongo:7` 등) 를 그대로 내려받는 것과 달리, 이 컨테이너는 의존성을 직접 설치해야 하므로 **`Dockerfile` 로 이미지를 직접 빌드**합니다. 설치는 빌드 시 1회만 수행되어 레이어 캐시에 남고, 이후 기동은 빠릅니다.

세 파일이 함께 동작합니다.

| File | Role |
|------|------|
| `requirements.txt` | 설치할 파이썬 패키지와 버전 목록. 빌드 중 `pip install -r` 로 설치됩니다 ([Appendix C](#appendix-c-requirementstxt) 참고). |
| `Dockerfile` | 베이스 이미지·네이티브 라이브러리·패키지 설치 절차와 기동 시 실행할 명령을 정의합니다. |
| `docker-compose.yml` | 위 `Dockerfile` 로 이미지를 빌드하고, 볼륨·네트워크·재시작 정책을 붙여 컨테이너로 띄우는 방법을 정의합니다. |

```powershell
# (first time only) Copy the example file and fill in the connection info. docker-compose.env is not committed to git.
Copy-Item docker-compose.env_example docker-compose.env

# Create the shared network mlops (leave it as is if it already exists), then build the image and start the container.
docker network create mlops
docker compose up -d --build
```

> `set_docker.ps1` (Windows) · `set_docker.sh` (Linux) 은 위 네트워크 생성과 `docker compose down` / `up` 을 한 번에 처리하는 편의 스크립트입니다. 다만 코드만 바꾸고 의존성은 그대로일 때는 재빌드가 필요 없으므로, 의존성을 바꿨을 때만 `--build` 를 붙입니다.

### `requirements.txt`

설치할 패키지를 버전까지 핀하여 한 줄에 하나씩 적습니다. 분류 주석으로 묶어 두면 어떤 목적의 패키지인지 한눈에 보입니다.

```text
numpy==1.26.4                  # numerical arrays (the baseline version for every dependency)
pandas==2.0.3                  # tabular data handling
scikit-learn==1.4.2            # classic machine learning algorithms
TA-Lib==0.4.29                 # technical analysis indicators (requires a C library)
```

### `Dockerfile`

아래는 핵심 골자입니다. 네이티브 라이브러리 설치 → 의존성 설치 → 코드 복사 → 기동 명령 순서입니다.

```dockerfile
# Base image pinned to version 3.11.15.
FROM python:3.11.15

# System packages needed to build native extensions.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install requirements.txt first. When only the code changes, this layer is cached and reinstallation is skipped.
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code.
COPY app/ .

# App to run automatically when the container starts.
CMD ["python", "start.py"]
```

- `COPY requirements.txt` 를 코드 복사보다 **먼저** 두는 것은 레이어 캐시를 위해서입니다. 코드만 바뀌면 의존성 설치 레이어가 캐시되어 재설치를 건너뜁니다.
- TA-Lib·ucrdtw 처럼 빌드가 까다로운 패키지는 numpy 헤더와 빌드 격리 (`--no-build-isolation`) 등을 별도로 다뤄야 합니다. 실제 `Dockerfile` 의 주석에 그 이유가 정리되어 있습니다.

### `docker-compose.yml`

```yaml
services:
  python:
    build: .                        # Build the image from the Dockerfile in the current folder.
    env_file:
      - docker-compose.env          # Inject connection info.
    volumes:
      # Connect the host's app/ to the container's /app so code changes apply without a rebuild.
      - ./app:/app
    networks:
      - mlops
    # One-shot run: when the app finishes, leave the container in the Exited state and do not restart it.
    restart: "no"                   # YAML reads no as a boolean, so wrap it in quotes.

networks:
  mlops:
    external: true
```

- `build: .` 은 `image:` 대신 현재 폴더의 `Dockerfile` 로 이미지를 직접 빌드한다는 뜻입니다.
- `volumes: ./app:/app` 은 호스트의 `app/` 폴더를 컨테이너 `/app` 에 **bind mount** 합니다. 호스트에서 코드를 고치면 재빌드 없이 컨테이너에 즉시 반영되며, 컨테이너가 `/app` 에 쓴 결과 파일도 호스트에 그대로 나타납니다 ([§3](#3-access) 의 핵심입니다).
- `restart: "no"` 는 앱이 끝나도 다시 띄우지 않고 `Exited` 상태로 둡니다. 종료 코드와 로그는 `docker compose logs` · `docker ps -a` 로 확인합니다.

## 3. Access

이 컨테이너의 핵심 사용법은 **호스트의 파이썬 코드와 데이터를 컨테이너의 파이썬으로 실행하고, 결과 파일을 호스트로 돌려받는 것**입니다. 실행 주체는 항상 컨테이너의 파이썬 (3.11.15 + 설치된 의존성) 이며, 호스트에는 코드·데이터·결과 **파일**만 존재합니다. 이를 가능하게 하는 것이 [§2](#2-docker-setup) 의 bind mount (`./app:/app`) 입니다.

### Folder Structure

호스트의 `app/` 아래에 코드와 데이터를 둡니다. 이 폴더가 컨테이너 `/app` 에 그대로 비칩니다.

```text
app/
├── requirements.txt
├── start.py            # default entrypoint run when the container starts
└── example/
    ├── example.py      # the code to run this time
    ├── input.txt       # input data
    └── output.txt      # result file (created by the code)
```

### Example Code (`app/example/example.py`)

같은 폴더의 `input.txt` 를 읽어 원문과 응답을 담은 `output.txt` 를 생성합니다. 경로는 스크립트 위치 기준 (`/app/example`) 으로 적어, 호스트와 컨테이너 어느 쪽에서 실행해도 동일하게 동작하게 합니다.

```python
"""Read input.txt and create output.txt containing the original text and a reply."""
from pathlib import Path

BASE = Path(__file__).parent          # /app/example inside the container

source = (BASE / "input.txt").read_text(encoding="utf-8").strip()
reply = "Couldn't be better !!"

(BASE / "output.txt").write_text(f"{source}\n{reply}\n", encoding="utf-8")
print(f"Done: created output.txt.\n{source}\n{reply}")
```

입력 `input.txt` 의 내용은 다음과 같습니다.

```text
How are you?
```

### Exited Container — `docker compose run`

기본 진입점 (`start.py`) 이 아닌 임의의 스크립트를 실행하려면, compose 의 기본 명령을 덮어쓰면 됩니다. `docker compose run` 은 `docker-compose.yml` 의 볼륨·네트워크·환경변수를 그대로 적용한 채 일회성으로 컨테이너를 띄웁니다.

```bash
# With app/ mounted at /app, run example.py with the container's Python.
docker compose run --rm python python example/example.py
```

실행이 끝나면 컨테이너 `/app/example/output.txt` 에 쓰인 결과가 bind mount 를 통해 **호스트의 `app/example/output.txt`** 에 그대로 나타납니다. 생성된 `output.txt` 의 내용은 다음과 같습니다.

```text
How are you?
Couldn't be better !!
```

`--rm` 은 실행이 끝난 컨테이너를 자동으로 삭제합니다.

> `docker compose up` 은 `docker-compose.yml` 의 기본 명령 (`CMD ["python", "start.py"]`) 을 실행하고, `docker compose run python python example/example.py` 는 그 명령을 `python example/example.py` 로 덮어씁니다. 즉 같은 이미지·같은 환경에서 **실행할 파일만 바꾸는 것**입니다.

### Running Container — `docker compose exec`

데이터를 바꿔 가며 여러 번 실행할 때는, 컨테이너를 살려 둔 채 그 안으로 들어가는 편이 빠릅니다. 단발성 `start.py` 대신 컨테이너를 계속 띄워 두려면 기동 명령을 대기 상태로 바꿉니다.

```bash
# (1) Start the container in a waiting state (override the default CMD with sleep).
docker compose run -d --name py-dev python sleep infinity

# (2) Run inside the container, or enter a shell.
docker compose exec python python example/example.py
docker compose exec python bash          # interactive shell

# (3) Clean up when done.
docker rm -f py-dev
```

### Temporary Package Install

컨테이너 셸에서 `pip install` 한 패키지는 그 컨테이너에만 남고, 컨테이너를 삭제하거나 재생성하면 사라집니다. **계속 쓸 패키지는 셸이 아니라 `requirements.txt` 에 추가하고 재빌드**해야 이미지에 영구히 남습니다 ([Appendix C](#appendix-c-requirementstxt) 참고).

| Action | Result of shell `pip install` |
|--------|-------------------------------|
| 컨테이너 재시작 (`restart`) | 유지됨 |
| 컨테이너 삭제 후 재생성 (`down` 후 `up`, `--rm`) | 사라짐 |
| 이미지 재빌드 (`build`) | 사라짐 |

## 4. Credentials

다른 서비스 (MongoDB·PostgreSQL 등) 에 접속하기 위한 연결 정보는 `docker-compose.env` 한 곳에 모으고, 컨테이너는 `env_file` 로 읽어 `os.environ` 에서 꺼내 씁니다. 실제 값이 담긴 `docker-compose.env` 는 `.gitignore` 로 git 추적에서 제외하고, 비밀값을 비운 `docker-compose.env_example` 만 커밋합니다.

```dotenv
# docker-compose.env_example  (Python)
# Fill every CHANGE_ME with a real value. This file holds secrets, so exclude it from git via .gitignore.

CHANGE_ME=CHANGE_ME
```

- 접속할 서비스가 정해지면 그 서비스가 요구하는 키 (예: `MONGODB_URI`) 를 이 파일에 추가하고, 코드에서는 `os.environ["MONGODB_URI"]` 처럼 환경변수로 읽습니다.
- 비밀값은 코드·`docker-compose.yml` 에 평문으로 적지 않습니다. 실제 `docker-compose.env` 는 git 이 아니라 안전한 채널로 공유합니다.
- 같은 호스트의 서비스끼리는 공유 네트워크 `mlops` 안에서 **서비스명** (예: `mongo`) 으로 접속하므로, 호스트명 자리에 `localhost` 대신 서비스명을 씁니다.

## Appendix A. Terminology

- **image** — 파이썬·의존성·코드를 담아 굳힌 읽기 전용 템플릿. `Dockerfile` 로 빌드합니다.
- **container** — image 를 실행한 인스턴스. 같은 image 로 여러 container 를 띄울 수 있습니다.
- **build** — `Dockerfile` 의 절차를 수행해 image 를 만드는 과정 (`docker compose build`).
- **layer cache** — `Dockerfile` 의 각 단계는 레이어로 캐시됩니다. 바뀌지 않은 단계는 재실행하지 않아 빌드가 빨라집니다.
- **build isolation** — pip 가 패키지를 빌드할 때 격리된 임시 환경을 쓰는 기본 동작. 빌드에 기존 설치본 (예: numpy 헤더) 이 필요하면 `--no-build-isolation` 으로 끕니다.
- **bind mount** — 호스트의 폴더를 컨테이너 경로에 연결하는 방식 (`./app:/app`). 파일이 양쪽에서 같은 실체를 가리킵니다.
- **named volume** — Docker 가 위치를 관리하는 영속 저장소. 데이터베이스 데이터처럼 컨테이너 밖에 보존할 때 씁니다.
- **one-shot container** — 실행 후 종료되는 단발성 컨테이너. 이 스택의 파이썬 컨테이너가 그 형태입니다 (`restart: "no"`).
- **docker commit** — 도는 컨테이너의 현재 상태를 새 image 로 굳히는 명령. 결과만 남고 과정이 기록되지 않아, 영구 환경은 `Dockerfile` 재빌드를 권장합니다.
- **pipreqs** — 코드가 실제 import 하는 패키지만 골라 `requirements.txt` 를 생성하는 도구 ([Appendix C](#appendix-c-requirementstxt)).

## Appendix B. CLI (Command Line Interface)

이 문서에서 쓰는 주요 명령만 정리합니다. `docker compose` 명령은 `docker-compose.yml` 이 있는 폴더에서 실행합니다.

| Category | Command | Description |
|----------|---------|-------------|
| Build | `docker compose build` | `Dockerfile` 로 image 를 빌드합니다. |
| Build | `docker compose build --no-cache` | 레이어 캐시를 무시하고 처음부터 빌드합니다. |
| Up | `docker compose up -d --build` | 빌드 후 컨테이너를 백그라운드로 띄웁니다. |
| Run | `docker compose run --rm python python <file>.py` | 기본 명령을 덮어써 임의의 스크립트를 실행하고 끝나면 삭제합니다. |
| Exec | `docker compose exec python bash` | 도는 컨테이너 안에서 대화형 셸로 진입합니다. |
| Exec | `docker compose exec python python <file>.py` | 도는 컨테이너 안에서 스크립트를 실행합니다. |
| State | `docker compose ps` · `docker ps -a` | 컨테이너 상태·종료 코드를 확인합니다. |
| Logs | `docker compose logs python` | 컨테이너 출력 로그를 봅니다. |
| Down | `docker compose down` | 스택을 내립니다 (named volume 은 유지). |
| Image | `docker images` | 빌드된 image 목록과 크기를 확인합니다. |
| Commit | `docker commit <container> <image>:<tag>` | 도는 컨테이너 상태를 새 image 로 굳힙니다 (임시 보존용). |

## Appendix C. Requirements.txt

`requirements.txt` 는 설치할 파이썬 패키지와 버전을 한 줄에 하나씩 적은 목록입니다. 만드는 방법은 두 가지이며 목적이 다릅니다.

### Method 1 — `pip freeze` (entire current environment)

현재 파이썬 환경에 설치된 **모든** 패키지를 버전과 함께 출력합니다. 의존성의 의존성 (간접 패키지) 까지 전부 포함되어 목록이 길어집니다.

```bash
pip freeze > requirements.txt
```

### Method 2 — `pipreqs` (only what the code actually uses)

`pipreqs` 는 소스 코드를 훑어 **실제로 `import` 하는 패키지만** 골라 `requirements.txt` 를 만듭니다. 환경에 깔려 있지만 코드가 쓰지 않는 패키지는 빠지므로, 목록이 간결하고 프로젝트의 실제 의존성에 가깝습니다.

```bash
# (1) Install pipreqs.
pip install pipreqs

# (2) Analyze the code in the target folder and generate requirements.txt there.
pipreqs ./app --encoding=utf-8

# (3) Add --force to overwrite an existing file.
pipreqs ./app --encoding=utf-8 --force
```

| Aspect | `pip freeze` | `pipreqs` |
|--------|--------------|-----------|
| 기준 | 환경에 설치된 모든 패키지 | 코드가 import 하는 패키지 |
| 간접 의존성 | 포함 (목록이 김) | 보통 제외 (목록이 간결) |
| 쓰지 않는 패키지 | 포함됨 | 제외됨 |
| 사용 권장 상황 | 환경을 그대로 재현할 때 | 프로젝트의 실제 의존성만 추릴 때 |

> `pipreqs` 가 추정한 버전이 항상 의도와 같지는 않으므로, 생성 후 핵심 패키지 (numpy·tensorflow 등) 의 버전을 직접 검토해 핀합니다. 네이티브 빌드가 필요한 TA-Lib·ucrdtw 등은 빠지거나 잘못 잡힐 수 있어 수동 확인이 필요합니다.

### Install — `pip install -r`

`requirements.txt` 의 패키지를 한 번에 설치합니다. `Dockerfile` 안에서도 이 명령으로 빌드 시 설치합니다.

```bash
pip install -r requirements.txt
```

- `-r` 은 *requirement file* 의 약자로, 인자로 준 파일에 나열된 패키지를 모두 설치하라는 뜻입니다.
- 이 컨테이너에서는 `Dockerfile` 의 `RUN pip install --no-cache-dir -r requirements.txt` 가 빌드 중 1회 실행됩니다. 따라서 호스트에서 직접 칠 일은 보통 없고, **패키지를 추가하면 `requirements.txt` 를 고치고 `docker compose build` 로 재빌드**하는 흐름을 따릅니다.
- `--no-cache-dir` 은 pip 의 다운로드 캐시를 남기지 않아 image 크기를 줄입니다.
