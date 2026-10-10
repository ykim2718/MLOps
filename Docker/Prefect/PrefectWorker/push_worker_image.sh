#!/usr/bin/env bash
# push_worker_image.sh — build the Prefect worker image for several CPU architectures and push it to the registry.
# __version__ = "0.0.0"  # Semantic Versioning:  Version = Major.Minor.Patch
# Author: yRocket
#
# Builds Dockerfile.worker as one multi-arch image <registry>/prefect-worker:<tag> and pushes it, so every worker
# machine (amd64 PC, arm64 Mac) pulls its own variant through run_worker.sh. The registry defaults to IMAGE_REGISTRY
# of ../docker-compose.env (else the _example), the same value run_worker.sh pulls from.
#
#   ./push_worker_image.sh                                  # registry = IMAGE_REGISTRY of ../docker-compose.env
#   ./push_worker_image.sh --registry localhost:12357       # on the registry machine itself
#   ./push_worker_image.sh --platform linux/arm64           # one architecture only
#
# A multi-arch build needs the containerd image store (Docker Desktop: Settings > General > "Use containerd for
# pulling and storing images") or a docker-container buildx builder. The final tag check reads the HTTP API of a
# plain registry:2 container.
#
set -euo pipefail

IMAGE_NAME="prefect-worker"              # the name docker-compose.worker.yml pulls
REGISTRY=""                              # <host>:<port>; empty = IMAGE_REGISTRY of the env file
PLATFORM="linux/amd64,linux/arm64"       # CPU architectures of the worker machines
TAG="latest"

usage() { echo "Usage: $0 [--registry <host:port>] [--platform <list>] [--tag <tag>]" >&2; }

while [ $# -gt 0 ]; do
    case "$1" in
        --registry|--platform|--tag)
            # a missing value would make 'shift 2' fail silently under set -e
            [ $# -ge 2 ] || { echo "$1 needs a value." >&2; usage; exit 1; }
            case "$1" in
                --registry) REGISTRY="$2" ;;
                --platform) PLATFORM="$2" ;;
                --tag)      TAG="$2" ;;
            esac
            shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

cd "$(dirname "$0")"   # Dockerfile.worker and ../docker-compose.env are relative to this folder
[ -f Dockerfile.worker ] || { echo "Dockerfile.worker not found in $(pwd)." >&2; exit 1; }

if [ -z "$REGISTRY" ]; then
    ENV_FILE="../docker-compose.env"
    [ -f "$ENV_FILE" ] || ENV_FILE="../docker-compose.env_example"
    [ -f "$ENV_FILE" ] || { echo "env file not found: $ENV_FILE" >&2; exit 1; }
    REGISTRY="$(sed -n 's/^IMAGE_REGISTRY=//p' "$ENV_FILE" | tail -n 1 | tr -d '\r')"
    REGISTRY_SOURCE="IMAGE_REGISTRY in $ENV_FILE"
else
    REGISTRY_SOURCE="--registry"
fi
if [ -z "$REGISTRY" ] || [[ "$REGISTRY" == *"<"* ]] || [[ "$REGISTRY" == */* ]]; then
    echo "Registry missing, a placeholder or not <host>:<port> (got '$REGISTRY' from $REGISTRY_SOURCE)." >&2
    echo "Set IMAGE_REGISTRY in ../docker-compose.env or pass --registry <host:port>." >&2
    exit 1
fi
if [ -z "$PLATFORM" ] || [ -z "$TAG" ]; then
    echo "--platform and --tag need non-empty values." >&2
    exit 1
fi

command -v docker >/dev/null 2>&1 || { echo "docker not found on PATH." >&2; exit 1; }
docker buildx version >/dev/null 2>&1 || { echo "docker buildx is required (Docker Desktop ships it)." >&2; exit 1; }

REF="$REGISTRY/$IMAGE_NAME:$TAG"
echo "Building $REF for $PLATFORM"
if ! docker buildx build --platform "$PLATFORM" -f Dockerfile.worker -t "$REF" --push .; then
    echo "push_worker_image.sh: ERROR: build or push of $REF failed." >&2
    echo "  A multi-arch build needs the containerd image store or a docker-container builder;" >&2
    echo "  an HTTP registry other than localhost needs 'insecure-registries' in this docker daemon." >&2
    exit 1
fi

# Confirm the registry now lists the tag, so a push that went elsewhere does not pass as done.
if command -v curl >/dev/null 2>&1; then
    tags="$(curl -s -m 10 "http://$REGISTRY/v2/$IMAGE_NAME/tags/list" || true)"
    if ! printf '%s' "$tags" | grep -q "\"$TAG\""; then
        echo "push_worker_image.sh: ERROR: pushed $REF, but the registry does not list tag '$TAG' (got: '$tags')." >&2
        exit 1
    fi
    echo "Registry lists $IMAGE_NAME tags: $tags"
else
    echo "push_worker_image.sh: WARNING: curl not found; the registry's tag list was not checked." >&2
fi
echo "pushed $REF"
