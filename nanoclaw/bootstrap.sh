#!/usr/bin/env bash
# Connect this machine's NanoClaw agent to Band. Run from your NanoClaw checkout.
#
# NanoClaw's Band channel is fork-shaped: it merges a version-pinned Band tag
# into core NanoClaw files. The add-band skill in band-ai/nanoclaw-band owns the
# merge, deps, build, and wiring. This snippet does only what the bootstrapper is
# uniquely placed to do: clone that integration repo, register a Band agent with
# your user key, plant the skill into the local NanoClaw checkout, write the
# agent-scoped credentials the skill needs, then hand off to the agent.
set -e

# >>> band:mini
export BAND_USER_API_KEY={{BAND_USER_API_KEY}}   # the web app fills this in
rm -rf /tmp/ncb && git clone --depth 1 --branch main https://github.com/band-ai/nanoclaw-band /tmp/ncb
export BAND_AGENT_NAME="${BAND_AGENT_NAME:-MyNanoClawAgent}"
export BAND_AGENT_DESCRIPTION="${BAND_AGENT_DESCRIPTION:-NanoClaw agent on Band}"
eval "$(/tmp/ncb/scripts/register-agent.sh)"
unset BAND_USER_API_KEY
DEST=".claude/skills/add-band"
rm -rf "$DEST" && mkdir -p "$(dirname "$DEST")" && cp -r /tmp/ncb/.claude/skills/add-band "$DEST"
{ echo "BAND_AGENT_ID=$BAND_AGENT_ID"; echo "BAND_API_KEY=$BAND_API_KEY"; } >> .env
mkdir -p data/env && cp .env data/env/env
claude /add-band 2>/dev/null || cat "$DEST/SKILL.md"
# <<< band:mini

echo "Registered agent $BAND_AGENT_ID. Agent API key written to .env (shown once): $BAND_API_KEY"
