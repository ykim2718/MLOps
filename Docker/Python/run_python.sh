#!/usr/bin/env bash

set -euo pipefail

# Convenience script (Linux) — create the shared network mlops if missing, then restart the stack.
sudo docker network inspect mlops >/dev/null 2>&1 || sudo docker network create mlops >/dev/null

# Take the compose stack down (volumes are kept) and bring it back up in the background.
sudo docker compose down
sudo docker compose up -d
