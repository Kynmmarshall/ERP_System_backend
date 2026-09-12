#!/usr/bin/env bash
# Appends a record of a successfully deployed release to a simple
# append-only log so ops/deploy/rollback.sh can find the previous known-
# good IMAGE_TAG. Deliberately plain text/JSON-lines on local disk - no
# extra service dependency for something this small.
set -euo pipefail

DEPLOY_PATH="${DEPLOY_PATH:?DEPLOY_PATH must be set}"
IMAGE_TAG="${IMAGE_TAG:?IMAGE_TAG must be set}"
BUILD_NUMBER="${BUILD_NUMBER:-unknown}"
GIT_COMMIT="${GIT_COMMIT:-unknown}"

releases_file="${DEPLOY_PATH}/releases.log"
timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)

entry=$(jq -nc \
  --arg ts "$timestamp" \
  --arg tag "$IMAGE_TAG" \
  --arg build "$BUILD_NUMBER" \
  --arg commit "$GIT_COMMIT" \
  '{timestamp: $ts, image_tag: $tag, jenkins_build: $build, git_commit: $commit}')

echo "$entry" >> "$releases_file"
echo "Recorded release: $entry"
