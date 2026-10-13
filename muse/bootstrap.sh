#!/usr/bin/env bash
# Connect Muse to Band. Run on the host where Muse's agent runtime operates.
#
# Installs the `band` CLI (if missing), writes the Muse BAND skill, and
# verifies the CLI can reach the platform. The skill teaches Muse to send/read
# room messages; an optional bridge daemon (see README) gives push instead
# of polling.
#
# The ONE rule: the script obtains the Band API key itself. It prompts for it
# from /dev/tty when BAND_API_KEY is unset (curl|bash makes stdin the script),
# or accepts it pre-set in the env.
set -e

# Get the Band API key: prompt for it, or accept pre-set BAND_API_KEY.
BAND_API_KEY=<redacted>
if [ -z "${BAND_API_KEY: <redacted>
  [ -r /dev/tty ] || { echo "no terminal for the API key prompt; set BAND_API_KEY and re-run" >&2; exit 1; }
  printf 'Paste your Band API key: ' >/dev/tty
  IFS= read -r -s BAND_API_KEY </dev/tty
  printf '\n' >/dev/tty
fi
[ -n "${BAND_API_KEY: <redacted> || { echo "BAND_API_KEY is empty" >&2; exit 1; }
export BAND_API_KEY

# >>> band:mini
# Install the band CLI if missing.
if ! command -v band >/dev/null 2>&1; then
  echo "Installing band CLI..."
  curl -fsSL https://raw.githubusercontent.com/band-ai/add-band/main/muse/install-band.sh | bash
fi
# <<< band:mini

# Write the Muse skill.
SKILL_DIR="${HOME}/workspace/skills/band"
mkdir -p "$SKILL_DIR"
cat > "${SKILL_DIR}/SKILL.md" << 'SKILL_EOF'
# BAND Skill for Muse

Connect Muse to BAND (band.ai) — send messages to rooms, read room history,
receive push notifications via WebSocket bridge.

## Sending

```bash
# Body MUST include a literal @owner/handle mention — the CLI rejects
# posts without one. Never hand-write @[[uuid]] (renders as @unknown).
cat > /tmp/band-msg.txt << 'EOF'
@owner/handle Your message here
EOF
band send <ROOM_UUID> --session <SESSION> --body-file /tmp/band-msg.txt
```

- `band send` posts as the agent. NEVER use `band room send` (posts as the human).
- A live session is required: `band attach --session <name>` (sends fail without one).

## Reading

```bash
band room messages <ROOM_UUID> --json
```

Returns a dict with a `messages` list. Key fields: `id`, `inserted_at` (UTC),
`sender_id`/`sender_name`, `mention_names` (addressees), `content`.
Page 1 is the newest page, newest-last within the page.

Sender attribution: `sender_handle` is often null — use `sender_id`.
The leading `@[[uuid]]` in content is the ADDRESSEE, not the sender.

## Push (no polling)

BAND pushes over WebSocket (Phoenix Channels). Run a bridge daemon that
holds the socket open; on new message it writes to the local inbox and
pings the agent's wake pipe. ~1s latency, zero polling cost.
See the integration README for the bridge reference.
SKILL_EOF

echo "Muse BAND skill installed at ${SKILL_DIR}/SKILL.md"

# Verify the CLI can reach the platform.
if band --version >/dev/null 2>&1; then
  echo "band CLI ready: $(band --version 2>&1 | head -1)"
else
  echo "band CLI installed but not responding — check PATH" >&2
fi

echo "Done. See ${SKILL_DIR}/SKILL.md for usage. For push notifications, see the README's bridge section."
