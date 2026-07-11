---
name: pa-conformance
description: Run the live PA conformance suite (NanoClaw, OpenClaw, Hermes on hosted Band) locally — preflight, run, triage, teardown. Use when asked to run, verify, or debug PA conformance tests.
---

# Run the PA conformance suite locally

The suite lives in `pa-conformance/` and is a self-contained uv project. CI
runs the same pytest command with workflow-provided setup and credentials.
Full design: `pa-conformance/README.md`.

## 1. Preflight

- Docker daemon running (`docker info` succeeds).
- `uv` and `git` installed.
- Network/auth access for the pinned upstream fetches: `uv` installs
  `band-sdk` from GitHub, and the suite auto-clones the matching toolkit
  checkout unless `BAND_SDK_PATH` points at an existing checkout. NanoClaw
  prepare also needs GitHub, Docker registry, and OneCLI release download
  access.
- Credentials in `.env.test` at the repo root (auto-loaded). If missing, copy
  `.env.test.example` and have the user fill in `BAND_API_KEY_USER` and
  `ANTHROPIC_API_KEY` locally (or export them); never ask the user to paste
  secret values into chat, and never invent or reuse keys from elsewhere.
- NanoClaw only — one-time image build (~4 min; node 22+, pnpm, bun):

  ```bash
  NANOCLAW_SRC=~/.cache/pa-nanoclaw/nanoclaw-band bash pa-conformance/stacks/nanoclaw/prepare.sh
  ```

  `NANOCLAW_SRC` must be a dedicated disposable checkout/cache path. The script
  resets that checkout to the requested upstream ref before applying the Band
  payload, so never point it at a user-edited NanoClaw working tree. Pass the
  same absolute `NANOCLAW_SRC` to every run (or set it in `.env.test`). Leave
  `NANOCLAW_REF` empty to use upstream `main`; only name a temporary branch
  after confirming it still exists.

## 2. Run

```bash
cd pa-conformance
E2E_TESTS_ENABLED=true uv run pytest tests -v --tb=short
```

- Subset: `PA_HARNESSES=hermes,openclaw` (the pair exchange and group scenarios
  need ≥2 selected; per-harness tests still run with one).
- One file: `E2E_TESTS_ENABLED=true uv run pytest tests/test_memory.py -v --tb=short`.
  Use `-k recalls_fact` or `-k leak_fact` to select one of its scenarios.
- A full 3-harness run typically takes 10–20 minutes. It provisions real Band
  agents and rooms, calls real LLMs, and reaps resources on pass or failure.

## 3. Report the results

Never end at pytest's raw tail — after the run, present a compact scorecard
the way pytest's pretty-output plugins do (pytest-pretty / pytest-sugar
style):

- A **harness × scenario matrix** — one row per harness, one column per
  scenario — with a clear pass/fail/skip mark per cell; suite-wide scenarios
  (fan-out, exchanges) get their own row. Derive rows and columns from what
  actually ran, never from a hardcoded list.
- Totals and wall-clock time on one line under the table.
- For scenario assertion failures: the test id, the assertion's one-line reason
  (they are written to name the missing behavior), and what the agent actually
  said (the captured transcript). For setup, Docker, auth, or network failures,
  summarize the relevant diagnostic instead.
- Skips are signal, not noise: say why (e.g. "pair exchange needs at least two
  harnesses").

The goal: per-harness conformance readable at a glance, like a CI scorecard.

## 4. Triage

- Failure output ends with the captured transcript — read what the agent
  actually said before touching code.
- Harness bring-up failures print the stack's diagnostics (compose ps + logs)
  in the fixture error; the stacks are named `pa-<harness>-<run_id>`.
- `httpx.ConnectTimeout` on the first Band call means no scenario ran. Check
  the configured Band endpoint and runner network access before changing test
  code; rerun when the failure may be transient.
- A transcript saying a provisioned mention "isn't me" is an identity/routing
  failure, not permission to weaken the run-scoped token assertion.
- A transcript saying earlier room history is unavailable is a real history
  or context failure. Report it against the attributed-history scenario rather
  than converting it into an infrastructure error.

## 5. Teardown backstop

The session tears down its own stacks and Band resources even on failure. If
a run was killed hard:

```bash
bash pa-conformance/stacks/down-all.sh
```

Band-side orphans are swept by the next run's age-gated orphan sweep.
