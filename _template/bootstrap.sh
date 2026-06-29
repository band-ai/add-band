#!/usr/bin/env bash
# Connect this machine's <Harness> agent to Band. Run where the agent runs.
#
# Author this in whatever shape fits the harness — clone a repo and hand it a
# skill, run a couple of curls + a CLI, install an SDK, etc. Keep it thin: fetch
# the integration's real artifact and hand off; the heavy lifting lives upstream.
#
# The ONE rule: the script must obtain the Band API key itself. Prompt for it
# from /dev/tty when BAND_API_KEY is unset (curl|bash makes stdin the script),
# or accept it pre-set in the env. check.py asserts the snippet references BAND_API_KEY.
#
# The whole script is what the web app serves behind a `curl … | bash` one-liner,
# so keep it thin and readable.
set -e

# Get the Band API key: prompt for it (or accept a pre-set BAND_API_KEY,
# also honoring BAND_USER_API_KEY as an alias).
: "${BAND_API_KEY:=${BAND_USER_API_KEY:-}}"
if [ -z "${BAND_API_KEY:-}" ]; then
  [ -r /dev/tty ] || { echo "no terminal for the API key prompt; set BAND_API_KEY and re-run" >&2; exit 1; }
  printf 'Paste your Band API key: ' >/dev/tty
  IFS= read -r -s BAND_API_KEY </dev/tty
  printf '\n' >/dev/tty
fi
[ -n "${BAND_API_KEY:-}" ] || { echo "Band API key required" >&2; exit 1; }
export BAND_API_KEY

# ... your connect steps ...
echo "TODO: replace with the real <Harness> connect steps"
