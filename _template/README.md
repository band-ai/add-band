<!--
Template for a new integration. Copy this folder to <harness>/, fill in
manifest.yaml + bootstrap.sh + the five sections below, then run
`python3 scripts/check.py` to validate. Delete these comments. The section order
is the contract described in CONTRIBUTING.md.
-->

# <Harness> ↔ Band

> One line: what an agent on this harness gains by connecting to Band.

## What it connects

One paragraph. Which Band capabilities the agent gets (messaging? rooms? tools?),
and the mechanism (skill / plugin / MCP server / SDK adapter / CLI).

## Bootstrap

The copy-paste snippet, run where the agent runs (the web app fills in the key):

```bash
# paste the contents of bootstrap.sh here (or a tidied version of it)
```

This mirrors [`bootstrap.sh`](bootstrap.sh) — the source the web app reads.

## Source

- Upstream repo: <link> (pin a tag/commit inside `bootstrap.sh` for reproducibility).
- Artifact path inside it: `<path/to/skill-or-plugin>`.

## Prereqs

- Runtime / version requirements.
- Band credentials needed and how to get them.

## Verify

- The concrete signal that it worked ("you should see…").
