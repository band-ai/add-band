# Hermes ↔ Band

> Connect a [Hermes](https://github.com/band-ai/hermes-band-platform) agent to Band:
> chat in Band rooms, plus tools to act on Band.

## What it connects

Installs the `band` plugin into your Hermes gateway. It links the agent to Band
over a persistent WebSocket, relays messages between Band rooms and the agent,
and bootstraps a private **Hermes Hub** (an owner↔agent control room that acts as
the Band main channel). It also registers a `band` toolset so the agent can
create rooms, look people up, and send messages from any conversation. Band owns
access control — only messages Band delivers reach the agent.

## Bootstrap

Run on the host where your Hermes gateway runs. First set credentials (pick one):

```bash
# Auto-register a Band agent from a short-lived user key (removed after registration):
export BAND_USER_API_KEY=...

# — or bring a pre-created agent from app.band.ai/agents/new —
export BAND_AGENT_ID=...
export BAND_API_KEY=...
```

Then run the bootstrap. The Band web app renders this snippet (from
[`manifest.yaml`](manifest.yaml)) with your key already filled in. From a clone of
this repo you can generate and run it yourself:

```bash
python3 scripts/gen.py      # writes hermes/bootstrap.sh (+ .min.sh)
bash hermes/bootstrap.sh
```

It pulls the official `add-band` setup skill from the plugin repo and hands it to
Hermes, which installs the plugin into the gateway's Python, enables it,
registers the Band agent, restarts the gateway, and verifies the hub. The skill
is the source of truth for every step — this snippet stays thin and never goes
stale.

## Source

- **Repo:** [`band-ai/hermes-band-platform`](https://github.com/band-ai/hermes-band-platform)
  — tracks the `main` branch by default; pin a tag/commit via `BAND_HERMES_REF`
  for a reproducible install.
- **Skill:** `hermes_band_platform/skills/add-band/SKILL.md` (also available as
  `hermes /add-band` once the plugin is installed).
- **Fresh box / non-Hermes agent:** the one-shot install prompt at
  [`docs/INSTALL-PROMPT.md`](https://github.com/band-ai/hermes-band-platform/blob/main/docs/INSTALL-PROMPT.md).

## Prereqs

- Hermes installed, with its gateway running on **Python 3.11–3.13** (the Band
  SDK has no 3.14 wheels yet).
- Shell access as the user who owns the Hermes install.
- A Band account and one credential path:
  - **Recommended:** a Band user API key in `BAND_USER_API_KEY` that can create
    external agents — the skill registers an agent and saves only the returned
    agent-scoped credentials.
  - **Manual:** a pre-created external agent from `app.band.ai/agents/new`, giving
    you `BAND_AGENT_ID` + `BAND_API_KEY`.

| Variable | Required | Description |
| --- | --- | --- |
| `BAND_AGENT_ID` | ✅ (or via registration) | Band agent ID (UUID). |
| `BAND_API_KEY` | ✅ (or via registration) | Band agent API key — authenticates the link. |
| `BAND_USER_API_KEY` | optional | User key for one-step agent registration; removed after. |

Full configuration (hub pinning, allowlists, failover) is documented in the
[plugin README](https://github.com/band-ai/hermes-band-platform#environment-variables).

## Verify

After the gateway restarts, check the real connection signals:

```bash
grep -E '\[band\] Connected as agent|\[band\] Hub ready: room|✓ band connected' ~/.hermes/logs/gateway.log
grep BAND_HUB_ROOM ~/.hermes/.env   # a non-empty UUID = hub created
```

Then open the auto-created **"Hermes Agent Hub"** room in Band and **@mention the
agent** — Band has no DMs, so an un-mentioned message is ignored by design. A
reply means you're live.

## Maintaining

`bootstrap.sh` and `bootstrap.min.sh` are **generated** from
[`manifest.yaml`](manifest.yaml) and **git-ignored** — change a fact (repo, ref,
skill path, run command) in the manifest, then run `python3 scripts/gen.py`. The
full generation flow is in [CONTRIBUTING.md](../CONTRIBUTING.md#how-generation-works).
