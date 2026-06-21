#!/usr/bin/env bash
# Connect this machine's <Harness> agent to Band. Run where the agent runs.
#
# Author this in whatever shape fits the harness — clone a repo and hand it a
# skill, run a couple of curls + a CLI, install an SDK, etc. Keep it thin: fetch
# the integration's real artifact and hand off; the heavy lifting lives upstream.
#
# The ONE rule: the script must obtain the Band user API key itself. Prompt for it
# from /dev/tty when BAND_USER_API_KEY is unset (curl|bash makes stdin the script),
# or accept it pre-set in the env. check.py asserts the snippet references BAND_USER_API_KEY.
#
# The web app shows a comment-stripped copy-paste version of this script. If it
# runs past ~25 command lines, mark the subset to show with '# >>> band:mini' /
# '# <<< band:mini'; otherwise the whole (comment-stripped) script is the snippet.
# Preview it with `python3 scripts/check.py --mini <harness>`.
set -e

# Get the Band user API key: prompt for it (or accept a pre-set BAND_USER_API_KEY).
if [ -z "${BAND_USER_API_KEY:-}" ]; then
  [ -r /dev/tty ] || { echo "no terminal for the API key prompt; set BAND_USER_API_KEY and re-run" >&2; exit 1; }
  printf 'Paste your Band user API key: ' >/dev/tty
  IFS= read -r -s BAND_USER_API_KEY </dev/tty
  printf '\n' >/dev/tty
fi
[ -n "${BAND_USER_API_KEY:-}" ] || { echo "Band user API key required" >&2; exit 1; }
export BAND_USER_API_KEY

# ... your connect steps ...
echo "TODO: replace with the real <Harness> connect steps"
