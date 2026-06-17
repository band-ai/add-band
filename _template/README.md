<!--
Template for a new integration. Copy this folder to <harness>/, fill in
manifest.yaml + the five sections below, then run `python3 scripts/gen.py` to
generate the bootstrap scripts. Delete these comments. The section order is the
contract described in CONTRIBUTING.md.
-->

# <Harness> ↔ Band

> One line: what an agent on this harness gains by connecting to Band.

## What it connects

One paragraph. Which Band capabilities the agent gets (messaging? rooms? tools?),
and the mechanism (skill / plugin / MCP server / SDK adapter).

## Bootstrap

The Band web app renders the minimal snippet from [`manifest.yaml`](manifest.yaml).
From a clone you can generate and run it locally:

```bash
python3 scripts/gen.py      # writes <harness>/bootstrap.sh (+ .min.sh)
bash <harness>/bootstrap.sh
```

## Source

- Upstream repo: <link>, pinned via the `ref` in [`manifest.yaml`](manifest.yaml).
- Artifact path inside it: `<path/to/skill-or-plugin>`.

## Prereqs

- Runtime / version requirements.
- Band credentials needed and how to get them.

## Verify

- The concrete signal that it worked ("you should see…").

## Maintaining

`bootstrap.sh` and `bootstrap.min.sh` are **generated** from
[`manifest.yaml`](manifest.yaml) — edit the manifest, run `python3 scripts/gen.py`,
and never hand-edit the scripts. See [CONTRIBUTING.md](../CONTRIBUTING.md).
