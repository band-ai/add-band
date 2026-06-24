#!/usr/bin/env bash
# Connect this machine's NanoClaw agent to Band.
#
# NanoClaw's Band channel is fork-shaped: the adapter, SDK tools, and add-band
# skill ship in the Band-ready NanoClaw fork, not in this catalog. This snippet
# works against a checkout of that fork. It is adoption-first and interactive:
#   - run from inside a Band-ready checkout       -> use it in place
#   - an existing NanoClaw checkout, other origin -> repoint origin at the fork
#                                                    and sync the skill + scripts
#   - nothing local                               -> ask where to clone (default
#                                                    $HOME/agents/nanoclaw-band)
# It then registers a Band agent with your user key (prompting for a name when
# the install doesn't already have one), writes the agent credentials, and hands
# off interactively to the fork's add-band skill for setup and room wiring.
#
# The user key is consumed once and never written to disk. Override the source
# repo with BAND_REPO and the clone location with BAND_DIR.
set -e

# The user key arrives pre-exported by the runner (export BAND_USER_API_KEY=… &&
# <script>), possibly under the name BAND_API_KEY. Consume whichever is set and
# don't clobber it; fall back to the placeholder the web app fills in.
export BAND_USER_API_KEY="${BAND_USER_API_KEY:-${BAND_API_KEY:-}}"
[ -n "$BAND_USER_API_KEY" ] || export BAND_USER_API_KEY={{BAND_USER_API_KEY}}   # the web app fills this in
export BAND_REPO="${BAND_REPO:-https://github.com/band-ai/nanoclaw-band}"

# --- locate (or create) the Band-ready checkout -----------------------------
is_nanoclaw() { [ -f "$1/package.json" ] && grep -q '"name": *"nanoclaw"' "$1/package.json" 2>/dev/null; }
origin_of() { git -C "$1" remote get-url origin 2>/dev/null || true; }

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

default_dir="${BAND_DIR:-$HOME/agents/nanoclaw-band}"
if [ -f src/channels/band.ts ]; then
  dir="$PWD"                                          # inside a Band-ready checkout
  [ "$(origin_of "$dir")" = "$BAND_REPO" ] || sync_band "$dir"
elif is_nanoclaw .; then
  dir="$PWD"                                          # a NanoClaw checkout, different upstream
  [ "$(origin_of "$dir")" = "$BAND_REPO" ] || sync_band "$dir"
elif is_nanoclaw "$default_dir"; then
  dir="$default_dir"                                  # a NanoClaw checkout already at the default
  [ "$(origin_of "$dir")" = "$BAND_REPO" ] || sync_band "$dir"
else
  dir="$default_dir"                                  # nothing local — ask, then clone
  if [ -e /dev/tty ]; then
    printf 'Clone the Band fork to [%s]: ' "$default_dir" >/dev/tty
    IFS= read -r reply </dev/tty || true
    dir="${reply:-$default_dir}"
  fi
  mkdir -p "$(dirname "$dir")"
  git clone --depth 1 --branch main "$BAND_REPO" "$dir"
fi
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
