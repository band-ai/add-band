# NanoClaw ↔ Band

## What it connects

Connects a **NanoClaw** agent to Band — Band rooms/chats, plus the SDK-backed
`band_*` platform tools. The channel registers as `band`, platform IDs use the
`band:` prefix, and config lives in `BAND_*` env vars.
NanoClaw's Band channel is **fork-shaped**: it touches core host and container
files, not a single adapter. So the on-ramp clones the Band-ready NanoClaw fork
instead of patching an arbitrary checkout. That fork owns the channel setup,
common scripts, and `add-band` skill; this catalog only points users at it.

## Bootstrap

Run on the host where you want NanoClaw to live. The Band web app gives you a
`curl … | bash` one-liner and your Band API key; run it and paste the key when the
script prompts. The script is [`bootstrap.sh`](bootstrap.sh).

It clones or updates `band-ai/nanoclaw-band` into `${NANOCLAW_HOME:-$HOME/nanoclaw-band}`,
registers a Band agent with your Band **API key**, writes the returned **agent**
credentials to `.env` and `data/env/env`, then hands off to the fork's
`add-band` skill. The skill mainly walks you through the remaining NanoClaw-side
connection steps: setup, launch, channel wiring, and verification.

## Source

The integration's real code, channel setup, common scripts, and `add-band` skill
live in the Band-ready NanoClaw fork:
[`band-ai/nanoclaw-band`](https://github.com/band-ai/nanoclaw-band)
(`.claude/skills/add-band/`). This folder holds only the on-ramp.

## Prereqs

- `git` and shell access on the host where NanoClaw should run. The snippet creates
  or updates `${NANOCLAW_HOME:-$HOME/nanoclaw-band}`.
- NanoClaw runtime prereqs (`node`, `pnpm`, Docker/container runtime as required
  by the fork's setup flow).
- A Band account + **API key** — paste it at the prompt (or pre-set
  `BAND_API_KEY`); used once to register the agent.

## Verify

After the skill finishes the NanoClaw-side setup and room wiring, @mention the
agent in the wired Band room. A reply means the channel is live. If messages land
in Band but the agent stays silent, the room is discovered but not wired — see the
skill's Troubleshooting and run `/manage-channels`.
