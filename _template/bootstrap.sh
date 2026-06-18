#!/usr/bin/env bash
# Connect this machine's <Harness> agent to Band. Run where the agent runs.
#
# Author this in whatever shape fits the harness — clone a repo and hand it a
# skill, run a couple of curls + a CLI, install an SDK, etc. Keep it thin: fetch
# the integration's real artifact and hand off; the heavy lifting lives upstream.
#
# The ONE rule the web app relies on: put the user's key behind the literal
# token {{BAND_USER_API_KEY}} (in an env export, a CLI flag, a config write — your call).
set -e

# ... your connect steps ...
export BAND_API_KEY={{BAND_USER_API_KEY}}   # the web app fills this in
echo "TODO: replace with the real <Harness> connect steps"
