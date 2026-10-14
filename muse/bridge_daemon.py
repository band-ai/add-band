"""BAND push bridge: WebSocket events -> local inbox + wake pipe. No polling."""
import asyncio
import json
import logging
import os
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
    fname = f"{int(time.time() * 1000)}-bridge.md"
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


if __name__ == "__main__":
    asyncio.run(main())
