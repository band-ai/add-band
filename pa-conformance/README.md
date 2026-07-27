# PA conformance

Live proof that three personal-agent harnesses — **NanoClaw**, **OpenClaw**,
**Hermes** — come up headlessly, connect to hosted Band, retain room context,
and route messages through a shared Band room. Coverage spans L0a through L4
plus F4 onboarding; deterministic Tier-1 checks read what each harness feeds
its model at the provider boundary through the suite's model stand-in.

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
credentials (the suite auto-loads it), or export them. The default hosted lane
is E2E (real Band and a real model):

```bash
cd pa-conformance
E2E_TESTS_ENABLED=true uv run pytest tests -v --tb=short
```

The deterministic integration lane keeps real disposable Band resources but
supplies every model decision through the strict model seam. It must not have
provider egress:

```bash
cd pa-conformance
E2E_TESTS_ENABLED=true PA_TEST_LANE=integration PA_MODEL_MODE=strict \
  uv run pytest -m integration -v --tb=short
```

`uv` builds the environment from `pyproject.toml`; `uv.lock` pins the
`band-sdk` git commit. On first run the suite clones the SDK's baseline toolkit
into `.deps/` at the installed commit.

The stand-in's own tests are hermetic (in-process, no Band) and run without the
gate: `uv run pytest -m hermetic`.

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
  chat.py      OwnerChat — the owner's turns with one PA (ask / ask_scripted)
  standin.py   model stand-in client: decision DSL + recorded ModelCalls
harness/    PA-side runners — one per harness, one shared contract
  contract.py  the runner verbs + the per-harness conformance Profile
  compose.py   project-namespaced `docker compose` wrapper
  nanoclaw.py · openclaw.py · hermes.py
stacks/     per-harness deployment config (never vendors integration code)
  standin/     the suite-owned model stand-in — server.py + image + fragment
tests/      L0a liveness ×N, L2 memory + mention delivery ×N, L3 group
            scenarios and relays, L4 restart, F4 onboarding, T1 wire rows;
            test_standin_server.py is the stand-in's own hermetic tests
            (`hermetic` marker, in-process, no Band — exempt from the E2E gate)
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
| `wait_ready()` | block until the harness's readiness probe passes (or `ReadyTimeout`) |
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

5. **Mention delivery.** `tests/test_mention_delivery.py` verifies that an
   agent does not independently reply to a turn addressed to another
   participant. Whether an agent retains room or cross-room history is a
   harness policy, not a generic conformance requirement.

6. **Teardown, three rings.** Each harness's `down()` (compose `down -v`,
   plus NanoClaw sweeping the sibling agent containers its host spawns
   outside compose) → `reap_all()` for every Band agent and room, including
   rooms the agents created themselves → `stacks/down-all.sh` as the
   `if: always()` CI backstop, with the toolkit's age-gated orphan sweep
   covering anything a crashed run leaked on Band.

## The model stand-in & Profile (Tier-1)

The harnesses are black-box containers, so the only universal window into
*what a PA feeds its model* is the provider HTTP boundary. When enabled
(`PA_STANDIN` on, the default), each stack runs a `standin` service
(`stacks/standin/`, one small aiohttp image) in the model path — each harness
routes to it via `ANTHROPIC_BASE_URL`, or a provider-config knob where the SDK
ignores that env var (OpenClaw):

- **Passthrough + recording (default).** Requests forward to the real
  Anthropic API (auth forwarded, SSE streamed back, ambient Claude-runtime
  routes included) and every `/v1/messages` request is recorded as a
  `ModelCall` — system prompt, messages, tools, never headers. The recording
  is the Tier-1 read point: context-composition and tool-surface rows assert
  on it directly (`tests/test_context_composition.py`,
  `tests/test_tool_surface.py`).
- **Scripting (per turn, token-keyed).** A test binds a FIFO of neutral
  decisions (`decision(text=…)` / `decision(tool_calls=[call(name, args)])`,
  the INT-800 DSL) to its run-scoped marker token via `pa.model.script(…)`.
  The stand-in serves them only to tool-bearing model requests whose *latest*
  user message carries that token — interleaved turns on shared harnesses
  can't collide, and history echoes can't re-trigger a script. Everything
  else passes through. `driver/chat.py:OwnerChat` opens each conversation on a
  fresh room, which keeps a single scripted turn free of interleaving traffic;
  correctness rests on the token match, not on being the room's first turn.
- **Control API.** A second, dynamically published port serves the driver
  (`pa.model`), authenticated with a per-run token minted by the runner and
  scrubbed like every other run secret.

Routing is a validated per-harness fact, never assumed: `Profile.model_wire`
(declared next to each runner) records the live verdict, and every wire test
carries `@pytest.mark.requires_profile(PROFILE_FIELD.model_wire)` — a harness
whose model calls can't be routed skips declaratively. `PA_STANDIN=off` is an
operational escape hatch: the standin service is left out of every stack, the
harnesses reach `api.anthropic.com` directly, `pa.model` access skips, and
Profile verdicts are untouched.

**Profile** (`harness/contract.py`) is the other half: frozen, per-harness
declared conformance facts (tool namespace, hub identity, PROCESSED emission,
…). Every non-UNKNOWN field carries an adjacent `#:` comment naming its
evidence — a live validation or an upstream `file:line` (AGENTS.md rule); an
unvalidated fact is declared `UNKNOWN`, and rows gated on it skip with a
reason derived from the declaration itself.

