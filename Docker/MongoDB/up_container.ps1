# mlops 네트워크가 없으면 생성
docker network inspect mlops *> $null
if ($LASTEXITCODE -ne 0) { docker network create mlops | Out-Null }

# compose 스택을 내렸다가(볼륨은 유지) 다시 백그라운드로 띄운다.
docker compose down
docker compose up -d