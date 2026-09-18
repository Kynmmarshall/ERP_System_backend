#!/usr/bin/env bash
# Brings the stack up on pinned, already-pulled images and waits for every
# service to report healthy before handing control back to the pipeline.
# Does NOT build anything (--no-build via docker-compose.prod.yml having
# no build: keys once !reset applies) and does not touch migrations
# (ops/deploy/migrate.sh runs strictly before this, as a separate stage).
set -euo pipefail

# Both overridable so a single-VPS deploy can build on the box instead of
# pulling registry-pinned images (BUILD_FLAG=--build).
COMPOSE_FILES="${COMPOSE_FILES:--f docker-compose.yml -f docker-compose.prod.yml}"
BUILD_FLAG="${BUILD_FLAG:---no-build}"
READY_TIMEOUT_SECONDS="${READY_TIMEOUT_SECONDS:-120}"
GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:2022}"

HEALTHZ_PATHS=(
  "/healthz"
  "/api/v1/auth/healthz"
  "/api/v1/academic/healthz"
  "/api/v1/finance/healthz"
  "/api/v1/hr/healthz"
)

cd "${DEPLOY_PATH:?DEPLOY_PATH must be set}"

echo "=== Bringing up stack (${BUILD_FLAG}) ==="
docker compose $COMPOSE_FILES up -d $BUILD_FLAG

# nginx resolves upstream hostnames once, at startup. Any service that got a
# new container IP in the step above leaves the gateway pointing at a dead
# address, which surfaces as 404 on every /api/v1/... route rather than 502.
echo "=== Restarting gateway so it re-resolves upstream addresses ==="
docker compose $COMPOSE_FILES restart gateway

echo "=== Waiting for all services to report healthy (timeout ${READY_TIMEOUT_SECONDS}s) ==="
deadline=$(( $(date +%s) + READY_TIMEOUT_SECONDS ))
for path in "${HEALTHZ_PATHS[@]}"; do
  echo "-- waiting on ${GATEWAY_URL}${path}"
  until curl -fsS -o /dev/null "${GATEWAY_URL}${path}"; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
      echo "FAIL: ${GATEWAY_URL}${path} did not become healthy within ${READY_TIMEOUT_SECONDS}s" >&2
      docker compose $COMPOSE_FILES ps >&2
      exit 1
    fi
    sleep 2
  done
  echo "OK: ${path}"
done

echo "Stack is up and all health checks pass."
