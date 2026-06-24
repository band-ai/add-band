#!/usr/bin/env bash
# Connect this machine's OpenClaw agent to Band. Run where OpenClaw runs.
#
# Mints a Band agent from your Band API key (inline curl — no cloned repo), then
# the openclaw CLI installs the band channel plugin and wires that agent in as a
# channel account.
set -euo pipefail

command -v openclaw >/dev/null || { echo "install openclaw first (the 'openclaw' CLI must be on PATH)"; exit 1; }
command -v curl >/dev/null || { echo "install curl first"; exit 1; }

# Get your Band API key: paste it at the prompt (pre-set BAND_API_KEY to skip;
# BAND_USER_API_KEY is honored as an alias).
: "${BAND_API_KEY:=${BAND_USER_API_KEY:-}}"
if [ -z "${BAND_API_KEY:-}" ]; then
  [ -r /dev/tty ] || { echo "no terminal for the API key prompt; set BAND_API_KEY and re-run" >&2; exit 1; }
  printf 'Paste your Band API key: ' >/dev/tty
  IFS= read -r -s BAND_API_KEY </dev/tty
  printf '\n' >/dev/tty
fi
[ -n "${BAND_API_KEY:-}" ] || { echo "Band API key required" >&2; exit 1; }

# Install the channel plugin before minting the agent, so a failed install
# doesn't leave an orphaned Band agent behind.
openclaw plugins install @band-ai/openclaw-channel-band --force

# Band agent names must be unique per account, so a bare default collides on a
# second run (or with anyone else's default) as "name has been taken". Offer a
# name with a unique default; pre-set BAND_AGENT_NAME to skip the prompt.
if [ -z "${BAND_AGENT_NAME:-}" ]; then
  default_name="OpenClaw Agent ($(hostname -s 2>/dev/null || echo local) $(date +%Y%m%d-%H%M%S))"
  if [ -r /dev/tty ]; then
    printf 'Agent name [%s]: ' "$default_name" >/dev/tty
    IFS= read -r BAND_AGENT_NAME </dev/tty
  fi
  BAND_AGENT_NAME="${BAND_AGENT_NAME:-$default_name}"
fi

# Register a Band agent. The API key goes through curl's --config (-K -) on
# stdin, so it never appears in any process's argv (`ps`).
base="${BAND_BASE_URL:-https://app.band.ai}"; base="${base%/}"
name="$BAND_AGENT_NAME"
desc="${BAND_AGENT_DESCRIPTION:-OpenClaw agent on Band}"
resp=$(curl -sS -X POST "$base/api/v1/me/agents/register" \
  -H "Content-Type: application/json" \
  -d "$(printf '{"agent":{"name":"%s","description":"%s"}}' "$name" "$desc")" \
  -w $'\n%{http_code}' -K - <<EOF
header = "X-API-Key: $BAND_API_KEY"
EOF
) || true
unset BAND_API_KEY

code=${resp##*$'\n'}; out=${resp%$'\n'*}
case "$code" in
  200 | 201) ;;
  *) echo "agent registration failed (HTTP ${code:-?}): $(printf '%.300s' "$out")" >&2; exit 1 ;;
esac

if command -v jq >/dev/null 2>&1; then
  AGENT_ID=$(printf '%s' "$out" | jq -r '.data.agent.id // empty')
  AGENT_KEY=$(printf '%s' "$out" | jq -r '.data.credentials.api_key // empty')
elif command -v python3 >/dev/null 2>&1; then
  read -r AGENT_ID AGENT_KEY < <(printf '%s' "$out" | python3 -c \
    'import sys, json; d = json.load(sys.stdin); print(d["data"]["agent"]["id"], d["data"]["credentials"]["api_key"])')
else
  echo "need jq or python3 to parse the registration response" >&2; exit 1
fi
[ -n "${AGENT_ID:-}" ] && [ -n "${AGENT_KEY:-}" ] || { echo "agent registration failed (no credentials returned)" >&2; exit 1; }

openclaw channels add --channel openclaw-channel-band --account "$AGENT_ID" --token "$AGENT_KEY"
openclaw config set "channels.openclaw-channel-band.accounts.$AGENT_ID.agentId" "$AGENT_ID"
openclaw gateway restart
echo "Registered agent $AGENT_ID. Channel wired; the openclaw CLI stored its credentials."
