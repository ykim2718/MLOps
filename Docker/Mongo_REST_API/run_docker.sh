#!/usr/bin/env bash
# run_docker.sh, author: yRocket
# Rebuild and restart the MongoDB REST API stack (ycontrol :3000, yimprove :3001) from this folder.
#
# Usage
#   bash run_docker.sh
#
# The containers mount ~/.config/y read-only and authenticate with ~/.config/y/ymongo.json when it exists,
# so run it from the shell whose home holds that file (WSL: /home/<user>, Git Bash: C:\Users\<user>).
__version__="0.1.0.2026.9.27"  # Semantic Versioning: Major.Minor.Patch.Date(YYYY.M.D)
# 0.1.0: replaces x.bat; same steps in bash, without `docker network prune`, which removed every unused
#        network on the host (e.g. the external mlops network while no container was attached)

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
compose=(docker compose -f "$here/docker-compose.yml")

echo "[1/4] docker version"
docker --version
docker compose version

echo "[2/4] stop and remove this stack's containers"
"${compose[@]}" down --remove-orphans

echo "[3/4] remove dangling images and build cache left by earlier builds"
docker image prune -f

echo "[4/4] build and start in the background"
"${compose[@]}" up --build -d
"${compose[@]}" ps

echo "done: ycontrol http://localhost:3000, yimprove http://localhost:3001"
