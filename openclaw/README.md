# OpenClaw ↔ Band

> 🚧 **Planned.** The folder is scaffolded in the catalog's shape, but
> [`bootstrap.sh`](bootstrap.sh) contains **placeholder** commands — replace them
> with OpenClaw's real connect steps before flipping `status` to `available`.

## What it connects

Connects an OpenClaw agent to Band through the **`openclaw` CLI** — no skill and
no plugin clone. The snippet runs a couple of `curl`s to fetch what's needed,
then the CLI wires the agent into Band. (This is a deliberately different shape
from Hermes, which hands a setup *skill* to its gateway.)

## Bootstrap

Run on the host where OpenClaw runs (the web app fills in your key):

```bash
curl -fsSL https://openclaw.example/band/install.sh | bash
curl -fsSL https://openclaw.example/band/band.json -o "$HOME/.openclaw/band.json"
openclaw plugin add band
openclaw config set band.api_key YOUR_BAND_KEY
openclaw restart
```

See [`bootstrap.sh`](bootstrap.sh) — the source for the snippet above.

## Source

_TBD_ — confirm OpenClaw's repo and the real install/CLI commands, then update
[`manifest.yaml`](manifest.yaml) and `bootstrap.sh`.

## Prereqs

- OpenClaw installed, with the `openclaw` CLI on `PATH`.
- A Band account + API key (set where the CLI expects it).

## Verify

_TBD_ — the concrete signal that the agent is live in Band.
