#!/usr/bin/env bash
# Connect this machine's NanoClaw agent to Band.
#
# NanoClaw's Band channel is fork-shaped: the adapter, SDK tools, and add-band
# skill ship in the Band-ready NanoClaw fork, not in this catalog. So this
# snippet works against a checkout of that fork. It is adoption-first: if you run
# it from inside a Band-ready checkout (or already have one), it uses that in
# place; only on a fresh box does it clone. It then registers a Band agent with
# your user key, writes the agent-scoped credentials into the checkout, and hands
# off to the fork's add-band skill for the remaining setup and room wiring.
#
# Override the clone location with BAND_DIR; override the source with BAND_REPO.
set -e

# >>> band:mini
# The user key arrives pre-exported by the runner (export BAND_USER_API_KEY=… &&
# <script>), possibly under the name BAND_API_KEY. Consume whichever is set and
# don't clobber it; fall back to the placeholder the web app fills in. The key is
# ephemeral — it is unset right after registration and never written to disk.
export BAND_USER_API_KEY="${BAND_USER_API_KEY:-${BAND_API_KEY:-}}"
[ -n "$BAND_USER_API_KEY" ] || export BAND_USER_API_KEY={{BAND_USER_API_KEY}}   # the web app fills this in
export BAND_REPO="${BAND_REPO:-https://github.com/band-ai/nanoclaw-band}"
# Adopt a Band-ready checkout if we're in one (or already have one); else clone.
# src/channels/band.ts is the marker that this checkout carries the Band channel.
if [ -f src/channels/band.ts ]; then dir="$PWD"; else dir="${BAND_DIR:-$HOME/agents/nanoclaw-band}"; fi
[ -f "$dir/src/channels/band.ts" ] || { mkdir -p "$(dirname "$dir")"; git clone --depth 1 --branch main "$BAND_REPO" "$dir"; }
cd "$dir"
export BAND_AGENT_NAME="${BAND_AGENT_NAME:-MyNanoClawAgent}" BAND_AGENT_DESCRIPTION="${BAND_AGENT_DESCRIPTION:-NanoClaw agent on Band}"
unset BAND_API_KEY   # drop the alias before registration so a failure can't leak the user key as the agent key
eval "$(bash .claude/skills/add-band/scripts/register-agent.sh)"
unset BAND_USER_API_KEY
{ echo "BAND_AGENT_ID=$BAND_AGENT_ID"; echo "BAND_API_KEY=$BAND_API_KEY"; } >> .env
mkdir -p data/env && cp .env data/env/env
claude /add-band 2>/dev/null || cat .claude/skills/add-band/SKILL.md
# <<< band:mini

echo "Registered agent $BAND_AGENT_ID in $dir. Agent API key written to .env (shown once): $BAND_API_KEY"
