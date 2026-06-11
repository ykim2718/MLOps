# 2026.6.4

$imageName = "prefecthq/prefect:3-latest"
$containerName = "prefect-server"

# 1. 로컬에 해당 Docker 이미지가 이미 존재하는지 확인
$imageExists = docker images -q $imageName

if (-not $imageExists) {
    Write-Host "Local image not found. Pulling $imageName..." -ForegroundColor Cyan
    docker pull $imageName
} else {
    Write-Host "Image '$imageName' already exists locally. Skipping pull." -ForegroundColor Green
}

# 2. 동일한 이름의 기존 컨테이너가 있다면 먼저 중지 및 삭제 (에러 방지)
$existingContainer = docker ps -a -q --filter "name=$containerName"
if ($existingContainer) {
    Write-Host "Stopping and removing existing '$containerName' container..." -ForegroundColor Yellow
    docker stop $containerName | Out-Null
    docker rm $containerName | Out-Null
}

# 3. Prefect 서버 컨테이너 실행
Write-Host "Starting Prefect Server..." -ForegroundColor Green
docker run -d -p 4200:4200 --name $containerName $imageName -- prefect server start --host 0.0.0.0

Write-Host "Prefect Server is running! Access via http://localhost:4200" -ForegroundColor Green
