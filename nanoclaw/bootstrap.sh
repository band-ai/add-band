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
export BAND_API_KEY
export NANOCLAW_REPO="${NANOCLAW_REPO:-https://github.com/band-ai/nanoclaw-band}"

# Pick where the Band-ready NanoClaw checkout lives. We don't clone into a
# hidden $HOME dir behind your back — prefer the current directory. git + tar
# only; no gh or other tooling assumed.
#   - NANOCLAW_HOME set            → honor it (explicit override / escape hatch)
#   - pwd is Band-ready            → use it in place
#   - pwd is a NanoClaw clone      → make it Band-ready in place (see below)
#   - pwd is empty                 → clone the fork right here
#   - pwd is non-empty (anything else) → clone into ./nanoclaw-band (never clobber)
band_ready() { [ -f "$1/.claude/skills/add-band/scripts/register-agent.sh" ]; }
is_nanoclaw() { [ -e "$1/.git" ] && { [ -f "$1/nanoclaw.sh" ] || [ -f "$1/container/agent-runner/package.json" ]; }; }
if [ -z "${NANOCLAW_HOME:-}" ]; then
  if band_ready "$PWD" || is_nanoclaw "$PWD"; then NANOCLAW_HOME="$PWD"
  elif [ -z "$(ls -A . 2>/dev/null)" ]; then NANOCLAW_HOME="$PWD"
  else NANOCLAW_HOME="$PWD/nanoclaw-band"; fi
fi
export NANOCLAW_HOME
if band_ready "$NANOCLAW_HOME"; then
  : # already has the add-band skill — use it in place
elif is_nanoclaw "$NANOCLAW_HOME"; then
  # An existing NanoClaw clone without the Band skill. The fork has diverged
  # (its own history), so we don't pull/merge it — that would conflict or
  # disturb your tree. Add the fork as a remote, fetch it (non-destructive),
  # and extract just the add-band skill into the working tree (no index churn,
  # no merge) so this script and /add-band have what they need.
  git -C "$NANOCLAW_HOME" remote get-url band >/dev/null 2>&1 \
    || git -C "$NANOCLAW_HOME" remote add band "$NANOCLAW_REPO"
  git -C "$NANOCLAW_HOME" fetch --depth 1 band main
  git -C "$NANOCLAW_HOME" archive band/main .claude/skills/add-band | tar -x -C "$NANOCLAW_HOME"
  band_ready "$NANOCLAW_HOME" || { echo "band: fetched the fork but the add-band skill didn't land — clone the fork instead." >&2; exit 1; }
elif [ -e "$NANOCLAW_HOME" ] && [ -n "$(ls -A "$NANOCLAW_HOME" 2>/dev/null)" ]; then
  echo "band: $NANOCLAW_HOME exists but isn't a NanoClaw checkout." >&2
  echo "      Re-run from an empty directory, or set NANOCLAW_HOME to where the fork should live." >&2
  exit 1
else
  git clone --depth 1 --branch main "$NANOCLAW_REPO" "$NANOCLAW_HOME"
fi
cd "$NANOCLAW_HOME"
# Don't default BAND_AGENT_NAME/DESCRIPTION here. register-agent.sh prompts for a
# unique name when they're unset; a fixed default ("MyNanoClawAgent") collides on
# the second install → HTTP 422 "name has already been taken". A pre-set
# BAND_AGENT_NAME/BAND_AGENT_DESCRIPTION (exported by the caller) is still honored.
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
