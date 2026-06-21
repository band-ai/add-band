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

Run on the host where your Hermes gateway runs. The Band web app gives you a
`curl … | bash` one-liner and your Band user API key; run it and paste the key when the
script prompts. The script ([`bootstrap.sh`](bootstrap.sh)) does only the two things
bash is uniquely placed to do, then hands off to the agent:

1. **Install** the `band` plugin (which ships the `add-band` skill) into the
   gateway's own uv-managed Python from a Git ref. A production PR should switch
   this to a pinned PyPI install only after `hermes-band-platform` is published
   and verified on PyPI.
2. **Mint** a Band agent from your *user* key — read by the package's
   temporary bundled `skills/add-band/scripts/register_agent.py` helper run by
   the gateway Python, so the broad key never reaches the agent's LLM. Only the
   agent-scoped `BAND_AGENT_ID` + `BAND_API_KEY` are written to the gateway
   `.env`; then the user key is dropped. Replace the helper with the SDK CLI
   once `band.cli.register_agent` is published in `band-sdk`.
3. **Hand off** to `hermes chat -s add-band`. The skill runs the steps that need
   agent smarts rather than bash: it completes plugin setup, wires Band in as a
   communication channel with context isolation, bootstraps the **Hermes Hub**,
   and sends you the agent's first message.

> **Pre-created agent instead?** Make one at `app.band.ai/agents/new`, save
> `BAND_AGENT_ID` + `BAND_API_KEY` to the gateway `.env`, and drop the
> `register_agent.py` + `unset` lines (keep the Git-ref `uv pip install` and the
> `hermes chat -s add-band` hand-off). See [Prereqs](#prereqs).

## Source

- **Repo:** [`band-ai/hermes-band-platform`](https://github.com/band-ai/hermes-band-platform)
  — the bootstrap installs from `BAND_HERMES_REF` (`main` by default while
  unreleased). Pin a tag/commit for a reproducible install.
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
    external agents — the bootstrap registers an agent and saves only the returned
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

If you choose Hermes's directory-plugin path instead of the package install path,
remember that directory plugins do not install Python dependencies. The setup
flow must prompt to install `band-sdk>=1.0.0,<2.0.0` into the gateway Python and
show a clear error if `import band` still fails.

## Verify

After the gateway restarts, check the real connection signals:

```bash
grep -E '\[band\] Connected as agent|\[band\] Hub ready: room|✓ band connected' ~/.hermes/logs/gateway.log
grep BAND_HUB_ROOM ~/.hermes/.env   # a non-empty UUID = hub created
```

Then open the auto-created **"Hermes Agent Hub"** room in Band and **@mention the
agent** — Band has no DMs, so an un-mentioned message is ignored by design. A
reply means you're live.
