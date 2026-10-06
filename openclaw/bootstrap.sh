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

# Agent names are unique per account, so a fixed default fails with HTTP 422
# ("name has been taken") on the second registration. Host + timestamp keeps the
# default unique per run and inside Band's name rules (3-100 chars, no @ or /).
name_default="OpenClaw Agent ($(hostname -s 2>/dev/null || echo local) $(date +%Y%m%d-%H%M%S))"
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

The Band API key is read from \$BAND_USER_API_KEY or \$BAND_API_KEY
(\$BAND_USER_API_KEY wins when both are set), or pasted at the prompt.
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
if command -v jq >/dev/null 2>&1; then
  json_parser=jq
elif command -v python3 >/dev/null 2>&1; then
  json_parser=python3
else
  echo "install jq or python3 first (needed to read the registration response)" >&2
  exit 1
fi

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

# Get your Band API key: paste it at the prompt (pre-set BAND_USER_API_KEY or
# BAND_API_KEY to skip). BAND_USER_API_KEY wins when both are set — a stale
# agent-scoped BAND_API_KEY must not hijack the user-scoped key. The key is held
# in an unexported shell variable and both names leave the environment at once, so
# no openclaw process (plugin install, gateway) inherits it; only curl's stdin
# config below sees it.
band_user_key="${BAND_USER_API_KEY:-${BAND_API_KEY:-}}"
unset BAND_USER_API_KEY BAND_API_KEY
if [ -z "$band_user_key" ]; then
  [ -r /dev/tty ] || { echo "band: no terminal here to ask on — set BAND_USER_API_KEY and run again." >&2; exit 1; }
  printf 'Paste your Band API key (hidden as you type): ' >/dev/tty
  IFS= read -r -s band_user_key </dev/tty
  printf '\n' >/dev/tty
fi
[ -n "$band_user_key" ] || { echo "band: a Band API key (with agent-create scope) is required to continue." >&2; exit 1; }

# Install the channel plugin before minting the agent, so a failed install
# doesn't leave an orphaned Band agent behind. OpenClaw releases that gate plugin
# capabilities refuse a non-interactive install without --accept-capabilities;
# older releases in the plugin's peer range reject that flag, so pass it only when
# this CLI's own help offers it. (Help is captured, not piped into `grep -q`: an
# early grep exit would SIGPIPE openclaw and fail the pipeline under pipefail.)
install_help=$(openclaw plugins install --help 2>&1 || true)
consent_flag=""
case "$install_help" in *--accept-capabilities*) consent_flag=--accept-capabilities ;; esac
openclaw plugins install @band-ai/openclaw-channel-band --force ${consent_flag:+"$consent_flag"}

# Register a Band agent. The API key goes through curl's --config (-K -) on
# stdin, so it never appears in any process's argv (`ps`).
base="${BAND_BASE_URL:-https://app.band.ai}"; base="${base%/}"
resp=$(curl -sS -X POST "$base/api/v1/me/agents/register" \
  -H "Content-Type: application/json" \
  -d "$(printf '{"agent":{"name":"%s","description":"%s"}}' "$(json_escape "$name")" "$(json_escape "$desc")")" \
  -w $'\n%{http_code}' -K - <<EOF
header = "X-API-Key: $band_user_key"
EOF
) || true
unset band_user_key

code=${resp##*$'\n'}; out=${resp%$'\n'*}
case "$code" in
  200 | 201) ;;
  *) echo "agent registration failed (HTTP ${code:-?}): $(printf '%.300s' "$out")" >&2; exit 1 ;;
esac

case "$json_parser" in
  jq)
    AGENT_ID=$(printf '%s' "$out" | jq -r '.data.agent.id // empty')
    AGENT_KEY=$(printf '%s' "$out" | jq -r '.data.credentials.api_key // empty')
    ;;
  python3)
    read -r AGENT_ID AGENT_KEY < <(printf '%s' "$out" | python3 -c \
      'import sys, json; d = json.load(sys.stdin); print(d["data"]["agent"]["id"], d["data"]["credentials"]["api_key"])')
    ;;
esac
[ -n "${AGENT_ID:-}" ] && [ -n "${AGENT_KEY:-}" ] || { echo "agent registration failed (no credentials returned)" >&2; exit 1; }

openclaw channels add --channel openclaw-channel-band --account "$AGENT_ID" --token "$AGENT_KEY"
openclaw config set "channels.openclaw-channel-band.accounts.$AGENT_ID.agentId" "$AGENT_ID"

# The plugin's config schema declares app.band.ai defaults for wsUrl/restUrl.
# Schema defaulting fills those into the account object before the plugin's own
# BAND_WS_URL/BAND_REST_URL env-var fallback ever runs, so exporting those env
# vars alone silently has no effect — set the account fields explicitly, derived
# from the same $base used to register.
case "$base" in
  https://*) default_ws_url="wss://${base#https://}/api/v1/socket/websocket" ;;
  http://*) default_ws_url="ws://${base#http://}/api/v1/socket/websocket" ;;
  *) default_ws_url="ws://${base}/api/v1/socket/websocket" ;;
esac
openclaw config set "channels.openclaw-channel-band.accounts.$AGENT_ID.wsUrl" "${BAND_WS_URL:-$default_ws_url}"
openclaw config set "channels.openclaw-channel-band.accounts.$AGENT_ID.restUrl" "$base"

# A from-scratch host (this script's target — no prior `openclaw onboard`) has no
# gateway.mode set, and the gateway refuses to start at all without it. Set it only
# if unset, so a host that already ran onboard keeps its own choice.
openclaw config get gateway.mode >/dev/null 2>&1 || openclaw config set gateway.mode local

# Restart the gateway so it loads the plugin and the new account. A host with no
# installed gateway service (fresh install, container) has nothing to restart:
# newer CLIs report "Gateway service disabled." and exit non-zero. Registration
# and config are already done by then, so that outcome ends with how to start the
# gateway instead of an error; any other restart failure stays fatal. The service
# state comes from `gateway status --json`; if it can't be read, the restart's own
# exit status stands.
gateway_service_missing() {
  local status loaded
  status=$(openclaw gateway status --json --no-probe 2>/dev/null) || return 1
  case "$json_parser" in
    jq) loaded=$(printf '%s' "$status" | jq -r '.service.loaded' 2>/dev/null) || return 1 ;;
    python3) loaded=$(printf '%s' "$status" | python3 -c \
      'import sys, json; print(json.dumps(json.load(sys.stdin)["service"]["loaded"]))' 2>/dev/null) || return 1 ;;
  esac
  [ "$loaded" = false ]
}
restart_rc=0
openclaw gateway restart || restart_rc=$?
gateway_note=""
if [ "$restart_rc" -ne 0 ]; then
  gateway_service_missing || exit "$restart_rc"
  gateway_note="No gateway service is installed, so nothing was restarted. Start the gateway to bring the agent online:
  openclaw gateway install   # install and start it as a background service
  openclaw gateway run       # or run it in the foreground"
fi
echo "Registered agent $AGENT_ID. Channel wired; the openclaw CLI stored its credentials."
[ -z "$gateway_note" ] || printf '%s\n' "$gateway_note"
