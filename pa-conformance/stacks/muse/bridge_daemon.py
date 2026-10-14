"""BAND push bridge: WebSocket events -> local inbox + wake pipe. Send via REST. No polling.

NOTE: This is a copy of muse/bridge_daemon.py plus the /tmp/bridge-ready
touch for the conformance healthcheck. Keep in sync with the upstream file.
"""
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

from band import BandLink
from band.platform.event import MessageEvent
from band.runtime.presence import RoomPresence

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bridge")

AGENT_ID = os.environ.get("BAND_AGENT_ID", "")
API_KEY = os.environ.get("BAND_API_KEY", "")

# Fall back to the creds file (written by bootstrap or manual setup).
if not AGENT_ID or not API_KEY:
    creds = Path(os.path.expanduser("~/.config/muse-band/agent.creds"))
    if creds.is_file():
        lines = creds.read_text().splitlines()
        AGENT_ID = AGENT_ID or (lines[0] if len(lines) > 0 else "")
        API_KEY = API_KEY or (lines[1] if len(lines) > 1 else "")
INBOX_DIR = Path(os.environ.get("BAND_INBOX_DIR", os.path.expanduser("~/shared/inbox/spark")))
WAKE_PIPE = Path(os.environ.get("BAND_WAKE_PIPE", os.path.expanduser("~/.jam/wake/spark.pipe")))


async def send_message(room_id: str, content: str, mentions: list[dict] | None = None) -> str:
    """Send a message to a room via the REST API. Returns the message ID."""
    from band_rest import AsyncRestClient, ChatMessageRequest, ChatMessageRequestMentionsItem

    if not API_KEY:
        raise SystemExit("Set BAND_API_KEY env var or ~/.config/muse-band/agent.creds")

    mention_items = [
        ChatMessageRequestMentionsItem(
            id=m.get("id", ""),
            handle=m.get("handle", ""),
            name=m.get("name", ""),
        )
        for m in (mentions or [])
    ]

    client = AsyncRestClient(api_key=API_KEY)
    try:
        resp = await client.agent_api_messages.create_agent_chat_message(
            chat_id=room_id,
            message=ChatMessageRequest(content=content, mentions=mention_items),
        )
        msg_id = resp.data.id
        log.info("sent %s to %s", msg_id, room_id)
        return msg_id
    finally:
        try:
            await client.aclose()
        except Exception:
            pass


async def on_message(room_id: str, event) -> None:
    """Called on EVERY message event pushed over the WebSocket."""
    if not isinstance(event, MessageEvent):
        return
    p = event.payload
    if p is None:
        return
    # Skip own messages
    if p.sender_id == AGENT_ID:
        return

    log.info(
        "room=%s id=%s sender=%s at=%s :: %.120s",
        room_id, p.id, p.sender_name, p.inserted_at, (p.content or "")[:120],
    )

    # Bridge action: write to inbox, ping wake pipe.
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    # Include message ID to avoid collisions under burst
    fname = f"{int(time.time() * 1000)}-{p.id[:8]}-bridge.md"
    body = (
        f"from: bridge\n"
        f"at: {p.inserted_at}\n"
        f"room: {room_id}\n"
        f"msg_id: {p.id}\n"
        f"sender: {p.sender_name} ({p.sender_id})\n\n"
        f"{p.content or ''}\n"
    )
    (INBOX_DIR / fname).write_text(body)

    # Ping the wake pipe (non-blocking; skip if no reader).
    try:
        fd = os.open(WAKE_PIPE, os.O_WRONLY | os.O_NONBLOCK)
        os.write(fd, f"bridge:{p.id}\n".encode())
        os.close(fd)
    except OSError:
        pass  # no listener; inbox file is the durable record


async def main() -> None:
    if not AGENT_ID or not API_KEY:
        raise SystemExit("Set BAND_AGENT_ID and BAND_API_KEY env vars")
    link = BandLink(agent_id=AGENT_ID, api_key=API_KEY)
    presence = RoomPresence(link)  # auto-subscribes to existing rooms
    presence.on_room_event = on_message
    await presence.start()
    log.info("bridge live for agent %s", AGENT_ID[:8])
    await link.run_forever(install_signal_handlers=False)


async def cli_send(room_id: str, content: str) -> None:
    """CLI entrypoint: python bridge_daemon.py send <room> <content>

    NOTE: Requires explicit mention UUIDs. Pass mentions as a JSON file:
        python bridge_daemon.py send <room> <content> <mentions.json>
    where mentions.json is [{"id": "<uuid>", "handle": "...", "name": "..."}].
    The API rejects mentions with empty/invalid UUIDs (HTTP 422).
    """
    import re
    mentions = []
    if len(sys.argv) >= 5:
        mentions = json.loads(Path(sys.argv[4]).read_text())
    else:
        # Fallback: extract handles, but UUIDs must be resolved via the
        # room participants API. Empty IDs will be rejected by the API.
        log.warning("No mentions file provided; mentions will have empty IDs and likely fail")
        handles = re.findall(r"@(\w+)", content)
        mentions = [{"id": "", "handle": h, "name": h} for h in handles]
    msg_id = await send_message(room_id, content, mentions)
    print(f"sent: {msg_id}")


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "send":
        asyncio.run(cli_send(sys.argv[2], sys.argv[3]))
    else:
        asyncio.run(main())
