#!/usr/bin/env bash
# Connect Muse to Band. Run on the host where Muse's agent runtime operates.
#
# Mints a Band agent from your Band API key (re-running reuses the stored
# agent unless --force is given), installs band-sdk (Python) into a
# dedicated venv, installs the Muse BAND skill (muse/SKILL.md), and
# stores the agent credentials. Muse acts as its own agent with its own
# identity — never as the human.
#
# The bridge daemon (muse/bridge_daemon.py) is a separate manual setup;
# see muse/README.md "Push bridge" for instructions.
# There is no `band` CLI in this integration: the skill drives the bridge
# daemon's SDK send path.
#
# Usage:
#   bootstrap.sh                          # prompts for API key, name, description
#   BAND_API_KEY=xxx bootstrap.sh         # skips the key prompt
#   bootstrap.sh --force                  # mint a new agent, replacing stored credentials
#
# The ONE rule: the script obtains the Band API key itself. It prompts for it
# from /dev/tty when BAND_API_KEY is unset (curl|bash makes stdin the script),
# or accepts it pre-set in the env.
set -euo pipefail

FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    *) echo "unknown argument: $arg (only --force is supported)" >&2; exit 1 ;;
  esac
done

CREDS_DIR="${HOME}/.config/muse-band"
CREDS_FILE="${CREDS_DIR}/agent.creds"

# >>> band:mini
# The bridge daemon uses band-sdk (Python), installed into a dedicated venv
# so the install never overrides the system Python's PEP 668 guard and its
# output (including failures) stays visible.
VENV_DIR="${HOME}/.config/muse-band/venv"
if [ ! -x "${VENV_DIR}/bin/python" ]; then
  python3 -m venv "${VENV_DIR}" || { echo "venv creation failed — install your distro's python3-venv package and re-run" >&2; exit 1; }
fi
"${VENV_DIR}/bin/pip" install band-sdk
"${VENV_DIR}/bin/python" -c "import band" || { echo "band-sdk install failed" >&2; exit 1; }
# <<< band:mini

if [ -f "$CREDS_FILE" ] && [ "$FORCE" -eq 0 ]; then
  # Idempotent re-run: the stored agent is reused, not orphaned by a fresh
  # mint. --force is the explicit way to replace it.
  AGENT_ID=$(sed -n '1p' "$CREDS_FILE")
  echo "Reusing stored agent credentials (${CREDS_FILE}); agent: $AGENT_ID"
  echo "Pass --force to mint a new agent instead."
else
  # Get the Band API key: prompt for it, or accept pre-set BAND_API_KEY.
  if [ -z "${BAND_API_KEY:-}" ]; then
    [ -r /dev/tty ] || { echo "no terminal for the API key prompt; set BAND_API_KEY and re-run" >&2; exit 1; }
    printf 'Paste your Band API key: ' >/dev/tty
    IFS= read -r -s BAND_API_KEY </dev/tty
    printf '\n' >/dev/tty
  fi
  [ -n "${BAND_API_KEY:-}" ] || { echo "BAND_API_KEY is empty" >&2; exit 1; }

  # Agent name/description (prompt or env).
  AGENT_NAME="${BAND_AGENT_NAME:-}"
  if [ -z "$AGENT_NAME" ]; then
    [ -r /dev/tty ] || { echo "no terminal; set BAND_AGENT_NAME and re-run" >&2; exit 1; }
    printf 'Agent name [Muse]: ' >/dev/tty
    IFS= read -r AGENT_NAME </dev/tty
    AGENT_NAME="${AGENT_NAME:-Muse}"
  fi
  AGENT_DESC="${BAND_AGENT_DESCRIPTION:-Muse assistant on Band}"

  # Mint a Band agent from the API key.
  json_escape() { printf '%s' "$1" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'; }
  base="${BAND_BASE_URL:-https://app.band.ai}"; base="${base%/}"
  echo "Registering agent '$AGENT_NAME'..."
  resp=$(curl -sS -X POST "$base/api/v1/me/agents/register" \
    -H "Content-Type: application/json" \
    -d "$(printf '{"agent":{"name":%s,"description":%s}}' "$(json_escape "$AGENT_NAME")" "$(json_escape "$AGENT_DESC")")" \
    -w $'\n%{http_code}' -K - <<EOF
header = "X-API-Key: $BAND_API_KEY"
EOF
  ) || true
  unset BAND_API_KEY

  code=${resp##*$'\n'}; out=${resp%$'\n'*}
  case "$code" in
    200|201) ;;
    *) echo "agent registration failed (HTTP ${code:-?}): $(printf '%.300s' "$out")" >&2; exit 1 ;;
  esac

  # Extract agent credentials (UUID + key) from the response.
  AGENT_ID=$(printf '%s' "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin)["agent"]["id"])')
  AGENT_KEY=$(printf '%s' "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin)["agent"]["api_key"])')
  [ -n "$AGENT_ID" ] && [ -n "$AGENT_KEY" ] || { echo "failed to parse agent credentials" >&2; exit 1; }

  # Store credentials.
  mkdir -p "$CREDS_DIR"
  chmod 700 "$CREDS_DIR"
  printf '%s\n%s\n' "$AGENT_ID" "$AGENT_KEY" > "$CREDS_FILE"
  chmod 600 "$CREDS_FILE"
  echo "Agent registered: $AGENT_ID (credentials at ${CREDS_FILE})"
fi

# Install the Muse skill. The skill ships in this repo as muse/SKILL.md:
# from a checkout, copy the sibling file; the curl|bash path fetches the
# same file from the upstream repo.
SKILL_DIR="${MUSE_SKILLS_DIR:-${HOME}/workspace/skills/band}"
mkdir -p "$SKILL_DIR"
if [ -f "${BASH_SOURCE[0]:-}" ] && [ -f "$(dirname "${BASH_SOURCE[0]}")/SKILL.md" ]; then
  cp "$(dirname "${BASH_SOURCE[0]}")/SKILL.md" "${SKILL_DIR}/SKILL.md"
else
  curl -fsSL "https://raw.githubusercontent.com/band-ai/add-band/main/muse/SKILL.md" -o "${SKILL_DIR}/SKILL.md"
fi

echo "Muse BAND skill installed at ${SKILL_DIR}/SKILL.md"
echo "Done. Agent $AGENT_ID ready. See ${SKILL_DIR}/SKILL.md for usage."
