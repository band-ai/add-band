# Adding an integration

An integration is one folder per harness, defined by a **`manifest.yaml`** (the
source of truth) plus a human-facing `README.md`. The bootstrap scripts are
**generated** from the manifest — you never hand-write them. That consistency is
what lets us generate the web-app snippet today and a `band` CLI later (see
[Going full CLI](#going-full-cli-later)).

## Steps

1. Copy the template:
   ```bash
   cp -r _template <harness>      # e.g. cp -r _template claude-code
   ```
2. Fill in `<harness>/manifest.yaml` (the facts) and `<harness>/README.md`
   (the five sections below).
3. Generate the scripts:
   ```bash
   python3 scripts/gen.py
   ```
4. Add a row to the **Integrations** table in the [root README](README.md).

## How generation works

```
<harness>/manifest.yaml ──┐
                          ├─► scripts/gen.py ─► <harness>/bootstrap.sh      (full installer)
scripts/templates/*.tmpl ─┘                  └─► <harness>/bootstrap.min.sh (web-app snippet)
```

- **`manifest.yaml`** — flat `key: value` facts (`repo`, `ref`, `skill`, `run`,
  `cred_env`, `installed_check`, …). Everything after the first `: ` is kept
  verbatim, so URLs and piped commands are fine. `name_upper` (override env vars)
  and `harness_bin` (the `run` command's first word) are derived automatically.
- **`scripts/templates/`** — the two shared script templates. Variable bits are
  `@@TOKEN@@` markers; every real shell `$var` is left untouched.
- **`scripts/gen.py`** — renders both scripts for every `<harness>/manifest.yaml`.
  Run it after editing a manifest or a template.
- **The web app** renders the same minimal snippet from the same manifest,
  substituting the user's key for `YOUR_BAND_KEY` — so there's one source of
  truth, no copy to drift.

**The generated scripts are git-ignored build artifacts — never commit or
hand-edit them.** CI regenerates them from the manifests, syntax-checks them, and
fails if any were committed.

## The five sections (the README contract)

Every integration README answers the same five things, in order:

1. **What it connects** — one paragraph: which Band capabilities the agent gets.
2. **Bootstrap** — the copy-paste snippet (the generated `bootstrap.min.sh`).
3. **Source** — link to the upstream repo where the real skill/plugin lives,
   pinned via the manifest `ref`, plus the path to the artifact inside it.
4. **Prereqs** — runtime/version requirements and the Band credentials needed.
5. **Verify** — the concrete signal that it worked ("you should see…").

## Conventions

- **This repo owns the on-ramp, not the integration.** Don't vendor the skill or
  plugin here — point at its repo and pin a ref. Install logic lives upstream.
- **Pin refs.** Track a tag/commit, not a moving default branch, for snippets
  that keep working. The generated script also honors a `BAND_<HARNESS>_REF`
  override for advanced users.
- **Fail loud on missing prereqs.** The full script checks for the harness binary
  up front; keep the manifest's `installed_check` accurate.
- **Never require pasting a secret into a command.** Credentials come from env.

## Going full CLI later

Today a human reads a README and copies a snippet. The manifest + generator above
are the first step toward `band add <harness>` (a CLI that installs an integration
for you). The **content per integration doesn't change — it's already
machine-readable**; what's left to build:

- **A registry / machine-readable index.** The CLI would list integrations from
  the manifests, not the Markdown table — the table becomes generated too.
- **The CLI consumes manifests directly.** It builds the invocation from
  `manifest.yaml` rather than running the generated `bootstrap.sh`.
- **Mandatory pinned refs.** `band add hermes` must be reproducible, so every
  manifest pins a tag/commit instead of tracking a branch.
- **Prereqs + credentials in the CLI.** Prompting for `BAND_API_KEY`, writing env,
  and running verification move from prose into CLI steps.
- **Schema validation in CI.** Once consumed as data, every manifest gets
  schema- and link-checked so a bad entry can't ship.
