#!/usr/bin/env bash
# One-shot, backward-compatible schema migrations for all four services,
# run BEFORE the new application code is brought up (docker compose up)
# so that N-1 application code never sees a schema it doesn't understand
# mid-rollout. Stops at the first failure - a partially-migrated cluster
# must be investigated by a human, never silently continued.
set -euo pipefail

# Overridable so a single-VPS deploy can point at docker-compose.vps.yml
# (images built on the box) instead of the registry-pinned prod file.
COMPOSE_FILES="${COMPOSE_FILES:--f docker-compose.yml -f docker-compose.prod.yml}"
SERVICES=(identity academic finance hr)

cd "${DEPLOY_PATH:?DEPLOY_PATH must be set}"

for service in "${SERVICES[@]}"; do
  echo "=== Migrating $service (alembic upgrade head) ==="
  # --rm: one-shot container, never left running; --no-deps: don't also
  # start postgres/rabbitmq here, they must already be up from the prior
  # release (migrations run against the existing, live database).
  if ! docker compose $COMPOSE_FILES run --rm --no-deps "$service" alembic upgrade head; then
    echo "FAIL: migration failed for '$service' - stopping before any other service is touched." >&2
    echo "The database may be in a partially migrated state; investigate manually before retrying or rolling back." >&2
    exit 1
  fi
  echo "OK: $service migrated."
done

echo "All migrations applied successfully."
