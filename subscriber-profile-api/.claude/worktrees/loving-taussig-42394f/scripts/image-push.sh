#!/usr/bin/env bash
set -euo pipefail

# Build and push all service images to the k3d local registry.

REGISTRY="k3d-aaa-registry.localhost:5111"
TAG="${1:-dev}"

SERVICES=(
  "aaa-lookup-service"
  "subscriber-profile-api"
  "aaa-management-ui"
  "aaa-radius-server"
  "aaa-regression-tester"
)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

for svc in "${SERVICES[@]}"; do
  if [ ! -d "${REPO_ROOT}/${svc}" ]; then
    echo "── Skipping ${svc} (directory not found) ─────────────────"
    continue
  fi
  echo "── Building ${svc} ────────────────────────────────────────"
  docker build -t "${REGISTRY}/${svc}:${TAG}" "${REPO_ROOT}/${svc}/"
  echo "── Pushing ${svc} ─────────────────────────────────────────"
  docker push "${REGISTRY}/${svc}:${TAG}"
done

echo ""
echo "All images pushed to ${REGISTRY}."
