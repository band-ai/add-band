#!/usr/bin/env bash
# Connect this machine's NanoClaw agent to Band. Run from your NanoClaw checkout.
#
# NanoClaw's Band channel is fork-shaped: the add-band skill (shipped in the
# NanoClaw repo) merges a version-pinned Band tag and reads the agent creds from
# .env. This snippet does the one thing the skill doesn't — register a Band agent
# with your user key — then writes the creds and hands off to the skill.
set -e

# 1. Register a Band agent with your user key; capture its agent ID + key.
RESP=$(curl -sS -X POST https://app.band.ai/api/v1/me/agents/register -H "X-API-Key: {{BAND_USER_API_KEY}}" -H "Content-Type: application/json" -d '{"agent":{"name":"MyNanoClawAgent","description":"NanoClaw agent on Band"}}')
read -r AGENT_ID AGENT_KEY < <(node -e 'const j=JSON.parse(require("fs").readFileSync(0));console.log(j.data.agent.id+" "+j.data.credentials.api_key);' <<<"$RESP")

# 2. Persist the agent creds the Band channel reads from .env (and data/env/env).
{ echo "BAND_AGENT_ID=$AGENT_ID"; echo "BAND_API_KEY=$AGENT_KEY"; } >> .env
mkdir -p data/env && cp .env data/env/env

# 3. Hand off to the add-band skill — it owns the real install (merge tag, deps,
#    build) and wiring. Runs it if `claude` is on PATH; else prints it to follow.
claude /add-band 2>/dev/null || cat .claude/skills/add-band/SKILL.md
echo "Registered agent $AGENT_ID. Agent API key written to .env (shown once): $AGENT_KEY"
