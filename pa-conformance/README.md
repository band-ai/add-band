# PA conformance

Live proof that three personal-agent harnesses — **NanoClaw**, **OpenClaw**,
**Hermes** — come up headlessly, connect to hosted Band, retain room context,
and route messages through a shared Band room. The live checks cover L0a, L2,
and L3; deterministic checks need an upstream observation seam.

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
  exchange.py  the bounded inter-agent ask-and-relay exchange
  waits.py     reply-presence waits (per-sender, per-turn window, fan-in)
harness/    PA-side runners — one per harness, one shared contract
  contract.py  up(identity) · wait_ready() · attach_room(room) · down()
  compose.py   project-namespaced `docker compose` wrapper
  nanoclaw.py · openclaw.py · hermes.py
stacks/     deployment config only (never vendors integration code)
tests/      L0a liveness ×N, L2 memory + context-boundary matrix ×N, L3 group scenarios and relays
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
   hand-listed): *L0a liveness* — one `@mention` in a fresh room must return a
   run-scoped codeword; *L2 memory* — turn one seeds a codeword, then turn two
   discloses a random suffix that the reply must append. The combined result
   cannot be a delayed first-turn echo. Waits are reply-presence, not
   delivery-status — status reporting is harness-dependent and belongs to
   later conformance levels.

4. **L3 group scenarios.** The driver posts one seed mentioning only the
   asker. The codeword can reach the responder only through a declared,
   ordered mention chain. Each hand-off must carry the target's structured
   Band mention; the pair ask-and-relay is bounded at ≤6/90s. *Group fan-out*
   sends one token-bearing turn to every PA in a room.

5. **Context-boundary matrix.** Band scopes an agent's context to its own
   conversation — what it said and what was said to it (delivery is
   mention-only; rehydration injects the same scope). The matrix
   (`tests/test_history_visibility.py`, reader × seed author × timing)
   plants turns the reader was never mentioned in and requires it to declare
   blindness with a run-scoped escape marker; a token echo is a boundary
   leak. This is the in-room counterpart of the L2 cross-room isolation
   scenario, and the reason there is no "attribute the author of an earlier
   peer turn" scenario: the design excludes reading unaddressed turns, so
   such a test could only pass by roster-guessing.

6. **Teardown, three rings.** Each harness's `down()` (compose `down -v`,
   plus NanoClaw sweeping the sibling agent containers its host spawns
   outside compose) → `reap_all()` for every Band agent and room, including
   rooms the agents created themselves → `stacks/down-all.sh` as the
   `if: always()` CI backstop, with the toolkit's age-gated orphan sweep
   covering anything a crashed run leaked on Band.

## Adding a PA harness

The suite is registry-driven — tests and CI parametrize over the `HARNESSES`
map in `harness/__init__.py`, never a hand-listed set — so a new harness is
additive and needs **no test changes**.

