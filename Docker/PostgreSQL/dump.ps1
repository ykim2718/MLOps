$OutDir = "dumped"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

foreach ($db in @("prefect", "mlflow", "optuna", "catalog")) {
    Write-Host "Dumping database: $db ..." -ForegroundColor Cyan
    docker exec postgresql-postgres-1 sh -c "pg_dump -U `$POSTGRES_USER -Fc -f /tmp/$db.dump $db"
    docker cp "postgresql-postgres-1:/tmp/$db.dump" "$OutDir/$db.dump"
    docker exec postgresql-postgres-1 rm "/tmp/$db.dump"
    Write-Host "  -> saved $OutDir/$db.dump" -ForegroundColor Green
}