### Classifying a PA scenario

Classify the behavior before adding a marker. A core conformance test applies
to every harness; it does not receive a harness-specific exception. A
capability test carries `@pytest.mark.requires_profile` and runs only for a
harness with an evidenced positive Profile declaration. An active, ticketed
defect in mandatory behavior uses `@pytest.mark.known_gap`: the target case
still runs and xfails when the defect reproduces. Intentional policy
differences, unsupported capabilities, and model-answer variance are not
known gaps. Use `harness_skip` only when the suite cannot drive or observe the
scenario, and `skipif` only for a test prerequisite.

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
   - `wait_ready()` — block until the harness's readiness probe passes, else
     raise `ReadyTimeout` (via the `wait_for(probe, timeout_s=…, desc=…)`
     helper). The exact signal varies by harness; do not infer Band reachability
     from it. Prove a real Band round-trip where you can.
   - `attach_room(room_id)` — default no-op (harnesses that answer any room
     they're `@mention`ed in). Override only if the harness routes per
     registered room, as NanoClaw does.
   - `down()` — stop everything and remove local state; must be safe after a
     partial or failed `up()`.

   Register agent keys/tokens in `stack.redactions` so they're scrubbed from
   surfaced logs, and extend `diagnostics()` to append stack logs (dumped on a
   failed run).

   Declare the harness's `profile` (`Profile`, next to `restart_services`) —
   validated facts with `#:` evidence comments, everything else `UNKNOWN`
   (the registry refuses a harness without one). Wire the model stand-in:
   spread `self.standin_env()` into the ComposeStack env and fold
   `self.standin_overrides()` into its `overrides` (this merges the shared
   `stacks/standin/` fragment — there is no per-stack standin service to add),
   call `self.up_standin()` before the runtime starts, and settle the
   `model_wire` verdict with a live canary before declaring it.

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
| `E2E_TESTS_ENABLED` | `false` | hard gate for both hosted lanes |
| `BAND_API_KEY_USER` | — | the owner/driver key (required) |
| `BAND_BASE_URL` / `BAND_WS_URL` | app.band.ai | the Band environment |
| `ANTHROPIC_API_KEY` | — | LLM key passed through to the harnesses |
| `PA_HARNESSES` | all | comma-separated harness subset |
| `PA_STANDIN` | `on` | model stand-in kill switch (`off` = direct provider wiring; wire tests skip) |
| `PA_TEST_LANE` | `e2e` | hosted lane: `integration` (strict scripted model) or `e2e` (provider passthrough) |
| `PA_MODEL_MODE` | `passthrough` | stand-in policy; `strict` for integration, `passthrough` for E2E |
| `NANOCLAW_SRC` | run work dir | prepared NanoClaw checkout |
| `NANOCLAW_REF` | `pins.env` pin | NanoClaw commit the band payload lands on |
| `OPENCLAW_IMAGE` | pinned tag | OpenClaw gateway image |
| `HERMES_IMAGE` | pinned tag | Hermes base image the Band plugin is baked into |
| `BAND_SDK_PATH` | auto-clone | explicit band-sdk-python checkout (for hacking on both) |
| `BAND_HERMES_REF` | `pins.env` pin | hermes-band-platform commit baked into the Hermes image |
| `BAND_HERMES_VERSION` | `pins.env` pin (empty) | released `hermes-band` version to bake in instead; falls back to the ref |

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

Upstream refs and Renovate-managed package/image versions live in
[`pins.env`](pins.env) — the single source of truth the harnesses, stacks,
prepare script, and CI read. Renovate (`renovate.json` at the repo root) opens
PRs to advance them. Components not tracked there are pinned where consumed:

| What | Where | Value |
| --- | --- | --- |
| hermes-band plugin | `pins.env` (`BAND_HERMES_VERSION`, else `BAND_HERMES_REF`) | PyPI version when set — unset today, so a commit SHA tracking `main` |
| NanoClaw base + payload | `pins.env` (`NANOCLAW_REF` / `NANOCLAW_PAYLOAD_REF`) | commit SHAs tracking `main` / `band/adapter` |
| OpenClaw Band channel plugin | `pins.env` (`OPENCLAW_CHANNEL_VERSION`) | npm version |
| OpenClaw image | `stacks/openclaw/compose.yaml` | `openclaw/openclaw:2026.6.11` |
| Hermes image | `pins.env` (`HERMES_IMAGE_TAG`) | `nousresearch/hermes-agent:v2026.7.7.2` |
| band-sdk + toolkit | `pyproject.toml` + `uv.lock` | git `main`, commit-pinned; refresh with `uv lock --upgrade-package band-sdk` |
| model stand-in image | `stacks/standin/Dockerfile` | `python:3.13-alpine` + `aiohttp==3.14.1` |
| Band SDK (NanoClaw payload) | `pins.env` (`NANOCLAW_BAND_SDK_VERSION` / `NANOCLAW_BAND_REST_CLIENT_VERSION`) | `@band-ai/sdk@0.1.6` + `@band-ai/rest-client@0.0.121` |
| OneCLI gateway / CLI | `pa_settings.py` / `prepare.sh` | `1.36.0` / `v2.2.5` (nanoclaw-band's `versions.json`), CLI archive SHA-256-verified |
