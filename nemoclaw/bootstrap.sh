#!/usr/bin/env bash
# Connect an OpenClaw agent running inside a NemoClaw sandbox to Band. Run where
# NemoClaw runs — NemoClaw itself, Docker Desktop or Colima, and ANTHROPIC_API_KEY
# must already be in place; see the Prereqs in README.md.
#
# Onboards a fresh NemoClaw sandbox on the Anthropic provider (non-interactive),
# applies the Band OpenClaw plugin's egress policy, installs the plugin, mints a
# Band agent from your Band API key (inline curl — no cloned repo), and wires
# that agent in as the sandbox's Band channel account. Sandbox setup runs before
# agent registration, so a failed onboard never leaves an orphaned Band agent.
#
# Usage:
#   ANTHROPIC_API_KEY=sk-ant-... bootstrap.sh                     # prompts for name + description
#   ANTHROPIC_API_KEY=sk-ant-... bootstrap.sh --name MyBot --sandbox my-band-demo
#   curl … | ANTHROPIC_API_KEY=sk-ant-... bash -s -- --name MyBot # pass flags through a piped one-liner
#
# Flags (name/description are optional and skip their prompt; sandbox always has a default):
#   -n, --name NAME             agent name
#   -d, --description DESC      agent description
#   -s, --sandbox NAME          NemoClaw sandbox name (default: band-demo). Must be
#                                lowercase, start with a letter, and contain only
#                                letters, numbers, and single internal hyphens.
#   -h, --help                  show usage and exit
#
# Env knobs: BAND_BASE_URL (default https://app.band.ai), BAND_AGENT_NAME,
#            BAND_AGENT_DESCRIPTION (set either to skip its prompt).
set -euo pipefail

name_default="NemoClawBandAgent"
desc_default="OpenClaw agent in a NemoClaw sandbox, on Band"
sandbox_default="band-demo"
plugin_version="0.2.1"

usage() {
  cat <<USAGE
Connect an OpenClaw agent inside a NemoClaw sandbox to Band.

Usage:
  bootstrap.sh [--name NAME] [--description DESC] [--sandbox NAME]

Options:
  -n, --name NAME            agent name (prompted if omitted)
  -d, --description DESC     agent description (prompted if omitted)
  -s, --sandbox NAME         NemoClaw sandbox name (default: band-demo)
  -h, --help                 show this help and exit

The Band API key is read from \$BAND_API_KEY (or \$BAND_USER_API_KEY), or
pasted at the prompt. \$ANTHROPIC_API_KEY must already be exported — the
sandbox onboards on the Anthropic provider.
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
sandbox="$sandbox_default"

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
    -s|--sandbox)
      [ $# -ge 2 ] || { echo "band: $1 needs a value right after it, e.g. $1 my-band-demo" >&2; exit 2; }
      sandbox="$2"; shift 2 ;;
    --sandbox=*)      sandbox="${1#*=}"; shift ;;
    -h|--help)        usage; exit 0 ;;
    *) echo "band: don't recognize \"$1\" — run with --help to see the options." >&2; usage >&2; exit 2 ;;
  esac
done

command -v nemoclaw >/dev/null || { echo "install NemoClaw first: curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash (the 'nemoclaw' CLI must be on PATH)" >&2; exit 1; }
command -v curl >/dev/null || { echo "install curl first" >&2; exit 1; }
[ -n "${ANTHROPIC_API_KEY:-}" ] || { echo "band: export ANTHROPIC_API_KEY first — this sandbox onboards on the Anthropic provider." >&2; exit 1; }
if command -v jq >/dev/null 2>&1; then
  json_parser=jq
elif command -v python3 >/dev/null 2>&1; then
  json_parser=python3
else
  echo "install jq or python3 first (needed to read the registration response)" >&2
  exit 1
fi

nemoclaw host probe >/dev/null || { echo "band: 'nemoclaw host probe' failed — start Docker Desktop or Colima (not OrbStack, which NemoClaw rejects) and retry." >&2; exit 1; }

