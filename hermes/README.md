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

Run [`bootstrap.sh`](bootstrap.sh) on the host where your Hermes gateway runs — the
Band web app hands it to you with your key already filled in. It does only what the
bootstrapper is uniquely placed to do, then hands off:

1. **Clone** the integration repo.
2. **Register** a Band agent from your *user* key — consumed in a plain shell, so the
   broad key never enters the agent's own environment. Only the agent-scoped
   `BAND_AGENT_ID` + `BAND_API_KEY` are written to Hermes, then the user key is dropped.
3. **Plant** the `add-band` skill into `$HERMES_HOME/skills` so `hermes chat -s add-band`
   is invocable on a fresh box (a plugin-shipped skill isn't, until installed).
4. **Hand off** to the skill, which installs the plugin, enables it, restarts the
   gateway, and verifies the hub — the single source of truth for those steps, so the
   snippet never reimplements them and never goes stale. Credentials are already saved,
   so the skill skips its credential gate straight to the live @mention test.

> **Pre-created agent instead?** Make one at `app.band.ai/agents/new`, save
> `BAND_AGENT_ID` + `BAND_API_KEY` with Hermes's env writer, and drop the registration
> step. See [Prereqs](#prereqs).

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

After the gateway restarts, the Band connection surfaces in the gateway log (a
"Connected as agent" / "Hub ready" line) and `BAND_HUB_ROOM` is set to a UUID in
Hermes's `.env` — the skill's `verify_gateway.py` checks both for you. Then open the
auto-created **"Hermes Agent Hub"** room in Band and **@mention the agent** — Band has
no DMs, so an un-mentioned message is ignored by design. A reply means you're live.
