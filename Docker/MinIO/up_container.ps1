param(
    [string]$ProjectName = $null
)

# mlops 네트워크가 없으면 생성
docker network inspect mlops *> $null
if ($LASTEXITCODE -ne 0) { docker network create mlops | Out-Null }

# $ProjectName이 있으면 지정된 이름으로, 없으면 기본 이름으로 실행됩니다.
docker compose -p "$ProjectName" down
docker compose -p "$ProjectName" up -d