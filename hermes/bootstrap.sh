#!/usr/bin/env bash
# Connect this machine's Hermes agent to Band. Run on the gateway host.
#
# Thin by design — this script does the four things only the bootstrapper can do,
# then hands off. It does NOT install/enable/restart/verify the plugin: those live
# in the add-band SKILL upstream (the single source of truth), so they never go
# stale here. What it does:
#   1. clone the integration repo
#   2. register a Band agent from your USER key — consumed here, in a plain shell,
#      so the broad user key never enters the agent's own environment; only the
#      agent-scoped BAND_AGENT_ID + BAND_API_KEY are saved to Hermes
#   3. plant the SKILL so `hermes chat -s add-band` is invocable before the plugin exists
#   4. hand off to the skill, which the agent follows to finish setup
set -e

export BAND_USER_API_KEY={{BAND_USER_API_KEY}}   # the web app fills this in
rm -rf /tmp/hbp && git clone --depth 1 --branch main https://github.com/band-ai/hermes-band-platform /tmp/hbp
SKILL=/tmp/hbp/hermes_band_platform/skills/add-band
# Mint the Band agent here, in a plain shell — your user key never reaches the agent.
eval "$(bash /tmp/hbp/scripts/register-agent.sh)"
unset BAND_USER_API_KEY
# Plant the skill so `hermes chat -s add-band` is invocable before the plugin is installed.
DEST="${HERMES_HOME:-$HOME/.hermes}/skills/add-band"
rm -rf "$DEST" && mkdir -p "$(dirname "$DEST")" && cp -r "$SKILL" "$DEST"
# Hand off: the agent runs the skill to install, enable, restart, and verify.
hermes chat -s add-band
