"""L3 delivery through Band's structured mention metadata."""

from __future__ import annotations

import pytest

from conftest import OwnerChatFactory
from driver.exchange import marker
from driver.ops import PAUserOps
from driver.waits import wait_for_reply_from

@pytest.mark.e2e
async def test_structured_mention_delivers_without_textual_address_prefix(
    pa, owner_chat: OwnerChatFactory, user_ops: PAUserOps, run_id: str
) -> None:
    """A PA receives a message addressed in metadata, not in its text prefix."""
    token = marker(run_id, prefix="PA-STRUCTURED-MENTION")

    async with owner_chat(pa) as chat:
        since = len(chat.room.messages)
        await user_ops.send_structured_mentions(
            chat.room_id,
            f"Reply with exactly {token}.",
            mentions=[pa.agent],
        )
        reply = await wait_for_reply_from(
            chat.room, pa.agent.id, since=since, containing=token
        )

    reply.assert_contains_any([token])
