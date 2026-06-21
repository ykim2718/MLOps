# Convenience script (Windows) — create the shared network mlops if missing, then restart the stack.
docker network inspect mlops *> $null
if ($LASTEXITCODE -ne 0) { docker network create mlops | Out-Null }

# Take the compose stack down (volumes are kept) and bring it back up in the background.
docker compose down
docker compose up -d
