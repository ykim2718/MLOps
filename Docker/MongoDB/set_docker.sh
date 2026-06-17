#!/usr/bin/env bash
# MongoDB 컨테이너 기동 스크립트 — 제어 노드(머신 A)에서 실행한다.
#
# 제어 노드의 서비스들(postgres / minio / mlflow / prefect_server / mongo)이 서비스명으로 서로
# 통신하도록 공유 네트워크 mlops 에 붙는다. 그 네트워크가 없으면 1회 만든다(이미 있으면 그대로 둔다).
set -euo pipefail

sudo docker network inspect mlops >/dev/null 2>&1 || sudo docker network create mlops >/dev/null

# compose 스택을 내렸다가(볼륨은 유지) 다시 백그라운드로 띄운다.
sudo docker compose down
sudo docker compose up -d
