#!/usr/bin/env bash
# Connect this machine's OpenClaw agent to Band. Run where OpenClaw runs.
#
# Fetches openclaw-channel-band's shared registration helper, mints a Band agent
# from your Band API key, then the openclaw CLI installs the band channel plugin
# and wires that agent in as a channel account.
set -euo pipefail

command -v git >/dev/null || { echo "install git first"; exit 1; }
command -v openclaw >/dev/null || { echo "install openclaw first (the 'openclaw' CLI must be on PATH)"; exit 1; }

# Get your Band API key: paste it at the prompt (pre-set BAND_API_KEY to skip).
if [ -z "${BAND_API_KEY:-}" ]; then
  [ -r /dev/tty ] || { echo "no terminal for the API key prompt; set BAND_API_KEY and re-run" >&2; exit 1; }
  printf 'Paste your Band API key: ' >/dev/tty
  IFS= read -r -s BAND_API_KEY </dev/tty
  printf '\n' >/dev/tty
fi
[ -n "${BAND_API_KEY:-}" ] || { echo "Band API key required" >&2; exit 1; }
export BAND_API_KEY
rm -rf /tmp/ocb && git clone --depth 1 --branch main https://github.com/band-ai/openclaw-channel-band /tmp/ocb
# Install the channel plugin before minting the agent, so a failed install
# doesn't leave an orphaned Band agent behind.
openclaw plugins install @band-ai/openclaw-channel-band --force
export BAND_AGENT_NAME="${BAND_AGENT_NAME:-MyOpenClawAgent}"
export BAND_AGENT_DESCRIPTION="${BAND_AGENT_DESCRIPTION:-OpenClaw agent on Band}"
# register-agent.sh prints `BAND_AGENT_ID=…` / `BAND_AGENT_API_KEY=…` on success.
# `eval "$(…)"` does not trip set -e if the helper fails, so assert the creds landed.
eval "$(bash /tmp/ocb/scripts/register-agent.sh)"
[ -n "${BAND_AGENT_ID:-}" ] && [ -n "${BAND_AGENT_API_KEY:-}" ] || { echo "agent registration failed (no credentials returned)" >&2; exit 1; }
unset BAND_API_KEY
openclaw channels add --channel openclaw-channel-band --account "$BAND_AGENT_ID" --token "$BAND_AGENT_API_KEY"
openclaw config set "channels.openclaw-channel-band.accounts.$BAND_AGENT_ID.agentId" "$BAND_AGENT_ID"
openclaw gateway restart
echo "Registered agent $BAND_AGENT_ID. Channel wired; the openclaw CLI stored its credentials."
