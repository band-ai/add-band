# Adding an integration

An integration is one folder per harness:

```
<harness>/
  manifest.yaml    ← catalog metadata (name, repo, connects_via, status, summary)
  bootstrap.sh     ← the copy-paste snippet — hand-authored, committed
  README.md        ← the human guide (the five sections below)
```

**Bootstraps don't share a shape, so they aren't generated.** Hermes installs a
plugin into its gateway and hands off to a setup skill; OpenClaw clones a repo and
runs the `openclaw` CLI. You author `bootstrap.sh` in whatever shape fits —
just keep it thin (fetch the real artifact and hand off; the heavy lifting lives
upstream).

## Steps

1. Copy the template:
   ```bash
   cp -r _template <harness>      # e.g. cp -r _template claude-code
   ```
2. Fill in `manifest.yaml`, author `bootstrap.sh`, and write the `README.md`.
3. Validate and test:
   ```bash
   python3 scripts/check.py
   pytest tests/ -q
   scripts/local-bootstrap.sh <harness> --print   # preview; drop --print to run it for real
   ```
   See [TESTING.md](TESTING.md) for the full local-testing workflow.
4. Add a row to the **Integrations** table in the [root README](README.md).

## The one rule the web app relies on

The web app hands the user a Band **API key** to copy and a `curl … | bash`
one-liner — it does **not** edit the script. So every `bootstrap.sh` must **acquire the
key itself**: when `BAND_API_KEY` is unset, prompt for it (read from `/dev/tty`,
since `curl … | bash` makes stdin the script), and otherwise accept it from the
environment. `check.py` enforces that the snippet references `BAND_API_KEY`.

The whole `bootstrap.sh` is what the web app serves behind the `curl … | bash`
one-liner, so keep it thin and readable.

## How the catalog is validated

`scripts/check.py` (run in CI) classifies every top-level integration folder:

- **participating** — has a `manifest.yaml` + `bootstrap.sh`. Validated:
  required manifest fields, a valid `status`, a `bootstrap.sh` that handles
  `BAND_API_KEY` (prompt or pre-set env), and (via the tests) `bash -n` syntax.
- **stub** — README-only, no snippet yet. Must be listed in `STUB_ONLY` in
  `scripts/check.py`, so it's a deliberate opt-out, not a silent gap.

`tests/` (pytest) asserts the same invariants in the
[thenvoi-sdk-python](../thenvoi-sdk-python) config-drift style: a folder that is
neither participating nor in `STUB_ONLY` fails the suite, and so do stale
`STUB_ONLY` entries. Every participating integration also gets its own
parametrized validation + `bash -n` test — so nothing drops out of CI unnoticed.

## The five sections (the README contract)

Every integration README answers the same five things, in order:

1. **What it connects** — one paragraph: which Band capabilities the agent gets.
2. **Bootstrap** — where and how to run it; link to `bootstrap.sh`, don't paste a
   copy of it. The web app serves the real snippet and the user pastes their key when
   it prompts, so a duplicate in the README only drifts.
3. **Source** — the upstream repo where the real artifact lives, plus its path.
4. **Prereqs** — runtime/version requirements and the Band credentials needed.
5. **Verify** — the concrete signal that it worked ("you should see…").

## Conventions

- **This repo owns the on-ramp, not the integration.** Don't vendor the skill or
  plugin here — point at its repo. Install logic lives upstream.
- **Shared helper scripts have one source of truth.** `scripts/register-agent.sh`
  is the canonical shell helper for minting agent-scoped Band credentials from a
  Band API key. Integration repos that need an offline copy should vendor it under
  their own add-band skill (for example
  `.claude/skills/add-band/scripts/register-agent.sh`) and keep it synced with
  `python3 scripts/check-register-agent-sync.py --sync`. Run the checker without
  `--sync` to compare any sibling copies that are checked out locally; run it
  with `--strict` in multi-repo CI when all integration repos are present.
- **Pin refs in the snippet.** Clone a tag/commit, not a moving branch, so a
  copied snippet keeps working.
- **Fail loud.** Prefer `set -e` and an early check for the harness binary.
- **Never bake a secret into the snippet.** Prompt for `BAND_API_KEY` from
  `/dev/tty` when it's unset, or accept it pre-set in the environment.

## Going full CLI later

A registry of these manifests is the first step toward `band add <harness>` (a
CLI that installs an integration for you). The metadata is already
machine-readable; what's left to build:

- **A registry / machine-readable index** the CLI lists from, instead of the
  Markdown table (which would be generated from it).
- **The CLI runs the integration's `bootstrap.sh`** (or a structured form of it),
  supplying `BAND_API_KEY` and checking the harness's prereqs.
- **Schema + link validation in CI**, extending `check.py` so a bad manifest
  can't ship.
