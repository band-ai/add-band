#!/usr/bin/env bash
# Connect Muse to Band. Run on the host where Muse's agent runtime operates.
#
# Mints a Band agent from your Band API key, installs the `band` CLI
# (if missing), writes the Muse BAND skill, and stores the agent credentials.
# Muse acts as its own agent with its own identity — never as the human.
#
# Usage:
#   bootstrap.sh                          # prompts for API key, name, description
#   BAND_API_KEY=xxx bootstrap.sh         # skips the key prompt
#
# The ONE rule: the script obtains the Band API key itself. It prompts for it
# from /dev/tty when BAND_API_KEY is unset (curl|bash makes stdin the script),
# or accepts it pre-set in the env.
set -euo pipefail

# Get the Band API key: prompt for it, or accept pre-set BAND_API_KEY.
if [ -z "${BAND_API_KEY:-}" ]; then
  [ -r /dev/tty ] || { echo "no terminal for the API key prompt; set BAND_API_KEY and re-run" >&2; exit 1; }
  printf 'Paste your Band API key: ' >/dev/tty
  IFS= read -r -s BAND_API_KEY </dev/tty
  printf '\n' >/dev/tty
fi
[ -n "${BAND_API_KEY:-}" ] || { echo "BAND_API_KEY is empty" >&2; exit 1; }
# Ensure the key is cleared on any exit path
trap 'unset BAND_API_KEY' EXIT

# Agent name/description (prompt or env).
AGENT_NAME="${BAND_AGENT_NAME:-}"
if [ -z "$AGENT_NAME" ]; then
  [ -r /dev/tty ] || { echo "no terminal; set BAND_AGENT_NAME and re-run" >&2; exit 1; }
  printf 'Agent name [Muse]: ' >/dev/tty
  IFS= read -r AGENT_NAME </dev/tty
  AGENT_NAME="${AGENT_NAME:-Muse}"
fi
AGENT_DESC="${BAND_AGENT_DESCRIPTION:-Muse assistant on Band}"

# >>> band:mini
# The bridge daemon uses band-sdk (Python). Install if missing.
# Note: the `band` CLI is a separate tool; the skill documents CLI usage
# for interactive use, but the bridge itself only needs the SDK.
if ! python3 -c "import band" 2>/dev/null; then
  echo "Installing band-sdk via pip..."
  pip install --quiet --break-system-packages band-sdk 2>/dev/null \
    || pip install --quiet band-sdk 2>/dev/null \
    || pip3 install --quiet --break-system-packages band-sdk 2>/dev/null \
    || pip3 install --quiet band-sdk
fi
python3 -c "import band" 2>/dev/null || { echo "band-sdk install failed" >&2; exit 1; }
# <<< band:mini

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
CREDS_DIR="${HOME}/.config/muse-band"
mkdir -p "$CREDS_DIR"
chmod 700 "$CREDS_DIR"
printf '%s\n%s\n' "$AGENT_ID" "$AGENT_KEY" > "${CREDS_DIR}/agent.creds"
chmod 600 "${CREDS_DIR}/agent.creds"
echo "Agent registered: $AGENT_ID (credentials at ${CREDS_DIR}/agent.creds)"

# Write the Muse skill.
SKILL_DIR="${MUSE_SKILLS_DIR:-${HOME}/workspace/skills/band}"
mkdir -p "$SKILL_DIR"
cat > "${SKILL_DIR}/SKILL.md" << 'SKILL_EOF'
# BAND Skill for Muse

Muse acts as its own BAND agent with its own identity. Send messages to
rooms, read room history. Never post as the human, never read with human
credentials.

## Identity

Credentials are at `~/.config/muse-band/agent.creds` (line 1: agent UUID,
line 2: API key, mode 600). Every `band` call uses these — never the
human's account.

## Sending

```bash
# Use mktemp (not a fixed path) to avoid races on concurrent sends.
# Body MUST include a literal @owner/handle mention — the CLI rejects
# posts without one. Never hand-write @[[uuid]] (renders as @unknown).
f=$(mktemp)
cat > "$f" << 'EOF'
@owner/handle Your message here
EOF
AGENT_ID=$(sed -n '1p' ~/.config/muse-band/agent.creds)
band send <ROOM_UUID> --as "$AGENT_ID" --body-file "$f"
rm -f "$f"
```

- Muse posts as itself. NEVER use `band room send` (posts as the human).

## Reading

```bash
AGENT_ID=$(sed -n '1p' ~/.config/muse-band/agent.creds)
band room messages <ROOM_UUID> --as "$AGENT_ID" --json
```

Returns a dict with a `messages` list. Key fields: `id`, `inserted_at` (UTC),
`sender_id`/`sender_name`, `mention_names` (addressees), `content`.
Page 1 is the newest page, newest-last within the page.

Sender attribution: `sender_handle` is often null — use `sender_id`.
The leading `@[[uuid]]` in stored content is the ADDRESSEE, not the sender
(this describes content you read, not syntax you write).

## Communicating human words

When the human asks Muse to pass a message to the room, Muse posts as
itself with explicit attribution — never blurring identity:

```
@owner/handle [Muse relaying from Vibhor]: <verbatim words>
```

This is citation, not impersonation. It is always clear Muse is speaking.
SKILL_EOF

echo "Muse BAND skill installed at ${SKILL_DIR}/SKILL.md"
echo "Done. Agent $AGENT_ID ready. See ${SKILL_DIR}/SKILL.md for usage."
