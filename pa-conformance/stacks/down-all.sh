#!/usr/bin/env bash
# Tear down every PA-conformance compose project on this host.
#
# The pytest session already downs each stack it started (even on failure);
# this is the deterministic backstop for a killed process — run it from an
# `if: always()` CI step. Projects are namespaced `pa-<harness>-<run_id>`, so
# matching on the prefix is precise. Sibling containers NanoClaw spawned
# outside compose carry its project label too via the compose network; any
# stragglers are caught by the label sweep below.
set -euo pipefail

# `compose ls` reports each project's config file(s); pass them to `down` with
# -f so named volumes declared in the compose file are removed too (a bare
# `down` by project label leaves them behind). Tab-separated: name<TAB>files.
docker compose ls -a --format json 2>/dev/null \
  | python3 -c 'import json,sys
for p in json.load(sys.stdin):
    if p["Name"].startswith("pa-"):
        print(p["Name"] + "\t" + (p.get("ConfigFiles") or ""))' \
  | while IFS=$'\t' read -r name cfgs; do
      files=()
      IFS=',' read -ra parts <<< "$cfgs"
      for f in "${parts[@]}"; do [ -n "$f" ] && files+=(-f "$f"); done
      echo "==> docker compose -p $name down -v"
      docker compose "${files[@]}" -p "$name" down -v --remove-orphans || true
    done

# NanoClaw's host spawns per-agent sibling containers directly through the
# docker socket — not compose-managed, so sweep by image as a last resort.
# The agent image is slug-suffixed (nanoclaw-agent-v2-<slug>), so match the
# family prefix rather than one literal tag.
docker ps -a --format '{{.ID}} {{.Image}}' \
  | awk '$2 ~ /^nanoclaw-agent/ {print $1}' \
  | xargs -r docker rm -f
