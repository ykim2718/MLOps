> ⚠️ **This is an auto-synced copy.** Do not edit here.

# Docker Network

<sub>rev. 2</sub>

이 스택의 컨테이너 간 통신에 쓰는 docker network 를 정리합니다. 기본은 **Local Network** (호스트별 bridge + 크로스머신은 LAN IP) 이고, 전 노드가 LAN-native Linux 인 경우에 한해 **Swarm Overlay Network** 로 docker 서비스 이름을 머신 너머까지 통일할 수 있습니다.

## 1. Local Network

이 스택의 기본 방식입니다. 각 호스트에 로컬 bridge network `mlops` 를 두고, 접근 방식은 컨테이너가 **같은 머신**인지 **다른 머신**인지에 따라 갈립니다 (**LAN IP 모델**):

- **같은 머신** → docker **서비스 이름** (`prefect_server`·`minio`·`postgres`·`mlflow`). 같은 호스트의 `mlops` 에 붙은 컨테이너끼리 이름으로 바로 찾습니다.
- **다른 머신** → 그 서비스가 있는 **호스트의 LAN IP + 게시 포트** (예: `http://192.168.0.13:4200/api`, `<MinIO 호스트 IP>:9000`).

왜 다른 머신은 이름이 안 되나 — 기본 `bridge` network 는 **호스트 로컬**이라, 각 머신에 같은 이름 `mlops` 를 만들어도 **이름만 같을 뿐 별개의 network** 입니다. docker 서비스 이름은 그 호스트의 network 안에서만 해석되므로 **머신을 넘지 못합니다.** 그래서 크로스머신 접근은 LAN IP 로 합니다. 이름을 머신 너머까지 쓰려면 [§2 Swarm Overlay Network](#2-swarm-overlay-network) 가 필요하지만, 전 노드가 LAN-native Linux 여야 합니다.

### Create the Network

  컨테이너를 띄울 **각 호스트**에서 로컬 bridge `mlops` 를 한 번 만듭니다 (이미 있으면 무해).

  ```bash
  docker network create mlops        # local bridge; run once per host
  docker network ls | grep mlops     # DRIVER = bridge, SCOPE = local
  ```

  각 서비스의 compose 는 이 `mlops` 를 external network 로 참조합니다. 같은 호스트의 컨테이너는 **서비스 이름**으로, 다른 호스트의 서비스는 **LAN IP** 로 접근합니다 (`PREFECT_API_URL`·credential endpoint 등에서 지정).

## 2. Swarm Overlay Network

여러 머신에서 LAN IP 대신 **docker 서비스 이름을 그대로** 쓰고 싶으면, **Docker Swarm 의 overlay network** 로 전 호스트를 하나의 가상 network 로 묶습니다. [§1 Local Network](#1-local-network) 의 LAN IP 모델 대신 쓰는 **멀티 머신·all-Linux 대안** 입니다.

> ⚠️ **제약** — overlay 데이터플레인 (VXLAN) 은 각 노드가 **LAN 에 직접 붙은 native Linux Docker** 일 때만 흐릅니다. **Windows/macOS 의 Docker Desktop 노드는 VM (WSL2 등) NAT 뒤라 크로스호스트 overlay 가 동작하지 않습니다** — 그 경우 §1 의 LAN IP 모델을 씁니다. overlay 로 가려면 모든 노드가 LAN-native Linux (베어메탈 또는 bridged Linux VM) 여야 합니다.

세 단계로 구성합니다 — **Firewall** (노드 간 포트) · **Swarm Configuration** (매니저·worker) · **Overlay Network** (attachable overlay 생성). 성공하면 각 compose 는 `mlops` 를 external network 로 참조하고, 주소를 LAN IP 대신 **서비스 이름** 으로 통일할 수 있습니다.

### Firewall

  Swarm 노드끼리 아래 포트가 서로 열려 있어야 합니다.

  | Port | Protocol | Purpose |
  |------|----------|---------|
  | 2377 | tcp | cluster management (manager only) |
  | 7946 | tcp + udp | node-to-node communication (gossip / discovery) |
  | 4789 | udp | overlay data plane (VXLAN) |

  보통 Swarm join 뒤 `docker node ls` (Swarm Configuration) 에 노드가 모두 보이면 방화벽은 문제없는 것입니다. worker 가 안 보이거나 join 이 막히면, 각 노드의 **ufw** 로 위 포트를 엽니다.

  ```bash
  # check whether ufw is active (inactive -> not blocking, no action needed)
  sudo ufw status verbose

  # if active, open the swarm ports
  #   manager (prefect_server machine): 2377 + 7946 + 4789
  sudo ufw allow 2377/tcp        # cluster management (manager only)
  sudo ufw allow 7946            # node-to-node gossip (tcp + udp)
  sudo ufw allow 4789/udp        # overlay data plane (VXLAN)
  #   worker machines: 7946 + 4789 only (2377 not needed inbound)

  # confirm the rules landed
  sudo ufw status numbered       # 2377/tcp, 7946, 4789/udp should show ALLOW
  ```

  > ufw 를 새로 켤 때는 잠금 방지를 위해 SSH 부터 허용합니다 — `sudo ufw allow OpenSSH` 후 `sudo ufw enable`.

### Swarm Configuration

  한 머신 (예: prefect_server machine) 을 **매니저**로 초기화하고, 나머지 머신 (prefect_worker machine · backing service machine 들) 을 **worker**로 조인합니다.

  ```bash
  # on the manager (e.g. the prefect_server machine)
  docker swarm init --advertise-addr <manager LAN IP>
  #   -> prints a "docker swarm join --token <TOKEN> <manager IP>:2377" command

  # on each worker machine — run that printed join command
  docker swarm join --token <TOKEN> <manager IP>:2377
  ```

  검증 — 매니저에서 모든 노드가 `Ready` 로 보이는지 확인합니다.

  ```bash
  docker node ls          # manager (Leader) + every joined worker, STATUS = Ready
  ```

  > ⚠️ worker 가 **Docker Desktop (Windows/macOS)** 이면 `Ready` 로 보여도 overlay 데이터플레인이 안 흘러, 아래 Overlay Network 의 관통 테스트에서 실패합니다 (`context deadline exceeded`). all-Linux 노드여야 합니다.

### Overlay Network

  전 노드가 공유할 **attachable overlay** network 를 매니저에서 한 번 만듭니다. `--attachable` 이라야 compose / `docker run` 으로 뜨는 **일반 컨테이너** (이 스택은 swarm service 가 아님) 와 worker 가 소켓으로 띄우는 `pipeline_flow` 컨테이너도 붙을 수 있습니다.

  ```bash
  # on the manager
  docker network create --driver overlay --attachable mlops
  ```

  overlay network 는 매니저에서 생성되고, worker 에는 **컨테이너가 처음 attach 될 때** 나타납니다 (그 전에는 worker 의 `docker network ls` 에 안 보여도 정상). 생성 직후 확인은 매니저에서 driver·scope 만 봅니다.

  ```bash
  # on the manager: confirm it is an overlay on the swarm scope
  docker network ls | grep mlops        # DRIVER = overlay, SCOPE = swarm
  ```

  **관통 테스트** — worker 에 테스트 컨테이너를 붙여 매니저에서 이름으로 ping 되면 크로스호스트 데이터플레인이 정상입니다 (이게 통과해야 overlay 를 실제로 쓸 수 있습니다).

  ```bash
  # on a worker: attach a test container to the overlay
  docker run -d --name t1 --network mlops nginx
  # on the manager: resolve + reach it by name across hosts
  docker run --rm --network mlops busybox ping -c2 t1
  #   -> replies => overlay OK.  timeout/'context deadline exceeded' => a node is not LAN-native (e.g. Docker Desktop)
  ```

  성공하면 각 compose 는 `mlops` 를 external network 로 참조하고, 주소를 LAN IP 대신 **서비스 이름** (`prefect_server`·`minio`·`postgres`·`mlflow`) 으로 통일합니다.