1. **Write the runner** — `harness/<name>.py`, a `Harness` subclass (see
   `harness/contract.py`). Set the `name` class attribute (a short lowercase
   slug — both the registry key and the `PA_HARNESSES` value); bump
   `ready_timeout_s` if bring-up is slow. In `__init__`, call
   `super().__init__(ctx)` and build a `ComposeStack` (`harness/compose.py`)
   with the `pa-<name>-<run_id>` project namespace; point the PA at
   `ctx.band_base_url` / `ctx.band_ws_url`, pin `ctx.anthropic_model`, and pass
   provider keys from `ctx.llm_env`. Then implement the four verbs:
   - `up(identity)` — start the stack, wired to the **injected** `BandIdentity`
     (`agent_id`, `api_key`). Never register your own agent — the driver owns
     every Band identity so teardown stays centralized.
   - `wait_ready()` — block until the agent is live on Band, else raise
     `ReadyTimeout` (via the `wait_for(probe, timeout_s=…, desc=…)` helper).
     Prove a real Band round-trip where you can, not just "process is up".
   - `attach_room(room_id)` — default no-op (harnesses that answer any room
     they're `@mention`ed in). Override only if the harness routes per
     registered room, as NanoClaw does.
   - `down()` — stop everything and remove local state; must be safe after a
     partial or failed `up()`.

   Register agent keys/tokens in `stack.redactions` so they're scrubbed from
   surfaced logs, and extend `diagnostics()` to append stack logs (dumped on a
   failed run).

2. **Register it** — import the module in `harness/__init__.py` and add the
   class to the `HARNESSES` tuple and `__all__`; that map is the single source
   of truth. Registry order sets the default pair — the multi-harness scenarios
   use the first two selected.

3. **Add deployment config** — `stacks/<name>/` (a compose file; a `Dockerfile`
   and/or `prepare.sh` when there's no published image, like NanoClaw).
   Deployment config only — never vendor the integration code; point at the
   upstream image/ref, pinned, and record it in the [Pins](#pins) table.

4. **Wire CI** — in `.github/workflows/pa-conformance.yml`: add `<name>` (and
   any useful pairs) to the `harnesses` choice input, add a version/ref input
   if it's pinnable, and add any per-harness setup step (build / pull /
   prepare) gated on `contains(env.PA_HARNESSES, '<name>')`. Map any new secret
   with the `E2E_` prefix.

5. **Settings, if needed** — add typed knobs to `pa_settings.py` (e.g. a
   prepared-checkout path). Provider keys already flow in via
   `HarnessContext.llm_env`.

`conftest.py` then instantiates `HARNESSES[name](ctx)` and the per-harness
scenarios parametrize automatically; the pair-exchange and group scenarios pick
the harness up once at least two are selected. Verify the new harness alone
first, then the full set:

```bash
cd pa-conformance && E2E_TESTS_ENABLED=true PA_HARNESSES=<name> uv run pytest tests -v
```

This is the conformance side; a participating PA is also a catalog integration
(`bootstrap.sh` + `manifest.yaml` + guide) — see
[CONTRIBUTING.md](../CONTRIBUTING.md).

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
| `NANOCLAW_REF` | `pins.env` pin | NanoClaw commit the band payload lands on |
| `OPENCLAW_IMAGE` | pinned tag | OpenClaw gateway image |
| `HERMES_IMAGE` | pinned tag | Hermes base image the Band plugin is baked into |
| `BAND_SDK_PATH` | auto-clone | explicit band-sdk-python checkout (for hacking on both) |
| `BAND_HERMES_REF` | `pins.env` pin | hermes-band-platform commit baked into the Hermes image |

## CI

`.github/workflows/pa-conformance.yml` runs the same suite on manual dispatch
and for pull requests from this repository that change `pins.env` or `uv.lock`.
It provisions real agents and calls real models, so fork pull requests skip the
live job because repository secrets are unavailable to them. One job, one
runner, all three stacks side by side: the PAs only ever talk to hosted Band,
never to each other directly, so the only real constraint is temporal overlap.
Every component version is a dispatch input (`harnesses`,
`openclaw_version`, `hermes_version`, `hermes_plugin_ref`, `nanoclaw_branch`,
   `band_sdk_ref`); empty means the repo's pinned default. Secrets carry the
   `E2E_` prefix and map 1:1 onto the bare names above.

## Pins

Branch-tracking commit pins live in [`pins.env`](pins.env) — the single source
of truth the harnesses, stacks, prepare script, and CI read; Renovate
(`renovate.json` at the repo root) opens PRs to advance them. Everything else
is pinned where it is consumed:

| What | Where | Value |
| --- | --- | --- |
| hermes-band-platform | `pins.env` (`BAND_HERMES_REF`) | commit SHA tracking `main` |
| NanoClaw base + payload | `pins.env` (`NANOCLAW_REF` / `NANOCLAW_PAYLOAD_REF`) | commit SHAs tracking `main` / `band/adapter` |
| OpenClaw Band channel plugin | `pins.env` (`OPENCLAW_CHANNEL_VERSION`) | npm version |
| OpenClaw image | `stacks/openclaw/compose.yaml` | `openclaw/openclaw:2026.6.11` |
| Hermes image | `stacks/hermes/Dockerfile` | `nousresearch/hermes-agent:v2026.7.7.2` |
| band-sdk + toolkit | `pyproject.toml` + `uv.lock` | git `main`, commit-pinned; refresh with `uv lock --upgrade-package band-sdk` |
| Band SDK (NanoClaw payload) | `stacks/nanoclaw/prepare.sh` | `@band-ai/sdk@0.1.6` + `@band-ai/rest-client@0.0.121` |
| OneCLI gateway / CLI | `pa_settings.py` / `prepare.sh` | `1.36.0` / `v2.2.5` (nanoclaw-band's `versions.json`), CLI archive SHA-256-verified |
