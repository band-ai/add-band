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

Say where and how to run it (the host/context) and what it does at a high level — but
**link to [`bootstrap.sh`](bootstrap.sh); don't paste a copy of it.** The web app serves
the real snippet with the key filled in, and a duplicate here only drifts.

## Source

- Upstream repo: <link> (pin a tag/commit inside `bootstrap.sh` for reproducibility).
- Artifact path inside it: `<path/to/skill-or-plugin>`.

## Prereqs

- Runtime / version requirements.
- Band credentials needed and how to get them.

## Verify

- The concrete signal that it worked ("you should see…").
