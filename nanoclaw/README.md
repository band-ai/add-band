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

It uses `NANOCLAW_HOME` when set; otherwise it uses the current NanoClaw checkout,
clones into an empty current directory, or clones into `./nanoclaw-band`. A
checkout that can't merge the fork's `main` (an upstream NanoClaw clone usually
can't) is left untouched; run the bootstrap from an empty directory instead.

NanoClaw's own setup (`bash nanoclaw.sh`) must have run for that checkout first:
it installs OneCLI and the service the skill restarts. If it hasn't, the bootstrap
stops after the clone and prints the exact command; run it, then re-run the
bootstrap. The bootstrap then registers a Band agent with your Band **API key**,
stores the returned agent credentials in `.env` and the OneCLI vault (scoped to the
`BAND_BASE_URL` host, default `app.band.ai`; a non-default `BAND_BASE_URL` is saved
to `.env` too), then hands off to the fork's `add-band` skill for the Band install,
channel wiring, and verification. Your API key never reaches the skill's session.

## Source

The integration's real code, channel setup, common scripts, and `add-band` skill
live in the Band-ready NanoClaw fork:
[`band-ai/nanoclaw-band`](https://github.com/band-ai/nanoclaw-band)
(`.claude/skills/add-band/`). This folder holds only the on-ramp.

## Prereqs

- `git` and shell access on the host where NanoClaw should run. Set
  `NANOCLAW_HOME` to choose the checkout location.
- NanoClaw runtime prereqs (`node`, `pnpm`, Docker/container runtime as required
  by the fork's setup flow), and NanoClaw set up with `bash nanoclaw.sh`.
- A Band account + **API key** — paste it at the prompt (or pre-set
  `BAND_USER_API_KEY` or `BAND_API_KEY`; `BAND_USER_API_KEY` wins when both are
  set); used once to register the agent.

## Verify

After the skill finishes the NanoClaw-side setup and room wiring, @mention the
agent in the wired Band room. A reply means the channel is live. If messages land
in Band but the agent stays silent, the room is discovered but not wired — see the
skill's Troubleshooting and run `/manage-channels`.
