# Prefect 기동 스크립트 — 역할(server/worker)의 compose 를 띄운다.
#
# worker compose 의 command 안 bash 는 docker compose up 시점에 ${CREATE_POOL}/${WORK_POOL}/${WORKER_LIMIT}
# 를 "이 셸의 환경변수"에서 보간(compose interpolation)한다. 그래서 up 전에 그 값들을 세션 env 로 올린다.
# (CONTROL_NODE_HOST·POSTGRES_*·MINIO_* 등은 컨테이너가 env_file=docker-compose.env 로 직접 읽으므로 여기서 설정하지 않는다.)
#
#   .\set_docker.ps1                                                  # server (Control Node)
#   .\set_docker.ps1 -Role worker                                     # 첫 worker — default pool
#   .\set_docker.ps1 -Role worker -CreatePool false -WorkPool pool-1  # 추가 worker — 전용 pool
#
param(
    [ValidateSet('server', 'worker')]
    [string]$Role = 'server',
    [ValidateSet('true', 'false')]
    [string]$CreatePool = 'true',     # true=pool 생성 후 worker 시작(첫 worker), false=생성 건너뜀(추가 worker)
    [string]$WorkPool = 'default',    # worker 가 폴링할 work pool (전용이면 pool-1 등)
    [int]$WorkerLimit = 8             # 이 worker 의 동시 실행 상한
)

$ErrorActionPreference = "Stop"

# worker compose 의 ${...} 보간용 — 현재 셸 환경변수로 올린다(이번 docker compose up 에 적용).
$env:CREATE_POOL  = $CreatePool
$env:WORK_POOL    = $WorkPool
$env:WORKER_LIMIT = "$WorkerLimit"

$compose = "docker-compose.$Role.yml"

# server 는 다른 서비스(postgres/minio/mlflow)와 서비스명으로 통신하므로 공유 네트워크 mlops 가 필요하다(없으면 1회 생성).
if ($Role -eq 'server') {
    docker network inspect mlops *> $null
    if ($LASTEXITCODE -ne 0) { docker network create mlops | Out-Null }
}

# 해당 역할의 compose 스택을 내렸다가(볼륨은 유지) 다시 백그라운드로 띄운다.
docker compose -f $compose down
docker compose -f $compose up -d
