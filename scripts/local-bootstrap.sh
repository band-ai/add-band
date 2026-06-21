#!/usr/bin/env bash
# Run an integration's local bootstrap.sh the way the web app's `curl ... | bash`
# delivery does, so you can test your own edits before they ship. No key substitution:
# you'll be prompted for your Band user API key (or pre-set BAND_USER_API_KEY).
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
Usage: scripts/local-bootstrap.sh <harness> [--pipe|--curl|--print]

  <harness>   integration folder name (e.g. hermes, nanoclaw, openclaw)

Modes (default --pipe):
  --pipe    cat <harness>/bootstrap.sh | bash             stdin is a pipe, exactly like curl|bash
  --curl    curl -fsSL "file://.../bootstrap.sh" | bash   also exercises the file:// fetch path
  --print   print the script that would run, then exit    (dry run; no execution)

The bootstrap prompts for BAND_USER_API_KEY from /dev/tty; export it first to skip the prompt.
USAGE
}

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
harness="${1:-}"
mode="${2:---pipe}"

case "$harness" in
  -h|--help) usage; exit 0 ;;
  "") usage; exit 2 ;;
esac

script="$root/$harness/bootstrap.sh"
[ -f "$script" ] || { echo "no bootstrap at $script (expected $harness/bootstrap.sh)" >&2; exit 1; }

case "$mode" in
  --print)
    cat "$script"
    ;;
  --pipe)
    # cat | bash (not `bash < file`) so stdin is a pipe, matching curl|bash exactly.
    cat "$script" | bash
    ;;
  --curl)
    command -v curl >/dev/null || { echo "curl not found" >&2; exit 1; }
    curl -fsSL "file://$script" | bash
    ;;
  *)
    echo "unknown mode: $mode" >&2
    usage
    exit 2
    ;;
esac
