#!/usr/bin/env bash
# Connect this machine's NanoClaw agent to Band.
#
# NanoClaw's Band channel is fork-shaped: the channel setup and add-band skill
# live in the Band-ready NanoClaw fork, not in this catalog. This snippet clones
# or updates that fork, registers a Band agent with your Band API key, writes the
# agent-scoped credentials into the cloned checkout, then hands off to the
# fork's skill. The skill can focus on walking the user through the remaining
# NanoClaw-side connection steps.
set -euo pipefail

command -v git >/dev/null || { echo "install git first"; exit 1; }

# Get your Band API key: paste it at the prompt (pre-set BAND_API_KEY to skip).
if [ -z "${BAND_API_KEY:-}" ]; then
  [ -r /dev/tty ] || { echo "no terminal for the API key prompt; set BAND_API_KEY and re-run" >&2; exit 1; }
  printf 'Paste your Band API key: ' >/dev/tty
  IFS= read -r -s BAND_API_KEY </dev/tty
  printf '\n' >/dev/tty
fi
[ -n "${BAND_API_KEY:-}" ] || { echo "Band API key required" >&2; exit 1; }
export BAND_API_KEY
export NANOCLAW_HOME="${NANOCLAW_HOME:-$HOME/nanoclaw-band}"
export NANOCLAW_REPO="${NANOCLAW_REPO:-https://github.com/band-ai/nanoclaw-band}"
if [ -d "$NANOCLAW_HOME/.git" ]; then if git -C "$NANOCLAW_HOME" remote get-url upstream >/dev/null 2>&1; then git -C "$NANOCLAW_HOME" remote set-url upstream "$NANOCLAW_REPO"; else git -C "$NANOCLAW_HOME" remote add upstream "$NANOCLAW_REPO"; fi; git -C "$NANOCLAW_HOME" pull --ff-only upstream main; else git clone --depth 1 --branch main "$NANOCLAW_REPO" "$NANOCLAW_HOME"; fi
cd "$NANOCLAW_HOME"
export BAND_AGENT_NAME="${BAND_AGENT_NAME:-MyNanoClawAgent}"
export BAND_AGENT_DESCRIPTION="${BAND_AGENT_DESCRIPTION:-NanoClaw agent on Band}"
# register-agent.sh prints `BAND_AGENT_ID=…` / `BAND_AGENT_API_KEY=…` on success.
# `eval "$(…)"` does not trip set -e if the helper fails, so assert the creds landed.
eval "$(bash .claude/skills/add-band/scripts/register-agent.sh)"
[ -n "${BAND_AGENT_ID:-}" ] && [ -n "${BAND_AGENT_API_KEY:-}" ] || { echo "agent registration failed (no credentials returned)" >&2; exit 1; }
unset BAND_API_KEY
export BAND_AGENT_ID BAND_AGENT_API_KEY
{ echo "BAND_AGENT_ID=$BAND_AGENT_ID"; echo "BAND_AGENT_API_KEY=$BAND_AGENT_API_KEY"; } >> .env
mkdir -p data/env && cp .env data/env/env
echo "Registered agent $BAND_AGENT_ID. Agent credentials written to .env."

# Hand off to the fork's skill; print it if the claude CLI isn't installed.
if command -v claude >/dev/null; then claude /add-band < /dev/tty; else cat .claude/skills/add-band/SKILL.md; fi
