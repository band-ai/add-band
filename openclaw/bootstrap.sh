#!/usr/bin/env bash
# Connect this machine's OpenClaw agent to Band. Run where OpenClaw runs.
#
# Mints a Band agent from your Band API key (inline curl — no cloned repo), then
# the openclaw CLI installs the band channel plugin and wires that agent in as a
# channel account.
#
# Usage:
#   bootstrap.sh                          # prompts for name + description
#   bootstrap.sh --name MyBot --description 'A helpful bot'
#   curl … | bash -s -- --name MyBot      # pass flags through a piped one-liner
#
# Flags (both optional; a flag skips its prompt):
#   -n, --name NAME            agent name
#   -d, --description DESC     agent description
#   -h, --help                 show usage and exit
#
# Env knobs: BAND_BASE_URL (default https://app.band.ai), BAND_AGENT_NAME,
#            BAND_AGENT_DESCRIPTION (set either to skip its prompt).
set -euo pipefail

name_default="MyOpenClawAgent"
desc_default="OpenClaw agent on Band"

usage() {
  cat <<USAGE
Connect an OpenClaw agent to Band.

Usage:
  bootstrap.sh [--name NAME] [--description DESC]

Options:
  -n, --name NAME            agent name (prompted if omitted)
  -d, --description DESC     agent description (prompted if omitted)
  -h, --help                 show this help and exit

The Band API key is read from \$BAND_API_KEY (or \$BAND_USER_API_KEY), or
pasted at the prompt.
USAGE
}

# JSON-escape a string (backslash first, then double-quote) so a user-typed
# name/description with quotes can't break the request body below.
json_escape() { local s=$1; s=${s//\\/\\\\}; s=${s//\"/\\\"}; printf '%s' "$s"; }

# Name/description precedence: CLI flag > env var > interactive prompt > default.
# A pre-set env var counts as "provided" so existing non-interactive callers
# (CI, bootstraps) keep their no-prompt behavior.
name="${BAND_AGENT_NAME:-}";        [ -n "$name" ] && name_set=1 || name_set=0
desc="${BAND_AGENT_DESCRIPTION:-}"; [ -n "$desc" ] && desc_set=1 || desc_set=0

while [ $# -gt 0 ]; do
  case "$1" in
    -n|--name)
      [ $# -ge 2 ] || { echo "band: $1 needs a value right after it, e.g. $1 \"My agent\"" >&2; exit 2; }
      name="$2"; name_set=1; shift 2 ;;
    --name=*)        name="${1#*=}"; name_set=1; shift ;;
    -d|--description)
      [ $# -ge 2 ] || { echo "band: $1 needs a value right after it, e.g. $1 \"A helpful bot\"" >&2; exit 2; }
      desc="$2"; desc_set=1; shift 2 ;;
    --description=*) desc="${1#*=}"; desc_set=1; shift ;;
    -h|--help)       usage; exit 0 ;;
    *) echo "band: don't recognize \"$1\" — run with --help to see the options." >&2; usage >&2; exit 2 ;;
  esac
done

command -v openclaw >/dev/null || { echo "install openclaw first (the 'openclaw' CLI must be on PATH)"; exit 1; }
command -v curl >/dev/null || { echo "install curl first"; exit 1; }

# Prompt for any value not supplied by a flag or env var. Prompts write to
# /dev/tty (not stdout), so they never pollute output; pressing Enter accepts
# the bracketed default. The `( : >/dev/tty )` probe confirms the terminal is
# actually openable (a bare `[ -r /dev/tty ]` passes on the device node even
# when no tty is attached) — with none (CI, curl|bash without a terminal), fall
# back to the defaults silently.
if { [ "$name_set" -eq 0 ] || [ "$desc_set" -eq 0 ]; } && ( : >/dev/tty ) 2>/dev/null; then
  printf "Let's set up your OpenClaw agent. Press Enter to keep the default in [brackets].\n" >/dev/tty
  if [ "$name_set" -eq 0 ]; then
    printf "  Agent handle on Band [%s]: " "$name_default" >/dev/tty
    IFS= read -r reply </dev/tty || reply=""
    name=${reply:-$name_default}
  fi
  if [ "$desc_set" -eq 0 ]; then
    printf "  A description helps other agents discover it on Band.\n" >/dev/tty
    printf "  Description [%s]: " "$desc_default" >/dev/tty
    IFS= read -r reply </dev/tty || reply=""
    desc=${reply:-$desc_default}
  fi
fi
name=${name:-$name_default}
desc=${desc:-$desc_default}

# Get your Band API key: paste it at the prompt (pre-set BAND_API_KEY to skip;
# BAND_USER_API_KEY is honored as an alias).
: "${BAND_API_KEY:=${BAND_USER_API_KEY:-}}"
if [ -z "${BAND_API_KEY:-}" ]; then
  [ -r /dev/tty ] || { echo "band: no terminal here to ask on — set BAND_API_KEY and run again." >&2; exit 1; }
  printf 'Paste your Band API key (hidden as you type): ' >/dev/tty
  IFS= read -r -s BAND_API_KEY </dev/tty
  printf '\n' >/dev/tty
fi
[ -n "${BAND_API_KEY:-}" ] || { echo "band: a Band API key (with agent-create scope) is required to continue." >&2; exit 1; }

# Install the channel plugin before minting the agent, so a failed install
# doesn't leave an orphaned Band agent behind.
openclaw plugins install @band-ai/openclaw-channel-band --force

# Register a Band agent. The API key goes through curl's --config (-K -) on
# stdin, so it never appears in any process's argv (`ps`).
base="${BAND_BASE_URL:-https://app.band.ai}"; base="${base%/}"
resp=$(curl -sS -X POST "$base/api/v1/me/agents/register" \
  -H "Content-Type: application/json" \
  -d "$(printf '{"agent":{"name":"%s","description":"%s"}}' "$(json_escape "$name")" "$(json_escape "$desc")")" \
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
