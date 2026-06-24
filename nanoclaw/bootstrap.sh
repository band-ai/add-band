#!/usr/bin/env bash
# Connect this machine's NanoClaw agent to Band.
#
# NanoClaw's Band channel is fork-shaped: the channel setup and add-band skill
# live in the Band-ready NanoClaw fork, not in this catalog. This snippet clones
# or updates that fork, registers a Band agent with your Band API key, writes the
# agent-scoped credentials into the cloned checkout, then hands off to the
# fork's skill. The skill can focus on walking the user through the remaining
# NanoClaw-side connection steps.
#
# NANOCLAW_HOME pins the install location; when unset we discover where NanoClaw
# actually runs — its launchd/systemd service definition, then the ncl CLI
# symlink, then the default $HOME/nanoclaw-band — so a service-managed install at
# any path is adopted rather than duplicated.
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
# Resolve NANOCLAW_HOME. An explicit value wins; otherwise discover where
# NanoClaw actually runs. It installs as a per-root service whose definition
# records the project root (launchd com.nanoclaw-v2-<slug> / systemd
# nanoclaw-v2-<slug>), so probe that first, then the ncl CLI symlink
# ($root/bin/ncl), then the default path — accepting the first that is a real
# checkout. Falls back to the default for a fresh clone below.
nanoclaw_default="$HOME/nanoclaw-band"
is_nanoclaw() { [ -f "$1/package.json" ] && grep -q '"name": *"nanoclaw"' "$1/package.json" 2>/dev/null; }
plist_workdir() {
  /usr/libexec/PlistBuddy -c 'Print :WorkingDirectory' "$1" 2>/dev/null && return 0
  awk '/<key>WorkingDirectory<\/key>/{getline; gsub(/.*<string>|<\/string>.*/,""); print; exit}' "$1" 2>/dev/null
}
discover_nanoclaw() {
  local root label unit plist
  if command -v launchctl >/dev/null 2>&1; then          # macOS / launchd
    for label in $(launchctl list 2>/dev/null | awk '/com\.nanoclaw-v2-/ {print $NF}' || true); do
      plist="$HOME/Library/LaunchAgents/$label.plist"
      [ -f "$plist" ] || continue
      root="$(plist_workdir "$plist")" || root=""
      is_nanoclaw "$root" && { printf '%s\n' "$root"; return 0; }
    done
  fi
  if command -v systemctl >/dev/null 2>&1; then           # Linux / systemd
    for unit in $(systemctl --user list-units --all --no-legend 'nanoclaw-v2-*' 2>/dev/null | awk '{print $1}' || true); do
      root="$(systemctl --user show -p WorkingDirectory --value "$unit" 2>/dev/null)" || root=""
      is_nanoclaw "$root" && { printf '%s\n' "$root"; return 0; }
    done
  fi
  if [ -L "$HOME/.local/bin/ncl" ]; then                  # ncl symlink -> $root/bin/ncl
    root="$(cd "$(dirname "$(dirname "$(readlink "$HOME/.local/bin/ncl")")")" 2>/dev/null && pwd)" || root=""
    is_nanoclaw "$root" && { printf '%s\n' "$root"; return 0; }
  fi
  is_nanoclaw "$nanoclaw_default" && { printf '%s\n' "$nanoclaw_default"; return 0; }
  return 1
}
if [ -z "${NANOCLAW_HOME:-}" ]; then
  NANOCLAW_HOME="$(discover_nanoclaw || true)"
  [ -n "$NANOCLAW_HOME" ] || NANOCLAW_HOME="$nanoclaw_default"
fi
export NANOCLAW_HOME
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
