#!/usr/bin/env bash
# Connect this machine's <Harness> agent to Band. Run where the agent runs.
#
# Author this in whatever shape fits the harness — clone a repo and hand it a
# skill, run a couple of curls + a CLI, install an SDK, etc. Keep it thin: fetch
# the integration's real artifact and hand off; the heavy lifting lives upstream.
#
# The ONE rule the web app relies on: consume the user's key from the
# BAND_USER_API_KEY environment variable. The web app hands the user a snippet
# that exports it before running this script; prompt for it when it's absent so a
# copy-pasted run still works. Never bake the key into this committed file.
set -e

# Acquire the Band user API key: env first (the web app's snippet exports it),
# else an interactive prompt. Reusable as-is.
export BAND_USER_API_KEY="${BAND_USER_API_KEY:-}"
if [ -z "$BAND_USER_API_KEY" ] && [ -e /dev/tty ]; then
  printf 'Band user API key: ' >/dev/tty
  IFS= read -rs BAND_USER_API_KEY </dev/tty || true
  printf '\n' >/dev/tty
  export BAND_USER_API_KEY
fi
[ -n "$BAND_USER_API_KEY" ] || { echo "band: no Band user API key — set BAND_USER_API_KEY or run interactively." >&2; exit 1; }

# ... your connect steps (use "$BAND_USER_API_KEY" to register the agent) ...
echo "TODO: replace with the real <Harness> connect steps"
