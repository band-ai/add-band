# PA conformance — Phase 0

Live proof that three personal-agent harnesses — **NanoClaw**, **OpenClaw**,
**Hermes** — come up headlessly, connect to hosted Band, answer a direct
`@mention`, and talk to each other in a shared Band room. This is Phase 0 of
the PA conformance baseline; the full per-level scorecard builds on it.

Two principles carry the design:

- **The driver owns every Band resource.** One owner key
  (`BAND_API_KEY_USER`) provisions all three agent identities and every room;
  harnesses get identities *injected* and never register their own. Teardown
  is a single `reap_all()` no matter what any harness did locally.
- **A test contains the scenario, never the plumbing.** All variance across
  harnesses is confined to the three runner modules; shared invariants include
  identity ownership, capture semantics, teardown guarantees, and assertion
  style.

## Quickstart

Requires Docker, [uv](https://docs.astral.sh/uv/), git, and access to the
pinned upstream repos. Copy the repo root's
[`.env.test.example`](../.env.test.example) to `.env.test` and fill in the
credentials (the suite auto-loads it), or export them. Then:

```bash
cd pa-conformance
E2E_TESTS_ENABLED=true uv run pytest tests -v --tb=short
```

`uv` builds the environment from `pyproject.toml`; `uv.lock` pins the
`band-sdk` git commit. On first run the suite clones the SDK's baseline toolkit
into `.deps/` at the installed commit.

Scope to a subset with `PA_HARNESSES=hermes,openclaw` (the inter-agent test
needs at least two; the asker/responder pair is the first two selected).

**NanoClaw** additionally needs node 22+/pnpm/bun and a one-time prepare —
it has no published image, so the Band payload branch is materialized onto
`main` and its images are built locally:

```bash
NANOCLAW_SRC=~/.cache/pa-nanoclaw/nanoclaw-band bash stacks/nanoclaw/prepare.sh
```

Use a dedicated disposable `NANOCLAW_SRC`; prepare resets that checkout before
applying the Band payload.

## Layout

```
driver/     Band-side primitives, acting as the OWNER identity
  checkout.py  acquires the band-sdk-python checkout (BAND_SDK_PATH or .deps/)
  sdk.py       the one bridge to band-sdk-python's baseline E2E toolkit
  ops.py       driver sends beyond UserOps (multi-mention fan-out)
  exchange.py  the bounded inter-agent ask-and-relay + three-way relay
  waits.py     reply-presence waits (per-sender, per-turn window, fan-in)
harness/    PA-side runners — one per harness, one shared contract
  contract.py  up(identity) · wait_ready() · attach_room(room) · down()
  compose.py   project-namespaced `docker compose` wrapper
  nanoclaw.py · openclaw.py · hermes.py
stacks/     deployment config only (never vendors integration code)
tests/      liveness ×N, memory ×N, group fan-out, exchange, 3-way relay
pa_settings.py  every suite knob, typed (pydantic-settings)
conftest.py     session wiring: SDK fixtures replicated + the `pas` fixture
```

**`driver/`** acts as you. `sdk.py` is the single bridge to the SDK's
pytest-free baseline toolkit: `ResourceManager` (provision/reap with guarded
`e2e-band-<run>-` names + orphan sweep), `UserOps` (send with structured
mentions), `reply_capture` (WS observer that subscribes *before* anything is
sent, so no frame can be missed), `Replies` (assertions). Nothing else
touches the toolkit's namespace.

**`harness/`** is the PA side. Every runner implements four verbs:

| Verb | Meaning |
| --- | --- |
| `up(identity)` | start the stack, wired to a pre-provisioned Band agent |
| `wait_ready()` | block until the agent is live on Band (or `ReadyTimeout`) |
| `attach_room(room)` | wire a driver-created room in (no-op except NanoClaw) |
| `down()` | stop everything, remove local state — safe after a partial `up()` |

Every stack gets a compose project namespace (`pa-<harness>-<run_id>`), so
three stacks coexist on one host and teardown is a precise `down -v` per
project.

## How a run works

1. **Provision & inject.** The session fixture provisions one Band agent per
   selected harness, reads each agent's namespaced handle back from
   `/agent/me`, and hands each harness a frozen `BandIdentity`. Injection per
   dialect: Hermes → `$HERMES_HOME/.env`; OpenClaw → `channels add`;
   NanoClaw → its `.env` plus the OneCLI credential vault.

2. **Bring-up.** Hermes: state pre-written (plugin enabled, model pinned),
   access policy set with the plugin's own idempotent script, readiness =
   the plugin's `verify_gateway.py` reporting a real Band round-trip.
   OpenClaw: all config lands before first start via one-shot `compose run`
   containers; readiness = `/readyz` + the health RPC showing the Band
   account running. NanoClaw: compose stack (postgres + OneCLI + host),
   credential vault seeded via the pinned host-side `onecli` CLI; readiness =
   the host serving its CLI socket.

3. **Per-harness scenarios** (parametrized over the harness registry, never
   hand-listed): *liveness* — one `@mention` in a fresh room, wait for a
   reply from that sender id; *memory* — turn one seeds a run-scoped
   codeword, turn two must recall it, waited on a per-turn window so an
   earlier reply cannot satisfy a later turn. Waits are reply-presence, not
   delivery-status — status reporting is harness-dependent and belongs to
   later conformance levels.

4. **The exchanges.** The driver posts one seed mentioning only the first
   agent. Band delivers messages only to mentioned agents, so the codeword
   in the seed can reach the others solely through the @mention chain —
   codeword-in-reply *is* the delivery proof, bounded by a turn cap and a
   deadline (≤6 msgs/90s pair, ≤10/150s for the three-way relay, where every
   leg must author the codeword so a shortcut fails the middle leg). The
   *group fan-out* covers the remaining shape: one message mentioning every
   PA, each replies in the same room.

5. **Teardown, three rings.** Each harness's `down()` (compose `down -v`,
   plus NanoClaw sweeping the sibling agent containers its host spawns
   outside compose) → `reap_all()` for every Band agent and room, including
   rooms the agents created themselves → `stacks/down-all.sh` as the
   `if: always()` CI backstop, with the toolkit's age-gated orphan sweep
   covering anything a crashed run leaked on Band.

