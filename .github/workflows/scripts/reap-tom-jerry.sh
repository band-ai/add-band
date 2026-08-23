#!/usr/bin/env bash
# Delete the smoke run's Tom/Jerry agents from the test account, so the next
# run doesn't collide on the platform's per-owner unique-name constraint.
# Best-effort: a missing agent (404) is fine and transient failures on one
# name don't stop the other; only unexpected API errors flip the exit code.
#
# Names come from argv, not a hardcoded "Tom Jerry" — the matrix's three OS
# lanes now run in parallel under distinct names (Tom-<os>/Jerry-<os>), so
# each lane's reap must only ever touch its own two names, never another
# lane's.
#
# Usage: reap-tom-jerry.sh NAME...
set -uo pipefail

base="${BAND_REST_URL:-https://app.band.ai}"; base="${base%/}"
fail=0

for name in "$@"; do
  resp=$(curl -sSL -w $'\n%{http_code}' -H "X-API-Key: $BAND_USER_API_KEY" \
    "$base/api/v1/me/agents?name=$name") || {
    echo "reap: listing $name failed" >&2; fail=1; continue
  }
  code=${resp##*$'\n'}; resp=${resp%$'\n'*}
  case "$code" in
    2*) ;;
    *) echo "reap: listing $name failed (HTTP $code)" >&2; fail=1; continue ;;
  esac
  ids=$(printf '%s' "$resp" |
    jq -r --arg name "$name" '.data // [] | .[]? | select(.name == $name) | .id') || {
    echo "reap: unexpected list response for $name" >&2; fail=1; continue
  }
  for id in $ids; do
    code=$(curl -sSL -o /dev/null -w '%{http_code}' -X DELETE \
      -H "X-API-Key: $BAND_USER_API_KEY" "$base/api/v1/me/agents/$id?force=true")
    case "$code" in
      2* | 404) echo "reaped agent $name ($id)" ;;
      *) echo "reap: deleting $name ($id) failed (HTTP $code)" >&2; fail=1 ;;
    esac
  done
done

exit "$fail"
