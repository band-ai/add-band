#!/usr/bin/env bash
# Connect this machine's Hermes agent to Band, then hand off setup to the add-band skill.
set -euo pipefail

# Locate the `hermes` entrypoint. Hosted/managed Hermes runtimes (e.g. Nous
# Research) install to a fixed prefix like /opt/hermes/bin that a non-login
# shell's PATH usually doesn't include, so a bare `command -v hermes` fails even
# though Hermes is installed and the run dies with a misleading "install hermes
# first". Honor an explicit HERMES_BIN override, then PATH, then a short list of
# well-known install locations.
find_hermes() {
  if [ -n "${HERMES_BIN:-}" ]; then
    [ -x "$HERMES_BIN" ] && { printf '%s' "$HERMES_BIN"; return 0; }
    echo "HERMES_BIN=$HERMES_BIN is not an executable file" >&2; return 1
  fi
  local p
  p="$(command -v hermes 2>/dev/null)" && { printf '%s' "$p"; return 0; }
  for p in \
    /opt/hermes/bin/hermes \
    "${HOME:-}/.hermes/bin/hermes" \
    "${HOME:-}/.local/bin/hermes" \
    /usr/local/bin/hermes \
    /opt/homebrew/bin/hermes; do
    [ -x "$p" ] && { printf '%s' "$p"; return 0; }
  done
  return 1
}
hermes_bin="$(find_hermes)" || {
  echo "can't find the 'hermes' command. If Hermes lives somewhere unusual, set HERMES_BIN=/path/to/hermes and re-run; otherwise install hermes first." >&2
  exit 1
}
# Put the resolved dir on PATH so the bare `hermes ...` calls later in this
# script resolve even when Hermes wasn't on PATH to begin with. Do this before
# the uv check so a hermes that bundles uv alongside it (common on hosted
# runtimes) is found too.
case ":$PATH:" in
  *":$(dirname "$hermes_bin"):"*) ;;
  *) PATH="$(dirname "$hermes_bin"):$PATH"; export PATH ;;
esac

command -v uv >/dev/null || { echo "install uv first: https://docs.astral.sh/uv/"; exit 1; }
command -v hermes >/dev/null || { echo "install hermes first"; exit 1; }
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

# Install the band platform as a Hermes DIRECTORY plugin via the repo's
# installer. Everything lands under $HERMES_HOME (default ~/.hermes): plugin
# files in plugins/band/, its band-sdk dependency in band-libs/ (resolved with
# the gateway's own interpreter so the wheels match, installed with --target).
# Nothing is written to the gateway's venv — hosted runtimes mount it
# read-only (e.g. root-owned /opt/hermes/.venv), where a pip install into the
# gateway Python dies with Permission denied. The installer is idempotent and
# also runs `hermes plugins enable band` (directory plugins are CLI-native, no
# config fallback needed).
hermes_home="${HERMES_HOME:-$HOME/.hermes}"
BAND_HERMES_REF="${BAND_HERMES_REF:-main}"
clone_dir="$(mktemp -d)"
trap 'rm -rf "$clone_dir"' EXIT
git clone --quiet --depth 1 --branch "$BAND_HERMES_REF" \
  https://github.com/band-ai/hermes-band-platform "$clone_dir/hermes-band-platform"
"$clone_dir/hermes-band-platform/install.sh"

# Band agent names must be unique per account, so a bare default collides on a
# second run (or with anyone else's "Hermes Agent") as "name has been taken".
# Offer a name with a unique default; pre-set BAND_AGENT_NAME to skip the prompt.
if [ -z "${BAND_AGENT_NAME:-}" ]; then
  default_name="Hermes Agent ($(hostname -s 2>/dev/null || echo local) $(date +%Y%m%d-%H%M%S))"
  if [ -r /dev/tty ]; then
    printf 'Agent name [%s]: ' "$default_name" >/dev/tty
    IFS= read -r BAND_AGENT_NAME </dev/tty
  fi
  BAND_AGENT_NAME="${BAND_AGENT_NAME:-$default_name}"
fi
export BAND_AGENT_NAME

# Mint the Band agent with the helper the installed plugin ships — resolved by
# path under $HERMES_HOME, no Python package import, no SDK. The helper reads
# the user key from the environment (never argv), saves only the agent-scoped
# credentials through Hermes's env writer, and never prints the user key.
skill_dir="$hermes_home/plugins/band/skills/add-band"
[ -f "$skill_dir/scripts/register_agent.py" ] || { echo "add-band skill missing at $skill_dir (install failed?)" >&2; exit 1; }
# Same gateway-interpreter resolution the installer uses (HERMES_PY overrides).
if [ -z "${HERMES_PY:-}" ]; then
  for py in python3 python; do
    command -v "$py" >/dev/null || continue
    if HERMES_PY="$("$py" "$skill_dir/scripts/gateway_python.py" --print)"; then
      break
    fi
    HERMES_PY=""
  done
  [ -n "${HERMES_PY:-}" ] || { echo "could not resolve the gateway Python; set HERMES_PY and re-run" >&2; exit 1; }
fi
"$HERMES_PY" "$skill_dir/scripts/register_agent.py"
unset BAND_API_KEY

# Hand off to the agent: the add-band skill restarts the gateway, wires Band in
# as a comms channel, bootstraps the hub, and sends you the agent's first
# message — the steps that need agent smarts, not bash. The band plugin
# namespaces its skills, so the skill resolves as `band:add-band`, not the bare
# `add-band` (plugin skills never enter the flat ~/.hermes/skills tree).
hermes chat -s band:add-band < /dev/tty
