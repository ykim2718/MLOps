# Prefect Docker Registry
Rev. 0 | Created: 2026-10-08 | Updated: 2026-10-08 13:12 CDT

- [1. Purpose](#1-purpose)
- [2. Summary](#2-summary)
- [3. Taxonomy and its Hierarchy](#3-taxonomy-and-its-hierarchy)
  - [3.1 Placement](#31-placement)
- [4. Principle](#4-principle)
  - [4.1 Image Name](#41-image-name)
  - [4.2 Pull Policy](#42-pull-policy)
  - [4.3 Where Image and Policy Are Set](#43-where-image-and-policy-are-set)
  - [4.4 Insecure Registry](#44-insecure-registry)
- [5. Application](#5-application)
  - [5.1 Running a Registry](#51-running-a-registry)
  - [5.2 Pushing an Image](#52-pushing-an-image)
  - [5.3 Registering a Deployment](#53-registering-a-deployment)
  - [5.4 Worker Machine](#54-worker-machine)
  - [5.5 Verification](#55-verification)
  - [5.6 Failure Cases](#56-failure-cases)
- [References](#references)
- [Appendix A. Terminology](#appendix-a-terminology)
- [Appendix B. Registry of This Stack](#appendix-b-registry-of-this-stack)

## 1. Purpose

- **Problem Statement**: docker work pool 의 worker 는 deployment 가 적은 image 를 자기 machine 의 docker daemon 에서 찾으므로, worker machine 이 여럿이면 image 를 machine 마다 build 하거나 복사해야 하고, 같은 tag 로 새로 build 한 image 는 이미 받아 둔 machine 에 반영되지 않는다.
- **Goal**: 실무자의 Prefect Docker Registry Guide 로서, image 를 registry 에 한 번 push 하면 모든 worker machine 이 run 마다 그 image 를 받고, 같은 tag 로 다시 push 한 image 가 다음 run 부터 바로 반영되게 한다.
- **Non-Goal**: image 의 Dockerfile 과 build 내용, TLS 와 인증을 갖춘 registry, Docker Hub 계정 운용은 다루지 않는다.

## 2. Summary

Prefect 가 registry 에 대해 아는 것은 deployment 의 `image` 이름뿐이다. Worker 는 run 마다 자기 machine 의 docker daemon 에 그 이름으로 container 를 요청하고, daemon 이 이름 앞의 `<host>:<port>` 를 registry 주소로 읽어 pull 한다. 새로 push 한 image 가 run 에 반영되는지는 deployment 의 `image_pull_policy` 가 정하며, `Always` 면 run 마다 registry 에 묻고 `IfNotPresent` 면 machine 에 한 번 받은 image 를 계속 쓴다.

Registry 를 쓰는 stack 은 아래 네 단계로 만든다.

1. Registry container 를 한 machine 에 띄우고 그 port 의 inbound 를 연다 ([5.1](#51-running-a-registry)).
2. Build 한 image 를 `localhost:<PORT>/<NAME>:<TAG>` 로 tag 해 push 한다 ([5.2](#52-pushing-an-image)).
3. Deployment 를 `image="<REGISTRY_IP>:<PORT>/<NAME>:<TAG>"`, `job_variables={"image_pull_policy": "Always"}`, `build=False`, `push=False` 로 등록한다 ([5.3](#53-registering-a-deployment)).
4. Worker machine 마다 docker daemon 의 `insecure-registries` 에 `<REGISTRY_IP>:<PORT>` 를 넣고 daemon 을 다시 시작한다 ([5.4](#54-worker-machine)).

네 단계를 적용한 stack 의 상태는 [Appendix B](#appendix-b-registry-of-this-stack) 에 있다.

## 3. Taxonomy and its Hierarchy

Image 가 worker machine 에 오는 길은 세 가지이고, 그 image 를 run 마다 다시 받을지는 pull policy 네 값 가운데 하나가 정한다.

```text
axis 1: where the worker's daemon gets the image
  local build        docker build on every worker machine          no registry, no daemon setting
  HTTP registry      one registry container on the LAN             insecure-registries on every pulling daemon
  HTTPS registry     Docker Hub or a TLS registry                   login or certificate on every pulling daemon

axis 2: image_pull_policy of the deployment (job_variables) or of the pool (base job template)
  Never              local image only; a missing image fails the run
  IfNotPresent       pull once; a later push of the same tag is ignored
  Always             pull on every run; same digest -> no layer download
  IfPossible         try to pull; on failure fall back to the local image

push path                                   pull path (every run, policy Always)
  docker build  <NAME>:<TAG>                  worker  -> daemon: run <REGISTRY_IP>:<PORT>/<NAME>:<TAG>
  docker tag    localhost:<PORT>/<NAME>:<TAG>   daemon  -> registry: manifest of <TAG>
  docker push   ---> registry container        registry -> daemon: only the layers this machine lacks
```

<a id="fig-1"></a>
Fig 1. Image sources, pull policies, push path and pull path

한 단계 내려갈수록 machine 이 늘어도 할 일이 같아지고, 대신 daemon 마다 한 번의 설정이 붙는다. Local build 는 설정이 없지만 machine 마다 build 해야 하고 같은 tag 가 machine 마다 다른 image 를 가리킬 수 있다. HTTP registry 는 push 한 곳 하나가 기준이 되고 pulling daemon 마다 `insecure-registries` 한 줄이 든다. HTTPS registry 는 그 한 줄 대신 인증서나 login 이 들고, LAN 밖에서도 pull 이 된다. Pull policy 는 어느 길에서나 같은 뜻이며, 같은 tag 를 다시 push 하는 운용에서는 `Always` 만 새 image 를 반영한다.

### 3.1 Placement

Table 1. What each image source requires

| Image source   | Image name in the deployment         | On the registry machine     | On every worker machine            |
| :------------: | :----------------------------------: | :-------------------------: | :--------------------------------: |
| local build    | `<NAME>:<TAG>`                       | none                        | `docker build` of the same image   |
| HTTP registry  | `<REGISTRY_IP>:<PORT>/<NAME>:<TAG>`  | registry container, open port | `insecure-registries` + daemon restart |
| HTTPS registry | `<HOST>/<NAME>:<TAG>`                | none                        | `docker login` or a CA certificate |

Table 2. Source and policy by need

| Need                                                   | Source         | Pull policy    | Section                                        |
| :----------------------------------------------------: | :------------: | :------------: | :--------------------------------------------: |
| worker machine 이 하나이고 image 를 그 machine 에서 build | local build    | `IfNotPresent` | [4.2](#42-pull-policy)                         |
| 여러 machine 이 같은 image 를 돌리고 같은 tag 로 갱신     | HTTP registry  | `Always`       | [5.1](#51-running-a-registry) 부터 [5.4](#54-worker-machine) |
| 여러 machine, tag 마다 새 이름 (예: version tag)          | HTTP registry  | `IfNotPresent` | [4.2](#42-pull-policy)                         |
| LAN 밖의 machine 도 pull                                  | HTTPS registry | `Always`       | out of scope                                   |

## 4. Principle

### 4.1 Image Name

Image 이름의 첫 부분이 `<host>:<port>` 꼴이면 docker daemon 은 그 부분을 registry 주소로 읽는다 [[1](#ref-1)]. 그래서 `localhost:<PORT>/<NAME>:<TAG>` 는 registry 를 띄운 machine 에서 push 할 때의 이름이고, `<REGISTRY_IP>:<PORT>/<NAME>:<TAG>` 는 다른 machine 이 같은 repository 를 pull 할 때의 이름이다. 두 이름은 registry 안의 같은 `<NAME>:<TAG>` 를 가리키며, deployment 에는 worker machine 이 닿을 수 있는 쪽인 `<REGISTRY_IP>:<PORT>/...` 를 적는다. Registry 가 없는 `<NAME>:<TAG>` 는 Docker Hub 의 공개 image 이름이거나 그 machine 에만 있는 local image 이름이다.

### 4.2 Pull Policy

`image_pull_policy` 는 worker 가 run container 를 만들기 전에 image 를 받을지를 정하며, 값은 `IfNotPresent`, `Always`, `IfPossible`, `Never` 네 가지이다 [[2](#ref-2)].

- `IfNotPresent` 는 machine 에 그 이름의 image 가 없을 때만 받는다. 같은 tag 를 다시 push 해도 machine 은 처음 받은 image 를 계속 쓴다.
- `Always` 는 run 마다 registry 에 그 tag 의 manifest 를 묻고, digest 가 같으면 layer 를 받지 않는다. Run 마다 더 드는 것은 manifest 조회 하나이고, 새로 push 한 image 는 다음 run 부터 돈다.
- `IfPossible` 은 pull 을 시도하고 실패하면 local image 로 돌아간다 [[2](#ref-2)]. Registry 가 잠시 내려가도 run 이 멈추지 않지만, 그 run 은 이전 image 로 돈다.
- `Never` 는 local image 만 쓰고, 없으면 run 이 실패한다. Registry 없이 machine 마다 build 하는 운용의 값이다.

같은 tag (예: `latest`) 를 계속 갱신하는 운용은 `Always` 를 쓰고, tag 마다 새 이름을 붙이는 운용은 `IfNotPresent` 로도 새 image 가 반영된다.

### 4.3 Where Image and Policy Are Set

`image` 와 `image_pull_policy` 는 work pool 의 base job template 에 기본값으로 있고, deployment 의 `job_variables` 가 그 기본값을 덮는다 [[2](#ref-2)]. Pool template 의 기본값은 그 pool 의 모든 deployment 에 들고, 한 deployment 만 다르게 하려면 그 deployment 의 `job_variables` 에 적는다. `deploy()` 는 기본으로 image 를 build 해 `image` 가 가리키는 registry 에 push 하므로, 이미 push 한 image 를 쓰는 deployment 는 `build=False` 와 `push=False` 를 함께 준다 [[2](#ref-2)].

### 4.4 Insecure Registry

TLS 없이 HTTP 로 서는 registry 는 pull 하는 모든 docker daemon 에 `insecure-registries` 로 등록해야 하고, 등록 뒤 daemon 을 다시 시작한다 [[3](#ref-3)]. 등록이 없으면 daemon 이 HTTPS 로 접속하다 `tls: oversized record received` 로 실패한다 [[3](#ref-3)]. Registry 를 띄운 machine 에서 `localhost:<PORT>` 로 하는 push 는 이 등록 없이 된다. HTTP registry 는 basic authentication 을 붙일 수 없으므로 [[3](#ref-3)], 신뢰하는 LAN 안에서만 쓴다.

## 5. Application

아래 명령에서 `<PORT>` 는 registry container 가 host 에 게시한 port 이고, `<REGISTRY_IP>` 는 그 machine 의 LAN IP 이다.

### 5.1 Running a Registry

Registry 는 `registry` image 의 container 하나이고, image 는 volume 에 남는다.

```yaml
# YAML
name: registry
services:
  registry:
    image: registry:2
    container_name: registry
    ports:
      - "<PORT>:5000"            # push as localhost:<PORT>/<NAME> here, pull as <REGISTRY_IP>:<PORT>/<NAME> elsewhere
    volumes:
      - registry-data:/var/lib/registry
    restart: unless-stopped
volumes:
  registry-data:
```

```bash
docker compose up -d
curl http://localhost:<PORT>/v2/_catalog       # {"repositories":[]} while the registry is empty
```

다른 machine 이 pull 하려면 이 machine 의 방화벽에서 TCP `<PORT>` inbound 를 연다. Registry 는 container 안에서 5000 을 듣고, host 의 다른 service 가 5000 을 쓰면 `<PORT>` 를 다른 수로 둔다.

### 5.2 Pushing an Image

Build 한 image 에 registry 주소가 든 이름을 붙여 push 한다 [[1](#ref-1)].

```bash
docker build -t <NAME>:<TAG> .
docker tag  <NAME>:<TAG> localhost:<PORT>/<NAME>:<TAG>
docker push localhost:<PORT>/<NAME>:<TAG>
curl http://localhost:<PORT>/v2/<NAME>/tags/list   # {"name":"<NAME>","tags":["<TAG>"]}
```

- 같은 tag 로 다시 push 하면 registry 의 그 tag 가 새 digest 를 가리키고, 바뀐 layer 만 올라간다.
- Push 가 실패해도 registry 에는 이전 image 가 남으므로, `Always` 로 도는 deployment 는 이전 image 로 계속 돈다.

### 5.3 Registering a Deployment

Deployment 는 registry 주소가 든 `image` 와 `Always` policy 로 등록하고, build 와 push 는 끈다 [[2](#ref-2)].

```python
# Python
from prefect import flow

@flow
def my_flow():
    ...

my_flow.deploy(
    name="my-deployment",
    work_pool_name="<POOL>",
    image="<REGISTRY_IP>:<PORT>/<NAME>:<TAG>",     # the name every worker machine can pull
    build=False, push=False,                      # the image is already in the registry
    job_variables={"image_pull_policy": "Always"},  # pool templates default to IfNotPresent
)
```

- `image` 에는 `localhost:<PORT>/...` 를 적지 않는다. Worker machine 의 daemon 이 그 이름을 자기 machine 의 registry 로 읽는다.
- `build=False` 와 `push=False` 가 없으면 `deploy()` 가 이 machine 에서 image 를 build 해 push 하려 한다 [[2](#ref-2)].
- 등록 뒤 `prefect deployment inspect "<FLOW>/<DEPLOYMENT>"` 의 `job_variables` 에 `image` 와 `image_pull_policy` 가 보인다.

### 5.4 Worker Machine

Worker machine 의 docker daemon 에 registry 를 insecure 로 등록하고 daemon 을 다시 시작한다 [[3](#ref-3)].

```json
// /etc/docker/daemon.json on Linux; Docker Desktop: Settings > Docker Engine
{
  "insecure-registries": ["<REGISTRY_IP>:<PORT>"]
}
```

```bash
sudo systemctl restart docker                                   # Linux; Docker Desktop restarts from its settings
docker info --format '{{json .RegistryConfig.IndexConfigs}}'    # the registry appears with "Secure":false
docker pull <REGISTRY_IP>:<PORT>/<NAME>:<TAG>                    # a manual pull proves the path before the first run
```

Worker container 자체는 설정이 없다. Worker 는 host 의 docker socket 으로 host daemon 에 container 를 요청하므로, pull 은 host daemon 의 설정으로 된다.

### 5.5 Verification

Registry 에 image 가 있고, deployment 가 그 이름을 가리키고, worker machine 이 pull 하는지를 차례로 본다.

```bash
curl http://<REGISTRY_IP>:<PORT>/v2/_catalog                       # repositories in the registry
curl http://<REGISTRY_IP>:<PORT>/v2/<NAME>/tags/list                # tags of one repository
prefect deployment inspect "<FLOW>/<DEPLOYMENT>"                    # job_variables.image, image_pull_policy
docker images <REGISTRY_IP>:<PORT>/<NAME>                           # on a worker machine, after a run
```

`Always` 로 도는 deployment 는 새로 push 한 뒤의 첫 run 이 끝나면 worker machine 의 `docker images` 가 보이는 image ID 가 새 image 의 것으로 바뀐다.

### 5.6 Failure Cases

Table 3. Symptom, cause and fix

| Symptom                                                        | Cause                                                      | Fix                                              |
| :------------------------------------------------------------: | :--------------------------------------------------------: | :----------------------------------------------: |
| run 이 `tls: oversized record received` 로 실패                 | worker machine 의 daemon 에 `insecure-registries` 가 없음    | [5.4](#54-worker-machine)                         |
| run 이 image 를 찾지 못해 실패                                    | deployment 의 `image` 이름이 push 한 이름과 다름              | `tags/list` 로 대조, [5.2](#52-pushing-an-image)  |
| 새로 push 했는데 run 이 이전 image 로 돎                          | `image_pull_policy` 가 `IfNotPresent`                       | `Always` 로 재등록, [5.3](#53-registering-a-deployment) |
| registry 를 띄운 machine 에서만 run 이 됨                         | `image` 가 `localhost:<PORT>/...`                           | `<REGISTRY_IP>:<PORT>/...` 로 재등록, [4.1](#41-image-name) |
| `deploy()` 가 build 를 시작하거나 push 에서 실패                  | `build=False`, `push=False` 가 없음                          | [5.3](#53-registering-a-deployment)               |
| push 가 `connection refused`                                    | registry container 가 내려감                                 | `docker compose up -d`, [5.1](#51-running-a-registry) |

## References

<a id="ref-1"></a>
[1] CNCF Distribution. [Deploy a registry server](https://distribution.github.io/distribution/about/deploying/). Distribution documentation.<br>
<a id="ref-2"></a>
[2] Prefect. [Run flows in Docker containers](https://docs.prefect.io/v3/how-to-guides/deployment_infra/docker). Prefect 3 documentation, How-to guides.<br>
<a id="ref-3"></a>
[3] CNCF Distribution. [Test an insecure registry](https://distribution.github.io/distribution/about/insecure/). Distribution documentation.

---

## Appendix A. Terminology

- **base job template**: work pool 이 띄우는 모든 run container 의 공통 설정. `image` 와 `image_pull_policy` 의 기본값이 여기에 있다.
- **digest**: image manifest 의 내용 hash. 같은 tag 라도 다시 push 하면 digest 가 바뀐다.
- **image_pull_policy**: run container 를 만들기 전에 image 를 받을지 정하는 값. `IfNotPresent`, `Always`, `IfPossible`, `Never`.
- **insecure registry**: TLS 없이 HTTP 로 서는 registry. Pull 하는 daemon 마다 `insecure-registries` 에 등록해야 한다.
- **job_variables**: deployment 가 base job template 의 기본값을 덮어쓰는 값들.
- **registry**: image 를 repository 와 tag 로 보관하고 HTTP API 로 push 와 pull 을 받는 service.
- **repository**: registry 안에서 한 image 이름이 갖는 tag 들의 집합.
- **work pool**: Prefect server 에 등록된, run 을 모아 두고 실행 방식을 정하는 단위. Docker type pool 의 run 은 worker 가 container 로 실행한다.
- **worker**: work pool 을 polling 하다가 run 을 가져가 host 의 docker daemon 에 container 를 요청하는 process.

## Appendix B. Registry of This Stack

이 stack 은 registry 를 띄운 machine 에서 image 를 build 해 push 하고, 두 work pool 의 worker 가 run 마다 그 image 를 받는다.

- Registry 는 `registry:2` container 로 host port `12357` 에 있고, repository `yrocket-finance` 의 tag `latest` 하나를 갖는다. 5000 은 같은 machine 의 MLflow 가 쓰므로 12357 을 골랐다.
- Build script 는 image 를 `localhost:12357/yrocket-finance:latest` 로 tag 해 push 하고, push 가 실패하면 exit code 1 로 끝나 pool 의 run 이 이전 image 로 도는 것을 알린다.
- Deployment 를 등록하는 serve container 는 환경 변수 `POOL_IMAGE=<REGISTRY_IP>:12357/yrocket-finance:latest` 를 받아, pool deployment 를 `image=POOL_IMAGE`, `build=False`, `push=False`, `job_variables` 의 `image_pull_policy="Always"` 로 등록한다.
- Worker machine 의 docker daemon 은 `insecure-registries` 에 `<REGISTRY_IP>:12357` 을 갖는다. 그 machine 의 `docker images` 에 남은 `<REGISTRY_IP>:12357/yrocket-finance:latest` 는 지난 pull 의 cache 이며, `Always` 이므로 다음 run 이 registry 의 최신 digest 로 바꾼다.
- Pool template 의 `image_pull_policy` 기본값은 `IfNotPresent` 이고, deployment 의 `job_variables` 가 `Always` 로 덮는다 ([4.3](#43-where-image-and-policy-are-set)).
