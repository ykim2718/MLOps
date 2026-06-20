# MLflow 컨테이너 기동 스크립트 — 제어 노드(머신 A)에서 실행한다.
#
# MLflow 는 같은 제어 노드의 postgres(backend)와 minio(artifact)에 서비스명으로 접속하므로,
# 그 두 컨테이너가 먼저 떠 있어야 한다(PostgreSQL → MinIO → MLflow 순서 권장).
# 공유 네트워크 mlops 가 없으면 1회 만든다(이미 있으면 그대로 둔다).

docker network inspect mlops *> $null
if ($LASTEXITCODE -ne 0) { docker network create mlops | Out-Null }

# compose 스택을 내렸다가(볼륨은 유지) 다시 백그라운드로 띄운다.
docker compose down
docker compose up -d
