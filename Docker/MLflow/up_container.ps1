param(
    [string]$ProjectName = $null
)

# mlops 네트워크가 없으면 생성
docker network inspect mlops *> $null
if ($LASTEXITCODE -ne 0) { docker network create mlops | Out-Null }

# $ProjectName 입력 여부에 따라 명령어를 분기합니다.
if ($ProjectName) {
    # 프로젝트 이름을 지정했을 때
    docker compose -p "$ProjectName" down
    docker compose -p "$ProjectName" up -d
} else {
    # 프로젝트 이름을 지정을 안 했을 때 (폴더명이 기본 프로젝트명이 됨)
    docker compose down
    docker compose up -d
}