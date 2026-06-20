# build_dispatcher.ps1 — (once) build the dispatcher image (prefect + prefect-docker baked in).
docker build -f Dockerfile.dispatcher -t prefect-dispatcher:latest .
