#!/usr/bin/env bash
# Connect this machine's NanoClaw agent to Band.
#
# NanoClaw's Band channel is fork-shaped: the adapter, SDK tools, and add-band
# skill ship in the Band-ready NanoClaw fork, not in this catalog. This snippet
# connects an existing NanoClaw install to Band — or stands one up if there's
# none. NanoClaw is a global, service-managed install, not a checkout in the
# current directory, so we locate it the way the host does: from the running
# service's recorded working directory, then the ncl CLI symlink, then the
# documented default path. Each candidate is validated as a real checkout before
# we trust it. It is adoption-first and interactive:
#   - inside the Band fork's own checkout       -> use it in place
#   - an install found via service/symlink/path -> repoint origin at the fork
#                                                  and sync the skill + scripts
#   - nothing found                             -> ask for the path; clone there,
#                                                  or to the default
#                                                  ($HOME/agents/nanoclaw-band)
#                                                  when left blank
# It then registers a Band agent with your user key (prompting for a name when
# the install doesn't already have one), writes the agent credentials, and hands
# off interactively to the fork's add-band skill for setup and room wiring.
#
# The user key is consumed once and never written to disk. Override the source
# repo with BAND_REPO and the clone/install location with BAND_DIR.
set -e

# The user key arrives pre-exported by the snippet the web app hands you
# (export BAND_USER_API_KEY=… && <this script>), possibly under the name
# BAND_API_KEY. Consume whichever is set; if neither is, prompt for it.
export BAND_USER_API_KEY="${BAND_USER_API_KEY:-${BAND_API_KEY:-}}"
if [ -z "$BAND_USER_API_KEY" ] && [ -e /dev/tty ]; then
  printf 'Band user API key: ' >/dev/tty
  IFS= read -rs BAND_USER_API_KEY </dev/tty || true
  printf '\n' >/dev/tty
  export BAND_USER_API_KEY
fi
[ -n "$BAND_USER_API_KEY" ] || { echo "band: no Band user API key — set BAND_USER_API_KEY or run interactively." >&2; exit 1; }
export BAND_REPO="${BAND_REPO:-https://github.com/band-ai/nanoclaw-band}"

# --- locate (or create) the Band-ready checkout -----------------------------
is_nanoclaw() { [ -f "$1/package.json" ] && grep -q '"name": *"nanoclaw"' "$1/package.json" 2>/dev/null; }
origin_of() { git -C "$1" remote get-url origin 2>/dev/null || true; }

default_dir="${BAND_DIR:-$HOME/agents/nanoclaw-band}"

# Read WorkingDirectory out of a launchd plist we wrote — PlistBuddy first, with
# a text parse fallback for the XML template setup emits.
plist_workdir() {
  /usr/libexec/PlistBuddy -c 'Print :WorkingDirectory' "$1" 2>/dev/null && return 0
  awk '/<key>WorkingDirectory<\/key>/{getline; gsub(/.*<string>|<\/string>.*/,""); print; exit}' "$1" 2>/dev/null
}

# Find where NanoClaw actually runs. It installs as a per-root service
# (com.nanoclaw-v2-<slug> / nanoclaw-v2-<slug>) whose definition records the
# project root — the host's own source of truth — so try that first, then the
# ncl CLI symlink setup installs ($root/bin/ncl), then the documented default.
# We can't know which location is live up front, so probe in order of authority
# and accept the first candidate that's a real checkout.
discover_install() {
  local root label unit plist

  if command -v launchctl >/dev/null 2>&1; then          # macOS / launchd
    for label in $(launchctl list 2>/dev/null | awk '/com\.nanoclaw-v2-/ {print $NF}'); do
      plist="$HOME/Library/LaunchAgents/$label.plist"
      [ -f "$plist" ] || continue
      root="$(plist_workdir "$plist")" || root=""
      is_nanoclaw "$root" && { printf '%s\n' "$root"; return 0; }
    done
  fi

  if command -v systemctl >/dev/null 2>&1; then           # Linux / systemd
    for unit in $(systemctl --user list-units --all --no-legend 'nanoclaw-v2-*' 2>/dev/null | awk '{print $1}'); do
      root="$(systemctl --user show -p WorkingDirectory --value "$unit" 2>/dev/null)" || root=""
      is_nanoclaw "$root" && { printf '%s\n' "$root"; return 0; }
    done
  fi

  if [ -L "$HOME/.local/bin/ncl" ]; then                  # ncl symlink -> $root/bin/ncl
    root="$(cd "$(dirname "$(dirname "$(readlink "$HOME/.local/bin/ncl")")")" 2>/dev/null && pwd)" || root=""
    is_nanoclaw "$root" && { printf '%s\n' "$root"; return 0; }
  fi

  is_nanoclaw "$default_dir" && { printf '%s\n' "$default_dir"; return 0; }   # documented default
  return 1
}

