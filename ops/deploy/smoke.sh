#!/usr/bin/env bash
# Post-deploy smoke test against a dedicated, non-production smoke-test
# account (never real user/tenant data). Verifies the gateway, auth, and
# each service are actually reachable and answering through the real
# network path (host Nginx -> gateway -> services), not just that
# containers report "healthy" locally.
#
# Prerequisite (not yet provisioned - documented gap, same spirit as
# docs/backup-recovery.md): a dedicated smoke-test account must exist in
# the production identity database with a role that can read but not
# mutate real records, and its credentials supplied to Jenkins as
# SMOKE_TEST_EMAIL / SMOKE_TEST_PASSWORD credentials (never committed).
set -euo pipefail

GATEWAY_URL="${GATEWAY_URL:-https://${ERP_DOMAIN:?ERP_DOMAIN must be set}}"
SMOKE_TEST_EMAIL="${SMOKE_TEST_EMAIL:?SMOKE_TEST_EMAIL must be set (dedicated read-only smoke-test account)}"
SMOKE_TEST_PASSWORD="${SMOKE_TEST_PASSWORD:?SMOKE_TEST_PASSWORD must be set}"

echo "=== Smoke: gateway health ==="
curl -fsS "${GATEWAY_URL}/healthz" >/dev/null
echo "OK"

echo "=== Smoke: login ==="
login_response=$(curl -fsS -X POST "${GATEWAY_URL}/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${SMOKE_TEST_EMAIL}\",\"password\":\"${SMOKE_TEST_PASSWORD}\"}")
token=$(echo "$login_response" | jq -r '.access_token // empty')
if [ -z "$token" ]; then
  echo "FAIL: login did not return an access_token" >&2
  exit 1
fi
echo "OK"

echo "=== Smoke: authenticated read-only calls ==="
READ_PATHS=(
  "/api/v1/academic/programs"
  "/api/v1/academic/terms"
  "/api/v1/finance/expenses"
  "/api/v1/hr/positions"
)
for path in "${READ_PATHS[@]}"; do
  status=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer ${token}" "${GATEWAY_URL}${path}")
  if [ "$status" != "200" ]; then
    echo "FAIL: ${path} returned HTTP ${status} (expected 200)" >&2
    exit 1
  fi
  echo "OK: ${path} -> 200"
done

echo "Smoke test passed."