## Configuration

All knobs are env vars (typed in `pa_settings.py`; Band credentials are read
by the SDK's own settings):

| Variable | Default | Meaning |
| --- | --- | --- |
| `E2E_TESTS_ENABLED` | `false` | hard gate — the suite is live-only |
| `BAND_API_KEY_USER` | — | the owner/driver key (required) |
| `BAND_BASE_URL` / `BAND_WS_URL` | app.band.ai | the Band environment |
| `ANTHROPIC_API_KEY` | — | LLM key passed through to the harnesses |
| `PA_HARNESSES` | all | comma-separated harness subset |
| `NANOCLAW_SRC` | run work dir | prepared NanoClaw checkout |
| `NANOCLAW_REF` | `main` | NanoClaw branch the band payload lands on |
| `OPENCLAW_IMAGE` | pinned tag | OpenClaw gateway image |
| `HERMES_IMAGE` | pinned tag | Hermes base image the Band plugin is baked into |
| `BAND_SDK_PATH` | auto-clone | explicit band-sdk-python checkout (for hacking on both) |
| `BAND_HERMES_REF` | `main` | hermes-band-platform git ref baked into the Hermes image |

## CI

`.github/workflows/pa-conformance.yml` runs the same suite on manual dispatch
(it provisions real agents and calls real models — not per-PR). One job, one
runner, all three stacks side by side: the PAs only ever talk to hosted Band,
never to each other directly, so the only real constraint is temporal
overlap. Every component version is a dispatch input (`harnesses`,
`openclaw_version`, `hermes_version`, `hermes_plugin_ref`, `nanoclaw_branch`,
   `band_sdk_ref`); empty means the repo's pinned default. Secrets carry the
   `E2E_` prefix and map 1:1 onto the bare names above.

## Pins

| What | Where | Value |
| --- | --- | --- |
| OpenClaw image | `stacks/openclaw/compose.yaml` | `openclaw/openclaw:2026.6.11` |
| Hermes image | `stacks/hermes/Dockerfile` | `nousresearch/hermes-agent:v2026.7.7.2` |
| hermes-band-platform | `BAND_HERMES_REF` (build arg / CI input) | `main` |
| band-sdk + toolkit | `pyproject.toml` + `uv.lock` | git `main`, commit-pinned; refresh with `uv lock --upgrade-package band-sdk` |
| Band SDK (NanoClaw payload) | `stacks/nanoclaw/prepare.sh` | `@band-ai/sdk@0.1.6` + `@band-ai/rest-client@0.0.121` |
| OneCLI gateway / CLI | `pa_settings.py` / `prepare.sh` | `1.36.0` / `v2.2.5` (nanoclaw-band's `versions.json`) |
