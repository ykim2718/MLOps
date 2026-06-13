# Prefect 스택 리셋 후 재기동 스크립트
#
# 주의: 이 프로젝트(compose)와 무관한 컨테이너(mongo, redis, flask 등)는 건드리지 않는다.

# 0) compose 스택이 떠 있으면 깔끔히 내린다 (compose 컨테이너는 이걸로 관리, 볼륨은 유지)
docker compose down

# 1) 과거에 '단독'으로 띄운 잔재 컨테이너만 정리 (compose 포트와 충돌하는 것들)
#    - minio          : 예전에 수동으로 띄운 MinIO (9000/9001 점유)
#    - prefect-server : 삭제된 setup_prefect.ps1 이 만들던 서버 (4200 점유)
foreach ($name in 'minio', 'prefect-server') {
    if (docker ps -aq --filter "name=^$name$") {
        Write-Host "Removing leftover standalone container: $name" -ForegroundColor Yellow
        docker stop $name | Out-Null
        docker rm   $name | Out-Null
    }
}

# 2) 전체 스택 기동 (postgres + minio + mlflow + server + worker)
docker compose up -d
