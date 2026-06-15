# Prefect 기동 스크립트 — 역할(server/worker)을 골라 해당 compose 파일을 띄운다.
#
#   .\set_docker.ps1                 # 기본값: server (제어 노드, 머신 A)
#   .\set_docker.ps1 -Role worker    # worker (워커 노드, 머신 B)
#
# server 는 제어 노드의 다른 서비스(postgres/minio/mlflow)와 서비스명으로 통신하므로 공유 네트워크 mlops 가 필요하다.
# worker 는 다른 컴퓨터에서 CONTROL_PLANE_HOST(머신 A IP)로 접속하므로 mlops 네트워크가 필요 없다.
param(
    [ValidateSet('server', 'worker')]
    [string]$Role = 'server'
)

$compose = "docker-compose.$Role.yml"

if ($Role -eq 'server') {
    # 공유 네트워크 mlops 가 없으면 1회 만든다(이미 있으면 그대로 둔다).
    docker network inspect mlops *> $null
    if ($LASTEXITCODE -ne 0) { docker network create mlops | Out-Null }
}

# 해당 역할의 compose 스택을 내렸다가(볼륨은 유지) 다시 백그라운드로 띄운다.
docker compose -f $compose down
docker compose -f $compose up -d
