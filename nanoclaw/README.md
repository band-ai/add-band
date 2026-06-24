# NanoClaw ↔ Band

## What it connects

Connects a **NanoClaw** agent to Band — Band rooms/chats, plus the SDK-backed
`band_*` platform tools. The channel registers as `band`, platform IDs use the
`band:` prefix, and config lives in `BAND_*` env vars.
NanoClaw's Band channel is **fork-shaped**: it touches core host and container
files, not a single adapter. So the on-ramp works against the Band-ready NanoClaw
fork instead of patching an arbitrary checkout. That fork owns the channel setup,
common scripts, and `add-band` skill; this catalog only points users at it.

## Bootstrap

Run on the host where you want NanoClaw to live — the Band web app hands you the
snippet with your key already filled in; the script is [`bootstrap.sh`](bootstrap.sh).

It is **adoption-first**: if you run it from inside a Band-ready checkout (detected
by `src/channels/band.ts`), or already have one at `${BAND_DIR:-$HOME/agents/nanoclaw-band}`,
it uses that in place; only on a fresh box does it clone `band-ai/nanoclaw-band`.
It then registers a Band agent with your **user** key, writes the returned
**agent** credentials to `.env` and `data/env/env`, and hands off to the fork's
`add-band` skill. The skill walks you through the remaining NanoClaw-side
connection steps: setup, launch, channel wiring, and verification.

Override the clone location with `BAND_DIR` and the source repo with `BAND_REPO`.

## Source

The integration's real code, channel setup, common scripts, and `add-band` skill
live in the Band-ready NanoClaw fork:
[`band-ai/nanoclaw-band`](https://github.com/band-ai/nanoclaw-band)
(`.claude/skills/add-band/`). This folder holds only the on-ramp.

## Prereqs

- `git` and shell access on the host where NanoClaw should run. The snippet adopts
  an existing Band-ready checkout or clones one into `${BAND_DIR:-$HOME/agents/nanoclaw-band}`.
- NanoClaw runtime prereqs (`node`, `pnpm`, Docker/container runtime as required
  by the fork's setup flow).
- A Band account + **user** API key — supplied by the web app at the
  `{{BAND_USER_API_KEY}}` placeholder; used once to register the agent.

## Verify

After the skill finishes the NanoClaw-side setup and room wiring, @mention the
agent in the wired Band room. A reply means the channel is live. If messages land
in Band but the agent stays silent, the room is discovered but not wired — see the
skill's Troubleshooting and run `/manage-channels`.
