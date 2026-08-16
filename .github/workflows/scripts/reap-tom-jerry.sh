#!/usr/bin/env bash
# Delete the smoke run's Tom/Jerry agents from the test account, so the next
# run doesn't collide on the platform's per-owner unique-name constraint.
# Best-effort: a missing agent is fine; only unexpected API errors fail.
set -euo pipefail

base="${BAND_REST_URL:-https://app.band.ai}"; base="${base%/}"

for name in Tom Jerry; do
  ids=$(curl -fsSL -H "X-API-Key: $BAND_USER_API_KEY" \
    "$base/api/v1/me/agents?name=$name" |
    jq -r --arg name "$name" '.data[] | select(.name == $name) | .id')
  for id in $ids; do
    echo "reaping agent $name ($id)"
    curl -fsSL -X DELETE -H "X-API-Key: $BAND_USER_API_KEY" \
      "$base/api/v1/me/agents/$id?force=true" > /dev/null
  done
done
