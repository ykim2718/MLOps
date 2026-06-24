#!/usr/bin/env bash

set -euo pipefail

# mlops 네트워크가 없으면 생성
sudo docker network inspect mlops >/dev/null 2>&1 || sudo docker network create mlops >/dev/null

# compose 스택을 내렸다가(볼륨은 유지) 다시 백그라운드로 띄운다.
sudo docker compose down
sudo docker compose up -d
