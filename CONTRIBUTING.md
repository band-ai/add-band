# Adding an integration

An integration is one folder per harness:

```
<harness>/
  manifest.yaml    ← catalog metadata (name, repo, connects_via, status, summary)
  bootstrap.sh     ← the copy-paste snippet — hand-authored, committed
  README.md        ← the human guide (the five sections below)
```

**Bootstraps don't share a shape, so they aren't generated.** Hermes clones a
plugin repo and hands a setup skill to its gateway; OpenClaw runs a couple of
curls and the `openclaw` CLI. You author `bootstrap.sh` in whatever shape fits —
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
   ```
4. Add a row to the **Integrations** table in the [root README](README.md).

## The one rule the web app relies on

Put the user's key behind the literal token **`YOUR_BAND_KEY`** in `bootstrap.sh`
— in an env export, a CLI flag, a config write, whatever the harness wants. The
web app reads the script and string-replaces that token with the user's key, so
it needs no per-shape logic. `check.py` enforces the token's presence.

## How the catalog is validated

`scripts/check.py` (run in CI) classifies every top-level integration folder:

- **participating** — has a `manifest.yaml` + `bootstrap.sh`. Validated:
  required manifest fields, a valid `status`, a `bootstrap.sh` carrying the
  `YOUR_BAND_KEY` placeholder, and (via the tests) `bash -n` syntax.
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
2. **Bootstrap** — the copy-paste snippet (mirrors `bootstrap.sh`).
3. **Source** — the upstream repo where the real artifact lives, plus its path.
4. **Prereqs** — runtime/version requirements and the Band credentials needed.
5. **Verify** — the concrete signal that it worked ("you should see…").

## Conventions

- **This repo owns the on-ramp, not the integration.** Don't vendor the skill or
  plugin here — point at its repo. Install logic lives upstream.
- **Pin refs in the snippet.** Clone a tag/commit, not a moving branch, so a
  copied snippet keeps working.
- **Fail loud.** Prefer `set -e` and an early check for the harness binary.
- **Never require pasting a secret into a command.** Use the `YOUR_BAND_KEY`
  placeholder; the user's key arrives via the web app or their environment.

## Going full CLI later

A registry of these manifests is the first step toward `band add <harness>` (a
CLI that installs an integration for you). The metadata is already
machine-readable; what's left to build:

- **A registry / machine-readable index** the CLI lists from, instead of the
  Markdown table (which would be generated from it).
- **The CLI runs the integration's `bootstrap.sh`** (or a structured form of it),
  prompting for `YOUR_BAND_KEY` and the harness's prereqs.
- **Schema + link validation in CI**, extending `check.py` so a bad manifest
  can't ship.
