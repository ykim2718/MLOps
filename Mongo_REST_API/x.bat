@echo off
:: chcp 65001: 터미널 인코딩을 UTF-8로 변경하는 명령어입니다.
chcp 65001 > nul
echo [1/5] Docker 버전 확인...
docker --version
docker-compose --version

echo [2/5] 기존 컨테이너 및 네트워크 정리...
:: 기존에 실행 중인 컨테이너를 멈추고 삭제합니다.
docker-compose down --remove-orphans
:: 혹시나 남아있을 수 있는 좀비 컨테이너 강제 종료 (주의: 다른 컨테이너도 중지됨)
:: docker rm -f $(docker ps -aq --filter "name=mongo_rest_api")  :: linux 문법이라 windows에서 오류 발생함.
:: 네트워크 리소스 정리
docker network prune -f

echo [3/5] 미사용 이미지 및 빌드 캐시 정리...
docker image prune -f

echo [4/5] 컨테이너 빌드 및 실행 (백그라운드)...
:: --build 옵션이 있으면 코드가 수정되었을 때 알아서 새 이미지를 만듭니다.
docker-compose up --build -d

echo [5/5] 실행 상태 및 포트 확인...
timeout /t 3 /nobreak > nul
docker compose ps

echo.
echo 완료! MongoDB REST API가 http://localhost 에서 실행 중입니다.
pause