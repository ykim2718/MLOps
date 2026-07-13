#!/usr/bin/env bash
# export POSTGRES_USER="실제_유저명"        # docker-compose.env의 값과 동일하게
# export POSTGRES_PASSWORD="실제_비밀번호"  # 검증에서 필요할 수 있음
# ./restore.sh

set -uo pipefail

CONTAINER="postgresql-postgres-1"
DBS=(prefect mlflow optuna catalog)
DUMP_DIR="dumped"

# ===== 복원 =====
for db in "${DBS[@]}"; do
  echo "==== Restoring: $db ===="
  if [ ! -f "$DUMP_DIR/$db.dump" ]; then
    echo "  !! $DUMP_DIR/$db.dump not found, skipping"
    continue
  fi
  docker exec -i "$CONTAINER" \
    createdb -U "$POSTGRES_USER" "$db" 2>/dev/null \
    && echo "  created db: $db" \
    || echo "  db exists (or create skipped): $db"
  docker exec -i "$CONTAINER" \
    pg_restore -U "$POSTGRES_USER" -d "$db" --no-owner --clean --if-exists < "$DUMP_DIR/$db.dump"
  echo "  done: $db"
done

# ===== 검증 =====
echo
echo "######## Verification ########"
for db in "${DBS[@]}"; do
  echo "== $db =="
  docker exec -i "$CONTAINER" \
    psql -U "$POSTGRES_USER" -d "$db" -c '\dt' | head
  echo
done
