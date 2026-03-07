#!/usr/bin/env bash
# Build and run the Claude Agent SDK demo in Docker.
# Usage:
#   ./adapters/claude-agent-sdk/run.sh              # quick mode
#   ./adapters/claude-agent-sdk/run.sh --mode observe
#   ./adapters/claude-agent-sdk/run.sh --role admin
#   ./adapters/claude-agent-sdk/run.sh --console    # needs console server on localhost:8000

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
IMAGE="edictum-claude-sdk-demo"

echo "Building $IMAGE..."
docker build -f "$REPO_ROOT/adapters/claude-agent-sdk/Dockerfile" -t "$IMAGE" "$REPO_ROOT"

# Use --network host when --console is passed (Docker needs to reach localhost:8000)
DOCKER_ARGS=()
if printf '%s\n' "$@" | grep -q -- '--console'; then
    DOCKER_ARGS+=(--network host)
fi

echo ""
echo "Running demo..."
docker run --rm -it \
    --env-file "$REPO_ROOT/.env" \
    "${DOCKER_ARGS[@]}" \
    "$IMAGE" "$@"
