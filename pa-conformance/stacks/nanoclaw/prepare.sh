#!/usr/bin/env bash
# Materialize a runnable, Band-wired NanoClaw checkout and build its images.
#
# nanoclaw-band's `band/adapter` is a payload-only overlay branch, and no
# prebuilt image is published. This script copies the payload files onto main,
# appends the self-registration imports, installs pinned SDK deps, and builds
# the host + agent images.
#
# Inputs:
#   NANOCLAW_SRC   where the checkout lives (created/updated; required)
#   NANOCLAW_REPO  clone URL (default: the band-ai fork)
#   NANOCLAW_REF   base branch the payload lands on (default: main)
# Host requirements: git, docker, node 22+, pnpm 10+, bun.
set -euo pipefail

SRC="${NANOCLAW_SRC:?set NANOCLAW_SRC to the checkout path}"
REPO="${NANOCLAW_REPO:-https://github.com/band-ai/nanoclaw-band.git}"
BASE_REF="${NANOCLAW_REF:-main}"
PAYLOAD_REF="band/adapter"

# The payload set, verbatim from .claude/skills/add-band/SKILL.md (band/adapter).
FILES=(
  src/channels/band.ts
  src/channels/band.test.ts
  src/modules/band-config.ts
  src/db/migrations/module-band-state.ts
  src/db/migrations/020-band-rename.ts
  container/agent-runner/src/mcp-tools/band.ts
  container/agent-runner/src/mcp-tools/band.test.ts
  container/agent-runner/src/mcp-tools/band.instructions.md
  container/agent-runner/src/band-lifecycle.ts
  container/agent-runner/src/band-lifecycle.test.ts
  container/agent-runner/src/band-memory-load.ts
  container/agent-runner/src/band-memory-load.test.ts
  container/agent-runner/src/band-memory-consolidate.ts
  container/agent-runner/src/band-memory-consolidate.test.ts
)

if [ ! -d "$SRC/.git" ]; then
  git clone --branch "$BASE_REF" "$REPO" "$SRC"
fi
cd "$SRC"
git fetch origin "+refs/heads/$BASE_REF:refs/remotes/origin/$BASE_REF" \
  "+refs/heads/$PAYLOAD_REF:refs/remotes/origin/$PAYLOAD_REF"
git checkout -q "$BASE_REF"
git reset -q --hard "origin/$BASE_REF"

echo "==> copying ${#FILES[@]} payload files from origin/$PAYLOAD_REF"
for f in "${FILES[@]}"; do
  mkdir -p "$(dirname "$f")"
  git show "origin/$PAYLOAD_REF:$f" > "$f"
  [ "$(git hash-object "$f")" = "$(git rev-parse "origin/$PAYLOAD_REF:$f")" ] \
    || { echo "payload copy of $f is not byte-identical" >&2; exit 1; }
done

append_once() { # append_once <file> <line>
  grep -qxF "$2" "$1" || printf '%s\n' "$2" >> "$1"
}
append_once src/channels/index.ts "import './band.js';"
append_once container/agent-runner/src/mcp-tools/index.ts "import './band.js';"
# This one is position-sensitive: after providers/index.js, before createProvider.
grep -qxF "import './band-lifecycle.js';" container/agent-runner/src/index.ts || \
  sed -i.bak "/import '\.\/providers\/index\.js';/a\\
import './band-lifecycle.js';
" container/agent-runner/src/index.ts && rm -f container/agent-runner/src/index.ts.bak

echo "==> installing pinned Band SDK deps"
pnpm add @band-ai/sdk@0.1.6 @band-ai/rest-client@0.0.121
( cd container/agent-runner && bun add @band-ai/sdk@0.1.6 )

echo "==> building host bundle + images"
pnpm run build
docker build -t nanoclaw-host:latest -f Dockerfile.host \
  --build-arg NANOCLAW_BUILD_HASH="$(git rev-parse --short HEAD)" .
./container/build.sh

# The host refuses to start after checkout changes until the upgrade marker is
# refreshed.
echo "==> recording the upgrade marker (payload applied by script)"
pnpm exec tsx scripts/upgrade-state.ts set

# The onecli CLI is host-side and is not in the compose images. Fetch the
# version pinned by the NanoClaw checkout.
CLI_VERSION=$(python3 -c "import json; print(json.load(open('versions.json'))['onecli-cli'])")
case "$(uname -s)" in Darwin) OS=darwin ;; *) OS=linux ;; esac
case "$(uname -m)" in arm64|aarch64) ARCH=arm64 ;; *) ARCH=amd64 ;; esac
echo "==> fetching onecli CLI v${CLI_VERSION} (${OS}/${ARCH})"
mkdir -p .pa
curl -fsSL "https://github.com/onecli/onecli-cli/releases/download/v${CLI_VERSION}/onecli_${CLI_VERSION}_${OS}_${ARCH}.tar.gz" \
  | tar -xz -C .pa onecli

echo "==> nanoclaw prepared at $SRC"
