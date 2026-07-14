#!/usr/bin/env bash
# Materialize a runnable, Band-wired NanoClaw checkout and build its images.
#
# nanoclaw-band's `band/adapter` is a payload-only overlay branch, and no
# prebuilt image is published. This script copies the payload files onto main,
# appends the self-registration imports, installs pinned SDK deps, and builds
# the host + agent images.
#
# Inputs (refs default to the pinned commits in pa-conformance/pins.env — a
# moving branch makes builds irreproducible and violates the catalog's
# upstream-pinning rule):
#   NANOCLAW_SRC          checkout path (created/updated; required)
#   NANOCLAW_REPO         clone URL (default: the band-ai fork)
#   NANOCLAW_REF          base commit the payload lands on (default: the pin)
#   NANOCLAW_PAYLOAD_REF  band/adapter payload commit (default: the pin)
# Host requirements: git, docker, node 22+, pnpm 10+, bun.
set -euo pipefail

SRC="${NANOCLAW_SRC:?set NANOCLAW_SRC to the checkout path}"
REPO="${NANOCLAW_REPO:-https://github.com/band-ai/nanoclaw-band.git}"
# Capture env overrides before sourcing the pins (sourcing would clobber them).
user_base="${NANOCLAW_REF:-}"
user_payload="${NANOCLAW_PAYLOAD_REF:-}"
# shellcheck source=../../pins.env
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/pins.env"
BASE_REF="${user_base:-$NANOCLAW_REF}"
PAYLOAD_REF="${user_payload:-$NANOCLAW_PAYLOAD_REF}"

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
  git clone -q "$REPO" "$SRC"
fi
cd "$SRC"
# Refuse to reuse a checkout that isn't this repo — this path is a disposable
# cache the script owns, not a working tree to respect. Read the raw config
# value: `git remote get-url` expands url.insteadOf rewrites, and CI rewrites
# band-ai URLs to token-authenticated HTTPS, which would never match $REPO.
actual_origin="$(git config --get remote.origin.url 2>/dev/null || true)"
[ "$actual_origin" = "$REPO" ] \
  || { echo "prepare: $SRC origin is '$actual_origin', expected $REPO" >&2; exit 1; }
# Commit SHAs, not branches: fetch them explicitly and hard-reset onto them.
git fetch -q origin "$BASE_REF" "$PAYLOAD_REF"
git checkout -q --force "$BASE_REF"
git reset -q --hard "$BASE_REF"
# reset leaves untracked/ignored files (node_modules, dist, .pa, a prior
# payload) that can taint dependency resolution and image contents; clean to a
# pristine tree — everything below is regenerated.
git clean -qxfd

echo "==> copying ${#FILES[@]} payload files from $PAYLOAD_REF"
for f in "${FILES[@]}"; do
  mkdir -p "$(dirname "$f")"
  git show "$PAYLOAD_REF:$f" > "$f"
  [ "$(git hash-object "$f")" = "$(git rev-parse "$PAYLOAD_REF:$f")" ] \
    || { echo "payload copy of $f is not byte-identical" >&2; exit 1; }
done

append_once() { # append_once <file> <import>: idempotent trailing import.
  grep -qxF "$2" "$1" || printf '%s\n' "$2" >> "$1"
}

insert_after() { # insert_after <file> <anchor> <import>
  # Idempotent, and loud: a missing anchor or a failed insert aborts the run.
  # The payload is inert without this wiring, so a silent no-op is worse than
  # a hard stop.
  local file="$1" anchor="$2" import="$3"
  grep -qxF "$import" "$file" && return 0
  grep -qF "$anchor" "$file" || { echo "prepare: anchor not in $file: $anchor" >&2; exit 1; }
  awk -v anchor="$anchor" -v import="$import" '
    { print }
    index($0, anchor) && !done { print import; done = 1 }
  ' "$file" > "$file.tmp"
  mv "$file.tmp" "$file"
  grep -qxF "$import" "$file" || { echo "prepare: failed to wire $import into $file" >&2; exit 1; }
}

append_once src/channels/index.ts "import './band.js';"
append_once container/agent-runner/src/mcp-tools/index.ts "import './band.js';"
# Position-sensitive per the upstream add-band instructions: the lifecycle
# import must follow the providers-registry import (not merely be appended),
# so insert after that anchor rather than at end of file.
insert_after container/agent-runner/src/index.ts \
  "import './providers/index.js';" "import './band-lifecycle.js';"

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
# version pinned by the NanoClaw checkout and verify its archive against an
# audited SHA-256 before extracting — a replaced release asset must not become
# executable test infrastructure. Bumping the version is deliberate: an unlisted
# version fails here until its checksum is added.
onecli_sha256() { # onecli_sha256 <version> <os> <arch>
  case "$1_$2_$3" in
    2.2.5_linux_amd64)  echo bd51bfbaed90d03081370d50b3733aa6b20790860a478191c216ac68b54d6495 ;;
    2.2.5_linux_arm64)  echo d7f053592c8a3d79570d8ca6e1aba1ffa3d4dad62e63f332bd2cd868f1ab7af3 ;;
    2.2.5_darwin_amd64) echo cd235c4caf5be7959f94a4671b4e10f4b2c22a25896686f1fbcb5f81256562d7 ;;
    2.2.5_darwin_arm64) echo 4e44a5661263887f895e78ce6b7a9ebc9924836c6c66337369c75b50dfe7a4d1 ;;
    *) return 1 ;;
  esac
}
CLI_VERSION=$(python3 -c "import json; print(json.load(open('versions.json'))['onecli-cli'])")
case "$(uname -s)" in Darwin) OS=darwin ;; *) OS=linux ;; esac
case "$(uname -m)" in arm64|aarch64) ARCH=arm64 ;; *) ARCH=amd64 ;; esac
expected="$(onecli_sha256 "$CLI_VERSION" "$OS" "$ARCH")" \
  || { echo "prepare: no audited onecli checksum for ${CLI_VERSION} ${OS}/${ARCH} — add it to prepare.sh" >&2; exit 1; }
echo "==> fetching onecli CLI v${CLI_VERSION} (${OS}/${ARCH})"
mkdir -p .pa
tarball="$(mktemp)"
curl -fsSL "https://github.com/onecli/onecli-cli/releases/download/v${CLI_VERSION}/onecli_${CLI_VERSION}_${OS}_${ARCH}.tar.gz" -o "$tarball"
actual="$( { sha256sum "$tarball" 2>/dev/null || shasum -a 256 "$tarball"; } | awk '{print $1}')"
[ "$actual" = "$expected" ] \
  || { echo "prepare: onecli checksum mismatch (${OS}/${ARCH}): got $actual, expected $expected" >&2; rm -f "$tarball"; exit 1; }
tar -xzf "$tarball" -C .pa onecli
rm -f "$tarball"

echo "==> nanoclaw prepared at $SRC"
