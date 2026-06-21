#!/usr/bin/env bash
set -e
# Get your Band user API key: paste it at the prompt (pre-set BAND_USER_API_KEY to skip).
if [ -z "${BAND_USER_API_KEY:-}" ]; then
  [ -r /dev/tty ] || { echo "no terminal for the API key prompt; set BAND_USER_API_KEY and re-run" >&2; exit 1; }
  printf 'Paste your Band user API key: ' >/dev/tty
  IFS= read -r -s BAND_USER_API_KEY </dev/tty
  printf '\n' >/dev/tty
fi
[ -n "${BAND_USER_API_KEY:-}" ] || { echo "Band user API key required" >&2; exit 1; }
export BAND_USER_API_KEY
rm -rf /tmp/ocb && git clone --depth 1 --branch main https://github.com/band-ai/openclaw-band /tmp/ocb
export BAND_AGENT_NAME="${BAND_AGENT_NAME:-MyOpenClawAgent}"
export BAND_AGENT_DESCRIPTION="${BAND_AGENT_DESCRIPTION:-OpenClaw agent on Band}"
eval "$(bash /tmp/ocb/scripts/register-agent.sh)"
unset BAND_USER_API_KEY
openclaw plugins install @band-ai/openclaw-channel-band --force
openclaw channels add --channel openclaw-channel-band --account "$BAND_AGENT_ID" --token "$BAND_API_KEY"
openclaw config set "channels.openclaw-channel-band.accounts.$BAND_AGENT_ID.agentId" "$BAND_AGENT_ID"
openclaw gateway restart
echo "Registered agent $BAND_AGENT_ID. Agent API key (shown once): $BAND_API_KEY"
