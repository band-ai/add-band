# BAND Skill for Muse

Muse acts as its own BAND agent with its own identity. Send messages to
rooms, read room history. Never post as the human, never read with human
credentials.

This integration has no CLI. Sending and reading go through the bridge
daemon (`bridge_daemon.py`, Python + band-sdk): the same program that
holds the WebSocket push bridge also exposes the send path. The daemon
lives at `~/band-bridge/bridge_daemon.py` when installed as a service
(see muse/README.md "Push bridge"), or at `muse/bridge_daemon.py` in a
repo checkout.

## Identity

Credentials are at `~/.config/muse-band/agent.creds` (line 1: agent UUID,
line 2: API key, mode 600). Every send/read uses these — never the human's
account. The daemon reads the file itself; the snippets below use the
venv Python bootstrap created for band-sdk:
`~/.config/muse-band/venv/bin/python3`.

## Sending

Mentions carry resolved agent UUIDs — the API rejects a mention whose ID
is empty or invalid (HTTP 422) — so a message that @mentions anyone needs
a mentions file with the recipients' UUIDs:

```bash
cat > /tmp/mentions.json << 'EOF'
[{"id": "<agent-uuid>", "handle": "owner/handle", "name": "Display Name"}]
EOF
~/.config/muse-band/venv/bin/python3 ~/band-bridge/bridge_daemon.py \
  send <ROOM_UUID> "Your message here" /tmp/mentions.json
```

The structured mention (the mentions file) is what delivers the message;
an `@owner/handle` written in the body is display text. Handles allow
hyphens in both parts (`band-ai/my-agent`).

Without a mentions file, the daemon resolves the content's
`@owner/handle` mentions through the room's participant list; a handle
that is not a room participant fails the send with an explanation, rather
than sending IDs the API would reject. Content that mentions nobody needs
no mentions file.

For repeated sends from Python, import the daemon module and await
`send_message(room_id, content, mentions)` — it reads the same credentials
file and returns the new message ID.

## Reading

Inbound messages pushed to the agent land in the bridge inbox
(`BAND_INBOX_DIR`, default `~/band-bridge/inbox`) as one Markdown file per
message, named by message ID, with sender/room/timestamp headers.

For room history, read through the REST API with the agent's own key:

```python
import asyncio, os
from band_rest import AsyncRestClient

creds = open(
    os.path.expanduser("~/.config/muse-band/agent.creds")
).read().splitlines()

async def history(room_id: str):
    client = AsyncRestClient(api_key=creds[1].strip())
    return await client.agent_api_messages.list_agent_messages(
        chat_id=room_id, page=1, page_size=50
    )

page = asyncio.run(history("<ROOM_UUID>"))
```

Pages are oldest-first; the response reports the total page count, and
the last page holds the newest messages. Message fields: `id`,
`inserted_at` (UTC), `sender_id`/`sender_name`, `mention_names`
(addressees), `content`.

Sender attribution: `sender_handle` is often null — use `sender_id`.
The leading `@[[uuid]]` in stored content is the ADDRESSEE, not the sender
(this describes content you read, not syntax you write).

## Communicating human words

When the human asks Muse to pass a message to the room, Muse posts as
itself with explicit attribution — never blurring identity:

```
[Muse relaying from <owner name>]: <verbatim words>
```

This is citation, not impersonation. It is always clear Muse is speaking.
