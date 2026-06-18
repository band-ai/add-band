# NanoClaw ↔ Band

## What it connects

Connects a **NanoClaw** agent to Band — Band rooms/chats, plus the SDK-backed
`band_*` platform tools. The channel registers as `band`, platform IDs use the
`band:` prefix, and config lives in `BAND_*` env vars.

NanoClaw's Band channel is **fork-shaped**: it touches core host and container
files, not a single adapter. So it installs by *merging a version-pinned
`band-v<X.Y.Z>` tag* (3-way, conflict-aware) rather than copying files — a merge
surfaces conflicts where your install has local changes instead of silently
overwriting them. That work lives in NanoClaw's [`add-band`](https://github.com/thenvoi/nanoclaw-thenvoi)
skill; the snippet below just registers a Band agent and hands off to it.

## Bootstrap

Run from your **NanoClaw checkout** — the Band web app hands you the snippet with
your key already filled in; the script is [`bootstrap.sh`](bootstrap.sh).

It does the one step the skill doesn't — register a Band agent with your **user**
key and capture its **agent** id + key — writes them to `.env`, then hands off to
`add-band`, which merges the Band tag, installs deps, builds, and wires the room.

## Source

The integration's real code and the `add-band` skill live in NanoClaw's own repo:
[`thenvoi/nanoclaw-thenvoi`](https://github.com/thenvoi/nanoclaw-thenvoi)
(`.claude/skills/add-band/`, installed via `band-v<X.Y.Z>` tags). This folder
holds only the on-ramp.

## Prereqs

- A working **NanoClaw checkout** on a tagged release (`node` + `pnpm` available),
  run the snippet from its root.
- A Band account + **user** API key — supplied by the web app at the
  `{{BAND_USER_API_KEY}}` placeholder; used once to register the agent.

## Verify

@mention the agent in the wired Band room. A reply means the channel is live. If
messages land in Band but the agent stays silent, the room is discovered but not
wired — see the skill's Troubleshooting and run `/manage-channels`.
