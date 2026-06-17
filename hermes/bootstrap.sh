#!/usr/bin/env bash
# Connect this machine's Hermes agent to Band. Run on the gateway host.
set -e
export BAND_USER_API_KEY=YOUR_BAND_KEY   # the web app fills this in
rm -rf /tmp/hbp
git clone --depth 1 --branch main https://github.com/band-ai/hermes-band-platform /tmp/hbp
hermes /add-band 2>/dev/null || cat /tmp/hbp/hermes_band_platform/skills/add-band/SKILL.md
