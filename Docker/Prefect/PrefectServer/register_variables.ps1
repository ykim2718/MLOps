# register_variables.ps1 — register the shared backing-service ADDRESS variables on the Prefect server.
# __version__ = "0.0.1"  # Semantic Versioning:  Version = Major.Minor.Patch
# Single, non-secret source of backing addresses (LAN IP). Flow code and host tools (catalog.py) read
# them via prefect Variables from the server, so no docker-compose.env is needed outside containers.
# Run after the server is up (run_server.ps1). Idempotent (--overwrite).
#
#   .\register_variables.ps1 -Minio http://192.168.0.8:9000 -PostgresHost 192.168.0.8 `
#                            -PostgresPort 5432 -Mlflow http://192.168.0.8:5000
#
param(
    [string]$Minio        = 'http://192.168.0.8:9000',     # MinIO S3 endpoint (data download / model upload)
    [string]$PostgresHost = '192.168.0.8',                 # PostgreSQL host (catalog / optuna DBs)
    [string]$PostgresPort = '5432',
    [string]$Mlflow       = 'http://192.168.0.8:5000',     # MLflow tracking server
    [string]$Compose      = 'docker-compose.server.yml'    # the server compose (its top-level name: sets the project)
)

$ErrorActionPreference = "Stop"

# set one variable on the server (overwrite so re-runs keep it in sync).
function Set-Var($name, $value) {
    docker compose -f $Compose exec -T prefect_server prefect variable set $name $value --overwrite
}

Set-Var 'minio_endpoint'      $Minio
Set-Var 'postgres_host'       $PostgresHost
Set-Var 'postgres_port'       $PostgresPort
Set-Var 'mlflow_tracking_uri' $Mlflow
Write-Host "[register_variables] set: minio_endpoint, postgres_host, postgres_port, mlflow_tracking_uri"
