#!/usr/bin/env bash
# Tear down every PA-conformance compose project on this host.
#
# The pytest session already downs each stack it started (even on failure);
# this is the deterministic backstop for a killed process — run it from an
# `if: always()` CI step. Projects are namespaced `pa-<harness>-<run_id>`, so
# matching on that prefix stays within this suite.
set -euo pipefail

# Compose expands guarded variables before it can process `down`. These
# teardown-only defaults let recorded configs parse after a killed run.
export PA_UID="${PA_UID:-$(id -u)}"
export PA_GID="${PA_GID:-$(id -g)}"
export PA_HERMES_HOME="${PA_HERMES_HOME:-/tmp/pa-conformance-hermes-teardown}"
export COMPOSE_POSTGRES_PASSWORD="${COMPOSE_POSTGRES_PASSWORD:-teardown-only-placeholder}"
export COMPOSE_ONECLI_IMAGE="${COMPOSE_ONECLI_IMAGE:-teardown-only-placeholder}"
export DOCKER_GID="${DOCKER_GID:-0}"
export NANOCLAW_HOST_PATH="${NANOCLAW_HOST_PATH:-/tmp}"

# `compose ls` reports each project's config file(s); pass them to `down` with
# -f so named volumes declared in the compose file are removed too (a bare
# `down` by project label leaves them behind). Tab-separated: name<TAB>files.
failed=0
if ! projects="$(docker compose ls -a --format json \
  | python3 -c 'import json,sys
for p in json.load(sys.stdin):
    if p["Name"].startswith(("pa-nanoclaw-", "pa-openclaw-", "pa-hermes-")):
        print(p["Name"] + "\t" + (p.get("ConfigFiles") or ""))')"; then
  echo "failed to list PA-conformance compose projects" >&2
  exit 1
fi

if [ -n "$projects" ]; then
  while IFS=$'\t' read -r name cfgs; do
    files=()
    IFS=',' read -ra parts <<< "$cfgs"
    for f in "${parts[@]}"; do [ -n "$f" ] && files+=(-f "$f"); done
    echo "==> docker compose -p $name down -v"
    if ! docker compose "${files[@]}" -p "$name" down -v --remove-orphans; then
      echo "teardown failed for compose project $name" >&2
      failed=1
    fi
  done <<< "$projects"
fi

# NanoClaw's host spawns per-agent sibling containers through the docker
# socket — outside compose, on the upstream's fixed `nanoclaw-compose` network,
# with no run- or project-scoped label. The only ownership signal is the agent
# image tag, which container/build.sh derives from the checkout path — so the
# sweep is scoped to THIS suite's checkout (NANOCLAW_SRC), never to a matching
# image family that could belong to a developer's own NanoClaw install.
if [ -n "${NANOCLAW_SRC:-}" ]; then
  slug=$(python3 -c 'import hashlib,pathlib,sys
print(hashlib.sha1(str(pathlib.Path(sys.argv[1]).expanduser().resolve()).encode()).hexdigest()[:8])' "$NANOCLAW_SRC")
  docker ps -aq --filter "ancestor=nanoclaw-agent-v2-${slug}:latest" \
    | xargs -r docker rm -f
else
  echo "NANOCLAW_SRC unset — skipping the NanoClaw sibling-container sweep" >&2
fi

exit "$failed"