# Repoint an existing NanoClaw checkout at the Band fork and overlay the add-band
# skill + scripts. A cross-fork `pull --ff-only` would fail on divergent history,
# so fetch and check out just those paths — history and local config untouched.
sync_band() {
  if [ -n "$(git -C "$1" status --short 2>/dev/null)" ]; then
    echo "band: $1 has uncommitted changes — commit or stash them, then re-run." >&2
    exit 1
  fi
  echo "band: pointing $1 at $BAND_REPO and syncing the add-band skill + scripts…"
  git -C "$1" remote set-url origin "$BAND_REPO" 2>/dev/null || git -C "$1" remote add origin "$BAND_REPO"
  git -C "$1" fetch --depth 1 origin main
  git -C "$1" checkout FETCH_HEAD -- .claude/skills/add-band scripts 2>/dev/null || true
}

if [ -f src/channels/band.ts ]; then
  dir="$PWD"                                          # inside the Band fork's own checkout
elif dir="$(discover_install)"; then
  :                                                   # found the host's NanoClaw install
else
  dir="$default_dir"                                  # nothing found — ask, then adopt or clone
  if [ -e /dev/tty ]; then
    printf 'NanoClaw install not found. Path to it (blank = clone to %s): ' "$default_dir" >/dev/tty
    IFS= read -r reply </dev/tty || true
    dir="${reply:-$default_dir}"
  fi
  if ! is_nanoclaw "$dir"; then
    mkdir -p "$(dirname "$dir")"
    git clone --depth 1 --branch main "$BAND_REPO" "$dir"
  fi
fi

# Whatever we landed on, make sure it points at the Band fork before we use it.
[ "$(origin_of "$dir")" = "$BAND_REPO" ] || sync_band "$dir"
cd "$dir"

# --- register the Band agent -------------------------------------------------
# A NanoClaw agent is named; reuse the existing name when this install already
# has one. On a fresh clone data/v2.db won't exist, so register-agent.sh prompts.
existing_name=""
if [ -f data/v2.db ] && command -v pnpm >/dev/null 2>&1; then
  existing_name="$(pnpm exec tsx scripts/q.ts data/v2.db 'SELECT name FROM agent_groups LIMIT 1' 2>/dev/null || true)"
fi

unset BAND_API_KEY   # drop the alias before registration so a failure can't leak the user key as the agent key
if [ -n "$existing_name" ]; then
  eval "$(bash .claude/skills/add-band/scripts/register-agent.sh --name "$existing_name")"
else
  eval "$(bash .claude/skills/add-band/scripts/register-agent.sh)"
fi
unset BAND_USER_API_KEY

# Persist the agent identity + key — the host's Band connection credential, kept
# like TELEGRAM_BOT_TOKEN and every other channel token. Replace any prior values
# rather than appending duplicates on re-run.
touch .env
grep -vE '^BAND_(AGENT_ID|API_KEY)=' .env > .env.band.tmp 2>/dev/null || true
{ cat .env.band.tmp; echo "BAND_AGENT_ID=$BAND_AGENT_ID"; echo "BAND_API_KEY=$BAND_API_KEY"; } > .env
rm -f .env.band.tmp
mkdir -p data/env && cp .env data/env/env
echo "band: registered agent $BAND_AGENT_ID in $dir; credentials written to .env"

# --- hand off to the add-band skill (interactive) ----------------------------
if command -v claude >/dev/null 2>&1; then
  claude /add-band
else
  echo "band: Claude Code isn't installed. Install it from https://claude.ai/code, then run:" >&2
  echo "        cd \"$dir\" && claude /add-band" >&2
  echo "      Setup steps live in $dir/.claude/skills/add-band/SKILL.md" >&2
  exit 1
fi
