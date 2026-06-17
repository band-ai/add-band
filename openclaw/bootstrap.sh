#!/usr/bin/env bash
# Connect this machine's OpenClaw agent to Band. Run on the host OpenClaw runs on.
#
# PLACEHOLDER — these are the *shape* of an OpenClaw connect (a couple of curls,
# then the openclaw CLI does the wiring; no skill, no plugin clone). Replace the
# URLs/commands with OpenClaw's real ones before marking status: available.
set -e

# 1. Fetch what OpenClaw needs to talk to Band (placeholder URLs):
curl -fsSL https://openclaw.example/band/install.sh | bash
curl -fsSL https://openclaw.example/band/band.json -o "${HOME}/.openclaw/band.json"

# 2. Let the openclaw CLI finish wiring the agent into Band:
openclaw plugin add band
openclaw config set band.api_key YOUR_BAND_KEY   # the web app fills this in
openclaw restart
