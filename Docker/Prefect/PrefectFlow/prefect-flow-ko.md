# Prefect Flow
Rev. 0 | Created: 2026-10-10 | Updated: 2026-10-10 09:28 CDT

- [1. Purpose](#1-purpose)
- [2. Role](#2-role)
- [3. Image](#3-image)
- [4. Deployment](#4-deployment)
- [5. pipeline.py](#5-pipelinepy)
- [Appendix A. Terminology](#appendix-a-terminology)
- [Appendix B. requirements.txt](#appendix-b-requirementstxt)
- [Appendix C. Mounting a Remote Data Folder](#appendix-c-mounting-a-remote-data-folder)
- [Appendix D. push_flow_image.sh](#appendix-d-push_flow_imagesh)

## 1. Purpose

- **Problem Statement**: Flow 코드는 worker 가 run 마다 띄우는 Pipeline Flow 컨테이너 안에서 돌므로, flow image 와 deployment 와 `pipeline.py` 가 서로 맞지 않으면 run 이 시작되지 않거나 다른 코드로 돕니다.
- **Goal**: 실무자가 flow image 를 build 해 registry 에 올리고, deployment 를 등록하고, `pipeline.py` 가 팀 코드를 받아 실행하는 차례를 따라갈 수 있게 합니다.
- **Non-Goal**: 팀원이 작성하는 학습 코드 (`my_flow.py`) 의 내용과 worker 기동은 다루지 않습니다.

## 2. Role

Pipeline Flow 는 worker 가 job 마다 띄우는 per-flow 컨테이너입니다. worker 하나가 동시 job 수만큼 **여러 개 (n 개)** 를 띄우며 (상한 `--limit`, 현재 8), 각 컨테이너는 독립입니다. 세 가지를 다룹니다 — 컨테이너가 쓰는 **이미지** ([§3](#3-image)), 그 이미지로 무엇을 실행할지 server 에 등록하는 **deployment** ([§4](#4-deployment)), 컨테이너 안에서 generic flow orchestrator 역할을 하는 `pipeline.py` ([§5](#5-pipelinepy)). worker 자신은 flow 를 실행하지 않으므로 flow 는 **별도 이미지** 를 쓰며 ([prefect-worker-ko.md §3](../PrefectWorker/prefect-worker-ko.md#3-image)), 팀 라이브러리는 이 flow image 에만 둡니다. 실행이 server UI 에 어떻게 보이는지는 [prefect-ko.md §9](../prefect-ko.md#9-prefect-ui) 입니다.

## 3. Image

  job 마다 뜨는 컨테이너의 python 환경입니다. **라이브러리와 orchestrator (`pipeline.py`) 만** 굽습니다. 팀 코드는 런타임에 그 커밋만 받는 **shallow `git fetch`** + `worktree` 로 (`git_commit_hash` 으로 특정 커밋에 고정) 컨테이너의 사설 `script/` 에 펼칩니다. 이미지가 한 번 빌드로 고정되어 모두 같은 런타임을 씁니다.

  #### Dockerfile

  ```dockerfile
  # Dockerfile.pipeline_flow — shared team Pipeline Flow image (libraries + orchestrator)
  # Dependency install runs once at build time and stays in the layer cache, so later container starts are fast.
  FROM python:3.11.15

  # System packages.
  #   git             : pipeline.py shallow-fetches the team repo into a per-run worktree at runtime
  #   build-essential : compiles C extensions (ucrdtw / dtaidistance / TA-Lib Python wrappers)
  #   wget            : downloads the TA-Lib C library source
  #   autotools-dev   : current config.guess / config.sub, which know aarch64 (see the TA-Lib step)
  RUN apt-get update && apt-get install -y --no-install-recommends \
          git build-essential wget autotools-dev \
      && rm -rf /var/lib/apt/lists/*

  # The TA-Lib Python package needs the C library of the same name, so build and install it from source.
  # ta-lib-0.4.0 ships config.guess / config.sub from 2007, whose configure stops on arm64 (aarch64) with
  # "cannot guess build type"; the copies from autotools-dev replace them so one Dockerfile builds amd64 and arm64.
  RUN wget -q http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz \
      && tar -xzf ta-lib-0.4.0-src.tar.gz \
      && cd ta-lib \
      && cp /usr/share/misc/config.guess /usr/share/misc/config.sub . \
      && ./configure --prefix=/usr \
      && make \
      && make install \
      && cd .. \
      && rm -rf ta-lib ta-lib-0.4.0-src.tar.gz

  WORKDIR /work

  # Copy requirements first so this layer is cached when only code changes.
  COPY requirements.txt .

  # ucrdtw / TA-Lib import numpy at build time, but pip's build isolation has no numpy, so a plain -r install fails.
  # Install numpy first, then those two with build isolation disabled, then the rest.
  RUN pip install --no-cache-dir numpy==1.26.4
  # SETUPTOOLS_USE_DISTUTILS=stdlib: the setuptools distutils shim lacks the msvccompiler that numpy.distutils looks for.
  RUN SETUPTOOLS_USE_DISTUTILS=stdlib pip install --no-cache-dir --no-build-isolation ucrdtw==0.201
  # TA-Lib 0.4.29's bundled C source uses the numpy 1.x C API; disable isolation so it compiles against the numpy 1.26 above.
  RUN pip install --no-cache-dir --no-build-isolation TA-Lib==0.4.29
  RUN pip install --no-cache-dir -r requirements.txt

  # pipeline.py — orchestrator (deployment entrypoint). Prefect's docker worker injects the run command; no CMD needed.
  COPY pipeline.py .
  ```

  - `FROM python:3.11.15` + `apt-get install git build-essential wget autotools-dev` — `git` 은 런타임 `git fetch`·`worktree` 용, `build-essential` 은 C 확장 (ucrdtw·dtaidistance·TA-Lib) 을 compile 하는 용도, `wget` 은 TA-Lib C library source 를 내려받는 용도, `autotools-dev` 는 arm64 를 아는 최신 `config.guess`·`config.sub` 를 주는 용도입니다.
  - TA-Lib C library — Python `TA-Lib` package 는 같은 이름의 C library 를 필요로 하므로, `ta-lib-0.4.0` source 를 build 해 `/usr` 에 설치합니다. 이 source 에 든 2007 년판 `config.guess`·`config.sub` 로는 arm64 에서 `configure` 가 "cannot guess build type" 으로 멈추므로, `configure` 전에 `autotools-dev` 의 최신판으로 바꿉니다.
  - `COPY requirements.txt` → `pip install` — 팀 라이브러리를 설치합니다 (코드보다 먼저 복사해 레이어 캐시를 살립니다). `ucrdtw` 와 `TA-Lib` 은 build 할 때 numpy 를 import 하므로, `numpy==1.26.4` 를 먼저 설치하고 두 package 를 build isolation 없이 설치한 뒤 나머지를 설치합니다. required: `prefect`·`boto3` · payload: `mlflow`·`optuna`·`scikit-learn`·`numpy`·`pyarrow` · optional: `pandas`·`torch`·`psycopg2-binary`.
  - `COPY pipeline.py` — orchestrator 만 이미지에 굽습니다. 팀 코드는 런타임에 shallow `git fetch` 로 받습니다.

  #### Execution Command

  build 하는 machine 의 `PrefectFlow/` 에서 `push_flow_image.sh` 를 실행합니다. `Dockerfile.pipeline_flow`, `requirements.txt`, `pipeline.py` 를 바꿀 때마다 다시 실행합니다 (코드는 [Appendix D](#appendix-d-push_flow_imagesh)).

  ```bash
  ./push_flow_image.sh                              # registry = IMAGE_REGISTRY of ../docker-compose.env
  ./push_flow_image.sh --registry localhost:12357   # on the registry machine itself
  ```

  - `--registry <host:port>` — image 를 올릴 registry 입니다. 생략하면 `../docker-compose.env` (없으면 `_example`) 의 `IMAGE_REGISTRY` 를 쓰고, 값이 비었거나 자리표시자면 build 전에 멈춥니다.
  - `--platform <list>` — build 할 CPU architecture 입니다. 기본값 `linux/amd64,linux/arm64` 는 두 architecture 의 이미지를 한 tag 로 묶고, worker machine 은 run 마다 자기 architecture 의 것을 받습니다. Build 하는 machine 과 다른 architecture 는 emulation 으로 build 되어 훨씬 오래 걸립니다.
  - `--tag <tag>` — image tag 입니다 (기본 `latest`). Base job template 의 기본값이 `pipeline-flow:latest` 이므로, 다른 tag 는 그 tag 를 지정한 deployment 에서만 쓰입니다.

  script 는 build 전에 `requirements.txt` 와 `pipeline.py` 가 있는지 확인하고, 아래 `docker buildx build` 를 실행한 뒤, registry 의 tag 목록에 그 tag 가 올라갔는지 확인합니다.

  ```bash
  docker buildx build --platform <PLATFORM> -f Dockerfile.pipeline_flow -t <REGISTRY>/pipeline-flow:<TAG> --push .
  ```

  - `-f Dockerfile.pipeline_flow` — build 할 Dockerfile 입니다.
  - `-t <REGISTRY>/pipeline-flow:<TAG>` — registry 주소가 든 image 이름입니다. `register_pool.sh` 가 base job template 의 `pipeline-flow:latest` 앞에 같은 `IMAGE_REGISTRY` 를 붙이므로, worker 는 이 이름으로 flow 컨테이너를 띄웁니다 ([prefect-server-ko.md §3 Work Pool Registration](../PrefectServer/prefect-server-ko.md#3-work-pool-registration)).
  - `--push` — build 한 이미지를 그 registry 에 바로 올립니다.
  - `.` — build context 입니다. `COPY` 소스가 이 안에서 해석되며, 같은 folder 의 `.dockerignore` 가 `requirements.txt` 와 `pipeline.py` 만 보냅니다.

  > Flow image 를 처음 올린 뒤에야 pool 을 `register_pool.sh` 로 다시 등록합니다. 등록이 pool 의 image 기본값을 `<IMAGE_REGISTRY>/pipeline-flow:latest` 로 바꾸므로, push 전에 등록하면 run 이 registry 에 없는 image 를 찾습니다 ([prefect-server-ko.md §3](../PrefectServer/prefect-server-ko.md#3-work-pool-registration)).

  > 두 architecture 를 한 번에 build 하려면 build 하는 machine 의 Docker 가 containerd image store 를 써야 합니다 (Docker Desktop: Settings > General > "Use containerd for pulling and storing images").

  **GPU** — 이 이미지로 GPU 를 쓰려면 `requirements.txt` 의 torch 를 CUDA 휠로 설치합니다 (CUDA 런타임이 휠에 번들되어 호스트 드라이버만 맞으면 동작). 더해 호스트에 NVIDIA 드라이버·nvidia-container-toolkit 을 두고, base job template 에서 GPU 를 요청합니다 ([prefect-server-ko.md §3 Work Pool Registration](../PrefectServer/prefect-server-ko.md#3-work-pool-registration)). 드라이버와 CUDA 버전이 안 맞으면 베이스 이미지를 `nvidia/cuda` 계열로 바꿉니다. GPU job 은 무거우므로 그 등급 worker 의 `--limit` 을 1–2 로 낮춰 동시 실행을 제한합니다.

## 4. Deployment

  work pool 등록은 **실행 방식** (routing lane 을 만드는 인프라) 이고, deployment 는 **실행 내용의 정의** 입니다.

  server 에 deployment 를 관리자가 container 밖에서 1회 등록합니다. Deployment 는 yaml 로 entrypoint, work pool, flow image 를 정의합니다. 팀원이 작성하는 학습 스크립트 (`my_flow.py`) 와는 무관합니다.

  #### Yaml

  ```yaml
  # high_deployment.yml - high-tier deployment definition
  # __version__ = "0.0.6"    # Semantic Versioning : Major.Minor.Patch
  deployments:
    - name: high_deployment
      entrypoint: pipeline.py:pipeline       # <file>:<@flow function>
      work_pool:
        name: high_performance
        job_variables:
          image: pipeline-flow:latest
      parameters:
        payload: my_flow.py
      pull:                                    # override Prefect's auto-injected /opt/prefect
        - prefect.deployments.steps.set_working_directory:
            directory: /work                   # pipeline.py lives at /work in pipeline-flow:latest (WORKDIR)
  ```

  - `name: high_deployment` — deployment 이름입니다 (등급별로 `high_deployment`·`low_deployment`).
  - `entrypoint: pipeline.py:pipeline` — 실행할 flow 를 `<파일>:<@flow 함수>` 로 가리킵니다 (어떻게 `pipeline.py` 가 되는지는 [§5](#5-pipelinepy)).
  - `work_pool.name: high_performance` — 이 deployment 가 제출될 work pool 입니다.
  - `job_variables.image: pipeline-flow:latest` — flow 를 띄울 이미지입니다 ([§3](#3-image)). 이 `job_variables` 블록은 `work_pool.name` 으로 등록된 work pool 의 **base job template 을 override** 합니다. `job_variables.image` 는 `job_configuration.image` 를 override 합니다 ([prefect-server-ko.md §3](../PrefectServer/prefect-server-ko.md#3-work-pool-registration)).
  - `parameters.payload: my_flow.py` — flow 파라미터 기본값입니다 (`git_repo`·`git_commit_hash`·`minio_key`·`submitter`·`prefect_block` 은 trigger 때 줍니다).
  - `pull` — flow 컨테이너가 시작할 때 실행하는 스텝입니다. Prefect 는 기본으로 작업 디렉터리를 `/opt/prefect` 로 잡는데, `pipeline.py` 는 이미지의 `WORKDIR` 인 `/work` 에 있으므로 `set_working_directory: /work` 로 덮어써 entrypoint (`pipeline.py:pipeline`) 를 찾게 합니다 (run log 의 `set_working_directory` 스텝이 이것).

  `job_variables.image` 가 base job template 을 덮어쓰는 흐름 — template 은 `image` 변수 (기본값 `pipeline-flow:latest`) 를 선언하고 `job_configuration` 에서 `"image": "{{ image }}"` 로 받습니다. job 제출 때 Prefect 가 그 `{{ image }}` 자리를 채우는데, deployment 에 `job_variables.image` 가 있으면 **템플릿 `default` 대신 이 값** 이 들어가 컨테이너가 그 이미지로 뜹니다 (`cpu`·`mem_limit`·`env` 등 다른 변수도 같은 방식; 우선순위 `job_variables` > `default` 는 [prefect-server-ko.md §3](../PrefectServer/prefect-server-ko.md#3-work-pool-registration)).

  #### Execution Command

  `prefect deploy` 는 yaml 정의를 server 에 등록합니다. 실행 폴더에는 `pipeline.py` 와 `high_deployment.yml` 가 있어야 합니다.

  ```bash
  cd PrefectFlow                                      # the folder with pipeline.py and high_deployment.yml
  prefect deploy --prefect-file high_deployment.yml --name high_deployment --no-prompt
  ```

  - `prefect CLI --prefect-file` — 정의 파일.
  - `prefect CLI --name` — 등록할 deployment.
  - `prefect CLI --no-prompt` — 대화형 질문을 끄고 yaml 정의대로 등록합니다 (이미지 빌드·스케줄 프롬프트 안 뜸).

  `prefect deploy` 는 DB 에 직접 쓰지 않고 server API 로 등록을 보냅니다 (server 가 Postgres `prefect` DB 에 저장). 등급마다 `high`·`low` yaml 로 두 벌 등록합니다.

  > **중요** — `prefect deploy` 는 entrypoint 인 `pipeline.py` 의 `pipeline` 함수 **시그니처를 introspect** 해 파라미터 스키마를 server DB (`prefect`) 에 저장합니다. 따라서 `prefect deploy` 는 `pipeline.py` 가 있는 폴더에서 실행하여야 하며, `pipeline` 함수가 바뀌면 이미지 `docker build` 와 함께 **`prefect deploy` 도 반드시** 다시 해야 합니다 (그래야 server 의 파라미터 스키마·UI Run 폼·trigger 검증이 새 시그니처와 맞습니다).

  #### Verification

  deployment 이 server 에 등록됐는지 확인합니다.

  ```bash
  prefect deployment ls
  prefect deployment inspect "pipeline/low_deployment"
  ```

  `deployment ls` 결과물 예시 — `pipeline/low_deployment` 가 `low_performance` pool 로 등록된 모습:

  ```text
                                       Deployments
  ┌───────────────────────────┬──────────────────────────────────────┬─────────────────┐
  │ Name                      │ ID                                   │ Work Pool       │
  ├───────────────────────────┼──────────────────────────────────────┼─────────────────┤
  │ pipeline/low_deployment │ a1b2c3d4-5e6f-7081-92a3-b4c5d6e7f809 │ low_performance │
  └───────────────────────────┴──────────────────────────────────────┴─────────────────┘
  ```

## 5. pipeline.py

  orchestrator (`pipeline.py`) 는 **"커밋 받아 → 팀원 코드 실행"** 만 하는 얇은 python 골격 (`@flow` 함수) 으로, [§3](#3-image) 이미지에 구워집니다. 관리자가 관리하는 스크립트이며 팀원이 작성하지 않습니다 — 팀원은 자기 학습 스크립트 (`my_flow.py` 등) 만 작성해 `payload` 파라미터로 지정합니다.

  ```python
  # pipeline.py — orchestrator; Prefect runs this as the deployment entrypoint.
  import collections
  import os
  import shutil
  import subprocess
  import tempfile
  from pathlib import Path
  from typing import Dict

  import boto3
  from prefect import flow, get_run_logger
  from prefect.blocks.core import Block
  from prefect.blocks.fields import SecretDict
  from prefect.variables import Variable

  __version__ = "0.0.36"  # Semantic Versioning:  Version = Major.Minor.Patch


  class Credentials(Block):              # ONE block holds a credential set as nested dicts (values hidden);
      minio: SecretDict                  # access_key, secret_key        (endpoint is a prefect Variable)
      postgresql_catalog: SecretDict     # username, password, database  (host:port is the prefect Variable 'postgresql_host_port')
      postgresql_optuna: SecretDict      # username, password, database  (host:port is the prefect Variable 'postgresql_host_port')


  def run_payload(*, payload: str, submitter: str, data: Path, script: Path, env: Dict[str, str]) -> None:
      """Run the team's payload in script/, streaming its output to this run's logs line-by-line and
      keeping the tail so the crash reason is visible even when the payload never created a flow run.

      A payload that dies BEFORE entering its @flow (import error, __main__ exception, bad CLI args)
      registers no Prefect flow run: in the dashboard Runs there is NO payload flow error to see - only
      this pipeline flow error. Raises RuntimeError on a non-zero exit; the tail carries the traceback."""
      log = get_run_logger()
      tail = collections.deque(maxlen=50)              # last N output lines -> attached to the error
      # -u: unbuffered so lines arrive live; stderr -> stdout so the traceback streams inline, in order.
      proc = subprocess.Popen(
          ["python", "-u", payload, "--submitter", submitter, "--data-folder", str(data)],
          cwd=script, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
      for line in proc.stdout:                          # stream each line to this run's UI logs as it arrives
          line = line.rstrip()
          log.info(line)
          tail.append(line)
      returncode = proc.wait()
      if returncode != 0:
          raise RuntimeError(
              f"payload {payload} exited {returncode} for {submitter}; last {len(tail)} output line(s):\n"
              + "\n".join(tail)
              + "\n-- if the payload died before entering its @flow (import error, __main__ exception, "
                "bad CLI args), no payload flow run is created: the Prefect dashboard Runs shows NO "
                "payload flow error, only this pipeline flow error.")


  # flow_run_name shows who submitted the run (e.g. alice@a1b2c3d).
  @flow(name="pipeline", flow_run_name="{submitter}#{git_commit_hash}")
  def pipeline(*, submitter: str = "", payload: str = "my_flow.py", prefect_block: str = "",
               git_repo: str, git_commit_hash: str, minio_key: str, minio_bucket: str = "datasets") -> None:
      log = get_run_logger()                         # writes to this run's UI logs
      log.info(f"pipeline v{__version__}")
      base = Path(tempfile.mkdtemp(prefix="run-"))   # per-run temp dir (removed in finally)
      repo = base / "repo"                           # git database (.git + the fetched commit)
      script = base / "script"                       # worktree: team repo snapshot at the commit
      data = base / "data"                           # MinIO download target
      try:
          # repo/: git database - init, add remote, shallow-fetch the one commit
          subprocess.run(["git", "init", repo], check=True)
          subprocess.run(["git", "-C", repo, "remote", "add", "origin", git_repo], check=True)
          subprocess.run(["git", "-C", repo, "fetch", "--depth", "1", "origin", git_commit_hash], check=True)

          # script/: expand the fetched commit into a clean detached worktree
          subprocess.run(["git", "-C", repo, "worktree", "add", "--detach", script, git_commit_hash], check=True)

          # data/: MinIO download target (git didn't create it)
          data.mkdir(parents=True, exist_ok=True)
          # this run's prefect_block -> its SECRETS (§7); service addresses are prefect Variables (§3).
          creds = Credentials.load(prefect_block)
          minio = creds.minio.get_secret_value()
          s3 = boto3.client("s3", endpoint_url=Variable.get("minio_endpoint"),
                            aws_access_key_id=minio["access_key"],
                            aws_secret_access_key=minio["secret_key"])
          # minio_key -> data/: download every object under the key (works for a single file or a whole prefix).
          paginator = s3.get_paginator("list_objects_v2")
          n = 0
          for page in paginator.paginate(Bucket=minio_bucket, Prefix=minio_key):
              for obj in page.get("Contents", []):
                  key = obj["Key"]
                  rel = key[len(minio_key):].lstrip("/") or Path(key).name  # path under the prefix
                  dest = data / rel
                  dest.parent.mkdir(parents=True, exist_ok=True)
                  s3.download_file(minio_bucket, key, str(dest))
                  n += 1
          if n == 0:
              raise FileNotFoundError(f"no objects under s3://{minio_bucket}/{minio_key}")
          log.info(f"downloaded {n} object(s) from s3://{minio_bucket}/{minio_key} to {data}")

          # bridge addresses (prefect Variables) to the payload via env: the MLflow tracking URI so
          # my_flow.py logs to the MLflow server (not a local ./mlruns), and the optuna study DSN
          # (Variable host/port + block creds) so a payload using Optuna hits the shared study DB.
          env = os.environ.copy()
          mlflow_uri = Variable.get("mlflow_tracking_uri")
          if mlflow_uri:
              env["MLFLOW_TRACKING_URI"] = mlflow_uri
          opt = creds.postgresql_optuna.get_secret_value()
          opt_host, _, opt_port = (Variable.get("postgresql_host_port") or "").partition(":")   # single Variable -> host, port
          opt_port = opt_port or "5432"                                               # tolerate a bare host with no ':port'
          env["POSTGRESQL_OPTUNA_DSN"] = (f"postgresql://{opt['username']}:{opt['password']}"
                                          f"@{opt_host}:{opt_port}/{opt['database']}")
          # run the team's payload in script/; run identity passed as CLI args. run_payload streams the
          # output to this run's logs and raises on a non-zero exit so the failure can't pass silently.
          run_payload(payload=payload, submitter=submitter, data=data, script=script, env=env)
      finally:
          shutil.rmtree(base, ignore_errors=True)    # one cleanup removes repo/ + script/ + data/
  ```

  - **자유로운 코드** — `payload` 로 팀원이 자기 스크립트를 지정하므로 코드를 정해진 틀에 맞출 필요가 없습니다. 입력은 CLI 인자 (`--submitter`·`--data-folder`) 로 받으므로, 팀원 스크립트는 `argparse` 로 그 값만 읽으면 됩니다. (payload 는 이미 체크아웃된 `script/` 안에서 돌므로 git 정보는 넘기지 않고, MLflow 서버 주소만 Variable `mlflow_tracking_uri` 를 `MLFLOW_TRACKING_URI` 환경변수로 넘깁니다.)
  - **데이터 이력** — `minio_bucket`·`minio_key` 가 **flow 파라미터** 라서 Prefect 가 run 마다 입력값을 `prefect` DB 에 자동 저장합니다 (어느 버킷·객체를 썼는지 lineage 로 남습니다).
  - **crash 확인** — payload 가 0 이 아닌 코드로 끝나면 `run_payload` 이 `RuntimeError` 를 raise 해 **pipeline run 이 `Failed` 로 표시됩니다**. payload 가 도는 동안 그 출력은 한 줄씩 pipeline run 의 **Logs** 로 스트리밍되고, 실패하면 마지막 출력 (stdout·stderr, traceback 포함) 이 예외 메시지에도 함께 담깁니다. payload 가 `@flow` 로 감싸여 자기 `my_flow` run 을 만든 경우엔 그 run 도 **Failed** 로 남아 [prefect-ko.md §9](../prefect-ko.md#9-prefect-ui) 에서 **어느 단계** 가 깨졌는지 함께 보입니다. 반면 payload 가 **`@flow` 에 진입하기 전에** 죽으면 (import error·`__main__` 예외·잘못된 CLI 인자) payload flow run 자체가 만들어지지 않으므로, dashboard 의 **Runs** 에는 payload flow error 가 **안 보이고 pipeline flow error 만** 보입니다 — 이때 crash 원인은 pipeline run 의 Logs·예외 메시지에서 확인합니다. git·MinIO 등 orchestrator **자신의** 오류도 그대로 raise 되어 pipeline run 이 **Failed** 로 표시됩니다.
  - **이력 자동 저장** — `@flow` 진입 시 Prefect 가 run 의 상태·로그·파라미터를 자동 기록합니다. 지표·모델은 팀원 코드가 MLflow 로 로깅하면 함께 남습니다 — pipeline.py 가 Variable `mlflow_tracking_uri` 를 `MLFLOW_TRACKING_URI` env 로 넘기므로 payload 는 그 tracking 서버로 로깅합니다 (없으면 로컬 `./mlruns` 로 빠지니 `mlflow_tracking_uri` Variable 을 등록해야 대시보드에 뜹니다). 마찬가지로 블록의 `postgresql_optuna` 비밀 + Variable `postgresql_host_port` 로 DSN 을 조립해 `POSTGRESQL_OPTUNA_DSN` env 로 넘기므로, Optuna 를 쓰는 payload 는 공유 postgres study 에 연결합니다 ([prefect-ko.md Appendix G](../prefect-ko.md#appendix-g-prefect-task)).

  [§4](#4-deployment) 의 deployment 가 entrypoint 를 **`pipeline.py:pipeline`** 로 가리킵니다. 이 문자열은 server 의 deployment 레코드 (`prefect` DB) 에 저장되고, worker 가 띄운 컨테이너 안에서 Prefect 런타임이 이미지 작업 디렉터리 (`/work`, `Dockerfile.pipeline_flow` 가 `pipeline.py` 를 COPY 한 곳) 기준으로 `pipeline.py` 를 import 해 콜론 뒤 **`@flow` 함수 `pipeline`** 을 run 파라미터 (`git_repo`·`git_commit_hash`·`minio_key`·`minio_bucket`·`submitter`·`prefect_block`·`payload`) 와 함께 호출합니다. 그래서 deployment entrypoint 가 곧 이 `pipeline.py` 입니다.

  `pipeline` 함수에 전달한 run 파라미터 **값** 은 **trigger 할 때** 지정합니다 — trigger 주체는 보통 **팀원** (또는 스케줄·automation) 입니다. 팀원이 자기 머신·CI 에서 CLI `prefect deployment run "pipeline/high_deployment" -p git_repo=… -p git_commit_hash=… -p minio_key=… -p submitter=… -p prefect_block=…` 을 실행하거나 (CLI 는 [prefect-ko.md Appendix B](../prefect-ko.md#appendix-b-prefect-cli)), server UI 의 Run 폼, 스케줄·automation, 또는 `run_deployment(name, parameters={…})` 로 ([prefect-ko.md §8.2](../prefect-ko.md#82-python-sdk)) trigger 합니다.

  `pipeline.py` 가 **`pipeline_flow` 컨테이너 안에서** run 마다 만드는 폴더 구조입니다 (끝나면 통째로 삭제 — 컨테이너 자체가 일시적이라 함께 사라집니다).

  ```text
  /tmp/run-<rand>/                 # per-run temp dir (base; removed after the run)
  ├─ repo/                         # git init + fetch --depth 1 origin <git_commit_hash> (shallow git db)
  ├─ script/                       # git worktree add --detach script <git_commit_hash> (clean worktree at the commit)
  │  ├─ my_flow.py                 # payload — my entry (run: python my_flow.py --data-folder ../data ...)
  │  └─ ...                        # the rest of my repo at <git_commit_hash>
  └─ data/                         # MinIO download target (bucket/key → here)
     └─ <object>                   # files or folders/files
  ```

  - **팀원별 repo** — `git_repo` 가 **flow 파라미터** 라 deployment 마다 다른 repo 를 기본값으로 등록할 수 있습니다. 팀원은 각자 repo·커밋을 쓰고, run 마다 사설 `script/` 에 펼쳐져 서로 간섭하지 않습니다. Prefect 가 `git_repo`·`git_commit_hash` 을 run 파라미터로 자동 기록해 재현·lineage 가 남습니다.
  - **데이터 준비** — `pipeline.py` 가 MinIO 에서 `minio_bucket`/`minio_key` 객체를 `data/` 로 미리 내려받고 `--data-folder` 로 경로를 넘깁니다. 접속 자격증명 (그 블록의 `minio` 섹션) 은 [prefect-ko.md §7](../prefect-ko.md#7-credentials) 의 Credential Blocks 로 받습니다. 팀원 코드는 자격증명·다운로드를 각자 짤 필요 없이 `--data-folder` 폴더의 파일을 읽기만 하면 됩니다 (`pipeline.py` 가 `boto3` 로 받으므로 flow image 에 `boto3` 가 있어야 합니다 — [§3](#3-image)).

---

## Appendix A. Terminology

- **base job template**: pool 이 띄우는 flow 컨테이너의 공통 설정 (image · env · network · 메모리 상한 등) 입니다.
- **deployment**: flow 를 어떤 work pool 과 parameter 로 실행할지 묶어 server DB (`prefect`) 에 저장한 레코드입니다.
- **entrypoint**: deployment 가 실행할 flow 를 `<file>:<@flow function>` 으로 가리키는 문자열입니다 (예: `pipeline.py:pipeline`).
- **flow image**: Pipeline Flow 컨테이너를 띄우는 image 입니다. deployment 의 `image` (없으면 base job template 의 `image` 기본값) 가 가리키며, 이 stack 에서는 `pipeline-flow:latest` 입니다.
- **Host**: 모든 컨테이너 (server · worker · pipeline_flow · postgres · minio · mlflow) 가 올라가는 한 대의 컴퓨터입니다.
- **Pipeline Flow**: worker 가 job 마다 띄우는 일시적 실행 컨테이너입니다. 받은 repo · commit 을 shallow `git fetch` 로 펼친 뒤 코드를 실행하고 끝나면 파괴됩니다.
- **registry**: image 를 보관하고 push 와 pull 을 받는 service 입니다.
- **work pool**: job 이 대기하는 큐이자 실행 방식 (type) 의 정의입니다. server 안의 메타데이터이며 컨테이너가 아닙니다.

## Appendix B. requirements.txt

flow image 에 설치하는 파이썬 의존성 목록입니다 ([§3](#3-image)). 팀 소스는 이미지에 굽지 않고 런타임에 git worktree 로 받으므로 여기에는 라이브러리만 고정합니다 (base: `python:3.11.15`). 카테고리로 나눠 두고 버전은 `numpy` 기준에 맞춥니다.

```text
# rev. 12
# Python dependencies for the shared team Pipeline Flow image (base: python:3.11.15, see Dockerfile).
# The team source is NOT baked; it is fetched into a git worktree at runtime, so only libraries are pinned here.

# WorkFlow
prefect>=3,<4                  # Prefect runtime (flow execution)
pydantic>=2,<3                 # Prefect blocks are pydantic models (SecretDict in pipeline.py); pinned to Prefect 3
boto3==1.34.131                # Object storage (MinIO, S3-compatible) access
psycopg2-binary==2.9.9         # Catalog DB (PostgreSQL) access
mlflow==2.14.1                 # Experiment tracking / model registry

# --- Core ML / DL: model training / inference frameworks ---
tensorflow==2.17.0             # Deep learning framework
tensorflow-datasets==4.9.9     # Standard dataset loader
keras==3.12.1                  # High-level neural network API
torch==2.9.1                   # Deep learning framework (PyTorch)
scikit-learn==1.4.2            # Classical machine learning algorithms
lightgbm==4.6.0                # Gradient boosting (LightGBM)
catboost==1.2.10               # Gradient boosting (CatBoost)
imbalanced-learn==0.14.1       # Imbalanced-data resampling
statsmodels==0.14.6            # Statistical models / tests
prophet==1.1.5                 # Time-series forecasting
bayesian-optimization==1.4.3   # Bayesian hyperparameter optimization
keract==4.5.1                  # Neural network activation / gradient visualization
optuna==4.8.0                  # Hyperparameter tuning

# --- Numeric / data: array & tabular ops and parallel processing ---
numpy==1.26.4                  # Numeric arrays (baseline version for all dependencies)
scipy==1.13.1                  # Scientific computing
pandas==2.0.3                  # Tabular data processing
numba==0.61.2                  # JIT compilation acceleration
numpy-ext==0.9.9               # numpy helper functions
dask==2025.12.0                # Parallel / distributed computation
h5py==3.15.1                   # HDF5 I/O

# --- Time series: pattern / distance / event detection ---
stumpy==1.14.1                 # Matrix Profile-based motif discovery
pyts==0.13.0                   # Time-series classification / transformation
dtaidistance==2.4.0            # DTW distance (C extension)
fastdtw==0.3.4                 # Approximate DTW
ucrdtw==0.201                  # UCR DTW (C extension)
peakdetect==1.2                # Peak detection

# --- Financial domain data: quotes / filings / calendars / technical indicators ---
dart-fss==0.4.10               # DART electronic disclosure collection
pandas-datareader==0.10.0      # External financial data loader
pandas-market-calendars==4.4.0 # Exchange trading calendars
ta==0.11.0                     # Technical analysis indicators (pure Python)
TA-Lib==0.4.29                 # Technical analysis indicators (requires C library)

# --- Visualization: graphs / plots ---
matplotlib==3.8.4              # Basic plotting
seaborn==0.11.2                # Statistical visualization
plotly==6.6.0                  # Interactive charts
mplcursors==0.6                # matplotlib cursors / tooltips
mpld3==0.5.11                  # matplotlib -> D3 web output
pydot==2.0.0                   # Graph (DOT) rendering
cycler==0.12.1                 # Plot style cycling

# --- File / IO / utils: storage / documents / crypto / general utils ---
pymongo==4.6.3                 # MongoDB driver
openpyxl==3.1.5                # Excel (xlsx) read / write
PyMuPDF==1.27.2.3              # PDF processing
Pillow==12.2.0                 # Image processing
pycryptodome==3.20.0           # Cryptographic algorithms
bcrypt==4.2.0                  # Password hashing
xmltodict==0.12.0              # XML <-> dict conversion
deepdiff==7.0.1                # Object diffing
semver==3.0.4                  # Semantic version handling
lockfile==0.12.2               # File locking
click==8.4.2                   # CLI building
rich==15.0.0                   # Terminal formatted output
tqdm==4.68.3                   # Progress bars
psutil==7.2.2                  # System / process info
packaging==24.2                # Version / package metadata handling
python-dateutil==2.9.0.post0   # Date parsing / arithmetic
pytz==2024.2                   # Timezone data
tzlocal==5.4.3                 # Local timezone detection
typing-extensions==4.15.0      # Type hint backport
protobuf==4.25.9               # Serialization (TensorFlow dependency)
pyarrow==15.0.2                # parquet I/O; mlflow 2.14.1 requires pyarrow<16
```

## Appendix C. Mounting a Remote Data Folder

같은 LAN 의 remote Ubuntu 머신에 있는 data 폴더를 worker 호스트의 docker 에 **NFS 로 mount** 해, `pipeline_flow` 컨테이너가 MinIO 다운로드 없이 그 폴더를 직접 읽게 하는 방법입니다. payload 는 `--data-folder` 로 경로만 받으므로 (`pipeline.py` [§5](#5-pipelinepy)) 다운로드든 mount 든 **무변경** 입니다.

**1) 데이터 호스트 (remote Ubuntu) — NFS export.** 폴더를 LAN 서브넷에 읽기전용으로 내보냅니다.

```bash
# on the data host (e.g. <DATA_HOST_IP>)
sudo apt-get install -y nfs-kernel-server
sudo mkdir -p /srv/datasets
# export read-only to the LAN subnet
echo "/srv/datasets <LAN_SUBNET>(ro,sync,no_subtree_check)" | sudo tee -a /etc/exports
sudo exportfs -ra
sudo systemctl enable --now nfs-kernel-server
```

**2) worker 호스트 — export 를 mount.** 두 방식 중 하나.

```bash
# option A: mount on the host, then bind-mount into the container (step 3)
sudo apt-get install -y nfs-common
sudo mkdir -p /mnt/datasets
sudo mount -t nfs <DATA_HOST_IP>:/srv/datasets /mnt/datasets        # ad-hoc
echo "<DATA_HOST_IP>:/srv/datasets /mnt/datasets nfs ro,_netdev 0 0" | sudo tee -a /etc/fstab   # persistent

# option B: a docker NFS volume (no host mount needed)
docker volume create --driver local \
  --opt type=nfs --opt o=addr=<DATA_HOST_IP>,ro \
  --opt device=:/srv/datasets datasets_nfs
```

**3) pool base job template 에 `volumes` 추가.** worker 가 띄우는 모든 `pipeline_flow` 컨테이너에 마운트를 겁니다 (docker-pool-template-*.json 의 job 변수 → register_pool 재실행). option A 는 호스트 경로, option B 는 볼륨 이름.

```json
"volumes": ["/mnt/datasets:/datasets:ro"]
```

**4) pipeline.py — 다운로드 대신 마운트 경로 사용.** MinIO 다운로드 블록을 마운트 하위 경로로 바꿉니다.

```python
# instead of downloading from MinIO, point at the mounted folder
data = Path("/datasets") / minio_key
```

- **읽기전용 (`ro`) 권장** — 여러 run 이 공유하는 불변 데이터. 각 run 의 쓰기 산출물은 컨테이너 내부 임시 경로로.
- **다중 머신** — worker 가 여러 대면 **모든 호스트에 같은 mount·같은 컨테이너 경로** (`/datasets`) 여야 payload 가 어디서 뜨든 동일하게 읽습니다.
- **lineage** — `minio_key` 를 경로 키로 재사용하면 "어느 데이터" 기록이 유지됩니다.
- **Windows/Docker Desktop worker** 라면 NFS 대신 **SMB/CIFS** 가 편합니다 (대안: SSHFS·CIFS). 권한은 컨테이너 안에서 읽기 가능한 UID/GID 인지 확인합니다.

## Appendix D. push_flow_image.sh

build 하는 machine 에서 flow image 를 여러 CPU architecture 로 build 해 registry 에 올리는 script 입니다 ([§3](#3-image)).

```bash
#!/usr/bin/env bash
# push_flow_image.sh — build the Pipeline Flow image (flow image) for several CPU architectures and push it.
# __version__ = "0.0.0"  # Semantic Versioning:  Version = Major.Minor.Patch
# Author: yRocket
#
# Builds Dockerfile.pipeline_flow as one multi-arch image <registry>/pipeline-flow:<tag> and pushes it, so every
# worker machine (amd64 PC, arm64 Mac) pulls its own variant for each flow run. The registry defaults to
# IMAGE_REGISTRY of ../docker-compose.env (else the _example), the same value register_pool.sh prefixes to the
# pool templates' image.default (pipeline-flow:latest).
#
#   ./push_flow_image.sh                                    # registry = IMAGE_REGISTRY of ../docker-compose.env
#   ./push_flow_image.sh --registry localhost:12357         # on the registry machine itself
#   ./push_flow_image.sh --platform linux/arm64             # one architecture only
#
# A multi-arch build needs the containerd image store (Docker Desktop: Settings > General > "Use containerd for
# pulling and storing images") or a docker-container buildx builder. The non-native variant builds under emulation
# and compiles C libraries (TA-Lib), so it takes much longer than the native one. The final tag check reads the
# HTTP API of a plain registry:2 container.
#
set -euo pipefail

IMAGE_NAME="pipeline-flow"               # the bare name the pool templates' image.default holds
REGISTRY=""                              # <host>:<port>; empty = IMAGE_REGISTRY of the env file
PLATFORM="linux/amd64,linux/arm64"       # CPU architectures of the worker machines
TAG="latest"

usage() { echo "Usage: $0 [--registry <host:port>] [--platform <list>] [--tag <tag>]" >&2; }

while [ $# -gt 0 ]; do
    case "$1" in
        --registry|--platform|--tag)
            # a missing value would make 'shift 2' fail silently under set -e
            [ $# -ge 2 ] || { echo "$1 needs a value." >&2; usage; exit 1; }
            case "$1" in
                --registry) REGISTRY="$2" ;;
                --platform) PLATFORM="$2" ;;
                --tag)      TAG="$2" ;;
            esac
            shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

cd "$(dirname "$0")"   # the Dockerfile, its COPY sources and ../docker-compose.env are relative to this folder
for f in Dockerfile.pipeline_flow requirements.txt pipeline.py; do
    [ -f "$f" ] || { echo "$f not found in $(pwd); the build copies it into the image." >&2; exit 1; }
done

if [ -z "$REGISTRY" ]; then
    ENV_FILE="../docker-compose.env"
    [ -f "$ENV_FILE" ] || ENV_FILE="../docker-compose.env_example"
    [ -f "$ENV_FILE" ] || { echo "env file not found: $ENV_FILE" >&2; exit 1; }
    REGISTRY="$(sed -n 's/^IMAGE_REGISTRY=//p' "$ENV_FILE" | tail -n 1 | tr -d '\r')"
    REGISTRY_SOURCE="IMAGE_REGISTRY in $ENV_FILE"
else
    REGISTRY_SOURCE="--registry"
fi
if [ -z "$REGISTRY" ] || [[ "$REGISTRY" == *"<"* ]] || [[ "$REGISTRY" == */* ]]; then
    echo "Registry missing, a placeholder or not <host>:<port> (got '$REGISTRY' from $REGISTRY_SOURCE)." >&2
    echo "Set IMAGE_REGISTRY in ../docker-compose.env or pass --registry <host:port>." >&2
    exit 1
fi
if [ -z "$PLATFORM" ] || [ -z "$TAG" ]; then
    echo "--platform and --tag need non-empty values." >&2
    exit 1
fi
if [ "$TAG" != "latest" ]; then
    # register_pool.sh points the pools at pipeline-flow:latest; another tag is used only by a deployment that names it
    echo "push_flow_image.sh: NOTE: pool templates use tag 'latest'; '$TAG' runs only where a deployment names it." >&2
fi

command -v docker >/dev/null 2>&1 || { echo "docker not found on PATH." >&2; exit 1; }
docker buildx version >/dev/null 2>&1 || { echo "docker buildx is required (Docker Desktop ships it)." >&2; exit 1; }

REF="$REGISTRY/$IMAGE_NAME:$TAG"
echo "Building $REF for $PLATFORM"
if ! docker buildx build --platform "$PLATFORM" -f Dockerfile.pipeline_flow -t "$REF" --push .; then
    echo "push_flow_image.sh: ERROR: build or push of $REF failed." >&2
    echo "  A multi-arch build needs the containerd image store or a docker-container builder;" >&2
    echo "  an HTTP registry other than localhost needs 'insecure-registries' in this docker daemon." >&2
    exit 1
fi

# Confirm the registry now lists the tag, so a push that went elsewhere does not pass as done.
if command -v curl >/dev/null 2>&1; then
    tags="$(curl -s -m 10 "http://$REGISTRY/v2/$IMAGE_NAME/tags/list" || true)"
    if ! printf '%s' "$tags" | grep -q "\"$TAG\""; then
        echo "push_flow_image.sh: ERROR: pushed $REF, but the registry does not list tag '$TAG' (got: '$tags')." >&2
        exit 1
    fi
    echo "Registry lists $IMAGE_NAME tags: $tags"
else
    echo "push_flow_image.sh: WARNING: curl not found; the registry's tag list was not checked." >&2
fi
echo "pushed $REF"
```
