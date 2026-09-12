#!/usr/bin/env bash
# Preflight checks before any production deployment mutation. Aborts
# (nonzero exit) before anything is touched if any check fails - per
# plan.md: "Abort before mutation on failed preflight, backup or schema
# validation."
set -euo pipefail

MIN_FREE_DISK_GB="${MIN_FREE_DISK_GB:-10}"
MIN_FREE_MEM_MB="${MIN_FREE_MEM_MB:-512}"
DEPLOY_PATH="${DEPLOY_PATH:?DEPLOY_PATH must be set (target deployment directory on the VPS)}"

echo "=== Preflight: required tools ==="
for tool in docker jq curl; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "FAIL: required tool '$tool' not found on this agent" >&2
    exit 1
  fi
done
if ! docker compose version >/dev/null 2>&1; then
  echo "FAIL: 'docker compose' (v2 plugin) not available" >&2
  exit 1
fi
echo "OK"

echo "=== Preflight: required parameters/environment ==="
for var in ERP_DOMAIN REGISTRY_HOST REGISTRY_NAMESPACE IMAGE_TAG; do
  if [ -z "${!var:-}" ]; then
    echo "FAIL: required variable '$var' is not set - refusing to deploy with a guessed/blank value" >&2
    exit 1
  fi
done
if [ "$IMAGE_TAG" = "latest" ]; then
  echo "FAIL: IMAGE_TAG must be an immutable tag/digest, never the floating 'latest' tag" >&2
  exit 1
fi
echo "OK"

echo "=== Preflight: disk headroom on deploy path ==="
available_kb=$(df --output=avail -k "$DEPLOY_PATH" | tail -n1 | tr -d ' ')
available_gb=$((available_kb / 1024 / 1024))
if [ "$available_gb" -lt "$MIN_FREE_DISK_GB" ]; then
  echo "FAIL: only ${available_gb}GB free at $DEPLOY_PATH, need >= ${MIN_FREE_DISK_GB}GB" >&2
  exit 1
fi
echo "OK (${available_gb}GB free)"

echo "=== Preflight: memory headroom ==="
available_mb=$(awk '/MemAvailable/ {printf "%d", $2/1024}' /proc/meminfo)
if [ "$available_mb" -lt "$MIN_FREE_MEM_MB" ]; then
  echo "FAIL: only ${available_mb}MB memory available, need >= ${MIN_FREE_MEM_MB}MB" >&2
  echo "This is a single 4GB VPS also running Jenkins - do not promise capacity without measuring it (plan.md)." >&2
  exit 1
fi
echo "OK (${available_mb}MB available)"

echo "=== Preflight: TLS termination reachable ==="
# The host's existing Nginx (outside this repo) is what terminates TLS on
# ERP_DOMAIN and proxies to this gateway - verify it, don't assume it.
if ! curl -fsS -o /dev/null "https://${ERP_DOMAIN}/healthz"; then
  echo "FAIL: https://${ERP_DOMAIN}/healthz not reachable - host Nginx/TLS not confirmed working" >&2
  exit 1
fi
echo "OK"

echo "Preflight passed."
