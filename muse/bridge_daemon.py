"""BAND push bridge: WebSocket events -> local inbox + wake pipe. Send via REST. No polling."""
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
INBOX_DIR = Path(os.environ.get("BAND_INBOX_DIR", os.path.expanduser("~/band-bridge/inbox")))
WAKE_PIPE = Path(os.environ.get("BAND_WAKE_PIPE", os.path.expanduser("~/.jam/wake/agent.pipe")))

# Optional non-production Band deployment (staging). BAND_BASE_URL is the
# https base; the WebSocket URL derives from it (https->wss, http->ws).
# Unset: the SDK defaults (production app.band.ai) apply.
BASE_URL = os.environ.get("BAND_BASE_URL", "").rstrip("/")


def _ws_url(base_url: str) -> str:
    """Derive the WebSocket URL from the https base: swap the scheme and,
    when the base has no path, append the socket path the SDK default
    carries (wss://app.band.ai/api/v1/socket/websocket)."""
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(base_url)
    scheme = {"https": "wss", "http": "ws"}.get(parts.scheme, parts.scheme)
    path = parts.path.rstrip("/") or "/api/v1/socket/websocket"
    return urlunsplit((scheme, parts.netloc, path, "", ""))


def _rest_client():
    from band_rest import AsyncRestClient

    kwargs = {"api_key": API_KEY}
    if BASE_URL:
        kwargs["base_url"] = BASE_URL
    return AsyncRestClient(**kwargs)


async def send_message(room_id: str, content: str, mentions: list[dict] | None = None) -> str:
    """Send a message to a room via the REST API. Returns the message ID."""
    from band_rest import ChatMessageRequest, ChatMessageRequestMentionsItem

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

    client = _rest_client()
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
    link_kwargs = {"agent_id": AGENT_ID, "api_key": API_KEY}
    if BASE_URL:
        link_kwargs.update(ws_url=_ws_url(BASE_URL), rest_url=BASE_URL)
    link = BandLink(**link_kwargs)
    presence = RoomPresence(link)  # auto-subscribes to existing rooms
    presence.on_room_event = on_message
    await presence.start()
    log.info("bridge live for agent %s", AGENT_ID[:8])
    # Readiness signal for supervisors/healthchecks that ask for one via env
    # (the pa-conformance stack sets BAND_BRIDGE_READY_FILE=/tmp/bridge-ready).
    ready_file = os.environ.get("BAND_BRIDGE_READY_FILE")
    if ready_file:
        Path(ready_file).touch()
    await link.run_forever(install_signal_handlers=False)


async def _resolve_mentions(room_id: str, handles: list[str]) -> list[dict]:
    """Resolve @owner/handle strings to mention dicts through the room's
    participant list (the participants API carries id/handle/name)."""
    client = _rest_client()
    resp = await client.agent_api_participants.list_agent_chat_participants(room_id)
    by_handle = {p.handle: p for p in resp.data}
    mentions = []
    for handle in handles:
        participant = by_handle.get(handle)
        if participant is None:
            raise SystemExit(
                f"cannot resolve @{handle}: not a participant of room "
                f"{room_id}; pass a mentions file with resolved UUIDs instead"
            )
        mentions.append(
            {
                "id": participant.id,
                "handle": participant.handle,
                "name": participant.name or participant.handle,
            }
        )
    return mentions


async def cli_send(room_id: str, content: str) -> None:
    """CLI entrypoint: python bridge_daemon.py send <room> <content>

    Mentions must carry resolved agent UUIDs — the API rejects mentions
    with empty/invalid UUIDs (HTTP 422). With an explicit mentions file,
    its UUIDs are used as given:
        python bridge_daemon.py send <room> <content> <mentions.json>
    where mentions.json is [{"id": "<uuid>", "handle": "...", "name": "..."}].
    Without one, the content's @mentions are resolved through the room's
    participant list. Handle format is "owner/handle" (e.g.
    "band-ai/my-agent"); hyphens are valid in both parts.
    """
    import re

    if len(sys.argv) >= 5:
        mentions = json.loads(Path(sys.argv[4]).read_text())
    else:
        handles = re.findall(r"@([\w-]+/[\w-]+|[\w-]+)", content)
        mentions = await _resolve_mentions(room_id, handles) if handles else []
    msg_id = await send_message(room_id, content, mentions)
    print(f"sent: {msg_id}")


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "send":
        asyncio.run(cli_send(sys.argv[2], sys.argv[3]))
    else:
        asyncio.run(main())
