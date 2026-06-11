# 1. API 주소 설정 (최초 1회 설정용이지만 매번 실행해도 무방함)
Write-Host "Configuring Prefect API URL..." -ForegroundColor Cyan
prefect config set PREFECT_API_URL="http://localhost:4200/api"

# 2. 팀원들의 AI 학습을 대신 처리해 줄 일꾼(Worker) 실행
Write-Host "Starting Prefect Worker in Background..." -ForegroundColor Green

# 일꾼 실행 (이 명령어가 터미널을 유지하며 대기 모드로 들어갑니다)
# pool 이름은 docker-compose.yml 의 워커가 쓰는 'default' 와 통일한다.
# prefect worker start --pool "default"
# WindowStyle Hidden을 주어 백그라운드에서 작동
Start-Process -FilePath "prefect" -ArgumentList "worker start --pool default" -WindowStyle Hidden
Write-Host "Worker is now running in the background! You can close this terminal." -ForegroundColor Green