# Prompt for any value not supplied by a flag or env var. Prompts write to
# /dev/tty (not stdout), so they never pollute output; pressing Enter accepts
# the bracketed default. The `( : >/dev/tty )` probe confirms the terminal is
# actually openable (a bare `[ -r /dev/tty ]` passes on the device node even
# when no tty is attached) — with none (CI, curl|bash without a terminal), fall
# back to the defaults silently.
if { [ "$name_set" -eq 0 ] || [ "$desc_set" -eq 0 ]; } && ( : >/dev/tty ) 2>/dev/null; then
  printf "Let's set up your NemoClaw OpenClaw agent. Press Enter to keep the default in [brackets].\n" >/dev/tty
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

echo "Onboarding NemoClaw sandbox '$sandbox' (OpenClaw agent, Anthropic provider)..."
NEMOCLAW_PROVIDER=anthropic NEMOCLAW_SANDBOX_NAME="$sandbox" \
  nemoclaw onboard --agent openclaw --name "$sandbox" --non-interactive --yes-i-accept-third-party-software

echo "Applying the Band egress policy..."
policy_file="$(mktemp)"
curl -fsSL -o "$policy_file" \
  "https://raw.githubusercontent.com/band-ai/band-sdk-typescript/main/packages/openclaw/examples/nemoclaw/presets/band.yaml"
nemoclaw "$sandbox" policy add --from-file "$policy_file" --yes
rm -f "$policy_file"

echo "Installing the Band channel plugin ($plugin_version)..."
nemoclaw "$sandbox" exec -- env HOME=/sandbox openclaw plugins install "@band-ai/openclaw-channel-band@${plugin_version}" --force

# The published 0.2.1 package omits its required WebAssembly file. Repair it from
# the matching @band-ai/band-sdk-core release until a later plugin release ships
# it directly.
nemoclaw "$sandbox" exec -- env HOME=/sandbox bash -c '
  set -euo pipefail
  plugin_dir="$(openclaw plugins inspect openclaw-channel-band --json | node -e "
    const input = require(\"node:fs\").readFileSync(0, \"utf8\");
    const json = input.slice(input.indexOf(\"{\"));
    process.stdout.write(JSON.parse(json).plugin.rootDir);
  ")"
  tmp_dir="$(mktemp -d)"
  archive="$(npm pack @band-ai/band-sdk-core@2.0.0 --pack-destination "$tmp_dir" --silent)"
  tar -xOf "$tmp_dir/$archive" package/band_sdk_core_bg.wasm > "$plugin_dir/dist/band_sdk_core_bg.wasm"
  rm -rf "$tmp_dir"
'

# Get your Band API key: paste it at the prompt (pre-set BAND_USER_API_KEY or
# BAND_API_KEY to skip). BAND_USER_API_KEY wins when both are set — a stale
# agent-scoped BAND_API_KEY must not hijack the user-scoped key.
BAND_API_KEY="${BAND_USER_API_KEY:-${BAND_API_KEY:-}}"
if [ -z "${BAND_API_KEY:-}" ]; then
  [ -r /dev/tty ] || { echo "no terminal for the API key prompt; set BAND_API_KEY and re-run" >&2; exit 1; }
  printf 'Paste your Band API key: ' >/dev/tty
  IFS= read -r -s BAND_API_KEY </dev/tty
  printf '\n' >/dev/tty
fi
[ -n "${BAND_API_KEY:-}" ] || { echo "band: a Band API key (with agent-create scope) is required to continue." >&2; exit 1; }

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

echo "Wiring the Band channel account inside the sandbox..."
nemoclaw "$sandbox" exec -- env HOME=/sandbox openclaw config set channels.openclaw-channel-band.enabled true --strict-json
nemoclaw "$sandbox" exec -- env HOME=/sandbox openclaw config set channels.openclaw-channel-band.accounts.default.enabled true --strict-json
nemoclaw "$sandbox" exec -- env HOME=/sandbox openclaw config set channels.openclaw-channel-band.accounts.default.agentId "$AGENT_ID"
nemoclaw "$sandbox" exec -- env HOME=/sandbox openclaw config set channels.openclaw-channel-band.accounts.default.apiKey "$AGENT_KEY"
nemoclaw "$sandbox" exec -- env HOME=/sandbox openclaw config set tools.alsoAllow '["bundle-mcp","openclaw-channel-band","message"]' --strict-json
unset AGENT_KEY

nemoclaw "$sandbox" gateway restart
echo "Registered agent $AGENT_ID. Sandbox '$sandbox' is wired; the openclaw CLI stored its credentials."
