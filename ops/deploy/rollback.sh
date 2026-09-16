#!/usr/bin/env bash
# Rolls back to the previous successfully recorded release's image tag.
# Per plan.md: "return to previous immutable app images only when schema
# remains compatible" - this script deliberately does NOT run migrations
# or attempt any schema down-grade; it only re-deploys the previous
# image set. A human must have already confirmed the previous schema is
# still compatible with the current database state before running this
# (this is exactly why migrations are required to be backward-compatible
# in the first place - see docs/security.md / plan.md).
set -euo pipefail

DEPLOY_PATH="${DEPLOY_PATH:?DEPLOY_PATH must be set}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

releases_file="${DEPLOY_PATH}/releases.log"
if [ ! -f "$releases_file" ]; then
  echo "FAIL: no releases.log found at $releases_file - nothing to roll back to" >&2
  exit 1
fi

line_count=$(wc -l < "$releases_file")
if [ "$line_count" -lt 2 ]; then
  echo "FAIL: releases.log has fewer than 2 entries - no previous release to roll back to" >&2
  exit 1
fi

previous_entry=$(tail -n 2 "$releases_file" | head -n 1)
previous_tag=$(echo "$previous_entry" | jq -r '.image_tag')
if [ -z "$previous_tag" ] || [ "$previous_tag" = "null" ]; then
  echo "FAIL: could not determine previous image_tag from: $previous_entry" >&2
  exit 1
fi

echo "Rolling back to previous release:"
echo "$previous_entry"
echo

read -r -p "Confirm this schema is compatible with the CURRENT database state and you want to redeploy IMAGE_TAG=${previous_tag}? [yes/NO] " confirmation
if [ "$confirmation" != "yes" ]; then
  echo "Aborted - no changes made."
  exit 1
fi

export IMAGE_TAG="$previous_tag"
"${SCRIPT_DIR}/deploy.sh"

echo "Rollback deploy complete. IMAGE_TAG is now ${previous_tag}."
echo "NOTE: this rollback did not touch the database. If the failed release" \
     "also ran a migration, confirm manually whether that migration needs" \
     "a compensating change before considering this rollback fully complete."
