# set_server.ps1 — bring up the Prefect server compose stack on the Control Node.
# (first time) Copy the example file and fill in the server section. docker-compose.env is not committed.
Copy-Item docker-compose.env_example docker-compose.env

$docker_network = "mlops"
$project_name   = "<Project Name>"
$docker_yml     = "docker-compose.server.yml"

# Create the shared network only if it does not exist yet.
docker network inspect $docker_network *> $null
if ($LASTEXITCODE -ne 0) { docker network create $docker_network }

docker compose -p $project_name -f $docker_yml up -d
