# Band Agent Skills

Copy-paste **bootstrap snippets** that connect an agent to [Band](https://app.band.ai)
in one step — one recipe per framework / harness.

This repo is a **catalog of on-ramps**, not the integrations themselves. The real
artifacts (skills, plugins, SDK adapters) live in each integration's own repo.
What lives here is the thin thing a user copies to wire their agent in, plus a
pointer to where the real code lives.

## Use it

1. Find your harness in the table below.
2. Copy its snippet — the Band web app shows it with your key already filled in.
3. Run it on the host where your agent runs.

The snippet is **generated** from the integration's `manifest.yaml` (the web app
renders the same source). To preview or run it from a clone, generate the scripts
with `python3 scripts/gen.py`.

## What happens when you run it

A snippet is deliberately thin: it fetches the integration's real artifact and
hands off. For Hermes:

```
clone the plugin repo  →  hand the add-band skill to Hermes
                          ├─ plugin already installed → `hermes /add-band` runs it
                          └─ fresh box                → prints the skill for the agent to follow
```

The upstream skill then does the real work — install the plugin into the
gateway's Python, enable it, register the Band agent, restart, and verify the
hub. You hit just two gates: provide credentials, then @mention the agent in Band
to confirm it replies. **One paste → two confirmations → a connected agent.**

## Who owns what

The on-ramp is split across three layers so the catalog stays thin and can't go
stale:

- **This repo** owns discovery + the copy-paste snippet. It never vendors a skill
  or install logic — only a snippet and a pinned pointer upstream.
- **The integration's repo** (e.g. [`band-ai/hermes-band-platform`](https://github.com/band-ai/hermes-band-platform))
  owns the skill and every real step of installing and wiring the agent in. If
  the procedure changes, only this changes.
- **The Band platform** owns credentials, agent registration, and access control.

## Integrations

| Harness | Connects via | Status | Guide |
| --- | --- | --- | --- |
| [Hermes](hermes/) | `add-band` setup skill + `band` plugin | ✅ Available | [hermes/README.md](hermes/README.md) |
| [NanoClaw](nanoclaw/) | TBD | 🚧 Planned | [nanoclaw/README.md](nanoclaw/README.md) |
| [OpenClaw](openclaw/) | TBD | 🚧 Planned | [openclaw/README.md](openclaw/README.md) |
| _your harness_ | — | 🟡 Wanted | [add one →](CONTRIBUTING.md) |

## Layout

```
README.md            ← this index (user-facing)
CONTRIBUTING.md      ← add an integration · how scripts are generated · roadmap
scripts/
  gen.py             ← renders the bootstrap scripts from each manifest
  templates/         ← shared script templates
_template/           ← copy to start a new integration
<harness>/
  manifest.yaml      ← source of truth: repo, ref, skill, run command, …
  README.md          ← what it connects · the snippet · prereqs · verify · source
  bootstrap.sh       ← generated · git-ignored · full installer (clone + run the skill)
  bootstrap.min.sh   ← generated · git-ignored · minimal copy-paste snippet (the web app renders this)
```

Each integration is defined by its `manifest.yaml`; the bootstrap scripts are
**generated** from it via `scripts/gen.py`, never hand-written. Adding one is
mechanical — copy `_template/`, fill the manifest + five README sections, run the
generator. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Roadmap

The `manifest.yaml` + generator are the first step toward a `band add <harness>`
CLI: integrations are already machine-readable, so a CLI could install them
directly. The remaining work — a registry, the CLI, schema validation in CI — is
in [CONTRIBUTING.md → Going full CLI](CONTRIBUTING.md#going-full-cli-later).
